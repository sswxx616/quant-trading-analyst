#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import sys
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from quant_core import (
    analyze,
    apply_local_runtime_env,
    ensure_state_dir,
    load_json,
    recommendation_label,
    send_notification,
    write_json,
)

try:
    import akshare as ak
except Exception:
    ak = None

try:
    import pandas as pd
except Exception:
    pd = None


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scan the A-share market for high-quality names with a factor layer plus the local quant engine."
    )
    parser.add_argument("--config", required=True, help="Path to the selector config JSON.")
    parser.add_argument("--output", help="Optional output path.")
    parser.add_argument("--env-file", help="Optional runtime env file.")
    parser.add_argument("--stdout-only", action="store_true", help="Print locally without notifier.")
    return parser.parse_args()


def selector_cache_dir() -> Path:
    return ensure_state_dir() / "cn_quality_selector"


def suppress_akshare(callable_obj, *args, **kwargs):
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        return callable_obj(*args, **kwargs)


def report_date_candidates(now: datetime) -> list[str]:
    quarter_dates = []
    year = now.year
    for offset in range(0, 10):
        target_year = year - (offset // 4)
        quarter = 4 - (offset % 4)
        if quarter == 4:
            quarter_dates.append(f"{target_year}1231")
        elif quarter == 3:
            quarter_dates.append(f"{target_year}0930")
        elif quarter == 2:
            quarter_dates.append(f"{target_year}0630")
        else:
            quarter_dates.append(f"{target_year}0331")
    seen = set()
    ordered = []
    for item in quarter_dates:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def quality_snapshot_cache_path(report_date: str) -> Path:
    return selector_cache_dir() / f"quality_snapshot_{report_date}.json"


def load_quality_snapshot(report_date: str, cache_ttl_hours: int):
    cache_path = quality_snapshot_cache_path(report_date)
    payload = load_json(cache_path, {})
    if payload.get("rows") and payload.get("cached_at"):
        age_seconds = int(time.time()) - int(payload["cached_at"])
        if age_seconds <= cache_ttl_hours * 3600:
            return pd.DataFrame(payload["rows"])
    return None


def fetch_quality_snapshot(report_date: str, cache_ttl_hours: int):
    if ak is None or pd is None:
        raise RuntimeError("A-share selector requires the optional 'akshare' and 'pandas' packages.")
    cached = load_quality_snapshot(report_date, cache_ttl_hours)
    if cached is not None:
        return cached
    frame = suppress_akshare(ak.stock_yjbb_em, date=report_date)
    rows = frame.to_dict("records")
    write_json(
        quality_snapshot_cache_path(report_date),
        {"cached_at": int(time.time()), "report_date": report_date, "rows": rows},
    )
    return frame


def resolve_quality_report_date(min_rows: int, cache_ttl_hours: int) -> tuple[str, "pd.DataFrame"]:
    best_date = None
    best_frame = None
    best_count = -1
    for report_date in report_date_candidates(datetime.now()):
        try:
            frame = fetch_quality_snapshot(report_date, cache_ttl_hours)
        except Exception:
            continue
        count = len(frame.index)
        if count > best_count:
            best_date = report_date
            best_frame = frame
            best_count = count
        if count >= min_rows:
            return report_date, frame
    if best_frame is None:
        raise RuntimeError("Failed to load any A-share report snapshot from AkShare.")
    return best_date, best_frame


def numeric_or_none(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    try:
        parsed = float(value)
    except Exception:
        return None
    if math.isnan(parsed):
        return None
    return parsed


def clean_quality_frame(frame: "pd.DataFrame", config: dict) -> "pd.DataFrame":
    df = frame.copy()
    rename_map = {
        "股票代码": "symbol",
        "股票简称": "name",
        "每股收益": "eps",
        "营业总收入-同比增长": "revenue_growth",
        "净利润-同比增长": "profit_growth",
        "净资产收益率": "roe",
        "每股经营现金流量": "ocf_per_share",
        "销售毛利率": "gross_margin",
        "所处行业": "industry",
        "最新公告日期": "announcement_date",
    }
    df = df.rename(columns=rename_map)
    keep_columns = [column for column in rename_map.values() if column in df.columns]
    df = df[keep_columns].copy()

    for column in ["eps", "revenue_growth", "profit_growth", "roe", "ocf_per_share", "gross_margin"]:
        if column in df.columns:
            df[column] = df[column].map(numeric_or_none)
    df["symbol"] = df["symbol"].astype(str).str.zfill(6)
    df["name"] = df["name"].astype(str)
    df["industry"] = df["industry"].fillna("未知行业")

    df = df[df["symbol"].str.fullmatch(r"\d{6}")]
    df = df[~df["symbol"].str.startswith(("200", "900"))]
    df = df[~df["name"].str.contains("ST|退", na=False)]

    thresholds = config.get("thresholds", {})
    min_eps = float(thresholds.get("min_eps", 0.1))
    min_revenue_growth = float(thresholds.get("min_revenue_growth", 5.0))
    min_profit_growth = float(thresholds.get("min_profit_growth", 5.0))
    min_roe = float(thresholds.get("min_roe", 8.0))
    min_ocf_per_share = float(thresholds.get("min_ocf_per_share", 0.0))
    min_gross_margin = float(thresholds.get("min_gross_margin", 10.0))

    df = df[
        (df["eps"].fillna(-999) >= min_eps)
        & (df["revenue_growth"].fillna(-999) >= min_revenue_growth)
        & (df["profit_growth"].fillna(-999) >= min_profit_growth)
        & (df["roe"].fillna(-999) >= min_roe)
        & (df["ocf_per_share"].fillna(-999) >= min_ocf_per_share)
        & (df["gross_margin"].fillna(-999) >= min_gross_margin)
    ].copy()
    if df.empty:
        raise RuntimeError("No A-share names passed the quality thresholds.")

    growth_weights = config.get(
        "growth_weights",
        {
            "profit_growth": 0.42,
            "revenue_growth": 0.33,
            "eps": 0.25,
        },
    )
    quality_weights = config.get(
        "quality_weights",
        {
            "roe": 0.40,
            "ocf_per_share": 0.34,
            "gross_margin": 0.26,
        },
    )
    total_weights = config.get(
        "fundamental_blend_weights",
        {
            "growth_score": 0.52,
            "business_quality_score": 0.48,
        },
    )

    for column in set(growth_weights) | set(quality_weights):
        df[f"{column}_rank"] = df[column].rank(pct=True, method="average")

    df["growth_score"] = 0.0
    for column, weight in growth_weights.items():
        df["growth_score"] += df[f"{column}_rank"] * float(weight) * 100.0

    df["business_quality_score"] = 0.0
    for column, weight in quality_weights.items():
        df["business_quality_score"] += df[f"{column}_rank"] * float(weight) * 100.0

    df["quality_score"] = (
        df["growth_score"] * float(total_weights.get("growth_score", 0.52))
        + df["business_quality_score"] * float(total_weights.get("business_quality_score", 0.48))
    )

    df["quality_grade"] = df["quality_score"].map(
        lambda value: "A" if value >= 80 else ("B" if value >= 65 else ("C" if value >= 50 else "D"))
    )
    return df.sort_values(["quality_score", "profit_growth", "roe"], ascending=False).reset_index(drop=True)


def diversify_by_industry(frame: "pd.DataFrame", max_per_industry: int, limit: int) -> "pd.DataFrame":
    picks = []
    per_industry = defaultdict(int)
    for _, row in frame.iterrows():
        industry = row.get("industry") or "未知行业"
        if per_industry[industry] >= max_per_industry:
            continue
        picks.append(row)
        per_industry[industry] += 1
        if len(picks) >= limit:
            break
    return pd.DataFrame(picks).reset_index(drop=True)


def score_quant_report(report: dict) -> tuple[float, str]:
    framework = report.get("trade_framework", {})
    base = max(0.0, min(100.0, float(report.get("score", 0)) + 50.0))
    recommendation = report.get("recommendation")
    setup_phase = framework.get("setup_phase")
    reward_grade = framework.get("reward_risk_grade")
    validation_quality = framework.get("validation_quality")
    risk_tier = framework.get("risk_tier")

    score = base
    if recommendation == "buy-or-add":
        score += 12
    elif recommendation == "watch-for-buy-confirmation":
        score += 6
    elif recommendation == "hold-and-wait":
        score -= 2
    else:
        score -= 18

    if setup_phase == "pullback-zone":
        score += 10
    elif setup_phase == "confirmation-zone":
        score += 7
    elif setup_phase == "mid-range":
        score += 1
    elif setup_phase == "extended-zone":
        score -= 12
    elif setup_phase == "defense-zone":
        score -= 20

    if reward_grade == "good":
        score += 10
    elif reward_grade == "acceptable":
        score += 4
    elif reward_grade == "weak":
        score -= 8

    if validation_quality == "strong":
        score += 8
    elif validation_quality == "moderate":
        score += 3
    else:
        score -= 4

    if risk_tier == "high":
        score -= 5
    elif risk_tier == "medium":
        score -= 2

    return max(0.0, min(100.0, score)), setup_phase or "unknown"


def score_valuation(current_price: float | None, eps: float | None, roe: float | None, gross_margin: float | None) -> tuple[float, float | None]:
    if current_price in (None, 0) or eps in (None, 0) or eps <= 0:
        return 25.0, None
    approx_pe = current_price / eps
    if approx_pe <= 10:
        score = 90.0
    elif approx_pe <= 15:
        score = 82.0
    elif approx_pe <= 20:
        score = 74.0
    elif approx_pe <= 30:
        score = 62.0
    elif approx_pe <= 40:
        score = 50.0
    elif approx_pe <= 55:
        score = 38.0
    elif approx_pe <= 80:
        score = 24.0
    else:
        score = 12.0
    if (roe or 0) >= 18 and (gross_margin or 0) >= 25:
        score += 6.0
    elif (roe or 0) >= 12:
        score += 3.0
    return max(0.0, min(100.0, score)), round(approx_pe, 2)


def score_timing_fit(report: dict) -> float:
    framework = report.get("trade_framework", {})
    recommendation = report.get("recommendation")
    setup_phase = framework.get("setup_phase")
    reward_grade = framework.get("reward_risk_grade")
    validation_quality = framework.get("validation_quality")
    position_posture = framework.get("position_posture")

    score = 50.0
    if recommendation == "buy-or-add":
        score += 16
    elif recommendation == "watch-for-buy-confirmation":
        score += 10
    elif recommendation == "hold-and-wait":
        score += 2
    else:
        score -= 18

    if setup_phase == "pullback-zone":
        score += 16
    elif setup_phase == "confirmation-zone":
        score += 12
    elif setup_phase == "mid-range":
        score += 2
    elif setup_phase == "extended-zone":
        score -= 14
    elif setup_phase == "defense-zone":
        score -= 24

    if reward_grade == "good":
        score += 10
    elif reward_grade == "acceptable":
        score += 5
    elif reward_grade == "weak":
        score -= 10

    if validation_quality == "strong":
        score += 8
    elif validation_quality == "moderate":
        score += 3
    else:
        score -= 4

    if position_posture == "accumulate":
        score += 6
    elif position_posture == "pilot-only":
        score += 2
    elif position_posture == "harvest-strength":
        score -= 8
    elif position_posture == "protect-capital":
        score -= 12

    return max(0.0, min(100.0, score))


def build_action(report: dict) -> str:
    framework = report.get("trade_framework", {})
    recommendation = report.get("recommendation")
    setup_phase = framework.get("setup_phase")
    posture = framework.get("position_posture")
    if recommendation == "buy-or-add" and setup_phase == "pullback-zone":
        return "回踩可分批接"
    if recommendation == "buy-or-add" and setup_phase == "confirmation-zone":
        return "确认后小仓跟"
    if recommendation == "watch-for-buy-confirmation":
        return "等确认再动"
    if posture == "harvest-strength":
        return "偏强但先锁利"
    if posture == "protect-capital":
        return "先防守"
    return "观察为主"


def analyze_candidate(row: dict) -> dict | None:
    try:
        report = analyze(row["symbol"], market="cn-stock", timeframe="1d")
    except Exception:
        return None
    quant_score, setup_phase = score_quant_report(report)
    fundamental_score = float(row["quality_score"])
    growth_score = float(row.get("growth_score") or 0.0)
    business_quality_score = float(row.get("business_quality_score") or 0.0)
    valuation_score, approx_pe = score_valuation(
        report["current_price"],
        numeric_or_none(row.get("eps")),
        numeric_or_none(row.get("roe")),
        numeric_or_none(row.get("gross_margin")),
    )
    timing_score = score_timing_fit(report)
    weights = {
        "fundamental": 0.36,
        "quant": 0.26,
        "timing": 0.22,
        "valuation": 0.16,
    }
    total_score = round(
        (fundamental_score * weights["fundamental"])
        + (quant_score * weights["quant"])
        + (timing_score * weights["timing"])
        + (valuation_score * weights["valuation"]),
        2,
    )
    return {
        "symbol": report["asset"]["symbol"],
        "name": row["name"],
        "industry": row["industry"],
        "quality_score": round(fundamental_score, 2),
        "growth_score": round(growth_score, 2),
        "business_quality_score": round(business_quality_score, 2),
        "quality_grade": row["quality_grade"],
        "quant_score": round(quant_score, 2),
        "timing_score": round(timing_score, 2),
        "valuation_score": round(valuation_score, 2),
        "approx_pe": approx_pe,
        "total_score": total_score,
        "current_price": report["current_price"],
        "recommendation": report["recommendation"],
        "recommendation_label": recommendation_label(report["recommendation"]),
        "setup_phase": setup_phase,
        "validation_quality": report.get("trade_framework", {}).get("validation_quality"),
        "position_posture": report.get("trade_framework", {}).get("position_posture"),
        "exit_posture": report.get("trade_framework", {}).get("exit_posture"),
        "reward_to_stop_ratio": report.get("trade_framework", {}).get("reward_to_stop_ratio"),
        "levels": report["levels"],
        "fundamentals": {
            "eps": numeric_or_none(row.get("eps")),
            "revenue_growth": numeric_or_none(row.get("revenue_growth")),
            "profit_growth": numeric_or_none(row.get("profit_growth")),
            "roe": numeric_or_none(row.get("roe")),
            "ocf_per_share": numeric_or_none(row.get("ocf_per_share")),
            "gross_margin": numeric_or_none(row.get("gross_margin")),
        },
        "action": build_action(report),
    }


def render_markdown(results: list[dict], report_date: str, universe_count: int, config: dict) -> str:
    title = config.get("title_cn", "A股优质股候选")
    lines = [
        f"# {title}",
        "",
        f"- 财报质量样本期: `{report_date}`",
        f"- 初筛通过数量: `{universe_count}`",
        f"- 最终候选数量: `{len(results)}`",
        f"- 方法: `finhack / Qlib / zvt` 风格多因子排序 + `ABu` 风格买卖/风控纪律 + 本地量化时机复核",
        "",
        "| 排名 | 代码 | 名称 | 行业 | 现价 | 成长分 | 质量分 | 估值分 | 时机分 | 总分 | 阶段 | 动作 |",
        "|---|---|---|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for index, row in enumerate(results, start=1):
        lines.append(
            f"| {index} | `{row['symbol']}` | {row['name']} | {row['industry']} | {row['current_price']} | "
            f"{row['growth_score']} | {row['business_quality_score']} | {row['valuation_score']} | {row['timing_score']} | "
            f"{row['total_score']} | {row['setup_phase']} | {row['action']} |"
        )
    lines.extend(["", "## 重点解释", ""])
    for row in results[: min(5, len(results))]:
        levels = row["levels"]
        fundamentals = row["fundamentals"]
        lines.extend(
            [
                f"### {row['name']} ({row['symbol']})",
                f"- 现价: `{row['current_price']}` | 建议: `{row['recommendation_label']}` | 总分: `{row['total_score']}`",
                f"- 因子拆解: 成长分 `{row['growth_score']}` | 质量分 `{row['business_quality_score']}` | 估值分 `{row['valuation_score']}` | 时机分 `{row['timing_score']}` | 估算PE `{row['approx_pe']}`",
                f"- 基本面: 利润增速 `{fundamentals['profit_growth']}`%, 营收增速 `{fundamentals['revenue_growth']}`%, ROE `{fundamentals['roe']}`%, 每股经营现金流 `{fundamentals['ocf_per_share']}`, 毛利率 `{fundamentals['gross_margin']}`%",
                f"- 策略框架: 阶段 `{row['setup_phase']}` | 验证 `{row['validation_quality']}` | 仓位姿态 `{row['position_posture']}` | 卖出姿态 `{row['exit_posture']}` | 奖惩比 `{row['reward_to_stop_ratio']}`",
                f"- 关键位: 观察买点 `{levels.get('best_buy_level')}` | 确认位 `{levels.get('confirmation_buy_level')}` | 第一卖点 `{levels.get('best_sell_level')}` | 止损 `{levels.get('stop_loss')}`",
                f"- 当前动作: {row['action']}",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def main():
    args = parse_args()
    apply_local_runtime_env(args.env_file)
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = (Path(__file__).resolve().parent / args.config).resolve()
    config = json.loads(config_path.read_text())

    cache_ttl_hours = int(config.get("cache_ttl_hours", 24))
    min_report_rows = int(config.get("min_report_rows", 3000))
    max_per_industry = int(config.get("max_per_industry", 2))
    preselect_limit = int(config.get("preselect_limit", 40))
    top_n = int(config.get("top_n", 10))
    max_workers = int(config.get("max_workers", 4))

    report_date, quality_frame = resolve_quality_report_date(min_report_rows, cache_ttl_hours)
    cleaned = clean_quality_frame(quality_frame, config)
    preselected = diversify_by_industry(cleaned, max_per_industry=max_per_industry, limit=preselect_limit)

    results = []
    candidate_rows = preselected.to_dict("records")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(analyze_candidate, row) for row in candidate_rows]
        for future in as_completed(futures):
            item = future.result()
            if item is not None:
                results.append(item)

    if not results:
        raise SystemExit("No A-share candidates completed the full selector run.")

    results.sort(key=lambda item: item["total_score"], reverse=True)
    final_results = results[:top_n]
    rendered = render_markdown(final_results, report_date, len(cleaned.index), config)

    if args.output:
        output_path = Path(args.output)
        if not output_path.is_absolute():
            output_path = (Path(__file__).resolve().parent / args.output).resolve()
        output_path.write_text(rendered)

    if not args.stdout_only and "notifier" in config:
        send_notification(config["notifier"], rendered, {"message": rendered, "text": rendered})
    sys.stdout.write(rendered)


if __name__ == "__main__":
    main()

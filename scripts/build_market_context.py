#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from quant_core import analyze, ensure_state_dir, load_json, write_json

SIGNAL_TRANSLATIONS = {
    "Price is holding above the 50-period average, which supports trend continuation.": "价格站在 50 周期均线上方，趋势延续性较好。",
    "The short-term trend is stronger than the medium-term trend.": "短期趋势强于中期趋势，说明多头结构仍在发挥作用。",
    "The medium-term trend still sits above the long-term baseline.": "中期趋势仍位于长期基线之上，长线结构没有走坏。",
    "MACD momentum is positive.": "MACD 动能为正，短线修复和上行动能仍在。",
    "RSI is in an oversold zone, which supports a rebound setup.": "RSI 处于超卖区，具备技术性反弹条件。",
    "RSI is in a healthy momentum range rather than at an exhaustion extreme.": "RSI 处于相对健康区间，暂未进入极端透支状态。",
    "Price is pressing resistance with above-average volume, which supports a breakout thesis.": "价格在放量逼近阻力位，突破逻辑正在增强。",
    "Price is below the 50-period average, which weakens trend quality.": "价格位于 50 周期均线下方，趋势质量偏弱。",
    "The short-term average remains below the medium-term average.": "短期均线仍低于中期均线，修复确认还不充分。",
    "The medium-term trend is below the long-term baseline.": "中期趋势低于长期基线，长线结构仍需修复。",
    "MACD momentum is negative.": "MACD 动能为负，短线仍有回落压力。",
    "RSI is stretched into an overbought zone.": "RSI 已进入偏高区域，短线存在回吐风险。",
    "Volume is light relative to the recent average, so conviction is weaker.": "成交量低于近期均值，当前信号说服力偏弱。",
    "Price is leaning on support while momentum remains negative.": "价格贴近支撑但动能仍为负，需警惕支撑失守。",
    "ATR volatility is elevated, which makes precise entries harder.": "ATR 波动率偏高，短线买点更难把握。",
}

DEFAULT_CONFIG = {
    "markets": {
        "us_stock": {
            "timeframe": "1d",
            "assets": [
                {"asset": "SPY", "market": "us-stock", "label": "S&P 500 ETF"},
                {"asset": "QQQ", "market": "us-stock", "label": "Nasdaq 100 ETF"},
                {"asset": "IWM", "market": "us-stock", "label": "Russell 2000 ETF"},
            ],
        },
        "cn_stock": {
            "timeframe": "1d",
            "tushare_mode": "http",
            "assets": [
                {"asset": "600519", "market": "cn-stock", "label": "贵州茅台"},
                {"asset": "300750", "market": "cn-stock", "label": "宁德时代"},
                {"asset": "002594", "market": "cn-stock", "label": "比亚迪"},
            ],
        },
        "crypto": {
            "timeframe": "4h",
            "assets": [
                {"asset": "BTC", "market": "crypto", "label": "BTC"},
                {"asset": "ETH", "market": "crypto", "label": "ETH"},
                {"asset": "SOL", "market": "crypto", "label": "SOL"},
            ],
        },
    }
}


def parse_args():
    parser = argparse.ArgumentParser(description="Build market-level context JSON for the daily recap workflow.")
    parser.add_argument("--config", help="Optional market context builder config JSON file.")
    parser.add_argument("--output", required=True, help="Path to save the generated market context JSON.")
    parser.add_argument("--memory-file", help="Optional learning memory path to reuse during analysis.")
    parser.add_argument(
        "--cache-ttl-hours",
        type=int,
        default=72,
        help="How long cached benchmark reports remain eligible for fallback. Defaults to 72 hours.",
    )
    parser.add_argument(
        "--overlay-file",
        help="Optional JSON file with current macro/news overlays. Matching fields override or prepend derived context.",
    )
    return parser.parse_args()


def load_json_file(path: Path | None) -> dict:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text())


def translate_signal(text: str) -> str:
    return SIGNAL_TRANSLATIONS.get(text, text)


def unique_items(items: list[str], limit: int = 3) -> list[str]:
    results = []
    seen = set()
    for item in items:
        normalized = translate_signal(item.strip()).rstrip(".").rstrip("。")
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        results.append(normalized)
        if len(results) >= limit:
            break
    return results


def action_bucket(report: dict) -> str:
    recommendation = report["recommendation"]
    if recommendation == "buy-or-add":
        return "buy"
    if recommendation in {"reduce-or-tighten-risk", "sell-or-avoid"}:
        return "sell"
    return "watch"


def average_score(reports: list[dict]) -> float:
    if not reports:
        return 0.0
    return sum(report["score"] for report in reports) / len(reports)


def market_display_name(market: str) -> str:
    return {
        "us_stock": "美股",
        "cn_stock": "A股",
        "crypto": "数字货币",
    }[market]


def technical_tone(market: str, reports: list[dict]) -> str:
    avg = average_score(reports)
    buy_count = sum(1 for report in reports if action_bucket(report) == "buy")
    sell_count = sum(1 for report in reports if action_bucket(report) == "sell")
    market_name = market_display_name(market)
    if avg >= 30 or buy_count >= max(2, len(reports)):
        return f"{market_name}整体偏强，风险偏好正在修复，右侧确认信号增加。"
    if avg <= -30 or sell_count >= max(2, len(reports)):
        return f"{market_name}整体承压，防守信号偏多，趋势修复仍不充分。"
    return f"{market_name}整体偏震荡，当前更像结构分化而不是单边趋势。"


def default_message(market: str) -> str:
    return {
        "us_stock": "建议重点结合美联储利率路径、就业与通胀数据、长端美债收益率，以及地缘局势对风险偏好的影响一起解读。",
        "cn_stock": "建议重点结合政策支持、市场流动性、北向资金节奏、产业催化与经济修复预期一起解读。",
        "crypto": "建议重点结合美元流动性、ETF 资金流、监管动态、链上事件，以及风险资产偏好一起解读。",
    }[market]


def default_latest(market: str, reports: list[dict]) -> str:
    candidate = max(reports, key=lambda report: abs(report.get("price_change_5_bars_pct") or 0))
    label = candidate["asset"].get("recap_label") or candidate["asset"].get("display_name") or candidate["asset"]["symbol"]
    change = candidate.get("price_change_5_bars_pct")
    return (
        f"{label} 近 5 个周期变动 {change}% ，当前评分 {candidate['score']}。"
        f"这反映出{market_display_name(market)}内部的强弱切换仍然值得继续跟踪。"
    )


def derive_entry(market: str, reports: list[dict]) -> dict:
    positives = unique_items([reason for report in reports for reason in report.get("reasons", [])], limit=3)
    negatives = unique_items([risk for report in reports for risk in report.get("risks", [])], limit=3)
    return {
        "message": default_message(market),
        "technical": (
            f"{technical_tone(market, reports)}"
            f" 当前基准篮子平均评分 {round(average_score(reports), 1)}。"
        ),
        "catalysts": positives or ["当前没有形成特别突出的共性利好催化。"],
        "risks": negatives or ["当前没有形成特别突出的共性风险。"],
        "latest": default_latest(market, reports),
    }


def merge_entry(base: dict, overlay: dict) -> dict:
    merged = dict(base)
    for key in ("message", "technical", "latest"):
        if overlay.get(key):
            merged[key] = overlay[key]
    for key in ("catalysts", "risks"):
        if overlay.get(key):
            existing = merged.get(key, [])
            combined = []
            seen = set()
            for item in overlay.get(key, []) + existing:
                normalized = item.strip()
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    combined.append(normalized)
            merged[key] = combined[:4]
    return merged


def resolve_config(args) -> tuple[dict, dict]:
    config_path = Path(args.config).resolve() if args.config else None
    config = json.loads(config_path.read_text()) if config_path else DEFAULT_CONFIG
    overlay_path = Path(args.overlay_file).resolve() if args.overlay_file else None
    if overlay_path is None and config.get("overlay_file"):
        overlay_path = Path(config["overlay_file"])
        if not overlay_path.is_absolute() and config_path is not None:
            overlay_path = (config_path.parent / overlay_path).resolve()
    overlays = load_json_file(overlay_path)
    return config, overlays


def benchmark_cache_path(item: dict, timeframe: str, tushare_mode: str) -> Path:
    slug = f"{item.get('market', 'auto')}__{item['asset']}__{timeframe}__{tushare_mode}".replace("/", "_").replace(" ", "_")
    return ensure_state_dir() / "market_context_cache" / f"{slug}.json"


def load_cached_report(item: dict, timeframe: str, tushare_mode: str, ttl_hours: int) -> dict | None:
    payload = load_json(benchmark_cache_path(item, timeframe, tushare_mode), {})
    if not payload.get("report") or not payload.get("cached_at"):
        return None
    age_seconds = int(datetime.now().timestamp()) - int(payload["cached_at"])
    if age_seconds > ttl_hours * 3600:
        return None
    report = payload["report"]
    report["context_cache_age_hours"] = round(age_seconds / 3600.0, 1)
    return report


def save_cached_report(item: dict, report: dict, timeframe: str, tushare_mode: str) -> None:
    write_json(
        benchmark_cache_path(item, timeframe, tushare_mode),
        {
            "cached_at": int(datetime.now().timestamp()),
            "report": report,
        },
    )


def analyze_market(market_name: str, market_config: dict, memory_file: Path | None, cache_ttl_hours: int) -> list[dict]:
    timeframe = market_config.get("timeframe", "1d")
    tushare_mode = market_config.get("tushare_mode", "http")
    reports = []
    for item in market_config.get("assets", []):
        item_timeframe = item.get("timeframe", timeframe)
        item_tushare_mode = item.get("tushare_mode", tushare_mode)
        try:
            report = analyze(
                asset_query=item["asset"],
                market=item.get("market", "auto"),
                timeframe=item_timeframe,
                memory_file=memory_file,
                tushare_mode=item_tushare_mode,
            )
            save_cached_report(item, report, item_timeframe, item_tushare_mode)
        except Exception:
            report = load_cached_report(item, item_timeframe, item_tushare_mode, cache_ttl_hours)
            if report is None:
                continue
        if item.get("label"):
            report["asset"] = {**report["asset"], "recap_label": item["label"]}
        reports.append(report)
    if not reports:
        raise RuntimeError(f"No usable benchmark reports were produced for market {market_name}.")
    return reports


def main():
    args = parse_args()
    memory_file = Path(args.memory_file) if args.memory_file else None
    config, overlays = resolve_config(args)
    result = {
        "_meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "generator": "build_market_context.py",
            "cache_ttl_hours": args.cache_ttl_hours,
        }
    }
    for market_name, market_config in config.get("markets", {}).items():
        reports = analyze_market(market_name, market_config, memory_file, args.cache_ttl_hours)
        entry = derive_entry(market_name, reports)
        overlay = overlays.get(market_name, {})
        result[market_name] = merge_entry(entry, overlay) if overlay else entry
    output_path = Path(args.output).resolve()
    write_json(output_path, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

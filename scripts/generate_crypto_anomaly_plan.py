#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.parse
from pathlib import Path

from quant_core import (
    analyze,
    derive_trade_framework,
    ensure_state_dir,
    fetch_json,
    load_json,
    recommendation_label,
    send_notification,
    write_json,
)
from scan_crypto_movers import fetch_binance_24h_tickers


DEFAULT_RECOMMENDATION_ALLOWLIST = ["watch-for-buy-confirmation", "buy-or-add"]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate early altcoin anomaly trade plans from short-term momentum, volume, and futures sentiment."
    )
    parser.add_argument("--config", help="Optional config JSON path.")
    parser.add_argument("--quote", default="USDT", help="Quote asset to scan. Defaults to USDT.")
    parser.add_argument("--spot-top", type=int, default=60, help="How many liquid spot candidates to inspect.")
    parser.add_argument("--analyze-top", type=int, default=12, help="How many shortlisted symbols to fully analyze.")
    parser.add_argument("--notify-top", type=int, default=3, help="How many plans to include in the notification.")
    parser.add_argument("--analysis-timeframe", default="1h", choices=["1h", "4h", "1d"])
    parser.add_argument("--min-quote-volume", type=float, default=8_000_000)
    parser.add_argument("--min-price-change-pct", type=float, default=2.5)
    parser.add_argument("--max-price-change-pct", type=float, default=45.0)
    parser.add_argument("--min-anomaly-score", type=int, default=30)
    parser.add_argument("--min-quant-score", type=int, default=20)
    parser.add_argument("--recommendation-allowlist", nargs="*")
    parser.add_argument("--state-file", help="Optional state file path.")
    parser.add_argument("--output", help="Optional output file path.")
    parser.add_argument("--format", default="markdown", choices=["markdown", "json"])
    return parser.parse_args()


def default_state_path() -> Path:
    return ensure_state_dir() / "crypto_anomaly_plan_state.json"


def default_factor_log_path() -> Path:
    return ensure_state_dir() / "crypto_anomaly_factor_log.jsonl"


def pct_change(current: float | None, previous: float | None) -> float | None:
    if current in (None, 0) or previous in (None, 0):
        return None
    return ((float(current) / float(previous)) - 1.0) * 100.0


def build_framework(report: dict) -> dict:
    return derive_trade_framework(
        {
            "current_price": report["current_price"],
            "levels": report["levels"],
            "signals": report["signals"],
            "backtest": report["backtest"],
        }
    )


def posture_cn(value: str | None) -> str:
    return {
        "accumulate": "可分批吸纳",
        "pilot-only": "只适合观察仓",
        "harvest-strength": "适合趁强兑现一部分",
        "protect-capital": "优先保护本金",
        "hold-and-assess": "先拿着评估",
        "trim-first-target": "到第一目标先减仓",
        "scale-out-hard": "接近二目标继续明显减仓",
        "reduce-strength": "反弹以减仓为主",
        "defense-first": "先转防守",
        "hold-core": "核心仓继续拿",
    }.get(value, value or "未定义")


def fetch_binance_klines(symbol: str, interval: str, limit: int = 120) -> list[dict]:
    url = (
        "https://api.binance.com/api/v3/klines"
        f"?symbol={urllib.parse.quote(symbol)}&interval={interval}&limit={limit}"
    )
    payload = fetch_json(url)
    candles = []
    for row in payload:
        candles.append(
            {
                "timestamp": int(row[0] / 1000),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
            }
        )
    return candles


def average(values: list[float]) -> float | None:
    filtered = [value for value in values if value is not None]
    if not filtered:
        return None
    return sum(filtered) / len(filtered)


def relative_volume(volumes: list[float], lookback: int = 20) -> float | None:
    if len(volumes) < lookback + 1:
        return None
    baseline = average(volumes[-(lookback + 1) : -1])
    if baseline in (None, 0):
        return None
    return volumes[-1] / baseline


def breakout_reference(highs: list[float], lookback: int = 20) -> float | None:
    if len(highs) < lookback + 1:
        return None
    return max(highs[-(lookback + 1) : -1])


def compression_ratio(closes: list[float], lookback: int = 20) -> float | None:
    if len(closes) < lookback:
        return None
    window = closes[-lookback:]
    center = average(window)
    if center in (None, 0):
        return None
    return statistics.pstdev(window) / center


def summarize_short_term(symbol: str) -> dict:
    candles_15m = fetch_binance_klines(symbol, "15m", 120)
    candles_1h = fetch_binance_klines(symbol, "1h", 120)

    closes_15m = [candle["close"] for candle in candles_15m]
    highs_15m = [candle["high"] for candle in candles_15m]
    volumes_15m = [candle["volume"] for candle in candles_15m]

    closes_1h = [candle["close"] for candle in candles_1h]
    highs_1h = [candle["high"] for candle in candles_1h]
    volumes_1h = [candle["volume"] for candle in candles_1h]

    return {
        "current_price": closes_15m[-1],
        "change_15m_4bars_pct": pct_change(closes_15m[-1], closes_15m[-5] if len(closes_15m) >= 5 else None),
        "change_1h_6bars_pct": pct_change(closes_1h[-1], closes_1h[-7] if len(closes_1h) >= 7 else None),
        "relative_volume_15m": relative_volume(volumes_15m, 20),
        "relative_volume_1h": relative_volume(volumes_1h, 20),
        "breakout_ref_15m": breakout_reference(highs_15m, 20),
        "breakout_ref_1h": breakout_reference(highs_1h, 20),
        "compression_15m": compression_ratio(closes_15m, 20),
        "compression_1h": compression_ratio(closes_1h, 20),
    }


def fetch_funding_rate_pct(symbol: str) -> float | None:
    try:
        payload = fetch_json(
            f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={urllib.parse.quote(symbol)}"
        )
    except Exception:
        return None
    value = payload.get("lastFundingRate")
    if value in (None, ""):
        return None
    return float(value) * 100.0


def fetch_open_interest_change_pct(symbol: str, period: str = "5m", limit: int = 12) -> float | None:
    try:
        payload = fetch_json(
            "https://fapi.binance.com/futures/data/openInterestHist"
            f"?symbol={urllib.parse.quote(symbol)}&period={period}&limit={limit}"
        )
    except Exception:
        return None
    if not isinstance(payload, list) or len(payload) < 2:
        return None
    first = payload[0].get("sumOpenInterestValue") or payload[0].get("sumOpenInterest")
    last = payload[-1].get("sumOpenInterestValue") or payload[-1].get("sumOpenInterest")
    if first in (None, "", "0") or last in (None, ""):
        return None
    return pct_change(float(last), float(first))


def score_anomaly(short_term: dict, ticker: dict, funding_rate_pct: float | None, oi_change_pct: float | None) -> tuple[int, list[str], list[str]]:
    score = 0
    reasons: list[str] = []
    risks: list[str] = []

    day_gain = float(ticker["price_change_pct"])
    if 3 <= day_gain <= 25:
        score += 10
        reasons.append("24h 涨幅还在可追踪区间，没有进入最极端的抛物线阶段。")
    elif day_gain > 35:
        score -= 8
        risks.append("24h 涨幅已经过大，容易进入高位震荡或冲高回落。")

    change_15m = short_term.get("change_15m_4bars_pct") or 0.0
    if change_15m >= 4:
        score += 20
        reasons.append("15 分钟级别动量明显抬升，异动已经从分时级别开始发酵。")
    elif change_15m >= 2:
        score += 12
        reasons.append("15 分钟级别已经出现可见抬升。")

    change_1h = short_term.get("change_1h_6bars_pct") or 0.0
    if change_1h >= 8:
        score += 20
        reasons.append("1 小时级别涨速明显，说明不仅是单根拉升，趋势已有延续。")
    elif change_1h >= 4:
        score += 12
        reasons.append("1 小时级别趋势已经开始走强。")

    rv_15m = short_term.get("relative_volume_15m")
    if rv_15m is not None:
        if rv_15m >= 2.5:
            score += 18
            reasons.append("15 分钟相对成交量明显放大，属于典型异动放量。")
        elif rv_15m >= 1.6:
            score += 10
            reasons.append("15 分钟相对成交量已经高于常态。")
        elif rv_15m < 0.9:
            risks.append("15 分钟量能不够突出，短线持续性要打折。")

    rv_1h = short_term.get("relative_volume_1h")
    if rv_1h is not None:
        if rv_1h >= 2.0:
            score += 14
            reasons.append("1 小时级别也有成交量放大，说明不是纯分时偷袭。")
        elif rv_1h < 0.9:
            risks.append("1 小时量能没有跟上，可能只是局部拉抬。")

    current_price = short_term.get("current_price")
    breakout_ref_15m = short_term.get("breakout_ref_15m")
    if current_price and breakout_ref_15m and current_price >= breakout_ref_15m * 0.997:
        score += 10
        reasons.append("价格已经逼近或轻微突破 15 分钟短期高点，具备继续扩散的条件。")

    compression_15m = short_term.get("compression_15m")
    if compression_15m is not None and compression_15m <= 0.018:
        score += 8
        reasons.append("15 分钟波动压缩后放量，更像突破前后的异动形态。")

    if oi_change_pct is not None:
        if oi_change_pct >= 8:
            score += 16
            reasons.append("合约未平仓量同步增长，说明新资金也在进来。")
        elif oi_change_pct >= 3:
            score += 8
            reasons.append("未平仓量温和上升，说明不只是现货一把拉。")
        elif oi_change_pct <= -3:
            risks.append("未平仓量没有配合，短线可能是空头回补而不是真正扩张。")

    if funding_rate_pct is not None:
        if funding_rate_pct >= 0.08:
            score -= 10
            risks.append("资金费率已经偏热，继续追高的性价比下降。")
        elif funding_rate_pct <= -0.02:
            score += 4
            reasons.append("资金费率不拥挤，情绪还没有完全过热。")

    return max(-100, min(100, score)), reasons[:5], risks[:5]


def build_plan(item: dict, config: dict) -> dict:
    ticker = item["ticker"]
    short_term = item["short_term"]
    report = item["report"]
    levels = report["levels"]
    framework = build_framework(report)
    anomaly_score = item["anomaly_score"]
    current_price = float(report["current_price"])
    confirmation = float(levels.get("confirmation_buy_level") or levels["best_buy_level"])
    observe = float(levels["best_buy_level"])
    first_sell = float(levels["best_sell_level"])
    funding_rate_pct = item.get("funding_rate_pct")
    oi_change_pct = item.get("oi_change_pct")

    over_confirm_pct = pct_change(current_price, confirmation) or 0.0
    if framework["setup_phase"] == "extended-zone" or framework["reward_risk_grade"] == "weak":
        action = "wait-pullback"
        summary_cn = "异动已经被看到，但位置和盈亏比一般，优先等回踩。"
        execution_cn = f"计划：先不追；等回踩 {observe:.4f} 附近，或下一次整理后再看。"
    elif anomaly_score >= 72 and over_confirm_pct <= 4 and report["recommendation"] == "buy-or-add":
        action = "starter-now"
        summary_cn = "异动、量能和量化过滤同时共振，可以先建小试探仓。"
        execution_cn = (
            f"计划：先建 {config.get('starter_position_pct', 10)}% 试探仓；只有继续站稳 {confirmation:.4f} 上方，再逐步加到 "
            f"{config.get('max_position_pct', 25)}% 上限。"
        )
    elif current_price < confirmation:
        action = "wait-breakout"
        summary_cn = "异动已出现，但还没真正站稳确认位，优先等突破。"
        execution_cn = (
            f"计划：先观察；只有价格有效站上 {confirmation:.4f}，再启动 "
            f"{config.get('starter_position_pct', 10)}% 试探仓。"
        )
    else:
        action = "wait-pullback"
        summary_cn = "已经启动，但位置偏高，优先等回踩到更舒服的位置。"
        execution_cn = (
            f"计划：先不追；等回踩 {observe:.4f} 附近，或量价重新整理后再看。"
        )

    metrics_cn = [
        f"24h涨幅 {ticker['price_change_pct']:.2f}%",
        f"15m动量 {short_term['change_15m_4bars_pct']:.2f}%" if short_term.get("change_15m_4bars_pct") is not None else None,
        f"1h动量 {short_term['change_1h_6bars_pct']:.2f}%" if short_term.get("change_1h_6bars_pct") is not None else None,
        f"15m量比 {short_term['relative_volume_15m']:.2f}" if short_term.get("relative_volume_15m") is not None else None,
        f"OI变化 {oi_change_pct:.2f}%" if oi_change_pct is not None else None,
        f"资金费率 {funding_rate_pct:.4f}%" if funding_rate_pct is not None else None,
    ]
    metrics_cn = [value for value in metrics_cn if value]
    time_stop_cn = f"时间止损：若 {framework['time_stop_bars']} 根K线内都没走向第一卖点，就把这轮计划降级处理。"
    framework_cn = (
        f"阶段 {framework['setup_phase']} | 盈亏比 {framework['reward_to_stop_ratio']} | "
        f"验证质量 {framework['validation_quality']} | 风险级别 {framework['risk_tier']} | "
        f"仓位姿态 {posture_cn(framework['position_posture'])} | 卖出姿态 {posture_cn(framework['exit_posture'])}"
    )

    return {
        "symbol": ticker["symbol"],
        "base_asset": ticker["base_asset"],
        "action": action,
        "anomaly_score": anomaly_score,
        "quant_score": report["score"],
        "recommendation": report["recommendation"],
        "current_price": report["current_price"],
        "observe_buy": levels["best_buy_level"],
        "confirmation_buy": levels.get("confirmation_buy_level"),
        "first_sell": levels["best_sell_level"],
        "stop_loss": levels["stop_loss"],
        "defensive_sell_trigger": levels["defensive_sell_trigger"],
        "starter_position_pct": int(config.get("starter_position_pct", 10)),
        "max_position_pct": int(config.get("max_position_pct", 25)),
        "summary_cn": summary_cn,
        "execution_cn": execution_cn,
        "time_stop_cn": time_stop_cn,
        "framework_cn": framework_cn,
        "trade_framework": framework,
        "invalidation_cn": (
            f"失效条件：跌破防守线 {levels['defensive_sell_trigger']} 先转谨慎；跌破止损参考 {levels['stop_loss']} 视为本轮计划失效。"
        ),
        "metrics_cn": metrics_cn,
        "reasons_cn": item["reasons"],
        "risks_cn": item["risks"],
    }


def append_factor_log(analyzed: list[dict], plans: list[dict]) -> None:
    plan_map = {plan["symbol"]: plan for plan in plans}
    path = default_factor_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for item in analyzed:
            report = item["report"]
            short_term = item["short_term"]
            ticker = item["ticker"]
            symbol = ticker["symbol"]
            plan = plan_map.get(symbol)
            row = {
                "recorded_at": int(time.time()),
                "symbol": symbol,
                "base_asset": ticker["base_asset"],
                "price": report["current_price"],
                "day_gain_pct": ticker["price_change_pct"],
                "quote_volume": ticker["quote_volume"],
                "anomaly_score": item["anomaly_score"],
                "quant_score": report["score"],
                "recommendation": report["recommendation"],
                "qualified": plan is not None,
                "plan_action": plan["action"] if plan else None,
                "starter_position_pct": plan["starter_position_pct"] if plan else None,
                "max_position_pct": plan["max_position_pct"] if plan else None,
                "setup_phase": plan["trade_framework"]["setup_phase"] if plan else None,
                "reward_to_stop_ratio": plan["trade_framework"]["reward_to_stop_ratio"] if plan else None,
                "validation_quality": plan["trade_framework"]["validation_quality"] if plan else None,
                "risk_tier": plan["trade_framework"]["risk_tier"] if plan else None,
                "position_posture": plan["trade_framework"]["position_posture"] if plan else None,
                "exit_posture": plan["trade_framework"]["exit_posture"] if plan else None,
                "observe_buy": report["levels"]["best_buy_level"],
                "confirmation_buy": report["levels"].get("confirmation_buy_level"),
                "first_sell": report["levels"]["best_sell_level"],
                "stop_loss": report["levels"]["stop_loss"],
                "change_15m_4bars_pct": short_term.get("change_15m_4bars_pct"),
                "change_1h_6bars_pct": short_term.get("change_1h_6bars_pct"),
                "relative_volume_15m": short_term.get("relative_volume_15m"),
                "relative_volume_1h": short_term.get("relative_volume_1h"),
                "breakout_ref_15m": short_term.get("breakout_ref_15m"),
                "breakout_ref_1h": short_term.get("breakout_ref_1h"),
                "compression_15m": short_term.get("compression_15m"),
                "compression_1h": short_term.get("compression_1h"),
                "funding_rate_pct": item.get("funding_rate_pct"),
                "oi_change_pct": item.get("oi_change_pct"),
                "reasons_cn": item.get("reasons", []),
                "risks_cn": item.get("risks", []),
            }
            handle.write(json.dumps(row, ensure_ascii=True) + "\n")


def render_markdown(plans: list[dict], analyzed: list[dict], config: dict) -> str:
    lines = [
        "# Crypto Altcoin Anomaly Plans",
        "",
        f"- Quote asset: {config.get('quote', 'USDT')}",
        f"- Shortlisted candidates: {len(analyzed)}",
        f"- Plans generated: {len(plans)}",
        f"- Analysis timeframe: {config.get('analysis_timeframe', '1h')}",
        "",
    ]
    if not plans:
        lines.append("- No anomaly plans passed the current filter set.")
        return "\n".join(lines) + "\n"
    for idx, plan in enumerate(plans, start=1):
        lines.extend(
            [
                f"## {idx}. {plan['base_asset']} ({plan['symbol']})",
                "",
                f"- Action: {plan['action']}",
                f"- Anomaly / quant score: {plan['anomaly_score']} / {plan['quant_score']}",
                f"- Current price: {plan['current_price']}",
                f"- Observe buy: {plan['observe_buy']}",
                f"- Confirmation buy: {plan['confirmation_buy']}",
                f"- First sell: {plan['first_sell']}",
                f"- Stop loss: {plan['stop_loss']}",
                f"- Starter / max position: {plan['starter_position_pct']}% / {plan['max_position_pct']}%",
                f"- Summary: {plan['summary_cn']}",
                f"- Execution: {plan['execution_cn']}",
                f"- Time stop: {plan['time_stop_cn']}",
                f"- Framework: {plan['framework_cn']}",
                f"- Metrics: {' | '.join(plan['metrics_cn'])}",
            ]
        )
    return "\n".join(lines) + "\n"


def render_notification(plans: list[dict], config: dict) -> str:
    if not plans:
        return (
            "【交易信号】\n[中文]\n山寨异动计划雷达：本轮没有新出现且同时满足异动与计划条件的币种。\n\n"
            "[Trading Signal]\n[EN]\nAltcoin anomaly radar: no newly qualifying symbols passed the anomaly-plus-plan filters this cycle."
        )
    lines = [
        "【交易信号】",
        "[中文]",
        "山寨异动计划雷达：以下币种刚进入“异动 + 计划条件”集合，只生成计划，不自动下单。",
    ]
    for plan in plans[: int(config.get("notify_top", 3))]:
        lines.extend(
            [
                f"- {plan['base_asset']}：{plan['summary_cn']}",
                f"  异动分 {plan['anomaly_score']} | 量化分 {plan['quant_score']} | 当前价 {plan['current_price']}",
                f"  观察买点 {plan['observe_buy']} | 确认位 {plan['confirmation_buy']} | 第一卖点 {plan['first_sell']}",
                f"  {plan['execution_cn']}",
                f"  {plan['time_stop_cn']}",
                f"  {plan['framework_cn']}",
            ]
        )
        if plan["metrics_cn"]:
            lines.append(f"  指标快照：{' | '.join(plan['metrics_cn'])}")
    lines.extend(
        [
            "",
            "[Trading Signal]",
            "[EN]",
            "Altcoin anomaly radar: the symbols below newly entered the anomaly-plus-plan set. Plans only, no automatic execution.",
        ]
    )
    for plan in plans[: int(config.get("notify_top", 3))]:
        lines.append(
            f"- {plan['base_asset']}: anomaly {plan['anomaly_score']} | quant {plan['quant_score']} | "
            f"price {plan['current_price']} | observe {plan['observe_buy']} | confirm {plan['confirmation_buy']} | first sell {plan['first_sell']} | "
            f"phase {plan['trade_framework']['setup_phase']} | rr {plan['trade_framework']['reward_to_stop_ratio']}"
        )
    return "\n".join(lines)


def qualifies(item: dict, config: dict) -> bool:
    report = item["report"]
    if item["anomaly_score"] < int(config.get("min_anomaly_score", 55)):
        return False
    if report["score"] < int(config.get("min_quant_score", 20)):
        return False
    allowlist = config.get("recommendation_allowlist") or DEFAULT_RECOMMENDATION_ALLOWLIST
    return report["recommendation"] in allowlist


def analyze_candidate(candidate: dict, config: dict) -> dict | None:
    try:
        short_term = summarize_short_term(candidate["symbol"])
        report = analyze(
            asset_query=candidate["symbol"],
            market="crypto",
            timeframe=config.get("analysis_timeframe", "1h"),
        )
    except Exception:
        return None
    funding_rate_pct = fetch_funding_rate_pct(candidate["symbol"])
    oi_change_pct = fetch_open_interest_change_pct(candidate["symbol"], period=config.get("oi_period", "5m"), limit=12)
    anomaly_score, reasons, risks = score_anomaly(short_term, candidate, funding_rate_pct, oi_change_pct)
    return {
        "ticker": candidate,
        "short_term": short_term,
        "report": report,
        "funding_rate_pct": funding_rate_pct,
        "oi_change_pct": oi_change_pct,
        "anomaly_score": anomaly_score,
        "reasons": reasons,
        "risks": risks,
    }


def should_send_new(plan: dict, planner_state: dict) -> bool:
    return plan["symbol"] not in set(planner_state.get("active_symbols", []))


def main():
    args = parse_args()
    config = {}
    if args.config:
        config = json.loads(Path(args.config).read_text())

    if args.quote:
        config["quote"] = args.quote
    if args.spot_top is not None:
        config["spot_top"] = args.spot_top
    if args.analyze_top is not None:
        config["analyze_top"] = args.analyze_top
    if args.notify_top is not None:
        config["notify_top"] = args.notify_top
    if args.analysis_timeframe:
        config["analysis_timeframe"] = args.analysis_timeframe
    if args.min_quote_volume is not None:
        config["min_quote_volume"] = args.min_quote_volume
    if args.min_price_change_pct is not None:
        config["min_price_change_pct"] = args.min_price_change_pct
    if args.max_price_change_pct is not None:
        config["max_price_change_pct"] = args.max_price_change_pct
    if args.min_anomaly_score is not None:
        config["min_anomaly_score"] = args.min_anomaly_score
    if args.min_quant_score is not None:
        config["min_quant_score"] = args.min_quant_score
    if args.recommendation_allowlist:
        config["recommendation_allowlist"] = args.recommendation_allowlist

    config.setdefault("quote", "USDT")
    config.setdefault("spot_top", 60)
    config.setdefault("analyze_top", 12)
    config.setdefault("notify_top", 3)
    config.setdefault("analysis_timeframe", "1h")
    config.setdefault("min_quote_volume", 8_000_000)
    config.setdefault("min_price_change_pct", 2.5)
    config.setdefault("max_price_change_pct", 45.0)
    config.setdefault("min_anomaly_score", 30)
    config.setdefault("min_quant_score", 20)
    config.setdefault("recommendation_allowlist", DEFAULT_RECOMMENDATION_ALLOWLIST)
    config.setdefault("starter_position_pct", 10)
    config.setdefault("max_position_pct", 25)
    config.setdefault("notify_new_only", True)
    config.setdefault("oi_period", "5m")

    tickers = fetch_binance_24h_tickers(config["quote"])
    candidates = []
    for ticker in tickers:
        if ticker["quote_volume"] < float(config["min_quote_volume"]):
            continue
        if ticker["price_change_pct"] < float(config["min_price_change_pct"]):
            continue
        if ticker["price_change_pct"] > float(config["max_price_change_pct"]):
            continue
        candidates.append(ticker)
        if len(candidates) >= int(config["spot_top"]):
            break

    analyzed = []
    for candidate in candidates[: int(config["analyze_top"])]:
        item = analyze_candidate(candidate, config)
        if item:
            analyzed.append(item)

    analyzed.sort(key=lambda item: (item["anomaly_score"], item["report"]["score"]), reverse=True)
    plans = [build_plan(item, config) for item in analyzed if qualifies(item, config)]
    append_factor_log(analyzed, plans)

    rendered = (
        json.dumps(
            {
                "generated_at": int(time.time()),
                "config": config,
                "plans": plans,
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n"
        if args.format == "json"
        else render_markdown(plans, analyzed, config)
    )
    if args.output:
        Path(args.output).write_text(rendered)

    state_path = Path(args.state_file) if args.state_file else default_state_path()
    state = load_json(state_path, {"planners": {}})
    planner_id = config.get("id", f"crypto-anomaly-plan:{config['quote']}:{config['analysis_timeframe']}")
    planner_state = state.setdefault("planners", {}).setdefault(planner_id, {"sent": {}, "last_run": None, "active_symbols": []})

    notifier = config.get("notifier")
    if config.get("notify_new_only"):
        sendable = [plan for plan in plans if should_send_new(plan, planner_state)]
    else:
        sendable = plans[: int(config.get("notify_top", 3))]
    if notifier and sendable:
        message = render_notification(sendable, config)
        send_notification(notifier, message, {"message": message, "plans": sendable})
        now = int(time.time())
        for plan in sendable:
            planner_state.setdefault("sent", {})[plan["symbol"]] = now

    planner_state["active_symbols"] = sorted(plan["symbol"] for plan in plans)
    planner_state["last_run"] = int(time.time())
    write_json(state_path, state)

    print(rendered, end="")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from quant_core import ensure_state_dir, load_json, recommendation_label, send_notification, write_json
from scan_crypto_movers import (
    DEFAULT_RECOMMENDATION_ALLOWLIST,
    analyze_candidates,
    fetch_binance_24h_tickers,
    select_candidates,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate staged crypto trade plans from Binance movers and push them to a channel."
    )
    parser.add_argument("--config", help="Optional config JSON path.")
    parser.add_argument("--quote", default="USDT", help="Quote asset to scan. Defaults to USDT.")
    parser.add_argument("--top", type=int, default=30, help="How many raw 24h gainers to keep before analysis.")
    parser.add_argument(
        "--analyze-top",
        type=int,
        default=8,
        help="How many filtered gainers to run through the quant engine.",
    )
    parser.add_argument(
        "--notify-top",
        type=int,
        default=3,
        help="How many trade plans to include in the notification.",
    )
    parser.add_argument("--timeframe", default="4h", choices=["1h", "4h", "1d"])
    parser.add_argument("--min-quote-volume", type=float, default=10_000_000)
    parser.add_argument("--min-price-change-pct", type=float, default=5.0)
    parser.add_argument("--min-score", type=int, default=20)
    parser.add_argument("--recommendation-allowlist", nargs="*")
    parser.add_argument("--memory-file", help="Optional learning memory path.")
    parser.add_argument("--state-file", help="Optional state file path.")
    parser.add_argument("--output", help="Optional output file path.")
    parser.add_argument("--format", default="markdown", choices=["markdown", "json"])
    return parser.parse_args()


def default_state_path() -> Path:
    return ensure_state_dir() / "crypto_trade_plan_state.json"


def pct_diff(base: float | None, price: float | None) -> float | None:
    if base in (None, 0) or price in (None, None):
        return None
    return ((float(price) / float(base)) - 1.0) * 100.0


def plan_action(item: dict, config: dict) -> tuple[str, str]:
    report = item["report"]
    ticker = item["ticker"]
    levels = report["levels"]
    price = float(report["current_price"])
    observe = float(levels["best_buy_level"])
    confirmation = float(levels.get("confirmation_buy_level") or observe)
    day_gain = float(ticker["price_change_pct"])
    above_confirm = pct_diff(confirmation, price) or 0.0
    near_observe = abs(pct_diff(observe, price) or 0.0) <= float(config.get("observe_band_pct", 3.0))
    max_chase = float(config.get("max_chase_above_confirmation_pct", 4.0))
    avoid_parabolic = float(config.get("avoid_parabolic_above_pct", 80.0))

    if day_gain >= avoid_parabolic:
        return (
            "watch-only",
            "24h 涨幅过大，先不追，优先等待回踩或更稳的二次确认。",
        )
    if report["recommendation"] == "buy-or-add" and above_confirm <= max_chase:
        return (
            "starter-now",
            "当前可建试探仓，但仍按计划分批，不直接满仓追击。",
        )
    if near_observe:
        return (
            "starter-now",
            "当前价格就在观察买点附近，可以按计划先建试探仓。",
        )
    if price < confirmation:
        return (
            "wait-breakout",
            "还没真正站稳确认位，优先等突破后再扩大仓位。",
        )
    if above_confirm > max_chase:
        return (
            "wait-pullback",
            "已经高于确认位太多，盈亏比变差，优先等回踩再说。",
        )
    return (
        "watch-only",
        "当前更适合观察，不急着追价。",
    )


def plan_positioning(item: dict, config: dict) -> tuple[int, int]:
    report = item["report"]
    score = int(report["score"])
    base_starter = int(config.get("starter_position_pct", 10))
    base_max = int(config.get("max_position_pct", 25))
    if score >= 50:
        return min(base_starter + 2, base_max), base_max
    if score >= 35:
        return base_starter, base_max
    return max(base_starter - 2, 6), max(base_max - 5, 15)


def build_plan(item: dict, config: dict) -> dict:
    report = item["report"]
    ticker = item["ticker"]
    levels = report["levels"]
    signals = report["signals"]
    action, action_cn = plan_action(item, config)
    starter_pct, max_pct = plan_positioning(item, config)
    price = float(report["current_price"])
    observe = float(levels["best_buy_level"])
    confirmation = float(levels.get("confirmation_buy_level") or observe)
    stop = float(levels["stop_loss"])
    defensive = float(levels["defensive_sell_trigger"])
    first_sell = float(levels["best_sell_level"])
    day_gain = float(ticker["price_change_pct"])

    if action == "starter-now":
        execution_cn = (
            f"计划：先建 {starter_pct}% 试探仓；若后续站稳 {confirmation:.4f} 上方，再加到 {max_pct}% 上限。"
        )
    elif action == "wait-breakout":
        execution_cn = (
            f"计划：先不进场；只有价格有效站上 {confirmation:.4f}，再启动 {starter_pct}% 试探仓。"
        )
    elif action == "wait-pullback":
        execution_cn = (
            f"计划：先不追；等回踩 {observe:.4f} 附近再看是否给 {starter_pct}% 试探仓机会。"
        )
    else:
        execution_cn = "计划：本轮先观察，不主动追击。"

    invalidation_cn = (
        f"失效条件：跌破防守线 {defensive:.4f} 先转谨慎；跌破止损参考 {stop:.4f} 视为计划失效。"
    )
    catalyst_cn = (
        f"触发背景：24h 涨幅 {day_gain:.2f}% | 评分 {report['score']} | "
        f"RSI {signals.get('rsi14')} | 当前判断 {recommendation_label(report['recommendation'])}"
    )

    return {
        "symbol": ticker["symbol"],
        "base_asset": ticker["base_asset"],
        "action": action,
        "starter_position_pct": starter_pct,
        "max_position_pct": max_pct,
        "current_price": report["current_price"],
        "observe_buy": levels["best_buy_level"],
        "confirmation_buy": levels.get("confirmation_buy_level"),
        "first_sell": levels["best_sell_level"],
        "defensive_sell_trigger": levels["defensive_sell_trigger"],
        "stop_loss": levels["stop_loss"],
        "day_gain_pct": ticker["price_change_pct"],
        "score": report["score"],
        "recommendation": report["recommendation"],
        "summary_cn": action_cn,
        "execution_cn": execution_cn,
        "invalidation_cn": invalidation_cn,
        "catalyst_cn": catalyst_cn,
        "reasons_cn": report.get("reasons", [])[:3],
        "risks_cn": report.get("risks", [])[:3],
    }


def render_markdown(plans: list[dict], config: dict, analyzed: list[dict]) -> str:
    lines = [
        "# Crypto Trade Plans",
        "",
        f"- Quote asset: {config.get('quote', 'USDT')}",
        f"- Timeframe: {config.get('timeframe', '4h')}",
        f"- Quant-analyzed movers: {len(analyzed)}",
        f"- Plans generated: {len(plans)}",
        "",
    ]
    if not plans:
        lines.append("- No trade plans met the current filter set.")
        return "\n".join(lines) + "\n"
    for idx, plan in enumerate(plans, start=1):
        lines.extend(
            [
                f"## {idx}. {plan['base_asset']} ({plan['symbol']})",
                "",
                f"- Action: {plan['action']}",
                f"- Current price: {plan['current_price']}",
                f"- Observe buy: {plan['observe_buy']}",
                f"- Confirmation buy: {plan['confirmation_buy']}",
                f"- First sell: {plan['first_sell']}",
                f"- Defensive trigger: {plan['defensive_sell_trigger']}",
                f"- Stop loss: {plan['stop_loss']}",
                f"- Starter / max position: {plan['starter_position_pct']}% / {plan['max_position_pct']}%",
                f"- 24h gain: {plan['day_gain_pct']:.2f}%",
                f"- Score: {plan['score']}",
                f"- View: {recommendation_label(plan['recommendation'])}",
                f"- Summary: {plan['summary_cn']}",
                f"- Execution: {plan['execution_cn']}",
                f"- Invalidation: {plan['invalidation_cn']}",
            ]
        )
    return "\n".join(lines) + "\n"


def render_notification(plans: list[dict], config: dict) -> str:
    if not plans:
        return (
            "【交易信号】\n[中文]\nOpenAlice 风格数字货币交易计划：本轮没有符合条件的计划单。\n\n"
            "[Trading Signal]\n[EN]\nOpenAlice-style crypto trade plans: no staged plans passed the current filters."
        )
    lines = [
        "【交易信号】",
        "[中文]",
        "OpenAlice 风格数字货币交易计划：只生成计划，不自动下单。",
    ]
    for plan in plans[: int(config.get("notify_top", 3))]:
        lines.extend(
            [
                f"- {plan['base_asset']}：{plan['summary_cn']}",
                f"  当前价 {plan['current_price']} | 观察买点 {plan['observe_buy']} | 确认位 {plan['confirmation_buy']} | 第一卖点 {plan['first_sell']}",
                f"  {plan['execution_cn']}",
                f"  {plan['invalidation_cn']}",
            ]
        )
    lines.extend(
        [
            "",
            "[Trading Signal]",
            "[EN]",
            "OpenAlice-style crypto trade plans: staged plans only, no automatic execution.",
        ]
    )
    for plan in plans[: int(config.get("notify_top", 3))]:
        lines.append(
            f"- {plan['base_asset']}: price {plan['current_price']} | observe {plan['observe_buy']} | "
            f"confirm {plan['confirmation_buy']} | first sell {plan['first_sell']} | "
            f"starter/max {plan['starter_position_pct']}%/{plan['max_position_pct']}%"
        )
    return "\n".join(lines)


def should_send(plan: dict, state_entry: dict, config: dict) -> bool:
    last_sent = state_entry.setdefault("sent", {}).get(plan["symbol"], 0)
    cooldown_hours = float(config.get("cooldown_hours", 12))
    return (time.time() - last_sent) >= cooldown_hours * 3600


def is_new_qualifying_plan(plan: dict, state_entry: dict) -> bool:
    active_symbols = set(state_entry.get("active_symbols", []))
    return plan["symbol"] not in active_symbols


def main():
    args = parse_args()
    config = {}
    if args.config:
        config = json.loads(Path(args.config).read_text())
    if args.quote:
        config["quote"] = args.quote
    if args.top is not None:
        config["top"] = args.top
    if args.analyze_top is not None:
        config["analyze_top"] = args.analyze_top
    if args.notify_top is not None:
        config["notify_top"] = args.notify_top
    if args.timeframe:
        config["timeframe"] = args.timeframe
    if args.min_quote_volume is not None:
        config["min_quote_volume"] = args.min_quote_volume
    if args.min_price_change_pct is not None:
        config["min_price_change_pct"] = args.min_price_change_pct
    if args.min_score is not None:
        config["min_score"] = args.min_score
    if args.recommendation_allowlist:
        config["recommendation_allowlist"] = args.recommendation_allowlist

    config.setdefault("quote", "USDT")
    config.setdefault("top", 30)
    config.setdefault("analyze_top", 8)
    config.setdefault("notify_top", 3)
    config.setdefault("timeframe", "4h")
    config.setdefault("min_quote_volume", 10_000_000)
    config.setdefault("min_price_change_pct", 5.0)
    config.setdefault("min_score", 20)
    config.setdefault("recommendation_allowlist", DEFAULT_RECOMMENDATION_ALLOWLIST)
    config.setdefault("starter_position_pct", 10)
    config.setdefault("max_position_pct", 25)
    config.setdefault("observe_band_pct", 3.0)
    config.setdefault("max_chase_above_confirmation_pct", 4.0)
    config.setdefault("avoid_parabolic_above_pct", 80.0)
    config.setdefault("cooldown_hours", 12)
    config.setdefault("notify_new_only", False)

    memory_file = Path(args.memory_file) if args.memory_file else None
    tickers = fetch_binance_24h_tickers(config["quote"])
    candidates = select_candidates(tickers, config)
    analyzed = analyze_candidates(candidates, config, memory_file)
    plans = [
        build_plan(item, config)
        for item in analyzed
        if item.get("report")
        and item["report"].get("score", -999) >= int(config["min_score"])
        and item["report"].get("recommendation") in (config.get("recommendation_allowlist") or DEFAULT_RECOMMENDATION_ALLOWLIST)
    ]

    rendered = (
        json.dumps(
            {
                "generated_at": int(time.time()),
                "config": config,
                "plans": plans,
                "analyzed": analyzed,
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n"
        if args.format == "json"
        else render_markdown(plans, config, analyzed)
    )

    if args.output:
        Path(args.output).write_text(rendered)

    state_path = Path(args.state_file) if args.state_file else default_state_path()
    state = load_json(state_path, {"planners": {}})
    planner_id = config.get("id", f"crypto-trade-plan:{config['quote']}:{config['timeframe']}")
    planner_state = state.setdefault("planners", {}).setdefault(planner_id, {"sent": {}, "last_run": None})
    if "active_symbols" not in planner_state:
        planner_state["active_symbols"] = sorted(planner_state.get("sent", {}).keys())

    notifier = config.get("notifier")
    if config.get("notify_new_only"):
        sendable = [plan for plan in plans if is_new_qualifying_plan(plan, planner_state)]
    else:
        sendable = [plan for plan in plans if should_send(plan, planner_state, config)]
    if notifier and sendable:
        message = render_notification(sendable, config)
        send_notification(notifier, message, {"message": message, "plans": sendable})
        now = int(time.time())
        for plan in sendable:
            planner_state["sent"][plan["symbol"]] = now
    planner_state["active_symbols"] = sorted(plan["symbol"] for plan in plans)
    planner_state["last_run"] = int(time.time())
    write_json(state_path, state)

    print(rendered, end="")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from quant_core import (
    analyze,
    default_monitor_state_path,
    load_json,
    recommendation_label,
    send_notification,
    write_json,
)


def parse_args():
    parser = argparse.ArgumentParser(description="Monitor a stock or crypto asset and send alerts when rules fire.")
    parser.add_argument("--config", required=True, help="Path to monitor config JSON.")
    parser.add_argument("--once", action="store_true", help="Run one cycle and exit.")
    parser.add_argument("--cycles", type=int, help="Maximum cycles before exiting.")
    parser.add_argument("--memory-file", help="Optional learning memory path.")
    parser.add_argument("--state-file", help="Optional monitor state path.")
    parser.add_argument(
        "--tushare-mode",
        choices=["http", "sdk"],
        help="Override the config Tushare mode for A-share analysis. Defaults to config value, then http.",
    )
    return parser.parse_args()


def should_fire(rule: dict, report: dict, previous: dict | None) -> tuple[bool, str]:
    kind = rule["kind"]
    value = rule.get("value")
    score = report["score"]
    price = report["current_price"]
    recommendation = report["recommendation"]
    previous_score = previous.get("score") if previous else None
    previous_price = previous.get("current_price") if previous else None
    previous_recommendation = previous.get("recommendation") if previous else None

    if kind == "score_at_least" and score >= value:
        return True, f"score {score} is at or above {value}"
    if kind == "score_at_most" and score <= value:
        return True, f"score {score} is at or below {value}"
    if kind == "price_at_or_above" and price >= value:
        return True, f"price {price} is at or above {value}"
    if kind == "price_at_or_below" and price <= value:
        return True, f"price {price} is at or below {value}"
    if kind == "score_crosses_above" and previous_score is not None and previous_score < value <= score:
        return True, f"score crossed above {value}"
    if kind == "score_crosses_below" and previous_score is not None and previous_score > value >= score:
        return True, f"score crossed below {value}"
    if kind == "price_crosses_above" and previous_price is not None and previous_price < value <= price:
        return True, f"price crossed above {value}"
    if kind == "price_crosses_below" and previous_price is not None and previous_price > value >= price:
        return True, f"price crossed below {value}"
    if kind == "recommendation_changes_to" and recommendation == value and previous_recommendation != recommendation:
        return True, f"recommendation changed to {recommendation_label(recommendation)}"
    return False, ""


def default_position_suggestion(rule: dict, report: dict) -> tuple[str, str]:
    kind = rule.get("kind")
    name = rule.get("name", "")
    recommendation = report["recommendation"]
    if "breakout" in name or kind in {"price_crosses_above", "price_at_or_above"}:
        return (
            "建议仓位：先建 20% 试探仓，放量站稳后再加到 40%-50%。",
            "Position sizing: start with a 20% starter position, then add toward 40%-50% only if the breakout holds.",
        )
    if kind in {"price_at_or_below", "price_crosses_below"}:
        return (
            "建议仓位：先建 25%-30% 分批仓位，若二次回踩不破再继续加仓。",
            "Position sizing: start with a 25%-30% scale-in position and add only if the retest holds.",
        )
    if recommendation == "watch-for-buy-confirmation":
        return (
            "建议仓位：先建 15%-20% 观察仓，等待确认后再扩大仓位。",
            "Position sizing: start with a 15%-20% pilot position and size up only after confirmation.",
        )
    return (
        "建议仓位：控制在 15%-25% 试探仓，等待下一次确认信号。",
        "Position sizing: keep this to a 15%-25% test position until a stronger confirmation appears.",
    )


def entry_context(config: dict, rule: dict, report: dict) -> tuple[str, str]:
    entry_price = rule.get("entry_price", config.get("entry_price"))
    if entry_price in (None, ""):
        return "", ""
    try:
        entry_value = float(entry_price)
    except (TypeError, ValueError):
        return "", ""
    current_price = report["current_price"]
    diff_value = current_price - entry_value
    diff_pct = (diff_value / entry_value) * 100.0 if entry_value else 0.0
    direction_cn = "浮盈" if diff_value >= 0 else "浮亏"
    direction_en = "unrealized gain" if diff_value >= 0 else "unrealized loss"
    return (
        f"持仓参考：你的成本价 {entry_value:.2f} | 当前相对成本 {direction_cn} {diff_pct:+.2f}% ({diff_value:+.2f})",
        f"Position context: your entry is {entry_value:.2f} | current {direction_en} {diff_pct:+.2f}% ({diff_value:+.2f})",
    )


def build_message(report: dict, config: dict, rule: dict, reason: str) -> str:
    levels = report["levels"]
    position_cn, position_en = default_position_suggestion(rule, report)
    position_cn = rule.get("position_suggestion_cn", position_cn)
    position_en = rule.get("position_suggestion_en", position_en)
    title_cn = rule.get("title_cn", rule.get("name", "交易提醒"))
    title_en = rule.get("title_en", rule.get("name", "trading alert"))
    reason_cn = rule.get("reason_cn", reason)
    reason_en = rule.get("reason_en", reason)
    entry_cn, entry_en = entry_context(config, rule, report)
    lines = [
        "【交易信号】",
        "[中文]",
        f"{report['asset']['symbol']} {report['timeframe']} 提醒：{title_cn}",
        f"当前价格：{report['current_price']} | 综合评分：{report['score']} | 当前判断：{recommendation_label(report['recommendation'])}",
        f"第一买点：{levels['best_buy_level']} | 第一卖点：{levels['best_sell_level']} | 止损参考：{levels['stop_loss']}",
    ]
    if entry_cn:
        lines.append(entry_cn)
    lines.extend(
        [
            position_cn,
            f"触发原因：{reason_cn}",
            "",
            "[Trading Signal]",
            "[EN]",
            f"{report['asset']['symbol']} {report['timeframe']} alert: {title_en}",
            f"Current price: {report['current_price']} | Score: {report['score']} | View: {recommendation_label(report['recommendation'])}",
            f"Best buy: {levels['best_buy_level']} | Best sell: {levels['best_sell_level']} | Stop: {levels['stop_loss']}",
        ]
    )
    if entry_en:
        lines.append(entry_en)
    lines.extend([position_en, f"Trigger: {reason_en}"])
    return "\n".join(lines)


def detect_suspected_bad_data(config: dict, report: dict, previous: dict | None) -> tuple[bool, str]:
    if previous is None:
        return False, ""
    previous_price = previous.get("current_price")
    current_price = report.get("current_price")
    if previous_price in (None, 0) or current_price in (None, 0):
        return False, ""
    try:
        previous_value = float(previous_price)
        current_value = float(current_price)
    except (TypeError, ValueError):
        return False, ""
    max_deviation_pct = float(config.get("max_price_deviation_pct", 30))
    deviation_pct = abs((current_value - previous_value) / previous_value) * 100.0
    if deviation_pct <= max_deviation_pct:
        return False, ""
    return (
        True,
        f"suspected bad data: price moved from {previous_value:.2f} to {current_value:.2f} "
        f"({deviation_pct:.2f}%), which is above the {max_deviation_pct:.2f}% threshold",
    )


def recap_cache_path(config: dict, tushare_mode: str) -> Path:
    timeframe = config.get("timeframe", "1d")
    market = config.get("market", "auto")
    asset = config["asset"]
    slug = f"{market}__{asset}__{timeframe}__{tushare_mode}".replace("/", "_").replace(" ", "_")
    return Path.home() / ".quant-trading-analyst" / "recap_cache" / f"{slug}.json"


def save_recap_cache(config: dict, report: dict, tushare_mode: str) -> None:
    write_json(
        recap_cache_path(config, tushare_mode),
        {
            "cached_at": int(time.time()),
            "report": report,
        },
    )


def main():
    args = parse_args()
    config_path = Path(args.config)
    config = json.loads(config_path.read_text())
    state_path = Path(args.state_file) if args.state_file else default_monitor_state_path()
    state = load_json(state_path, {"monitors": {}})
    monitor_id = config.get("id") or f"{config['market']}:{config['asset']}:{config.get('timeframe', '1d')}"
    previous = state["monitors"].get(monitor_id, {}).get("last_report")
    tushare_mode = args.tushare_mode or config.get("tushare_mode", "http")
    startup_delay_seconds = int(config.get("startup_delay_seconds", 0))

    cycle = 0
    if startup_delay_seconds > 0 and not args.once:
        time.sleep(startup_delay_seconds)
    while True:
        cycle += 1
        try:
            report = analyze(
                asset_query=config["asset"],
                market=config.get("market", "auto"),
                timeframe=config.get("timeframe", "1d"),
                memory_file=Path(args.memory_file) if args.memory_file else None,
                tushare_mode=tushare_mode,
            )
        except Exception as error:
            message = f"[monitor-error] {config.get('asset')} {config.get('timeframe', '1d')}: {error}"
            if args.once:
                raise SystemExit(message) from error
            print(message)
            time.sleep(int(config.get("poll_seconds", 300)))
            continue

        now = int(time.time())
        monitor_entry = state["monitors"].setdefault(monitor_id, {"sent": {}, "last_report": None})
        suspected_bad_data, bad_data_reason = detect_suspected_bad_data(config, report, previous)
        if suspected_bad_data:
            anomalies = monitor_entry.setdefault("suspected_data", [])
            anomalies.append(
                {
                    "detected_at": now,
                    "reason": bad_data_reason,
                    "asset_symbol": report.get("asset", {}).get("symbol"),
                    "current_price": report.get("current_price"),
                    "previous_price": previous.get("current_price") if previous else None,
                }
            )
            if len(anomalies) > 50:
                del anomalies[:-50]
            write_json(state_path, state)
            print(f"[monitor-suspected-data] {config.get('asset')} {config.get('timeframe', '1d')}: {bad_data_reason}")
            if args.once:
                break
            time.sleep(int(config.get("poll_seconds", 300)))
            continue
        for rule in config.get("rules", []):
            fired, reason = should_fire(rule, report, previous)
            if not fired:
                continue
            cooldown_seconds = int(rule.get("cooldown_minutes", 60) * 60)
            last_sent = monitor_entry["sent"].get(rule["name"], 0)
            if now - last_sent < cooldown_seconds:
                continue
            message = build_message(report, config, rule, reason)
            send_notification(config.get("notifier", {"type": "stdout"}), message, payload={"message": message, "report": report})
            monitor_entry["sent"][rule["name"]] = now

        # Keep the recap cache warm with the latest good monitor snapshot so
        # daily recaps can fall back to a recent report instead of a stale one.
        save_recap_cache(config, report, tushare_mode)
        monitor_entry["last_report"] = report
        previous = report
        write_json(state_path, state)

        if args.once:
            break
        if args.cycles is not None and cycle >= args.cycles:
            break
        time.sleep(int(config.get("poll_seconds", 300)))


if __name__ == "__main__":
    main()

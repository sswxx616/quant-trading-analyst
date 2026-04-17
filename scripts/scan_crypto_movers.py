#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from quant_core import (
    analyze,
    ensure_state_dir,
    fetch_json,
    load_json,
    recommendation_label,
    send_notification,
    write_json,
)


LEVERAGED_SUFFIXES = ("UP", "DOWN", "BULL", "BEAR")
STABLE_LIKE_BASES = {
    "USDT",
    "USDC",
    "FDUSD",
    "TUSD",
    "USDP",
    "BUSD",
    "DAI",
    "USDS",
    "USDE",
    "EUR",
    "EURC",
    "AEUR",
    "FDEUR",
}
DEFAULT_RECOMMENDATION_ALLOWLIST = ["watch-for-buy-confirmation", "buy-or-add"]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scan Binance crypto top gainers, then run quant analysis on the strongest movers."
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
        help="How many analyzed movers to include in an alert notification.",
    )
    parser.add_argument(
        "--min-quote-volume",
        type=float,
        default=10_000_000,
        help="Minimum 24h quote volume in quote currency.",
    )
    parser.add_argument(
        "--min-price-change-pct",
        type=float,
        default=5.0,
        help="Minimum 24h percent gain required to qualify.",
    )
    parser.add_argument(
        "--max-price-change-pct",
        type=float,
        help="Optional upper bound to ignore parabolic one-day squeezes.",
    )
    parser.add_argument(
        "--timeframe",
        default="4h",
        choices=["1h", "4h", "1d"],
        help="Quant analysis timeframe for shortlisted movers.",
    )
    parser.add_argument(
        "--format",
        default="markdown",
        choices=["markdown", "json"],
        help="Render as markdown or JSON.",
    )
    parser.add_argument(
        "--min-score",
        type=int,
        default=20,
        help="Minimum composite score required for a mover to qualify for alerts.",
    )
    parser.add_argument(
        "--recommendation-allowlist",
        nargs="*",
        help="Allowed recommendation labels for alerts.",
    )
    parser.add_argument("--memory-file", help="Optional learning memory path.")
    parser.add_argument("--state-file", help="Optional scanner state path.")
    parser.add_argument("--output", help="Optional output file path.")
    parser.add_argument("--once", action="store_true", help="Reserved for automation compatibility.")
    return parser.parse_args()


def default_state_path() -> Path:
    return ensure_state_dir() / "crypto_mover_state.json"


def is_leveraged_symbol(base_asset: str) -> bool:
    return base_asset.upper().endswith(LEVERAGED_SUFFIXES)


def is_stable_like_symbol(base_asset: str) -> bool:
    return base_asset.upper() in STABLE_LIKE_BASES


def fetch_binance_24h_tickers(quote: str) -> list[dict]:
    payload = fetch_json("https://api.binance.com/api/v3/ticker/24hr")
    quote = quote.upper()
    filtered: list[dict] = []
    for row in payload:
        symbol = str(row.get("symbol", ""))
        if not symbol.endswith(quote):
            continue
        base_asset = symbol[: -len(quote)]
        if not base_asset or is_leveraged_symbol(base_asset) or is_stable_like_symbol(base_asset):
            continue
        try:
            price_change_pct = float(row.get("priceChangePercent", 0.0))
            quote_volume = float(row.get("quoteVolume", 0.0))
            last_price = float(row.get("lastPrice", 0.0))
        except (TypeError, ValueError):
            continue
        if last_price <= 0:
            continue
        filtered.append(
            {
                "symbol": symbol,
                "base_asset": base_asset,
                "quote_asset": quote,
                "last_price": last_price,
                "price_change_pct": price_change_pct,
                "quote_volume": quote_volume,
                "volume": float(row.get("volume", 0.0) or 0.0),
                "high_price": float(row.get("highPrice", 0.0) or 0.0),
                "low_price": float(row.get("lowPrice", 0.0) or 0.0),
            }
        )
    filtered.sort(key=lambda item: item["price_change_pct"], reverse=True)
    return filtered


def select_candidates(tickers: list[dict], config: dict) -> list[dict]:
    min_quote_volume = float(config.get("min_quote_volume", 10_000_000))
    min_price_change_pct = float(config.get("min_price_change_pct", 5.0))
    max_price_change_pct = config.get("max_price_change_pct")
    top = int(config.get("top", 30))
    shortlisted = []
    for row in tickers:
        if row["quote_volume"] < min_quote_volume:
            continue
        if row["price_change_pct"] < min_price_change_pct:
            continue
        if max_price_change_pct is not None and row["price_change_pct"] > float(max_price_change_pct):
            continue
        shortlisted.append(row)
        if len(shortlisted) >= top:
            break
    return shortlisted


def analyze_candidates(candidates: list[dict], config: dict, memory_file: Path | None) -> list[dict]:
    timeframe = config.get("timeframe", "4h")
    results = []
    for rank, candidate in enumerate(candidates[: int(config.get("analyze_top", 8))], start=1):
        try:
            report = analyze(
                asset_query=candidate["symbol"],
                market="crypto",
                timeframe=timeframe,
                memory_file=memory_file,
            )
        except Exception as error:
            results.append({"rank": rank, "ticker": candidate, "error": str(error)})
            continue
        results.append({"rank": rank, "ticker": candidate, "report": report})
    return results


def mover_matches_quant_filter(item: dict, config: dict) -> bool:
    report = item.get("report")
    if not report:
        return False
    min_score = int(config.get("min_score", 20))
    allowlist = config.get("recommendation_allowlist") or DEFAULT_RECOMMENDATION_ALLOWLIST
    return report.get("score", -999) >= min_score and report.get("recommendation") in allowlist


def render_markdown(candidates: list[dict], analyzed: list[dict], config: dict) -> str:
    lines = [
        "# Crypto Movers Scan",
        "",
        f"- Quote asset: {config.get('quote', 'USDT')}",
        f"- Raw leaderboard size: {len(candidates)}",
        f"- Quant-analyzed movers: {len(analyzed)}",
        f"- Timeframe: {config.get('timeframe', '4h')}",
        "",
        "## 24h Top Movers",
        "",
    ]
    for item in candidates[: min(len(candidates), 10)]:
        lines.append(
            f"- {item['base_asset']} ({item['symbol']}): 24h {item['price_change_pct']:.2f}% | "
            f"price {item['last_price']:.4f} | quote volume {item['quote_volume']:.0f}"
        )
    lines.extend(["", "## Quant Screened Movers", ""])
    if not analyzed:
        lines.append("- No movers qualified for quant screening.")
        return "\n".join(lines) + "\n"
    for item in analyzed:
        ticker = item["ticker"]
        if item.get("error"):
            lines.append(
                f"- {ticker['base_asset']} ({ticker['symbol']}): 24h {ticker['price_change_pct']:.2f}% | analysis failed: {item['error']}"
            )
            continue
        report = item["report"]
        levels = report["levels"]
        lines.append(
            f"- #{item['rank']} {ticker['base_asset']} ({ticker['symbol']}): 24h {ticker['price_change_pct']:.2f}% | "
            f"{recommendation_label(report['recommendation'])} | score {report['score']} | "
            f"observe {levels['best_buy_level']} | confirm {levels.get('confirmation_buy_level')} | "
            f"first sell {levels['best_sell_level']}"
        )
    qualified = [item for item in analyzed if mover_matches_quant_filter(item, config)]
    if qualified:
        lines.extend(["", "## Alert Candidates", ""])
        for item in qualified:
            ticker = item["ticker"]
            report = item["report"]
            lines.append(
                f"- {ticker['base_asset']}: 24h {ticker['price_change_pct']:.2f}% | "
                f"{recommendation_label(report['recommendation'])} | score {report['score']}"
            )
    return "\n".join(lines) + "\n"


def render_notification(qualified: list[dict], config: dict) -> str:
    if not qualified:
        return "【交易信号】\n[中文]\n数字货币涨幅榜扫描：本轮没有同时满足涨幅、流动性和量化过滤条件的币种。\n\n[Trading Signal]\n[EN]\nCrypto movers scan: no tokens passed the gain, liquidity, and quant filters in this cycle."
    lines = [
        "【交易信号】",
        "[中文]",
        "数字货币涨幅榜提醒：以下币种同时满足近期强势、流动性和量化过滤。",
    ]
    for item in qualified[: int(config.get("notify_top", 3))]:
        ticker = item["ticker"]
        report = item["report"]
        levels = report["levels"]
        lines.append(
            f"- {ticker['base_asset']}：24h 涨幅 {ticker['price_change_pct']:.2f}% | "
            f"当前价 {report['current_price']} | 评分 {report['score']} | 判断 {recommendation_label(report['recommendation'])} | "
            f"观察买点 {levels['best_buy_level']} | 确认位 {levels.get('confirmation_buy_level')}"
        )
    lines.extend(
        [
            "",
            "[Trading Signal]",
            "[EN]",
            "Crypto movers alert: the tokens below passed the recent-strength, liquidity, and quant filters.",
        ]
    )
    for item in qualified[: int(config.get("notify_top", 3))]:
        ticker = item["ticker"]
        report = item["report"]
        levels = report["levels"]
        lines.append(
            f"- {ticker['base_asset']}: 24h {ticker['price_change_pct']:.2f}% | "
            f"price {report['current_price']} | score {report['score']} | view {recommendation_label(report['recommendation'])} | "
            f"observe {levels['best_buy_level']} | confirm {levels.get('confirmation_buy_level')}"
        )
    return "\n".join(lines)


def should_send(item: dict, scanner_state: dict, config: dict) -> bool:
    symbol = item["ticker"]["symbol"]
    last_sent = scanner_state.setdefault("sent", {}).get(symbol, 0)
    cooldown_hours = float(config.get("cooldown_hours", 12))
    return (time.time() - last_sent) >= cooldown_hours * 3600


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
    if args.min_quote_volume is not None:
        config["min_quote_volume"] = args.min_quote_volume
    if args.min_price_change_pct is not None:
        config["min_price_change_pct"] = args.min_price_change_pct
    if args.max_price_change_pct is not None:
        config["max_price_change_pct"] = args.max_price_change_pct
    if args.timeframe:
        config["timeframe"] = args.timeframe
    if args.min_score is not None:
        config["min_score"] = args.min_score
    if args.recommendation_allowlist:
        config["recommendation_allowlist"] = args.recommendation_allowlist

    config.setdefault("quote", "USDT")
    config.setdefault("top", 30)
    config.setdefault("analyze_top", 8)
    config.setdefault("notify_top", 3)
    config.setdefault("min_quote_volume", 10_000_000)
    config.setdefault("min_price_change_pct", 5.0)
    config.setdefault("timeframe", "4h")
    config.setdefault("min_score", 20)
    config.setdefault("recommendation_allowlist", DEFAULT_RECOMMENDATION_ALLOWLIST)

    memory_file = Path(args.memory_file) if args.memory_file else None
    tickers = fetch_binance_24h_tickers(config["quote"])
    candidates = select_candidates(tickers, config)
    analyzed = analyze_candidates(candidates, config, memory_file)

    rendered = (
        json.dumps(
            {
                "generated_at": int(time.time()),
                "config": config,
                "raw_candidates": candidates,
                "analyzed": analyzed,
            },
            indent=2,
            ensure_ascii=True,
        )
        + "\n"
        if args.format == "json"
        else render_markdown(candidates, analyzed, config)
    )

    if args.output:
        Path(args.output).write_text(rendered)

    notifier = config.get("notifier")
    state_path = Path(args.state_file) if args.state_file else default_state_path()
    state = load_json(state_path, {"scanners": {}})
    scanner_id = config.get("id", f"crypto-movers:{config['quote']}:{config['timeframe']}")
    scanner_state = state.setdefault("scanners", {}).setdefault(scanner_id, {"sent": {}, "last_scan": None})
    qualified = [item for item in analyzed if mover_matches_quant_filter(item, config)]
    sendable = [item for item in qualified if should_send(item, scanner_state, config)]
    if notifier and sendable:
        message = render_notification(sendable, config)
        send_notification(notifier, message, {"message": message, "items": sendable})
        now = int(time.time())
        for item in sendable:
            scanner_state["sent"][item["ticker"]["symbol"]] = now
    scanner_state["last_scan"] = int(time.time())
    write_json(state_path, state)

    print(rendered, end="")


if __name__ == "__main__":
    main()

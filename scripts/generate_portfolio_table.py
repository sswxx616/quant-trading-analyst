#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime
from pathlib import Path

from quant_core import (
    analyze,
    default_monitor_state_path,
    ensure_state_dir,
    fetch_json,
    load_json,
    pct_change,
    recommendation_label,
    round_price,
    send_notification,
    write_json,
)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate a cross-market portfolio table with posture-aware actions."
    )
    parser.add_argument("--config", required=True, help="Path to the portfolio table config JSON.")
    parser.add_argument("--output", help="Optional path to save the rendered table.")
    parser.add_argument("--env-file", help="Optional runtime env file.")
    parser.add_argument("--cache-ttl-hours", type=int, default=72)
    parser.add_argument("--stdout-only", action="store_true", help="Print locally without notifier.")
    return parser.parse_args()


def load_env_file(path: Path) -> dict[str, str]:
    loaded: dict[str, str] = {}
    if not path.exists():
        return loaded
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key:
            loaded[key] = value
    return loaded


def resolve_runtime_env(script_dir: Path, explicit_env_file: str | None) -> dict[str, str]:
    env = os.environ.copy()
    candidates = []
    if explicit_env_file:
        candidate = Path(explicit_env_file)
        if not candidate.is_absolute():
            candidate = (script_dir / explicit_env_file).resolve()
        candidates.append(candidate)
    else:
        candidates.extend(
            [
                (script_dir.parent / ".env.local").resolve(),
                (script_dir.parent / "assets" / "runtime.env.local").resolve(),
            ]
        )
    for candidate in candidates:
        env.update(load_env_file(candidate))
    return env


def portfolio_cache_path(item: dict) -> Path:
    slug = f"{item.get('market','auto')}__{item['asset']}__{item.get('timeframe','1d')}".replace("/", "_").replace(" ", "_")
    return ensure_state_dir() / "portfolio_cache" / f"{slug}.json"


def load_cached_report(item: dict, ttl_hours: int) -> dict | None:
    payload = load_json(portfolio_cache_path(item), {})
    if not payload.get("report") or not payload.get("cached_at"):
        return None
    age_seconds = int(datetime.now().timestamp()) - int(payload["cached_at"])
    if age_seconds > ttl_hours * 3600:
        return None
    report = payload["report"]
    report["portfolio_status"] = "cached"
    report["cache_age_hours"] = round(age_seconds / 3600.0, 1)
    return report


def save_cached_report(item: dict, report: dict) -> None:
    write_json(
        portfolio_cache_path(item),
        {"cached_at": int(datetime.now().timestamp()), "report": report},
    )


def market_matches(item_market: str, report_asset: dict) -> bool:
    if item_market == "crypto":
        return report_asset.get("market") == "crypto"
    if item_market == "cn-stock":
        return report_asset.get("market") == "stock" and report_asset.get("region") == "CN"
    if item_market == "stock":
        return report_asset.get("market") == "stock"
    if item_market == "us-stock":
        return report_asset.get("market") == "stock" and report_asset.get("region") != "CN"
    return True


def asset_matches(item: dict, report_asset: dict) -> bool:
    requested = str(item["asset"]).strip().upper()
    symbol = str(report_asset.get("symbol") or "").strip().upper()
    display = str(report_asset.get("display_name") or "").strip().upper()
    if requested == symbol or requested == display:
        return True
    if item.get("market") == "cn-stock":
        requested_code = requested.split(".", 1)[0]
        symbol_code = symbol.split(".", 1)[0]
        return requested_code == symbol_code
    if item.get("market") == "crypto":
        normalized = requested.replace("USDT", "")
        return symbol.startswith(normalized)
    return False


def load_monitor_fallback_report(item: dict, ttl_hours: int) -> dict | None:
    state = load_json(default_monitor_state_path(), {"monitors": {}})
    now = int(datetime.now().timestamp())
    timeframe = item.get("timeframe", "1d")
    best_report = None
    best_generated_at = 0
    for monitor in state.get("monitors", {}).values():
        report = monitor.get("last_report")
        if not report:
            continue
        generated_at = int(report.get("generated_at") or 0)
        if not generated_at or (now - generated_at) > ttl_hours * 3600:
            continue
        if report.get("timeframe") != timeframe:
            continue
        asset = report.get("asset", {})
        if not market_matches(item.get("market", "auto"), asset):
            continue
        if not asset_matches(item, asset):
            continue
        if generated_at > best_generated_at:
            best_generated_at = generated_at
            best_report = json.loads(json.dumps(report))
    if best_report is None:
        return None
    age_seconds = now - best_generated_at
    best_report["portfolio_status"] = "monitor-cache"
    best_report["cache_age_hours"] = round(age_seconds / 3600.0, 1)
    return best_report


def fetch_dubai_stock_quote(symbol: str) -> dict:
    rows = fetch_json("https://api2.dfm.ae/mw/v1/stocks")
    match = None
    symbol_upper = symbol.strip().upper()
    for row in rows:
        if str(row.get("id") or "").strip().upper() == symbol_upper:
            match = row
            break
    if match is None:
        raise RuntimeError(f"Dubai stock {symbol_upper} was not found in DFM market-watch data.")
    last_trade = float(match.get("lastradeprice") or 0.0)
    closing_price = float(match.get("closingprice") or 0.0)
    current = last_trade if last_trade > 0 else closing_price
    if current <= 0:
        raise RuntimeError(f"Dubai stock {symbol_upper} returned no valid live or closing price.")
    support = float(match["lowestprice"] or current)
    resistance = float(match["highestprice"] or current)
    stop_loss = min(support * 0.99, current * 0.97)
    defensive = support * 0.998
    take_profit_2 = current + max(current - support, resistance - current) * 1.5
    framework = {
        "setup_phase": (
            "pullback-zone"
            if current <= support * 1.01
            else "confirmation-zone"
            if current >= resistance * 0.995
            else "mid-range"
        ),
        "reward_to_stop_ratio": round(
            (((resistance / current) - 1.0) * 100.0) / abs(((stop_loss / current) - 1.0) * 100.0),
            2,
        )
        if current and stop_loss
        else None,
        "reward_risk_grade": "acceptable" if current < resistance else "weak",
        "validation_quality": "manual",
        "risk_tier": "medium",
        "exit_posture": "hold-core",
        "position_posture": "hold-and-assess",
        "upside_to_first_sell_pct": round(((resistance / current) - 1.0) * 100.0, 2) if current else None,
        "upside_to_second_sell_pct": round(((take_profit_2 / current) - 1.0) * 100.0, 2) if current else None,
        "stop_distance_pct": round(abs(((stop_loss / current) - 1.0) * 100.0), 2) if current else None,
        "defensive_distance_pct": round(abs(((defensive / current) - 1.0) * 100.0), 2) if current else None,
        "trailing_reference": round_price(support),
        "time_stop_bars": 3,
    }
    return {
        "generated_at": int(time.time()),
        "asset": {
            "market": "stock",
            "region": "AE",
            "source": "dfm-api",
            "symbol": symbol_upper,
            "display_name": symbol_upper,
            "exchange": "DFM",
        },
        "data_source": "dfm-api",
        "timeframe": "1d",
        "current_price": round_price(current),
        "price_change_5_bars_pct": None,
        "price_change_20_bars_pct": None,
        "recommendation": "hold-and-wait",
        "confidence": "low",
        "score": 0,
        "levels": {
            "best_buy_level": round_price(support),
            "first_buy_level": round_price(support),
            "confirmation_buy_level": round_price(resistance),
            "best_sell_level": round_price(resistance),
            "stop_loss": round_price(stop_loss),
            "defensive_sell_trigger": round_price(defensive),
            "take_profit_2": round_price(take_profit_2),
            "support": round_price(support),
            "resistance": round_price(resistance),
        },
        "signals": {
            "rsi14": None,
            "macd_histogram": None,
            "atr_percent": None,
            "volume_ratio": None,
            "sma20": None,
            "sma50": None,
            "sma200": None,
        },
        "reasons": [
            f"DFM close {current} with intraday range {support}-{resistance}.",
            f"Day change {match.get('changepercentage')}% with active turnover {match.get('totalvalue')}.",
        ],
        "risks": [
            "Dubai-stock fallback uses official DFM market-watch quotes but not the full local quant stack yet."
        ],
        "tags": [],
        "learning_insights": [],
        "backtest": {"horizon_bars": 3, "bullish": {"count": 0, "win_rate": None, "avg_return": None}, "bearish": {"count": 0, "win_rate": None, "avg_return": None}},
        "trade_framework": framework,
    }


def posture_cn(value: str | None) -> str:
    return {
        "accumulate": "可分批吸纳",
        "pilot-only": "只适合观察仓",
        "harvest-strength": "趁强兑现一部分",
        "protect-capital": "优先保护本金",
        "hold-and-assess": "先拿着评估",
        "trim-first-target": "到第一目标先减仓",
        "scale-out-hard": "接近二目标继续明显减仓",
        "reduce-strength": "反弹以减仓为主",
        "defense-first": "先转防守",
        "hold-core": "核心仓继续拿",
    }.get(value, value or "未定义")


def summarize_pnl(item: dict, report: dict) -> str:
    cost = item.get("cost_basis")
    if cost in (None, "", "None"):
        return "-"
    current = float(report["current_price"])
    pct = pct_change(current, float(cost))
    return f"{round(float(cost), 4)} / {pct:+.2f}%"


def action_for_item(item: dict, report: dict) -> str:
    framework = report.get("trade_framework", {})
    recommendation = report.get("recommendation")
    item_type = item.get("type", "holding")
    cost = item.get("cost_basis")
    current = float(report["current_price"])
    if item_type == "watch":
        if framework.get("position_posture") == "accumulate":
            return "可分批试探"
        if framework.get("setup_phase") == "pullback-zone":
            return "等回踩买点附近"
        if framework.get("setup_phase") == "confirmation-zone":
            return "等站稳确认位"
        return "继续观察"
    if framework.get("exit_posture") == "scale-out-hard":
        return "继续明显减仓"
    if framework.get("exit_posture") == "trim-first-target":
        return "先减一部分锁利润"
    if framework.get("position_posture") == "protect-capital":
        return "转防守，减少风险"
    if framework.get("position_posture") == "accumulate":
        return "可分批加仓"
    if cost not in (None, "", "None") and current < float(cost):
        if recommendation in {"buy-or-add", "watch-for-buy-confirmation"} and framework.get("setup_phase") in {"pullback-zone", "confirmation-zone"}:
            return "持有观察，不硬补"
        return "持有，不摊平"
    if framework.get("position_posture") == "hold-and-assess":
        return "持有，等确认"
    return "持有"


def key_levels(report: dict) -> str:
    levels = report["levels"]
    return f"买 {levels.get('best_buy_level')} / 确 {levels.get('confirmation_buy_level')} / 卖 {levels.get('best_sell_level')}"


def load_report(item: dict, ttl_hours: int) -> dict:
    market = item.get("market", "auto")
    if market == "dubai-stock":
        return fetch_dubai_stock_quote(item["asset"])
    try:
        report = analyze(item["asset"], market=market, timeframe=item.get("timeframe", "1d"))
        save_cached_report(item, report)
        return report
    except Exception:
        fallback = load_monitor_fallback_report(item, ttl_hours)
        if fallback is not None:
            return fallback
        cached = load_cached_report(item, ttl_hours)
        if cached is not None:
            return cached
        raise


def build_rows(config: dict, ttl_hours: int) -> tuple[list[dict], list[dict]]:
    holdings = []
    watchlist = []
    for item in config.get("items", []):
        report = load_report(item, ttl_hours)
        row = {
            "market": item.get("market", "auto"),
            "label": item.get("label") or item["asset"],
            "type": item.get("type", "holding"),
            "current_price": report["current_price"],
            "cost_pnl": summarize_pnl(item, report),
            "view": recommendation_label(report["recommendation"]),
            "position_posture": posture_cn(report.get("trade_framework", {}).get("position_posture")),
            "exit_posture": posture_cn(report.get("trade_framework", {}).get("exit_posture")),
            "levels": key_levels(report),
            "action": action_for_item(item, report),
            "report": report,
        }
        if row["type"] == "watch":
            watchlist.append(row)
        else:
            holdings.append(row)
    return holdings, watchlist


def market_view(holdings: list[dict], watchlist: list[dict]) -> str:
    rows = holdings + watchlist
    if not rows:
        return "市场视图：当前没有可分析标的。"
    strong = sum(1 for row in rows if row["view"] in {"Buy / Add", "Watch For Buy Confirmation"})
    defensive = sum(1 for row in rows if "防守" in row["action"] or "减仓" in row["action"])
    if strong >= max(2, len(rows) // 2):
        return "市场视图：整体偏震荡偏强，适合拿强、等确认，不适合中间位置乱追。"
    if defensive >= max(2, len(rows) // 3):
        return "市场视图：整体更偏修复与分化，优先控节奏，弱势仓位不要硬扛。"
    return "市场视图：整体仍是分化震荡，优先按关键位动作。"


def execution_priority(holdings: list[dict], watchlist: list[dict]) -> str:
    focus = []
    for row in holdings:
        if "减仓" in row["action"] or "防守" in row["action"] or "等确认" in row["action"]:
            focus.append(row["label"])
    for row in watchlist:
        if row["action"] != "继续观察":
            focus.append(row["label"])
    if not focus:
        return "执行优先级：先维持现有仓位结构，等待更清晰的确认或回踩。"
    return "执行优先级：" + "、".join(focus[:4]) + " 是今天最需要盯的标的。"


def render_table(title: str, holdings: list[dict], watchlist: list[dict]) -> str:
    lines = [f"# {title}", ""]
    lines.append(market_view(holdings, watchlist))
    lines.append(execution_priority(holdings, watchlist))
    lines.extend(["", "## 持仓", ""])
    if holdings:
        lines.append("| 市场 | 标的 | 现价 | 成本/浮盈亏 | 判断 | 仓位姿态 | 卖出姿态 | 关键位 | 动作 |")
        lines.append("|---|---|---:|---:|---|---|---|---|---|")
        for row in holdings:
            lines.append(
                f"| {row['market']} | {row['label']} | {row['current_price']} | {row['cost_pnl']} | {row['view']} | "
                f"{row['position_posture']} | {row['exit_posture']} | {row['levels']} | {row['action']} |"
            )
    else:
        lines.append("- 当前没有持仓条目。")
    lines.extend(["", "## 重点观察", ""])
    if watchlist:
        lines.append("| 市场 | 标的 | 现价 | 判断 | 仓位姿态 | 卖出姿态 | 关键位 | 动作 |")
        lines.append("|---|---|---:|---|---|---|---|---|")
        for row in watchlist:
            lines.append(
                f"| {row['market']} | {row['label']} | {row['current_price']} | {row['view']} | "
                f"{row['position_posture']} | {row['exit_posture']} | {row['levels']} | {row['action']} |"
            )
    else:
        lines.append("- 当前没有观察条目。")
    return "\n".join(lines) + "\n"


def main():
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    runtime_env = resolve_runtime_env(script_dir, args.env_file)
    os.environ.update(runtime_env)
    config_path = Path(args.config)
    if not config_path.is_absolute():
        config_path = (script_dir / args.config).resolve()
    config = json.loads(config_path.read_text())
    holdings, watchlist = build_rows(config, args.cache_ttl_hours)
    rendered = render_table(config.get("title", "Daily Portfolio Table"), holdings, watchlist)
    if args.output:
        out = Path(args.output)
        if not out.is_absolute():
            out = (script_dir / args.output).resolve()
        out.write_text(rendered)
    notifier = config.get("notifier")
    if notifier and not args.stdout_only:
        send_notification(notifier, rendered, payload={"message": rendered, "holdings": holdings, "watchlist": watchlist})
    print(rendered, end="")


if __name__ == "__main__":
    main()

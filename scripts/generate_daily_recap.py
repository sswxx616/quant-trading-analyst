#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from collections import defaultdict

from quant_core import (
    analyze,
    ensure_state_dir,
    load_json,
    recommendation_label,
    send_notification,
    write_json,
)

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


def parse_args():
    parser = argparse.ArgumentParser(description="Generate a daily recap for a watchlist and optionally send it.")
    parser.add_argument("--config", required=True, help="Path to a daily recap config JSON file.")
    parser.add_argument("--output", help="Optional path to save the rendered recap.")
    parser.add_argument("--memory-file", help="Optional learning memory path.")
    parser.add_argument(
        "--market-context-file",
        help="Optional market context JSON override. Useful when a separate builder generates the context before recap rendering.",
    )
    parser.add_argument(
        "--tushare-mode",
        choices=["http", "sdk"],
        help="Override the config Tushare mode for A-share analysis. Defaults to config value, then http.",
    )
    parser.add_argument(
        "--cache-ttl-hours",
        type=int,
        help="How long a cached report stays eligible for fallback. Defaults to config value, then 72 hours.",
    )
    return parser.parse_args()


def recap_cache_path(item: dict, default_timeframe: str, default_tushare_mode: str) -> Path:
    timeframe = item.get("timeframe", default_timeframe)
    market = item.get("market", "auto")
    tushare_mode = item.get("tushare_mode", default_tushare_mode)
    slug = f"{market}__{item['asset']}__{timeframe}__{tushare_mode}".replace("/", "_").replace(" ", "_")
    return ensure_state_dir() / "recap_cache" / f"{slug}.json"


def load_market_context(config: dict, config_path: Path, market_context_file_override: str | None = None) -> dict:
    context = dict(config.get("market_context", {}))
    context_file = market_context_file_override or config.get("market_context_file")
    if context_file:
        file_path = Path(context_file)
        if not file_path.is_absolute():
            file_path = (config_path.parent / file_path).resolve()
        if file_path.exists():
            loaded = json.loads(file_path.read_text())
            context.update(loaded)
    return context


def load_cached_report(item: dict, default_timeframe: str, default_tushare_mode: str, ttl_hours: int) -> dict | None:
    path = recap_cache_path(item, default_timeframe, default_tushare_mode)
    payload = load_json(path, {})
    if not payload.get("report") or not payload.get("cached_at"):
        return None
    age_seconds = int(datetime.now().timestamp()) - int(payload["cached_at"])
    if age_seconds > ttl_hours * 3600:
        return None
    report = payload["report"]
    report["recap_status"] = "cached"
    report["recap_cache_age_hours"] = round(age_seconds / 3600.0, 1)
    return report


def save_cached_report(item: dict, report: dict, default_timeframe: str, default_tushare_mode: str) -> None:
    path = recap_cache_path(item, default_timeframe, default_tushare_mode)
    write_json(
        path,
        {
            "cached_at": int(datetime.now().timestamp()),
            "report": report,
        },
    )


def report_origin_label(report: dict) -> tuple[str, str]:
    status = report.get("recap_status", "live")
    if status == "cached":
        age = report.get("recap_cache_age_hours")
        return (
            f"缓存回退，缓存年龄约 {age} 小时",
            f"cached fallback, cache age about {age}h",
        )
    return ("实时分析", "live analysis")


def action_bucket(report: dict) -> str:
    recommendation = report["recommendation"]
    if recommendation == "buy-or-add":
        return "buy"
    if recommendation in {"reduce-or-tighten-risk", "sell-or-avoid"}:
        return "sell"
    return "watch"


def action_label(bucket: str) -> str:
    return {
        "buy": "买入",
        "watch": "观望",
        "sell": "卖出",
    }[bucket]


def action_emoji(bucket: str) -> str:
    return {
        "buy": "🟢",
        "watch": "🟡",
        "sell": "🔴",
    }[bucket]


def summary_emoji(bucket: str) -> str:
    return {
        "buy": "🟢",
        "watch": "⚪",
        "sell": "🔴",
    }[bucket]


def bias_label(report: dict) -> str:
    score = report["score"]
    if score >= 45:
        return "看多"
    if score <= -45:
        return "看空"
    return "震荡"


def source_label(report: dict) -> str:
    asset = report["asset"]
    return str(report.get("data_source") or asset.get("data_source") or asset.get("source"))


def display_label(report: dict) -> str:
    asset = report["asset"]
    return asset.get("recap_label") or asset.get("display_name") or asset.get("symbol")


def translate_signal_text(text: str) -> str:
    return SIGNAL_TRANSLATIONS.get(text, text)


def join_items(items: list[str], default: str) -> str:
    cleaned = [translate_signal_text(item.strip()).rstrip(".").rstrip("。") for item in items if item]
    if not cleaned:
        return default
    return "；".join(cleaned[:2]) + "。"


def detail_sentiment(report: dict) -> str:
    positive = join_items(report.get("reasons", []), "量化信号暂时没有给出明显正向共振。")
    negative = join_items(report.get("risks", []), "当前未出现特别突出的短线风险项。")
    return (
        f"当前量化情绪偏{bias_label(report)}，主要依据：{positive}"
        f"需要留意：{negative}"
    )


def detail_expectation(report: dict) -> str:
    levels = report["levels"]
    origin_cn, _ = report_origin_label(report)
    buy_text = buy_guidance_text(report)
    return (
        f"当前价格 {report['current_price']}，综合评分 {report['score']}。"
        f"{buy_text}"
        f"第一卖出点：{levels['best_sell_level']}，"
        f"止损参考：{levels['stop_loss']}。"
        f"数据源：{source_label(report)}，{origin_cn}。"
    )


def buy_guidance_text(report: dict) -> str:
    levels = report["levels"]
    current_price = report["current_price"]
    first_buy = levels.get("first_buy_level")
    confirmation_buy = levels.get("confirmation_buy_level")
    if action_bucket(report) == "sell":
        if confirmation_buy is not None and confirmation_buy > current_price:
            return f"当前以防守为主，若反弹修复到 {confirmation_buy} 再观察，"
        return f"当前以防守为主，参考风险反抽位：{levels['best_buy_level']}，"
    if first_buy is not None and confirmation_buy is not None and first_buy < current_price < confirmation_buy:
        return f"建议第一观察买点：{first_buy}，若走强，确认买点：{confirmation_buy}，"
    if first_buy is not None and first_buy <= current_price:
        return f"建议第一观察买点：{first_buy}，"
    if confirmation_buy is not None and confirmation_buy > current_price:
        return f"建议确认买点：{confirmation_buy}，"
    return f"建议第一买入点：{levels['best_buy_level']}，"


def summary_line(report: dict) -> str:
    bucket = action_bucket(report)
    asset = report["asset"]
    levels = report["levels"]
    current_price = report["current_price"]
    first_buy = levels.get("first_buy_level")
    confirmation_buy = levels.get("confirmation_buy_level")
    if bucket == "sell":
        if confirmation_buy is not None and confirmation_buy > current_price:
            buy_label = f"反弹修复观察位：{confirmation_buy}"
        else:
            buy_label = f"风险反抽位：{levels['best_buy_level']}"
    elif first_buy is not None and confirmation_buy is not None and first_buy < current_price < confirmation_buy:
        buy_label = f"建议第一观察买点：{first_buy}；确认买点：{confirmation_buy}"
    elif first_buy is not None and first_buy <= current_price:
        buy_label = f"建议第一观察买点：{first_buy}"
    elif confirmation_buy is not None and confirmation_buy > current_price:
        buy_label = f"建议确认买点：{confirmation_buy}"
    else:
        buy_label = f"建议第一买入点：{levels['best_buy_level']}"
    return (
        f"{summary_emoji(bucket)} {display_label(report)} ({asset['symbol']}): "
        f"{action_label(bucket)} | 评分 {report['score']} | {bias_label(report)}｜"
        f"{buy_label} |"
    )


def asset_section(report: dict) -> list[str]:
    asset = report["asset"]
    lines = [
        f"{summary_emoji(action_bucket(report))} {display_label(report)} ({asset['symbol']})",
        "📰 重要信息速览",
        f"💭 市场情绪: {detail_sentiment(report)}",
        f"📊 量化结论: {detail_expectation(report)}",
    ]
    if report.get("learning_insights"):
        lines.append(f"🧠 历史经验: {join_items(report['learning_insights'], '当前还没有足够的历史标注样本。')}")
    return lines


def collect_risks(successes: list[dict], failures: list[dict]) -> list[str]:
    items = []
    seen = set()
    for report in successes:
        for risk in report.get("risks", []):
            key = translate_signal_text(risk.strip())
            if key and key not in seen:
                seen.add(key)
                items.append(key)
    for failure in failures:
        text = failure.get("error_cn")
        if text and text not in seen:
            seen.add(text)
            items.append(text)
    return items[:5]


def collect_catalysts(successes: list[dict]) -> list[str]:
    items = []
    seen = set()
    for report in successes:
        for reason in report.get("reasons", []):
            key = translate_signal_text(reason.strip())
            if key and key not in seen:
                seen.add(key)
                items.append(key)
    return items[:5]


def latest_dynamic(successes: list[dict], failures: list[dict]) -> str:
    cached_assets = [display_label(report) for report in successes if report.get("recap_status") == "cached"]
    if cached_assets:
        return f"【最新动态】本次复盘中 {', '.join(cached_assets)} 使用了最近缓存结果，说明对应实时数据源当下不可用或受限。"
    if not successes:
        return "【最新动态】本次没有拿到可用的行情结果。"
    candidate = max(successes, key=lambda report: abs(report.get("price_change_5_bars_pct") or 0))
    change = candidate.get("price_change_5_bars_pct")
    return (
        f"【最新动态】{display_label(candidate)} "
        f"近 5 个周期变动 {change}% ，当前评分 {candidate['score']}，"
        f"量化倾向为{bias_label(candidate)}。"
    )


def market_key(report: dict) -> str:
    asset = report["asset"]
    if asset.get("market") == "crypto":
        return "crypto"
    if asset.get("region") == "CN":
        return "cn_stock"
    return "us_stock"


def market_heading(market: str) -> str:
    return {
        "us_stock": "🇺🇸 美股整体",
        "cn_stock": "🇨🇳 A股整体",
        "crypto": "🪙 数字货币整体",
    }.get(market, market)


def market_reports(successes: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for report in successes:
        grouped[market_key(report)].append(report)
    return grouped


def market_counts(reports: list[dict]) -> dict[str, int]:
    counts = {"buy": 0, "watch": 0, "sell": 0}
    for report in reports:
        counts[action_bucket(report)] += 1
    return counts


def top_translated(items: list[str], limit: int = 2) -> list[str]:
    results = []
    seen = set()
    for item in items:
        text = translate_signal_text(item.strip()).rstrip(".").rstrip("。")
        if text and text not in seen:
            seen.add(text)
            results.append(text)
        if len(results) >= limit:
            break
    return results


def derived_market_message(market: str) -> str:
    return {
        "us_stock": "未提供最新外部宏观上下文时，本段默认以美股资产信号为主。建议结合利率路径、就业、通胀和地缘风险一起看。",
        "cn_stock": "未提供最新外部宏观上下文时，本段默认以A股资产信号为主。建议结合政策、流动性、产业催化和北向资金一起看。",
        "crypto": "未提供最新外部宏观上下文时，本段默认以数字货币资产信号为主。建议结合美元流动性、风险偏好和链上事件一起看。",
    }.get(market, "未提供最新外部宏观上下文，本段默认以技术面为主。")


def derived_market_technical(reports: list[dict]) -> str:
    counts = market_counts(reports)
    positives = top_translated([reason for report in reports for reason in report.get("reasons", [])], limit=2)
    negatives = top_translated([risk for report in reports for risk in report.get("risks", [])], limit=2)
    positive_text = "；".join(positives) if positives else "暂未形成明显共振"
    negative_text = "；".join(negatives) if negatives else "暂未出现突出的共性风险"
    return (
        f"当前市场篮子中，买入 {counts['buy']} 只，观望 {counts['watch']} 只，卖出 {counts['sell']} 只。"
        f"共性偏多信号：{positive_text}。"
        f"共性风险：{negative_text}。"
    )


def derived_market_latest(reports: list[dict]) -> str:
    cached_assets = [display_label(report) for report in reports if report.get("recap_status") == "cached"]
    if cached_assets:
        return f"本市场中 {', '.join(cached_assets)} 使用了缓存结果，说明对应实时数据源当前受限。"
    candidate = max(reports, key=lambda report: abs(report.get("price_change_5_bars_pct") or 0))
    change = candidate.get("price_change_5_bars_pct")
    return (
        f"{display_label(candidate)} 近 5 个周期变动 {change}% ，当前评分 {candidate['score']}，"
        f"量化倾向为{bias_label(candidate)}。"
    )


def market_context_entry(context: dict, market: str) -> dict:
    return context.get(market, {})


def render_market_overview(market: str, reports: list[dict], context: dict) -> list[str]:
    entry = market_context_entry(context, market)
    catalysts = entry.get("catalysts") or top_translated(
        [reason for report in reports for reason in report.get("reasons", [])],
        limit=3,
    )
    risks = entry.get("risks") or top_translated(
        [risk for report in reports for risk in report.get("risks", [])],
        limit=3,
    )
    lines = [
        market_heading(market),
        f"📰 消息面: {entry.get('message') or derived_market_message(market)}",
        f"📈 技术面: {entry.get('technical') or derived_market_technical(reports)}",
        "✨ 利好催化:",
    ]
    if catalysts:
        for index, item in enumerate(catalysts, start=1):
            lines.append(f"利好{index}：{item}")
    else:
        lines.append("利好1：当前没有明显新增催化。")
    lines.append("🚨 风险提示:")
    if risks:
        for index, item in enumerate(risks, start=1):
            lines.append(f"风险{index}：{item}")
    else:
        lines.append("风险1：当前没有显著新增风险。")
    lines.append(f"📢 最新影响: {entry.get('latest') or derived_market_latest(reports)}")
    return lines


def render_report(config: dict, generated_at: datetime, successes: list[dict], failures: list[dict]) -> str:
    date_label = generated_at.strftime("%Y-%m-%d")
    context = config.get("_loaded_market_context", {})
    counts = {"buy": 0, "watch": 0, "sell": 0}
    for report in successes:
        counts[action_bucket(report)] += 1
    grouped_reports = market_reports(successes)
    lines = [
        f"{date_label} 策略建议",
        f"共分析{len(successes)}个标的 | 🟢买入:{counts['buy']} 🟡观望:{counts['watch']} 🔴卖出:{counts['sell']}",
        "",
        "📊 分析结果摘要",
        "",
    ]
    if successes:
        for report in successes:
            lines.append(summary_line(report))
    else:
        lines.append("暂无成功分析结果。")
    if grouped_reports:
        lines.extend(["", "🌍 市场总览", ""])
        for market in ("us_stock", "cn_stock", "crypto"):
            reports = grouped_reports.get(market)
            if not reports:
                continue
            lines.extend(render_market_overview(market, reports, context))
            lines.append("")
    if successes:
        for report in successes:
            lines.extend(["", *asset_section(report), ""])
    if failures:
        lines.extend(["", "⚠️ 数据与执行异常", ""])
        for failure in failures:
            lines.append(f"- {failure['asset']}：{failure['error_cn']}")
    lines.append(f"📢 最新动态: {latest_dynamic(successes, failures)}")
    lines.extend(["", "---", f"生成时间: {generated_at.strftime('%H:%M')}"])
    return "\n".join(lines) + "\n"


def main():
    args = parse_args()
    config_path = Path(args.config)
    config = json.loads(config_path.read_text())
    tushare_mode = args.tushare_mode or config.get("tushare_mode", "http")
    default_timeframe = config.get("timeframe", "1d")
    cache_ttl_hours = args.cache_ttl_hours or int(config.get("cache_ttl_hours", 72))
    successes = []
    failures = []
    for item in config.get("assets", []):
        asset_query = item["asset"]
        try:
            report = analyze(
                asset_query=asset_query,
                market=item.get("market", "auto"),
                timeframe=item.get("timeframe", default_timeframe),
                memory_file=Path(args.memory_file) if args.memory_file else None,
                tushare_mode=item.get("tushare_mode", tushare_mode),
            )
            if item.get("label"):
                report["asset"] = {**report["asset"], "recap_label": item["label"]}
            report["recap_status"] = "live"
            save_cached_report(item, report, default_timeframe, tushare_mode)
            successes.append(report)
        except Exception as error:
            cached_report = load_cached_report(item, default_timeframe, tushare_mode, cache_ttl_hours)
            if cached_report is not None:
                if item.get("label"):
                    cached_report["asset"] = {**cached_report["asset"], "recap_label": item["label"]}
                successes.append(cached_report)
                failures.append(
                    {
                        "asset": asset_query,
                        "error_cn": f"实时分析失败，已回退到缓存：{error}",
                        "error_en": f"live analysis failed, cache used instead: {error}",
                    }
                )
                continue
            failures.append(
                {
                    "asset": asset_query,
                    "error_cn": str(error),
                    "error_en": str(error),
                }
            )
    config["_loaded_market_context"] = load_market_context(config, config_path, args.market_context_file)
    rendered = render_report(config, datetime.now(), successes, failures)
    if args.output:
        Path(args.output).write_text(rendered)
    print(rendered, end="")
    notifier = config.get("notifier")
    if notifier and notifier.get("type") != "stdout":
        send_notification(notifier, rendered, payload={"message": rendered, "reports": successes, "failures": failures})


if __name__ == "__main__":
    main()

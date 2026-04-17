#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

from quant_core import analyze, ensure_state_dir, load_json, recommendation_label, send_notification, write_json

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0 Safari/537.36"

DEFAULT_IGNORE_TITLE_SNIPPETS = [
    "stock quote",
    "price and forecast",
    "forecast",
    "prediction",
    "is it a buy",
    "stock quotes",
    "company news and chart analysis",
    "simplywall.st",
    "sahm",
    "careers",
    "investors -",
]

GLOBAL_EVENT_KEYWORDS = [
    "earnings",
    "results",
    "guidance",
    "conference",
    "conference call",
    "investor day",
    "annual meeting",
    "webcast",
    "keynote",
    "launch",
    "approval",
    "trial",
    "phase",
    "fda",
    "monthly revenue",
    "revenue report",
]

POSITIVE_KEYWORDS = [
    "approval",
    "approved",
    "beats",
    "record revenue",
    "launch",
    "partnership",
    "expands",
    "raises",
    "strong demand",
    "phase 3",
    "positive",
]

NEGATIVE_KEYWORDS = [
    "probe",
    "lawsuit",
    "delay",
    "ban",
    "restriction",
    "cuts",
    "misses",
    "warning",
    "recall",
    "downgrade",
    "antitrust",
    "tariff",
]

MACRO_POSITIVE_KEYWORDS = [
    "ceasefire",
    "pause",
    "truce",
    "oil falls",
    "inflation cools",
    "rate cut",
    "disinflation",
]

MACRO_NEGATIVE_KEYWORDS = [
    "strike",
    "attack",
    "missile",
    "bombing",
    "oil jumps",
    "oil rises",
    "inflation fears",
    "rate hike",
    "hawkish",
    "escalation",
    "sanctions",
]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Monitor material news flow and upcoming events for a watchlist, then notify through stdout, webhook, or OpenClaw."
    )
    parser.add_argument("--config", required=True, help="Path to the news/event monitor config JSON.")
    parser.add_argument("--once", action="store_true", help="Run a single monitoring cycle and exit.")
    parser.add_argument("--cycles", type=int, help="Maximum cycles before exiting.")
    parser.add_argument("--state-file", help="Optional path for the dedupe state file.")
    parser.add_argument("--memory-file", help="Optional learning memory path reused during technical analysis.")
    return parser.parse_args()


def default_state_path() -> Path:
    return ensure_state_dir() / "news_event_state.json"


def fetch_text(url: str, timeout: int = 20) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def google_news_rss_url(query: str) -> str:
    return (
        "https://news.google.com/rss/search?q="
        f"{urllib.parse.quote(query)}&hl=en-US&gl=US&ceid=US:en"
    )


def parse_google_news_feed(url: str) -> list[dict]:
    text = fetch_text(url)
    root = ET.fromstring(text)
    items = []
    for item in root.findall("./channel/item"):
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        guid = (item.findtext("guid") or link or title).strip()
        source = (item.findtext("source") or "").strip()
        pub_date_text = (item.findtext("pubDate") or "").strip()
        published_at = None
        if pub_date_text:
            try:
                published_at = parsedate_to_datetime(pub_date_text).astimezone(UTC)
            except Exception:
                published_at = None
        items.append(
            {
                "title": title,
                "link": link,
                "guid": guid,
                "source": source,
                "published_at": published_at,
            }
        )
    return items


def stable_news_id(asset_symbol: str, item: dict) -> str:
    raw = f"{asset_symbol}|{item.get('guid')}|{item.get('title')}|{item.get('source')}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def stable_macro_id(macro_name: str, item: dict) -> str:
    raw = f"{macro_name}|{item.get('guid')}|{item.get('title')}|{item.get('source')}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def parse_event_datetime(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def is_noise_title(title: str, asset_config: dict) -> bool:
    lowered = title.lower()
    for snippet in DEFAULT_IGNORE_TITLE_SNIPPETS + asset_config.get("ignore_title_snippets", []):
        if snippet.lower() in lowered:
            return True
    return False


def is_material_item(title: str, asset_config: dict) -> bool:
    lowered = title.lower()
    if is_noise_title(title, asset_config):
        return False
    material_keywords = [keyword.lower() for keyword in asset_config.get("material_keywords", [])]
    if any(keyword in lowered for keyword in material_keywords):
        return True
    return any(keyword in lowered for keyword in GLOBAL_EVENT_KEYWORDS)


def source_allowed(item: dict, config: dict) -> bool:
    allowlist = [value.lower() for value in config.get("source_allowlist", [])]
    if not allowlist:
        return True
    source = (item.get("source") or "").lower()
    return any(candidate in source for candidate in allowlist)


def alert_gap_seconds(config: dict) -> int:
    return int(float(config.get("min_alert_gap_hours", 0)) * 3600)


def max_alerts_per_cycle(config: dict) -> int:
    return max(0, int(config.get("max_alerts_per_cycle", 0)))


def classify_item(asset_config: dict, item: dict) -> dict:
    text = f"{item.get('title', '')} {item.get('source', '')}".lower()
    asset_name = asset_config.get("label") or asset_config["asset"]
    if any(keyword in text for keyword in ("earnings", "results", "conference call", "guidance", "quarter")):
        return {
            "kind": "earnings-event",
            "tone_cn": "事件催化 / 波动放大",
            "tone_en": "Event catalyst / volatility expansion",
            "impact_cn": f"{asset_name} 的财报或业绩会明显放大波动；若收入、利润率或指引超预期，通常偏利好，若指引下修则偏风险。",
            "impact_en": f"Earnings-related headlines can expand volatility for {asset_name}. Beats on revenue, margins, or guidance are bullish; guidance cuts are a risk.",
        }
    if any(keyword in text for keyword in ("approval", "approved", "fda", "trial", "phase")):
        return {
            "kind": "approval-or-trial",
            "tone_cn": "偏利好催化",
            "tone_en": "Bullish catalyst",
            "impact_cn": f"{asset_name} 的审批、临床或监管进展通常会重新定价增长预期，尤其容易影响中期趋势。",
            "impact_en": f"Regulatory approvals and trial updates can reprice growth expectations for {asset_name}, especially over the medium term.",
        }
    if any(keyword in text for keyword in ("launch", "keynote", "platform", "product", "conference", "investor day", "webcast")):
        return {
            "kind": "product-or-event-preview",
            "tone_cn": "偏催化，需看兑现",
            "tone_en": "Catalyst watch, but needs confirmation",
            "impact_cn": f"{asset_name} 的发布会、产品更新或投资者活动通常会影响市场预期；如果路线图或需求表述超预期，容易形成利好。",
            "impact_en": f"Launches, keynotes, and investor events can shift expectations for {asset_name}; positive roadmap or demand commentary is usually bullish.",
        }
    if any(keyword in text for keyword in NEGATIVE_KEYWORDS):
        return {
            "kind": "risk-news",
            "tone_cn": "偏风险",
            "tone_en": "Risk-off",
            "impact_cn": f"{asset_name} 出现监管、诉讼、限制或指引下修类消息时，通常会压制估值和风险偏好。",
            "impact_en": f"Regulatory, legal, restriction, or guidance-cut headlines typically pressure valuation and risk appetite for {asset_name}.",
        }
    if any(keyword in text for keyword in POSITIVE_KEYWORDS):
        return {
            "kind": "positive-news",
            "tone_cn": "偏利好",
            "tone_en": "Bullish tilt",
            "impact_cn": f"{asset_name} 的需求扩张、合作、产品和业绩超预期类消息通常偏利好，但仍要看量价是否跟上。",
            "impact_en": f"Demand, partnership, product, or beat-related headlines are generally bullish for {asset_name}, though price and volume still need to confirm.",
        }
    return {
        "kind": "watch-news",
        "tone_cn": "观察中",
        "tone_en": "Watch",
        "impact_cn": asset_config.get(
            "default_impact_cn",
            f"{asset_name} 的新消息值得跟踪，但最终影响还要结合后续价格、量能和管理层表述判断。",
        ),
        "impact_en": asset_config.get(
            "default_impact_en",
            f"New headlines around {asset_name} are worth tracking, but the real impact still depends on follow-through in price, volume, and management commentary.",
        ),
    }


def format_local_time(dt: datetime | None) -> str:
    if dt is None:
        return "unknown"
    return dt.astimezone().strftime("%Y-%m-%d %H:%M %Z")


def compact_title(title: str, limit: int = 160) -> str:
    title = " ".join(title.split())
    if len(title) <= limit:
        return title
    return title[: limit - 1].rstrip() + "…"


def build_news_message(asset_config: dict, item: dict, report: dict | None) -> str:
    profile = classify_item(asset_config, item)
    symbol = asset_config["asset"]
    label = asset_config.get("label") or symbol
    levels = report.get("levels", {}) if report else {}
    recommendation = recommendation_label(report["recommendation"]) if report else "Unavailable"
    current_price = report.get("current_price") if report else "Unavailable"
    return (
        f"【重大事件】\n"
        f"[中文]\n"
        f"{label} 消息提醒：{compact_title(item['title'])}\n"
        f"来源：{item.get('source') or 'Google News'} | 发布时间：{format_local_time(item.get('published_at'))}\n"
        f"消息判断：{profile['tone_cn']}\n"
        f"可能影响：{profile['impact_cn']}\n"
        f"当前技术面：{recommendation} | 当前价格：{current_price} | 观察买点：{levels.get('first_buy_level')} | 确认位：{levels.get('confirmation_buy_level')} | 防守线：{levels.get('defensive_sell_trigger')}\n"
        f"链接：{item.get('link')}\n\n"
        f"[Major Event]\n"
        f"[EN]\n"
        f"{symbol} news alert: {compact_title(item['title'])}\n"
        f"Source: {item.get('source') or 'Google News'} | Published: {format_local_time(item.get('published_at'))}\n"
        f"Take: {profile['tone_en']}\n"
        f"Potential impact: {profile['impact_en']}\n"
        f"Current technical view: {recommendation} | Price: {current_price} | First watch-buy: {levels.get('first_buy_level')} | Confirmation: {levels.get('confirmation_buy_level')} | Defense: {levels.get('defensive_sell_trigger')}\n"
        f"Link: {item.get('link')}"
    )


def build_event_message(asset_config: dict, event: dict, milestone_days: int, report: dict | None) -> str:
    symbol = asset_config["asset"]
    label = asset_config.get("label") or symbol
    start_at = parse_event_datetime(event["start_at"])
    levels = report.get("levels", {}) if report else {}
    recommendation = recommendation_label(report["recommendation"]) if report else "Unavailable"
    current_price = report.get("current_price") if report else "Unavailable"
    impact_cn = event.get(
        "impact_cn",
        f"{label} 的预告事件通常会提升波动率。若活动中的产品、指引或需求表述超预期，偏利好；若预期落空，则偏风险。",
    )
    impact_en = event.get(
        "impact_en",
        f"Upcoming events for {label} can raise volatility. Better-than-expected product, guidance, or demand commentary is bullish; disappointment is a risk.",
    )
    title_cn = event.get("title_cn") or event.get("title") or "事件提醒"
    title_en = event.get("title_en") or event.get("title") or "event reminder"
    return (
        f"【重大事件】\n"
        f"[中文]\n"
        f"{label} 事件提醒：{title_cn}\n"
        f"距离事件：约 {milestone_days} 天 | 时间：{format_local_time(start_at)}\n"
        f"为什么重要：{impact_cn}\n"
        f"当前技术面：{recommendation} | 当前价格：{current_price} | 观察买点：{levels.get('first_buy_level')} | 确认位：{levels.get('confirmation_buy_level')} | 防守线：{levels.get('defensive_sell_trigger')}\n"
        f"链接：{event.get('url', 'N/A')}\n\n"
        f"[Major Event]\n"
        f"[EN]\n"
        f"{symbol} event reminder: {title_en}\n"
        f"Time to event: about {milestone_days} day(s) | Scheduled: {format_local_time(start_at)}\n"
        f"Why it matters: {impact_en}\n"
        f"Current technical view: {recommendation} | Price: {current_price} | First watch-buy: {levels.get('first_buy_level')} | Confirmation: {levels.get('confirmation_buy_level')} | Defense: {levels.get('defensive_sell_trigger')}\n"
        f"Link: {event.get('url', 'N/A')}"
    )


def classify_macro_item(macro_config: dict, item: dict) -> dict:
    text = f"{item.get('title', '')} {item.get('source', '')}".lower()
    if any(keyword in text for keyword in MACRO_NEGATIVE_KEYWORDS):
        return {
            "tone_cn": "偏风险",
            "tone_en": "Risk-off",
        }
    if any(keyword in text for keyword in MACRO_POSITIVE_KEYWORDS):
        return {
            "tone_cn": "偏利好",
            "tone_en": "Risk-on",
        }
    return {
        "tone_cn": "中性偏观察",
        "tone_en": "Neutral / watch",
    }


def build_macro_message(macro_config: dict, item: dict, affected_reports: list[dict]) -> str:
    profile = classify_macro_item(macro_config, item)
    lines = [
        "【重大事件】",
        "[中文]",
        f"宏观/地缘提醒：{compact_title(item['title'])}",
        f"主题：{macro_config.get('label_cn') or macro_config.get('name', '宏观风险')}",
        f"来源：{item.get('source') or 'Google News'} | 发布时间：{format_local_time(item.get('published_at'))}",
        f"风险判断：{profile['tone_cn']}",
        f"为什么重要：{macro_config.get('summary_cn', '这类外部事件会先影响风险偏好、油价、利率预期，再传导到科技和成长股估值。')}",
    ]
    if affected_reports:
        lines.append("对持仓影响：")
        for report in affected_reports:
            label = report["asset"].get("recap_label") or report["asset"].get("display_name") or report["asset"]["symbol"]
            levels = report.get("levels", {})
            lines.append(
                f"- {label}: 当前价 {report.get('current_price')} | 判断 {recommendation_label(report['recommendation'])} | 观察买点 {levels.get('first_buy_level')} | 防守线 {levels.get('defensive_sell_trigger')}"
            )
    lines.extend(
        [
            f"链接：{item.get('link')}",
            "",
            "[Major Event]",
            "[EN]",
            f"Macro / geopolitical alert: {compact_title(item['title'])}",
            f"Theme: {macro_config.get('label_en') or macro_config.get('name', 'macro risk')}",
            f"Source: {item.get('source') or 'Google News'} | Published: {format_local_time(item.get('published_at'))}",
            f"Take: {profile['tone_en']}",
            f"Why it matters: {macro_config.get('summary_en', 'These external shocks usually hit risk appetite, oil, and rate expectations first, then flow into growth and semiconductor valuations.')}",
        ]
    )
    if affected_reports:
        lines.append("Portfolio impact:")
        for report in affected_reports:
            label = report["asset"].get("recap_label") or report["asset"].get("display_name") or report["asset"]["symbol"]
            levels = report.get("levels", {})
            lines.append(
                f"- {label}: price {report.get('current_price')} | view {recommendation_label(report['recommendation'])} | first watch-buy {levels.get('first_buy_level')} | defense {levels.get('defensive_sell_trigger')}"
            )
    lines.append(f"Link: {item.get('link')}")
    return "\n".join(lines)


def asset_state(state: dict, monitor_id: str, asset_symbol: str) -> dict:
    assets = state.setdefault("monitors", {}).setdefault(monitor_id, {}).setdefault("assets", {})
    return assets.setdefault(
        asset_symbol,
        {"seen_news_ids": [], "events_sent": {}, "bootstrapped_news": False, "last_news_sent_at": 0},
    )


def remember_news_id(asset_entry: dict, news_id: str, limit: int = 400) -> None:
    seen = asset_entry.setdefault("seen_news_ids", [])
    if news_id in seen:
        return
    seen.append(news_id)
    if len(seen) > limit:
        del seen[:-limit]


def maybe_analyze_asset(asset_config: dict, args) -> dict | None:
    try:
        return analyze(
            asset_query=asset_config["asset"],
            market=asset_config.get("market", "auto"),
            timeframe=asset_config.get("timeframe", "1d"),
            memory_file=Path(args.memory_file) if args.memory_file else None,
            tushare_mode=asset_config.get("tushare_mode", "http"),
        )
    except Exception:
        return None


def macro_state(state: dict, monitor_id: str) -> dict:
    monitor_entry = state.setdefault("monitors", {}).setdefault(monitor_id, {})
    return monitor_entry.setdefault("macro_watch", {"seen_ids": [], "bootstrapped": False})


def remember_seen_id(container: dict, key: str, seen_id: str, limit: int = 400) -> None:
    seen = container.setdefault(key, [])
    if seen_id in seen:
        return
    seen.append(seen_id)
    if len(seen) > limit:
        del seen[:-limit]


def process_news(asset_config: dict, monitor_config: dict, state_entry: dict, notifier: dict, args) -> None:
    report = maybe_analyze_asset(asset_config, args)
    first_run_seed = bool(monitor_config.get("seed_existing_news", True))
    bootstrap_send_limit = int(monitor_config.get("bootstrap_send_limit", 0))
    queries = asset_config.get("news_queries", [])
    if not queries:
        return

    collected = []
    for query in queries:
        try:
            for item in parse_google_news_feed(google_news_rss_url(query)):
                if not is_material_item(item.get("title", ""), asset_config):
                    continue
                collected.append(item)
        except Exception:
            continue

    deduped = []
    seen_runtime = set()
    for item in sorted(
        collected,
        key=lambda current: current.get("published_at") or datetime.fromtimestamp(0, tz=UTC),
        reverse=True,
    ):
        news_id = stable_news_id(asset_config["asset"], item)
        if news_id in seen_runtime:
            continue
        seen_runtime.add(news_id)
        deduped.append((news_id, item))

    per_cycle_limit = max_alerts_per_cycle(asset_config)
    sent_this_cycle = 0
    gap_seconds = alert_gap_seconds(asset_config)
    now = int(time.time())

    if not state_entry.get("bootstrapped_news"):
        for index, (news_id, item) in enumerate(deduped):
            if bootstrap_send_limit and index < bootstrap_send_limit:
                if source_allowed(item, asset_config):
                    message = build_news_message(asset_config, item, report)
                    send_notification(notifier, message, payload={"message": message, "item": item, "report": report})
                    state_entry["last_news_sent_at"] = now
            remember_news_id(state_entry, news_id)
        state_entry["bootstrapped_news"] = True
        if first_run_seed:
            return

    for news_id, item in deduped:
        if news_id in state_entry.get("seen_news_ids", []):
            continue
        remember_news_id(state_entry, news_id)
        if not source_allowed(item, asset_config):
            continue
        if per_cycle_limit and sent_this_cycle >= per_cycle_limit:
            continue
        if gap_seconds and now - int(state_entry.get("last_news_sent_at", 0)) < gap_seconds:
            continue
        message = build_news_message(asset_config, item, report)
        send_notification(notifier, message, payload={"message": message, "item": item, "report": report})
        state_entry["last_news_sent_at"] = now
        sent_this_cycle += 1


def process_macro_watch(config: dict, state: dict, notifier: dict, args) -> None:
    monitor_id = config.get("id", "news-event-monitor")
    macro_configs = config.get("macro_watch", [])
    if not macro_configs:
        return
    state_entry = macro_state(state, monitor_id)
    asset_index = {asset["asset"]: asset for asset in config.get("assets", [])}
    first_run_seed = bool(config.get("seed_existing_news", True))
    bootstrap_send_limit = int(config.get("bootstrap_send_limit", 0))

    for macro_config in macro_configs:
        collected = []
        for query in macro_config.get("queries", []):
            try:
                for item in parse_google_news_feed(google_news_rss_url(query)):
                    title = item.get("title", "")
                    if not title:
                        continue
                    lowered = title.lower()
                    keywords = [keyword.lower() for keyword in macro_config.get("material_keywords", [])]
                    if keywords and not any(keyword in lowered for keyword in keywords):
                        continue
                    collected.append(item)
            except Exception:
                continue

        deduped = []
        seen_runtime = set()
        for item in sorted(
            collected,
            key=lambda current: current.get("published_at") or datetime.fromtimestamp(0, tz=UTC),
            reverse=True,
        ):
            item_id = stable_macro_id(macro_config.get("name", "macro"), item)
            if item_id in seen_runtime:
                continue
            seen_runtime.add(item_id)
            deduped.append((item_id, item))

        macro_seen_key = f"seen_ids::{macro_config.get('name', 'macro')}"
        bootstrapped_key = f"bootstrapped::{macro_config.get('name', 'macro')}"
        last_sent_key = f"last_sent_at::{macro_config.get('name', 'macro')}"
        per_cycle_limit = max_alerts_per_cycle(macro_config)
        sent_this_cycle = 0
        gap_seconds = alert_gap_seconds(macro_config)
        now = int(time.time())

        if not state_entry.get(bootstrapped_key):
            for index, (item_id, item) in enumerate(deduped):
                if bootstrap_send_limit and index < bootstrap_send_limit:
                    if source_allowed(item, macro_config):
                        affected_reports = []
                        for asset_symbol in macro_config.get("affected_assets", []):
                            asset_config = asset_index.get(asset_symbol)
                            if not asset_config:
                                continue
                            report = maybe_analyze_asset(asset_config, args)
                            if report is not None:
                                report["asset"] = {**report["asset"], "recap_label": asset_config.get("label", asset_symbol)}
                                affected_reports.append(report)
                        message = build_macro_message(macro_config, item, affected_reports)
                        send_notification(notifier, message, payload={"message": message, "item": item, "reports": affected_reports})
                        state_entry[last_sent_key] = now
                remember_seen_id(state_entry, macro_seen_key, item_id)
            state_entry[bootstrapped_key] = True
            if first_run_seed:
                continue

        for item_id, item in deduped:
            if item_id in state_entry.get(macro_seen_key, []):
                continue
            remember_seen_id(state_entry, macro_seen_key, item_id)
            if not source_allowed(item, macro_config):
                continue
            if per_cycle_limit and sent_this_cycle >= per_cycle_limit:
                continue
            if gap_seconds and now - int(state_entry.get(last_sent_key, 0)) < gap_seconds:
                continue
            affected_reports = []
            for asset_symbol in macro_config.get("affected_assets", []):
                asset_config = asset_index.get(asset_symbol)
                if not asset_config:
                    continue
                report = maybe_analyze_asset(asset_config, args)
                if report is not None:
                    report["asset"] = {**report["asset"], "recap_label": asset_config.get("label", asset_symbol)}
                    affected_reports.append(report)
            message = build_macro_message(macro_config, item, affected_reports)
            send_notification(notifier, message, payload={"message": message, "item": item, "reports": affected_reports})
            state_entry[last_sent_key] = now
            sent_this_cycle += 1


def process_events(asset_config: dict, state_entry: dict, notifier: dict, args) -> None:
    events = asset_config.get("manual_events", [])
    if not events:
        return
    report = maybe_analyze_asset(asset_config, args)
    now = datetime.now(tz=UTC)
    sent_state = state_entry.setdefault("events_sent", {})
    for event in events:
        try:
            start_at = parse_event_datetime(event["start_at"])
        except Exception:
            continue
        if start_at <= now:
            continue
        delta_days = max(0, math.ceil((start_at - now).total_seconds() / 86400))
        milestones = sorted(set(int(value) for value in event.get("notify_days_before", [30, 14, 7, 3, 1])))
        eligible = [value for value in milestones if delta_days <= value]
        if not eligible:
            continue
        milestone = min(eligible)
        event_id = event.get("id") or hashlib.sha256(
            f"{asset_config['asset']}|{event.get('title')}|{event.get('start_at')}".encode("utf-8")
        ).hexdigest()
        milestone_key = str(milestone)
        sent_for_event = sent_state.setdefault(event_id, {})
        if sent_for_event.get(milestone_key):
            continue
        message = build_event_message(asset_config, event, milestone, report)
        send_notification(notifier, message, payload={"message": message, "event": event, "report": report})
        sent_for_event[milestone_key] = int(time.time())


def run_cycle(config: dict, state: dict, args) -> None:
    monitor_id = config.get("id", "news-event-monitor")
    notifier = config.get("notifier", {"type": "stdout"})
    process_macro_watch(config, state, notifier, args)
    for asset_config in config.get("assets", []):
        entry = asset_state(state, monitor_id, asset_config["asset"])
        process_events(asset_config, entry, notifier, args)
        process_news(asset_config, config, entry, notifier, args)


def main():
    args = parse_args()
    config_path = Path(args.config)
    config = json.loads(config_path.read_text())
    state_path = Path(args.state_file) if args.state_file else default_state_path()
    state = load_json(state_path, {"monitors": {}})

    cycle = 0
    while True:
        cycle += 1
        run_cycle(config, state, args)
        write_json(state_path, state)
        if args.once:
            break
        if args.cycles is not None and cycle >= args.cycles:
            break
        time.sleep(int(config.get("poll_seconds", 900)))


if __name__ == "__main__":
    main()

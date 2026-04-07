#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from quant_core import default_memory_path, load_json


def outcome_key(outcome: str) -> str:
    return {
        "win": "wins",
        "loss": "losses",
        "invalidated": "invalidated",
    }.get(outcome, "invalidated")


def parse_args():
    parser = argparse.ArgumentParser(description="Summarize historical labeled outcomes from the learning memory.")
    parser.add_argument("--memory-file", help="Optional learning memory path.")
    parser.add_argument("--format", default="markdown", choices=["markdown", "json"], help="Output format.")
    parser.add_argument("--limit", type=int, default=10, help="How many recent feedback rows to show.")
    return parser.parse_args()


def build_summary(memory: dict, limit: int) -> dict:
    feedback = list(memory.get("feedback", []))
    total = len(feedback)
    by_outcome = defaultdict(int)
    by_asset = defaultdict(lambda: {"count": 0, "wins": 0, "losses": 0, "invalidated": 0, "returns": []})
    by_tag = defaultdict(lambda: {"count": 0, "wins": 0, "losses": 0, "invalidated": 0})
    for item in feedback:
        outcome = item.get("outcome", "unknown")
        by_outcome[outcome] += 1
        asset_key = item.get("asset", {}).get("symbol") or item.get("asset", {}).get("display_name") or "unknown"
        asset_stats = by_asset[asset_key]
        asset_stats["count"] += 1
        asset_stats[outcome_key(outcome)] += 1
        if item.get("realized_return") is not None:
            asset_stats["returns"].append(float(item["realized_return"]))
        for tag in item.get("tags", []):
            tag_stats = by_tag[tag]
            tag_stats["count"] += 1
            tag_stats[outcome_key(outcome)] += 1
    asset_rows = []
    for asset_key, stats in by_asset.items():
        avg_return = round(sum(stats["returns"]) / len(stats["returns"]), 2) if stats["returns"] else None
        win_rate = round((stats["wins"] / stats["count"]) * 100.0, 1) if stats["count"] else None
        asset_rows.append(
            {
                "asset": asset_key,
                "count": stats["count"],
                "wins": stats["wins"],
                "losses": stats["losses"],
                "invalidated": stats["invalidated"],
                "win_rate": win_rate,
                "avg_return": avg_return,
            }
        )
    asset_rows.sort(key=lambda item: (-item["count"], item["asset"]))
    tag_rows = []
    for tag, stats in by_tag.items():
        win_rate = round((stats["wins"] / stats["count"]) * 100.0, 1) if stats["count"] else None
        tag_rows.append(
            {
                "tag": tag,
                "count": stats["count"],
                "wins": stats["wins"],
                "losses": stats["losses"],
                "invalidated": stats["invalidated"],
                "win_rate": win_rate,
            }
        )
    tag_rows.sort(key=lambda item: (-item["count"], item["tag"]))
    recent = list(reversed(feedback[-limit:]))
    return {
        "total_feedback": total,
        "by_outcome": dict(by_outcome),
        "by_asset": asset_rows,
        "by_tag": tag_rows,
        "recent": recent,
    }


def render_markdown(summary: dict) -> str:
    lines = [
        "# Historical Accuracy Report",
        "",
        f"- Total labeled cases: {summary['total_feedback']}",
        f"- Wins: {summary['by_outcome'].get('win', 0)}",
        f"- Losses: {summary['by_outcome'].get('loss', 0)}",
        f"- Invalidated: {summary['by_outcome'].get('invalidated', 0)}",
        "",
        "## By Asset",
        "",
    ]
    if summary["by_asset"]:
        for row in summary["by_asset"]:
            lines.append(
                f"- {row['asset']}: {row['wins']}W/{row['losses']}L/{row['invalidated']}I over {row['count']} cases, "
                f"win rate {row['win_rate']}%, avg return {row['avg_return']}%"
            )
    else:
        lines.append("- No labeled asset outcomes yet.")
    lines.extend(["", "## By Tag", ""])
    if summary["by_tag"]:
        for row in summary["by_tag"][:10]:
            lines.append(
                f"- {row['tag']}: {row['wins']}W/{row['losses']}L/{row['invalidated']}I over {row['count']} cases, "
                f"win rate {row['win_rate']}%"
            )
    else:
        lines.append("- No setup tags have labeled outcomes yet.")
    lines.extend(["", "## Recent Outcomes", ""])
    if summary["recent"]:
        for row in summary["recent"]:
            asset = row.get("asset", {}).get("symbol") or row.get("asset", {}).get("display_name") or "unknown"
            lines.append(
                f"- {asset} | {row.get('timeframe')} | {row.get('outcome')} | score {row.get('score')} | "
                f"return {row.get('realized_return')} | notes {row.get('notes') or '-'}"
            )
    else:
        lines.append("- No feedback recorded yet.")
    return "\n".join(lines) + "\n"


def main():
    args = parse_args()
    path = Path(args.memory_file) if args.memory_file else default_memory_path()
    memory = load_json(path, {"feedback": [], "tag_stats": {}})
    summary = build_summary(memory, args.limit)
    if args.format == "json":
        print(json.dumps(summary, indent=2, ensure_ascii=True))
    else:
        print(render_markdown(summary), end="")


if __name__ == "__main__":
    main()

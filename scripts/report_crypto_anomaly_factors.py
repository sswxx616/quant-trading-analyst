#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from quant_core import ensure_state_dir


def default_factor_log_path() -> Path:
    return ensure_state_dir() / "crypto_anomaly_factor_log.jsonl"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Summarize recorded crypto anomaly-factor snapshots and estimate forward hit rates."
    )
    parser.add_argument("--log-file", help="Optional anomaly factor log path.")
    parser.add_argument("--format", default="markdown", choices=["markdown", "json"])
    parser.add_argument("--horizon-hours", nargs="*", type=int, default=[6, 24])
    parser.add_argument("--limit", type=int, default=10, help="Recent qualified rows to show.")
    return parser.parse_args()


def load_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def pct_change(future: float | None, current: float | None) -> float | None:
    if current in (None, 0) or future in (None, 0):
        return None
    return ((float(future) / float(current)) - 1.0) * 100.0


def bucketize(row: dict) -> dict:
    anomaly = float(row.get("anomaly_score") or 0.0)
    rv15 = float(row.get("relative_volume_15m") or 0.0)
    h1 = float(row.get("change_1h_6bars_pct") or 0.0)
    oi = row.get("oi_change_pct")
    funding = row.get("funding_rate_pct")
    return {
        "anomaly_band": "30-39" if anomaly < 40 else "40-49" if anomaly < 50 else "50+",
        "rv15_band": "<1.0" if rv15 < 1.0 else "1.0-1.9" if rv15 < 2.0 else "2.0+",
        "h1_band": "<4%" if h1 < 4 else "4-8%" if h1 < 8 else "8%+",
        "oi_band": "positive" if (oi is not None and float(oi) > 0) else "flat-or-negative",
        "funding_band": "hot" if (funding is not None and float(funding) >= 0.08) else "normal-or-cool",
        "plan_action": row.get("plan_action") or "not-qualified",
    }


def resolve_forward_returns(rows: list[dict], horizons: list[int]) -> list[dict]:
    by_symbol = defaultdict(list)
    for row in rows:
        by_symbol[row["symbol"]].append(row)
    for symbol_rows in by_symbol.values():
        symbol_rows.sort(key=lambda item: item["recorded_at"])

    enriched = []
    for row in rows:
        symbol_rows = by_symbol[row["symbol"]]
        enriched_row = dict(row)
        for horizon in horizons:
            target_ts = int(row["recorded_at"]) + horizon * 3600
            future_price = None
            for future in symbol_rows:
                if future["recorded_at"] >= target_ts:
                    future_price = future.get("price")
                    break
            enriched_row[f"forward_{horizon}h_return_pct"] = pct_change(future_price, row.get("price"))
        enriched.append(enriched_row)
    return enriched


def summarize_group(rows: list[dict], horizons: list[int]) -> dict:
    summary = {"count": len(rows)}
    for horizon in horizons:
        key = f"forward_{horizon}h_return_pct"
        values = [float(row[key]) for row in rows if row.get(key) is not None]
        if not values:
            summary[f"{horizon}h_avg_return"] = None
            summary[f"{horizon}h_win_rate"] = None
            continue
        wins = sum(1 for value in values if value > 0)
        summary[f"{horizon}h_avg_return"] = round(sum(values) / len(values), 2)
        summary[f"{horizon}h_win_rate"] = round((wins / len(values)) * 100.0, 1)
    return summary


def build_summary(rows: list[dict], horizons: list[int], limit: int) -> dict:
    enriched = resolve_forward_returns(rows, horizons)
    qualified = [row for row in enriched if row.get("qualified")]
    by_dimension = {
        "anomaly_band": defaultdict(list),
        "rv15_band": defaultdict(list),
        "h1_band": defaultdict(list),
        "oi_band": defaultdict(list),
        "funding_band": defaultdict(list),
        "plan_action": defaultdict(list),
    }
    for row in qualified:
        buckets = bucketize(row)
        for key, value in buckets.items():
            by_dimension[key][value].append(row)

    grouped = {}
    for dimension, bucket_rows in by_dimension.items():
        grouped[dimension] = []
        for bucket, bucket_items in bucket_rows.items():
            grouped[dimension].append({"bucket": bucket, **summarize_group(bucket_items, horizons)})
        grouped[dimension].sort(key=lambda item: (-item["count"], item["bucket"]))

    qualified_recent = sorted(qualified, key=lambda row: row["recorded_at"], reverse=True)[:limit]
    return {
        "total_rows": len(enriched),
        "qualified_rows": len(qualified),
        "horizons": horizons,
        "overall": summarize_group(qualified, horizons) if qualified else {"count": 0},
        "dimensions": grouped,
        "recent_qualified": qualified_recent,
    }


def render_markdown(summary: dict) -> str:
    horizons = summary["horizons"]
    lines = [
        "# Crypto Anomaly Factor Report",
        "",
        f"- Total snapshots: {summary['total_rows']}",
        f"- Qualified anomaly-plan snapshots: {summary['qualified_rows']}",
    ]
    for horizon in horizons:
        lines.append(
            f"- Overall {horizon}h: avg return {summary['overall'].get(f'{horizon}h_avg_return')}% | "
            f"win rate {summary['overall'].get(f'{horizon}h_win_rate')}%"
        )
    for dimension, rows in summary["dimensions"].items():
        lines.extend(["", f"## {dimension}", ""])
        if not rows:
            lines.append("- No evaluable rows yet.")
            continue
        for row in rows:
            metrics = [f"{row['count']} cases"]
            for horizon in horizons:
                metrics.append(
                    f"{horizon}h avg {row.get(f'{horizon}h_avg_return')}% / win {row.get(f'{horizon}h_win_rate')}%"
                )
            lines.append(f"- {row['bucket']}: " + " | ".join(metrics))
    lines.extend(["", "## Recent Qualified Snapshots", ""])
    if not summary["recent_qualified"]:
        lines.append("- No qualified anomaly-plan snapshots yet.")
    else:
        for row in summary["recent_qualified"]:
            lines.append(
                f"- {row['base_asset']} ({row['symbol']}) | anomaly {row['anomaly_score']} | quant {row['quant_score']} | "
                f"action {row.get('plan_action')} | price {row['price']}"
            )
    return "\n".join(lines) + "\n"


def main():
    args = parse_args()
    path = Path(args.log_file) if args.log_file else default_factor_log_path()
    rows = load_rows(path)
    summary = build_summary(rows, args.horizon_hours, args.limit)
    if args.format == "json":
        print(json.dumps(summary, indent=2, ensure_ascii=True))
    else:
        print(render_markdown(summary), end="")


if __name__ == "__main__":
    main()

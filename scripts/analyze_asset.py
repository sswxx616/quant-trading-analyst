#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from quant_core import analyze, apply_local_runtime_env, format_markdown


def parse_args():
    parser = argparse.ArgumentParser(description="Analyze a stock or crypto asset with explainable quant signals.")
    parser.add_argument("--asset", required=True, help="Ticker, symbol, stock name, or crypto name.")
    parser.add_argument(
        "--market",
        default="auto",
        choices=["auto", "stock", "us-stock", "cn-stock", "crypto"],
        help="Asset class override. Use cn-stock for A-shares and us-stock for US equities when needed.",
    )
    parser.add_argument(
        "--tushare-mode",
        default="http",
        choices=["http", "sdk"],
        help="A-share data path. Default uses lightweight HTTP mode; sdk uses the optional tushare Python package.",
    )
    parser.add_argument("--timeframe", default="1d", choices=["1h", "4h", "1d"], help="Analysis timeframe.")
    parser.add_argument("--format", default="markdown", choices=["markdown", "json"], help="Output format.")
    parser.add_argument("--output", help="Optional output file path.")
    parser.add_argument("--memory-file", help="Optional learning memory path.")
    return parser.parse_args()


def main():
    args = parse_args()
    apply_local_runtime_env()
    try:
        report = analyze(
            asset_query=args.asset,
            market=args.market,
            timeframe=args.timeframe,
            memory_file=Path(args.memory_file) if args.memory_file else None,
            tushare_mode=args.tushare_mode,
        )
    except Exception as error:
        raise SystemExit(f"Analysis failed: {error}") from error
    rendered = format_markdown(report) if args.format == "markdown" else json.dumps(report, indent=2, ensure_ascii=True) + "\n"
    if args.output:
        Path(args.output).write_text(rendered)
    sys.stdout.write(rendered)


if __name__ == "__main__":
    main()

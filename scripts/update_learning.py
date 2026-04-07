#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path

from quant_core import update_learning


def parse_args():
    parser = argparse.ArgumentParser(description="Store a labeled trade outcome so the skill can build workspace memory.")
    parser.add_argument("--analysis", required=True, help="Path to a JSON analysis report from analyze_asset.py.")
    parser.add_argument("--outcome", required=True, choices=["win", "loss", "invalidated"], help="Outcome label.")
    parser.add_argument("--realized-return", type=float, help="Realized return in percent.")
    parser.add_argument("--notes", default="", help="Optional notes about what happened.")
    parser.add_argument("--memory-file", help="Optional learning memory path.")
    return parser.parse_args()


def main():
    args = parse_args()
    analysis_path = Path(args.analysis)
    report = json.loads(analysis_path.read_text())
    memory = update_learning(
        report=report,
        outcome=args.outcome,
        realized_return=args.realized_return,
        notes=args.notes,
        memory_file=Path(args.memory_file) if args.memory_file else None,
    )
    print(json.dumps(memory, indent=2, ensure_ascii=True))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(
        description="Refresh market context, render the daily recap, and optionally deliver it."
    )
    parser.add_argument(
        "--builder-config",
        default="../assets/market_context_builder.example.json",
        help="Path to the market-context builder config JSON.",
    )
    parser.add_argument(
        "--recap-config",
        help="Path to the daily recap config JSON.",
    )
    parser.add_argument(
        "--market-context-output",
        default="../assets/market_context.daily.json",
        help="Where to write the refreshed market context JSON.",
    )
    parser.add_argument("--overlay-file", help="Optional overlay JSON with current macro or event notes.")
    parser.add_argument("--memory-file", help="Optional learning memory path.")
    parser.add_argument(
        "--cache-ttl-hours",
        type=int,
        default=72,
        help="Benchmark-report cache TTL for market context generation.",
    )
    parser.add_argument("--output", help="Optional path to save the rendered daily recap.")
    parser.add_argument(
        "--stdout-only",
        action="store_true",
        help="Print the recap locally without using the notifier in the recap config.",
    )
    return parser.parse_args()


def run_step(command: list[str]) -> None:
    subprocess.run(command, check=True)


def main():
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    builder_config = (script_dir / args.builder_config).resolve()
    local_recap_config = (script_dir / "../assets/daily_recap.openclaw.discord.local.json").resolve()
    default_recap_config = (script_dir / "../assets/daily_recap.openclaw.discord.json").resolve()
    recap_config = (script_dir / args.recap_config).resolve() if args.recap_config else (
        local_recap_config if local_recap_config.exists() else default_recap_config
    )
    market_context_output = (script_dir / args.market_context_output).resolve()
    effective_recap_config = recap_config
    if args.stdout_only:
        effective_recap_config = (script_dir / "../assets/daily_recap.example.json").resolve()
    command = [
        sys.executable,
        str(script_dir / "build_market_context.py"),
        "--config",
        str(builder_config),
        "--output",
        str(market_context_output),
        "--cache-ttl-hours",
        str(args.cache_ttl_hours),
    ]
    if args.overlay_file:
        command.extend(["--overlay-file", str((script_dir / args.overlay_file).resolve())])
    if args.memory_file:
        command.extend(["--memory-file", args.memory_file])
    run_step(command)

    recap_command = [
        sys.executable,
        str(script_dir / "generate_daily_recap.py"),
        "--config",
        str(effective_recap_config),
        "--market-context-file",
        str(market_context_output),
    ]
    if args.memory_file:
        recap_command.extend(["--memory-file", args.memory_file])
    if args.output:
        recap_command.extend(["--output", str((script_dir / args.output).resolve())])
    run_step(recap_command)


if __name__ == "__main__":
    main()

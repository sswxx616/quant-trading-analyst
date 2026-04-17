#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
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
        "--env-file",
        help="Optional local env file with runtime secrets such as TWELVEDATA_API_KEY.",
    )
    parser.add_argument(
        "--stdout-only",
        action="store_true",
        help="Print the recap locally without using the notifier in the recap config.",
    )
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


def run_step(command: list[str], env: dict[str, str]) -> None:
    subprocess.run(command, check=True, env=env)


def main():
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    runtime_env = resolve_runtime_env(script_dir, args.env_file)
    local_builder_config = (script_dir / "../assets/market_context_builder.local.json").resolve()
    builder_config = (
        (script_dir / args.builder_config).resolve()
        if args.builder_config != "../assets/market_context_builder.example.json"
        else (local_builder_config if local_builder_config.exists() else (script_dir / args.builder_config).resolve())
    )
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
    run_step(command, runtime_env)

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
    run_step(recap_command, runtime_env)


if __name__ == "__main__":
    main()

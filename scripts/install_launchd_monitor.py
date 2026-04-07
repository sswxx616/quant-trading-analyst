#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import plistlib
import subprocess
import sys
from pathlib import Path

from quant_core import ensure_state_dir


def parse_args():
    parser = argparse.ArgumentParser(
        description="Install or remove a macOS LaunchAgent for 24/7 quant monitor execution."
    )
    parser.add_argument("--config", help="Path to monitor config JSON.")
    parser.add_argument("--label", required=True, help="LaunchAgent label, for example ai.quant.trading.btc.")
    parser.add_argument("--load", action="store_true", help="Load the LaunchAgent after writing it.")
    parser.add_argument("--remove", action="store_true", help="Unload and remove the LaunchAgent.")
    parser.add_argument("--print-plist", action="store_true", help="Print the plist path after creation.")
    return parser.parse_args()


def plist_path(label: str) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{label}.plist"


def log_paths(label: str) -> tuple[Path, Path]:
    log_dir = ensure_state_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    safe = label.replace("/", "-")
    return log_dir / f"{safe}.out.log", log_dir / f"{safe}.err.log"


def build_plist(label: str, config_path: Path) -> dict:
    script_dir = Path(__file__).resolve().parent
    monitor_script = script_dir / "monitor_asset.py"
    stdout_log, stderr_log = log_paths(label)
    env_vars = {
        "PATH": os.environ.get("PATH", ""),
    }
    for key in ("TWELVEDATA_API_KEY", "TUSHARE_TOKEN", "QUANT_SKILL_HOME"):
        value = os.environ.get(key)
        if value:
            env_vars[key] = value
    return {
        "Label": label,
        "ProgramArguments": [
            sys.executable,
            str(monitor_script),
            "--config",
            str(config_path.resolve()),
        ],
        "WorkingDirectory": str(script_dir),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(stdout_log),
        "StandardErrorPath": str(stderr_log),
        "EnvironmentVariables": env_vars,
    }


def run_launchctl(*args: str) -> None:
    subprocess.run(["launchctl", *args], check=True)


def remove_job(label: str) -> None:
    path = plist_path(label)
    if path.exists():
        subprocess.run(
            ["launchctl", "unload", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        path.unlink()
        print(f"Removed {path}")
    else:
        print(f"No LaunchAgent found at {path}")


def install_job(label: str, config: str, load: bool, print_plist: bool) -> None:
    if not config:
        raise SystemExit("--config is required unless --remove is used.")
    config_path = Path(config)
    if not config_path.exists():
        raise SystemExit(f"Config file not found: {config_path}")

    launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
    launch_agents_dir.mkdir(parents=True, exist_ok=True)
    path = plist_path(label)
    payload = build_plist(label, config_path)
    with path.open("wb") as handle:
        plistlib.dump(payload, handle)

    print(f"Created {path}")
    if print_plist:
        print(path)

    if load:
        subprocess.run(["launchctl", "unload", str(path)], check=False)
        run_launchctl("load", str(path))
        print(f"Loaded {label}")


def main():
    args = parse_args()
    if args.remove:
        remove_job(args.label)
        return
    install_job(args.label, args.config, args.load, args.print_plist)


if __name__ == "__main__":
    main()

# Automation Guide

This repository includes a macOS LaunchAgent installer so monitoring can run in the background continuously.

## Why LaunchAgent

- Starts automatically after login
- Keeps the monitoring process alive
- Writes logs to a predictable location
- Does not require an always-open terminal window

## Installer Script

Use:

```bash
python3 scripts/install_launchd_monitor.py --config ../assets/monitor_config.openclaw.example.json --label ai.quant.trading.btc --load
```

The installer:

- Creates a `~/Library/LaunchAgents/<label>.plist`
- Configures the process to run `monitor_asset.py`
- Stores stdout and stderr under `~/.quant-trading-analyst/logs/`
- Optionally loads the job with `launchctl`

## OpenClaw Setup

Before using `type: openclaw` notifications:

1. Install and configure OpenClaw
2. Confirm at least one chat channel is available
3. Put the correct `channel` and `target` in the monitor config

Helpful command:

```bash
openclaw channels list --json
```

## Remove A Job

```bash
python3 scripts/install_launchd_monitor.py --label ai.quant.trading.btc --remove
```

# Monitoring

Monitoring is designed for users who want threshold-driven alerts instead of manual one-off checks.

## What Monitoring Can Trigger On

- composite score crossing above or below a threshold
- price crossing above or below a configured level
- recommendation label changes

## Run Once

```bash
cd scripts
python3 monitor_asset.py --config ../assets/monitor_config.example.json --once
```

## Run In The Background On macOS

```bash
cd scripts
python3 install_launchd_monitor.py \
  --config ../assets/monitor_config.openclaw.example.json \
  --label ai.quant.trading.sample \
  --load
```

Logs are written under `~/.quant-trading-analyst/logs/`.

## Delivery Options

- `stdout`
- `webhook`
- `openclaw`

Example OpenClaw notifier:

```json
{
  "notifier": {
    "type": "openclaw",
    "channel": "discord",
    "target": "channel:YOUR_CHANNEL_ID"
  }
}
```

## Privacy Recommendation

Keep live delivery targets in ignored local config files rather than tracked examples.

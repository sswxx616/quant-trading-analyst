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
python3 scan_crypto_movers.py --config ../assets/crypto_movers.example.json
python3 generate_crypto_trade_plan.py --config ../assets/crypto_trade_plan.example.json
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

## Crypto Leaderboard Tracking

Use `scan_crypto_movers.py` when you want to track fast-moving Binance spot symbols rather than a fixed watchlist.

It is designed for workflows like:

- show me the strongest 24h gainers that still have acceptable liquidity
- find the hottest coins where the quant engine still says watch or buy
- alert me when a new ORDI-like mover enters the filtered leaderboard

The starter config lives at [`assets/crypto_movers.example.json`](../assets/crypto_movers.example.json).

Recommended defaults:

- `quote = USDT`
- `timeframe = 4h`
- `min_quote_volume = 10000000`
- `min_price_change_pct = 5`
- `min_score = 20`
- `recommendation_allowlist = ["watch-for-buy-confirmation", "buy-or-add"]`
- `cooldown_hours = 12`

## Staged Trade Plans

Use `generate_crypto_trade_plan.py` when you want a plan-first workflow instead of an immediate trade alert.

This mode is useful for:

- generating channel-ready trade plans without automatic execution
- copying the useful parts of an agentic trading engine while keeping manual approval
- limiting the first entry size on fast-moving crypto setups

Recommended defaults:

- `starter_position_pct = 10`
- `max_position_pct = 25`
- `observe_band_pct = 3`
- `max_chase_above_confirmation_pct = 4`
- `avoid_parabolic_above_pct = 80`
- `notify_new_only = true` if you only want alerts when a symbol newly enters the qualified trade-plan set

## Altcoin Anomaly Radar

Use `generate_crypto_anomaly_plan.py` when you want earlier altcoin discovery than a 24h gainers list.

This mode layers several filters before a symbol becomes a channel-ready plan:

- short-term momentum across `15m` and `1h`
- relative volume spikes
- Binance futures open-interest expansion when available
- funding-rate sanity checks so overheated setups get downgraded
- the existing local quant engine as the final gate

Recommended defaults:

- `min_quote_volume = 8000000`
- `min_price_change_pct = 2.5`
- `max_price_change_pct = 45`
- `min_anomaly_score = 30`
- `analysis_timeframe = "1h"`
- `notify_new_only = true`

Every anomaly-radar run also appends a lightweight factor snapshot to a local JSONL log. Review it with:

```bash
cd scripts
python3 report_crypto_anomaly_factors.py
```

This report estimates forward `6h` and `24h` outcomes from later snapshots, then breaks results down by:

- anomaly-score band
- short-term relative volume band
- 1h momentum band
- open-interest direction
- funding crowding
- final plan action

Starter config:

- [`assets/crypto_trade_plan.example.json`](../assets/crypto_trade_plan.example.json)

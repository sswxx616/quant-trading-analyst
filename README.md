# Quant Trading Analyst

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![Markets](https://img.shields.io/badge/markets-US%20stocks%20%7C%20A--shares%20%7C%20crypto-0a7ea4.svg)](./README.md#data-routing)
[![Delivery](https://img.shields.io/badge/delivery-stdout%20%7C%20webhook%20%7C%20OpenClaw-2f855a.svg)](./README.md#openclaw-notifications)

Explainable stock and crypto market analysis, monitoring, and strategy-brief daily recap generation for Codex workflows.

[中文说明](./README.zh-CN.md)

## Overview

`quant-trading-analyst` is an executable skill and script toolkit for:

- analyzing US equities, A-shares, and crypto assets with a transparent rule-based strategy stack
- generating recurring daily recap reports in a strategy-brief format
- sending alerts through stdout, webhooks, or OpenClaw channels
- recording labeled outcomes and reviewing hit-rate trends over time

The project is optimized for operational use. It favors deterministic logic, explicit trade levels, fallback data providers, and readable output over opaque model predictions.

## Why This Repository

Many market-analysis assistants produce narrative output that is difficult to audit or automate. This repository takes a different approach:

- deterministic signal generation instead of hidden scoring logic
- explicit entry, exit, and risk levels instead of vague bullish or bearish wording
- market-aware recap output that separates US equities, A-shares, and crypto context
- operational tooling for alerts, daily recap delivery, and outcome tracking

## Highlights

- Explainable signal engine: SMA, EMA, RSI, MACD, Bollinger Bands, ATR, support, resistance, and volume expansion
- Multi-market routing:
  US equities via Twelve Data with HTTP/Yahoo fallback
  A-shares via Tushare with AkShare and BaoStock fallback
  Crypto via Binance
- Strategy-aware entry levels:
  separate observation buy zones from breakout confirmation levels
- Market-aware daily recap:
  strategy-brief output with separate US equity, A-share, and crypto overviews
- Macro/news overlay support:
  inject rate-path, geopolitical, liquidity, policy, and ETF-flow context into recap generation
- Operational resilience:
  cached recap fallback when live market access is temporarily unavailable
- Notification-ready:
  OpenClaw, webhook, and stdout delivery

## What It Produces

- One-off analysis reports for a ticker, stock name, or crypto asset
- Recurring monitoring jobs for price, score, and recommendation changes
- Daily strategy briefs for a watchlist
- Historical accuracy reports from labeled trade outcomes

## Example Use Cases

- Generate a daily watchlist brief for NVDA, LLY, BYD, SOL, and ETH
- Run a 24/7 monitoring job for first-buy, confirmation-buy, or sell-risk thresholds
- Push Discord alerts through OpenClaw when a monitored asset reaches a configured level
- Track whether prior signals resolved into wins, losses, or neutral outcomes

## Architecture

### Data Routing

| Market | Primary | Fallbacks |
| --- | --- | --- |
| US equities | Twelve Data SDK | Twelve Data HTTP, Yahoo Finance |
| A-shares | Tushare (`http` or `sdk`) | AkShare, BaoStock |
| Crypto | Binance | None |

### Core Scripts

| Script | Purpose |
| --- | --- |
| `scripts/analyze_asset.py` | one-off analysis |
| `scripts/build_market_context.py` | benchmark-based market context builder |
| `scripts/monitor_asset.py` | threshold-based monitoring |
| `scripts/generate_daily_recap.py` | strategy-brief daily recap |
| `scripts/report_accuracy.py` | hit-rate and outcome summary |
| `scripts/update_learning.py` | store labeled outcomes |
| `scripts/install_launchd_monitor.py` | macOS LaunchAgent installer |

## Quick Start

Install dependencies:

```bash
python3 -m pip install --user --break-system-packages -r requirements.txt
```

Set environment variables as needed:

```bash
export TWELVEDATA_API_KEY="your_twelve_data_key"
export TUSHARE_TOKEN="your_tushare_token"
```

Run a one-off analysis:

```bash
cd scripts
python3 analyze_asset.py --asset NVDA --market us-stock --timeframe 1d --format markdown
python3 analyze_asset.py --asset 002594 --market cn-stock --timeframe 1d --format markdown
python3 analyze_asset.py --asset ETH --market crypto --timeframe 4h --format markdown
```

## Example Output

The recap generator is designed for channel delivery rather than notebook-style dumps. A typical report contains:

- a watchlist summary with buy, watch, and sell counts
- market overview blocks for US equities, A-shares, and crypto
- per-asset strategy cards with observation-buy and confirmation-buy levels
- an exceptions section when live data falls back to cache

## Daily Recap

The recap generator produces a strategy-brief report with:

- watchlist-level counts for buy, watch, and sell buckets
- market-level overview sections for US equities, A-shares, and crypto
- per-asset strategy cards
- cached fallback behavior when live requests fail

Run the default recap:

```bash
cd scripts
python3 generate_daily_recap.py --config ../assets/daily_recap.example.json
```

Send the recap to Discord through OpenClaw:

```bash
cd scripts
python3 generate_daily_recap.py --config ../assets/daily_recap.openclaw.discord.json
```

The repository includes a market-context schema and recap examples:

- [`assets/daily_recap.example.json`](./assets/daily_recap.example.json)
- [`assets/daily_recap.openclaw.discord.json`](./assets/daily_recap.openclaw.discord.json)
- [`assets/market_context.example.json`](./assets/market_context.example.json)
- [`assets/market_context_builder.example.json`](./assets/market_context_builder.example.json)

Use `assets/market_context.example.json` as a template rather than a production data source. Replace the placeholder text with current market context before using it in a live channel workflow.

### Market Context Injection

The recap renderer supports optional market-wide context for macro and news overlays. This is useful for adding information such as:

- Fed rate path, inflation, employment, and Treasury yield pressure on US equities
- policy support, liquidity conditions, and northbound flows for A-shares
- dollar liquidity, ETF flows, regulation, or geopolitical shocks for crypto

Provide a context file in the recap config:

```json
{
  "market_context_file": "../assets/market_context.example.json"
}
```

The context file can define `message`, `technical`, `catalysts`, `risks`, and `latest` for:

- `us_stock`
- `cn_stock`
- `crypto`

When no context file is supplied, the recap falls back to market-specific technical summaries derived from the analyzed assets. For automation runs, a recommended pattern is to refresh a context file before recap generation so the market-overview section can include current macro and geopolitical developments.

### Build A Fresh Context File

Generate a market-context JSON from benchmark baskets:

```bash
cd scripts
python3 build_market_context.py \
  --config ../assets/market_context_builder.example.json \
  --output /tmp/market-context.json
```

Inject the generated context into recap rendering without editing the base recap config:

```bash
cd scripts
python3 generate_daily_recap.py \
  --config ../assets/daily_recap.openclaw.discord.json \
  --market-context-file /tmp/market-context.json
```

If you already have manual macro notes or event bullets, merge them on top of the derived context:

```bash
cd scripts
python3 build_market_context.py \
  --config ../assets/market_context_builder.example.json \
  --overlay-file ../assets/market_context.example.json \
  --output /tmp/market-context.json
```

## Monitoring

Run one monitoring cycle:

```bash
cd scripts
python3 monitor_asset.py --config ../assets/monitor_config.example.json --once
```

Install a 24/7 background job on macOS:

```bash
cd scripts
python3 install_launchd_monitor.py \
  --config ../assets/monitor_config.openclaw.example.json \
  --label ai.quant.trading.sample \
  --load
```

Logs are written under `~/.quant-trading-analyst/logs/`.

## OpenClaw Notifications

OpenClaw delivery works for both monitoring and recap generation.

Example notifier block:

```json
{
  "notifier": {
    "type": "openclaw",
    "channel": "discord",
    "target": "channel:YOUR_CHANNEL_ID"
  }
}
```

For personal delivery targets, create a local ignored config such as `assets/daily_recap.openclaw.discord.local.json` rather than committing live channel IDs.

Inspect locally configured channels:

```bash
openclaw channels list --json
```

## Accuracy Reports

Record a labeled outcome:

```bash
cd scripts
python3 update_learning.py \
  --analysis /tmp/nvda-analysis.json \
  --outcome win \
  --realized-return 6.8 \
  --notes "Breakout held after confirmation."
```

Generate a historical accuracy report:

```bash
cd scripts
python3 report_accuracy.py --format markdown
```

## Roadmap

- optional macro/news context builders for fully automated daily recap enrichment
- broader provider coverage for Hong Kong equities and macro calendars
- stronger basket-level monitoring and portfolio summaries
- richer evaluation metrics beyond hit rate and realized return

## Repository Layout

```text
quant-trading-analyst/
├── SKILL.md
├── README.md
├── README.zh-CN.md
├── agents/
├── assets/
├── references/
├── requirements.txt
└── scripts/
```

## Design Principles

- Transparent over opaque
- Operationally useful over academically elaborate
- Fallback-first for unstable market data
- Human-readable output for recap and alert consumption

## Current Limitations

- Macro and news context is optional rather than fully auto-ingested by default
- The rule engine is technical-first and does not replace discretionary research
- Open-source users should still validate data-provider terms and quotas for their own usage

## Contributing

Issues and pull requests are welcome, especially in these areas:

- market context enrichment and news integrations
- additional broker or data provider adapters
- improved backtesting and evaluation tooling
- better portfolio- or basket-level monitoring

## Using As A Codex Skill

This repository ships with a `SKILL.md` entry point and can be installed into a local Codex skills directory if you want the workflow to be discoverable inside Codex.

## Disclaimer

This project is for research support and workflow automation. It does not guarantee returns and should not be treated as personalized investment advice.

# Quant Trading Analyst

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](./LICENSE)
[![Status](https://img.shields.io/badge/status-actively%20maintained-2563eb.svg)](./CHANGELOG.md)
[![Markets](https://img.shields.io/badge/markets-US%20stocks%20%7C%20A--shares%20%7C%20crypto-0a7ea4.svg)](./README.md#data-routing)
[![Delivery](https://img.shields.io/badge/delivery-stdout%20%7C%20webhook%20%7C%20OpenClaw-2f855a.svg)](./README.md#openclaw-notifications)

Explainable stock and crypto market analysis, monitoring, and strategy-brief daily recap generation for CLI, automation, and agent-driven workflows.

[中文说明](./README.zh-CN.md)

- [Quick Start](#quick-start)
- [Daily Recap](#daily-recap)
- [Monitoring](#monitoring)
- [Use As A Skill](#use-as-a-skill)
- [Docs](./docs/README.md)
- [Contributing](./CONTRIBUTING.md)
- [Security](./SECURITY.md)
- [Changelog](./CHANGELOG.md)

## Overview

`quant-trading-analyst` is a script toolkit with optional agent-adapter files for:

- analyzing US equities, A-shares, and crypto assets with a transparent rule-based strategy stack
- generating recurring daily recap reports in a strategy-brief format
- sending alerts through stdout, webhooks, or OpenClaw channels
- recording labeled outcomes and reviewing hit-rate trends over time

The project is optimized for operational use. It favors deterministic logic, explicit trade levels, fallback data providers, and readable output over opaque model predictions.

## Project Status

`quant-trading-analyst` is an actively maintained open-source toolkit. The current focus is:

- strengthening reliability across unstable market-data providers
- improving market-context generation for recap workflows
- keeping public examples safe, reproducible, and privacy-aware

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

## Who This Is For

- traders or researchers who want transparent signal logic instead of black-box recommendations
- operators who want scheduled recap and alert workflows
- developers integrating market-analysis scripts into bots, agents, or automation systems
- open-source contributors improving data routing, recap generation, and delivery tooling

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
| `scripts/scan_cn_quality_stocks.py` | A-share quality selector with factor ranking plus quant follow-through |
| `scripts/build_market_context.py` | benchmark-based market context builder |
| `scripts/monitor_asset.py` | threshold-based monitoring |
| `scripts/scan_crypto_movers.py` | Binance top-gainer scanner with quant follow-through |
| `scripts/generate_crypto_trade_plan.py` | staged crypto trade-plan generator for channel delivery |
| `scripts/generate_crypto_anomaly_plan.py` | early altcoin anomaly radar with short-term momentum, volume, and futures sentiment |
| `scripts/report_crypto_anomaly_factors.py` | evaluate anomaly-factor snapshots over forward 6h/24h horizons |
| `scripts/generate_daily_recap.py` | strategy-brief daily recap |
| `scripts/report_accuracy.py` | hit-rate and outcome summary |
| `scripts/update_learning.py` | store labeled outcomes |
| `scripts/install_launchd_monitor.py` | macOS LaunchAgent installer |
| `scripts/run_daily_recap_workflow.py` | refresh market context, then render and deliver the daily recap |

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

For unattended recap automations, you can also store local-only runtime secrets in an ignored file:

```bash
cp assets/runtime.env.example .env.local
```

`scripts/run_daily_recap_workflow.py` will load `.env.local` or `assets/runtime.env.local` automatically before it spawns the market-context builder and recap renderer.

Run a one-off analysis:

```bash
cd scripts
python3 analyze_asset.py --asset NVDA --market us-stock --timeframe 1d --format markdown
python3 analyze_asset.py --asset 002594 --market cn-stock --timeframe 1d --format markdown
python3 analyze_asset.py --asset ETH --market crypto --timeframe 4h --format markdown
python3 scan_cn_quality_stocks.py --config ../assets/cn_stock_selector.example.json --stdout-only
python3 scan_crypto_movers.py --config ../assets/crypto_movers.example.json
python3 generate_crypto_trade_plan.py --config ../assets/crypto_trade_plan.example.json
python3 generate_crypto_anomaly_plan.py --config ../assets/crypto_anomaly_plan.example.json
python3 report_crypto_anomaly_factors.py
```

## A-Share Quality Selector

The repository now includes a stronger A-share selector that combines a `finhack` / `Qlib` / `zvt` style multi-factor ranking layer with an `ABu`-style timing and risk-discipline layer, then routes the short list through the local quant engine.

Run a one-off selector:

```bash
cd scripts
python3 scan_cn_quality_stocks.py --config ../assets/cn_stock_selector.example.json --stdout-only
```

This selector:

- starts from a broad A-share financial-report snapshot
- breaks candidates into growth, business-quality, valuation, and timing scores
- applies industry caps so the final list is not dominated by a single hot sector
- routes the short list through the local quant engine before final ranking
- outputs an actionable Top list with levels, posture, and one clear action per candidate

Run the full recap workflow:

```bash
cd scripts
python3 run_daily_recap_workflow.py --stdout-only
```

## Example Output

The recap generator is designed for channel delivery rather than notebook-style dumps. A typical report contains:

- a watchlist summary with buy, watch, and sell counts
- market overview blocks for US equities, A-shares, and crypto
- per-asset strategy cards with observation-buy and confirmation-buy levels
- an exceptions section when live data falls back to cache

Sample recap excerpt:

```text
2026-04-07 策略建议
共分析5个标的 | 🟢买入:0 🟡观望:4 🔴卖出:1

📊 分析结果摘要
⚪ 英伟达 (NVDA): 观望 | 评分 0 | 震荡｜建议第一观察买点：177.61；确认买点：189.26 |
⚪ 礼来 (LLY): 观望 | 评分 -8 | 震荡｜建议第一观察买点：877.11；确认买点：938.12 |
⚪ 比亚迪 (002594.SZ): 观望 | 评分 8 | 震荡｜建议第一观察买点：96.34；确认买点：102.55 |
🔴 SOL (SOLUSDT): 卖出 | 评分 -52 | 看空｜反弹修复观察位：80.65 |
⚪ ETH (ETHUSDT): 观望 | 评分 16 | 震荡｜建议第一观察买点：2021.5；确认买点：2091.08 |

🌍 市场总览
🇺🇸 美股整体
📰 消息面: 建议重点结合美联储利率路径、就业与通胀数据、长端美债收益率，以及地缘局势对风险偏好的影响一起解读。
📈 技术面: 美股整体偏震荡，当前更像结构分化而不是单边趋势。 当前基准篮子平均评分 0.0。
```

For a fuller walkthrough, see [docs/daily-recap.md](./docs/daily-recap.md).

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

## Crypto Movers

The repository can also track Binance spot-market gainers so you can catch fast-moving names such as `ORDI`, `SUI`, or other sudden breakout candidates before they hit your manual watchlist.

Run a one-off scan:

```bash
cd scripts
python3 scan_crypto_movers.py --config ../assets/crypto_movers.example.json
```

This scanner:

- pulls the Binance 24h leaderboard
- filters out stablecoin-like symbols and leveraged tokens
- applies minimum quote-volume and gain thresholds
- runs the built-in quant engine on the shortlisted movers
- optionally pushes alerts through stdout, webhook, or OpenClaw with cooldown control

Example use cases:

- track the top 30 USDT gainers and analyze the top 8 on a `4h` basis
- alert only when a hot coin is also scoring `20+` and reaches `watch-for-buy-confirmation` or `buy-or-add`
- run the script every 30-60 minutes in an external scheduler or automation

The repository includes a starter config:

- [`assets/crypto_movers.example.json`](./assets/crypto_movers.example.json)

If you want live delivery, replace the example notifier with your local OpenClaw or webhook target in an ignored local config file.

## Crypto Trade Plans

The repository also supports an OpenAlice-inspired workflow for crypto ideas: scan the market, generate staged trade plans, and push the plans to a channel without placing any orders.

Run it like this:

```bash
cd scripts
python3 generate_crypto_trade_plan.py --config ../assets/crypto_trade_plan.example.json
```

This planner is designed to take the useful parts of an agentic trading engine without introducing live execution risk:

- detects strong Binance spot movers
- re-checks them with the local quant engine
- outputs staged plans instead of direct orders
- enforces simple guardrails such as starter position limits, maximum total allocation, and chase filters
- delivers the plan through stdout, webhook, or OpenClaw
- can stay quiet unless a symbol newly enters the qualified trade-plan set

Each plan includes:

- whether the idea is starter-now, wait-breakout, wait-pullback, or watch-only
- an observation buy level and confirmation-buy level
- a first sell level
- defensive and hard-stop invalidation levels
- suggested starter and maximum position sizes
- a trade-framework block with setup phase, reward/stop ratio, validation quality, risk tier, and a simple time-stop

If you only want channel pushes for newly qualifying movers, set `"notify_new_only": true`. In that mode a symbol alerts only when it first enters the qualified plan set, then stays quiet until it drops out and qualifies again later.

Starter config:

- [`assets/crypto_trade_plan.example.json`](./assets/crypto_trade_plan.example.json)

## Crypto Altcoin Anomaly Radar

If you want earlier altcoin discovery than a simple 24h gainers list, use the anomaly radar. It borrows the useful parts of stronger open-source scanners: short-term momentum, relative volume, futures open-interest expansion, and funding-rate sanity checks, then still converts the result into staged plans instead of live orders.

Run it like this:

```bash
cd scripts
python3 generate_crypto_anomaly_plan.py --config ../assets/crypto_anomaly_plan.example.json
```

This radar is designed to catch “something just started moving” setups rather than only coins that are already at the top of the daily leaderboard.

- checks `15m` and `1h` momentum together
- measures short-term relative volume spikes
- uses Binance futures funding and open-interest changes when available
- only pushes newly qualifying symbols when `notify_new_only` is set to `true`
- still routes every candidate through the local quant engine before it becomes a plan

Starter config:

- [`assets/crypto_anomaly_plan.example.json`](./assets/crypto_anomaly_plan.example.json)

The anomaly radar also writes a lightweight factor log on every run. You can review which anomaly features have been working over recent forward horizons with:

```bash
cd scripts
python3 report_crypto_anomaly_factors.py
```

This gives you a small `finhack`-style validation loop without bringing in a heavy research stack: the radar records anomaly-score, short-term momentum, relative volume, funding, open-interest context, setup phase, reward/risk quality, and validation tier, then the report estimates forward 6h and 24h outcomes from later snapshots.

For personal delivery, keep the live notifier target in an ignored local file such as `assets/crypto_trade_plan.discord.local.json`.

## Monitoring

Run one monitoring cycle:

```bash
cd scripts
python3 monitor_asset.py --config ../assets/monitor_config.example.json --once
python3 scan_crypto_movers.py --config ../assets/crypto_movers.example.json
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

## Security And Privacy

- tracked example files use placeholders instead of live delivery targets
- local delivery settings should live in ignored files such as `*.local.json`
- secrets should be passed through environment variables, not committed to the repository
- if you discover an exposure issue, review [SECURITY.md](./SECURITY.md) before opening a public report

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

## Non-Goals

- providing broker execution or order routing
- replacing fundamental research, compliance review, or portfolio construction
- guaranteeing returns or acting as personalized investment advice

## Contributing

Issues and pull requests are welcome, especially in these areas:

- market context enrichment and news integrations
- additional broker or data provider adapters
- improved backtesting and evaluation tooling
- better portfolio- or basket-level monitoring

See [CONTRIBUTING.md](./CONTRIBUTING.md) for contribution guidelines and [CHANGELOG.md](./CHANGELOG.md) for release notes.

## Documentation

- [docs/README.md](./docs/README.md)
- [docs/daily-recap.md](./docs/daily-recap.md)
- [docs/data-sources.md](./docs/data-sources.md)
- [docs/monitoring.md](./docs/monitoring.md)
- [docs/privacy.md](./docs/privacy.md)
- [docs/skill-usage.md](./docs/skill-usage.md)

## Use As A Skill

This repository can be used as a reusable skill package, not just as a standalone script toolkit.

It already includes:

- `SKILL.md` for prompt-level skill instructions
- `agents/openai.yaml` for optional adapter metadata
- executable entry points under `scripts/`

Generic setup flow:

1. Clone the repository.
2. Install dependencies from `requirements.txt`.
3. Export the provider keys you need.
4. Register the repository or expose `SKILL.md` to your runtime.
5. Let the runtime invoke the scripts in `scripts/`.

If your runtime does not support `SKILL.md`, you can still treat this repository as a skill by calling the same CLI entry points directly from your automation layer.

See [docs/skill-usage.md](./docs/skill-usage.md) for the full setup pattern and example task prompts.

## Disclaimer

This project is for research support and workflow automation. It does not guarantee returns and should not be treated as personalized investment advice.

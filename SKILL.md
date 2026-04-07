---
name: quant-trading-analyst
description: Analyze stocks and crypto assets with explainable quantitative trading signals, entry and exit levels, risk controls, and ongoing monitoring. Use when an agent or operator needs to evaluate a stock ticker, stock name, crypto ticker, or crypto name; compare buy and sell timing; explain why a setup looks bullish, bearish, or neutral; build watchlists; run evidence-based monitoring; or send alerts through stdout, webhooks, or OpenClaw channels.
---

# Quant Trading Analyst

## Overview

Use this skill to turn a stock or crypto request into a structured quant workflow: resolve the asset, fetch market data, compute common technical signals, explain the trade thesis, suggest buy and sell levels, and optionally start continuous monitoring with alerts.

Keep the advice evidence-based and explicit. Always explain which signals drove the conclusion, what could invalidate it, and how strong the conviction is. Never present the output as guaranteed returns or personalized financial advice.

## Workflow

1. Resolve the asset.
2. Run the quant analysis script.
3. Translate the output into a concise buy, hold, reduce, or sell view.
4. Offer monitoring only when the user asks for ongoing watch or reminders.
5. Update the learning memory only after the user shares outcome data or explicitly asks to store feedback.

## Quick Start

Run a one-off analysis:

```bash
python3 scripts/analyze_asset.py --asset AAPL --market stock --format markdown
python3 scripts/analyze_asset.py --asset 600519 --market cn-stock --format markdown
python3 scripts/analyze_asset.py --asset 600519 --market cn-stock --tushare-mode sdk --format markdown
python3 scripts/analyze_asset.py --asset bitcoin --market crypto --timeframe 4h --format markdown
```

Generate a watchlist recap:

```bash
python3 scripts/generate_daily_recap.py --config assets/daily_recap.example.json
```

Build market-wide recap context first, then inject it into the recap run:

```bash
python3 scripts/build_market_context.py \
  --config assets/market_context_builder.example.json \
  --output /tmp/market-context.json

python3 scripts/generate_daily_recap.py \
  --config assets/daily_recap.example.json \
  --market-context-file /tmp/market-context.json
```

Review labeled hit rates:

```bash
python3 scripts/report_accuracy.py --format markdown
```

Save a machine-readable report:

```bash
python3 scripts/analyze_asset.py --asset TSLA --market stock --format json --output /tmp/tsla-analysis.json
```

Store post-trade feedback so the skill can build evidence from prior outcomes:

```bash
python3 scripts/update_learning.py \
  --analysis /tmp/tsla-analysis.json \
  --outcome win \
  --realized-return 6.8 \
  --notes "Breakout held above the trigger after earnings."
```

Run one monitoring cycle from a config file:

```bash
python3 scripts/monitor_asset.py --config assets/monitor_config.example.json --once
```

## Output Standard

Every response should include:

- Asset name, market, timeframe, and current price.
- Recommendation label plus confidence.
- Best buy level or confirmation trigger.
- Best sell level or risk-off trigger.
- Stop-loss or invalidation level.
- The 3-5 strongest reasons behind the suggestion.
- A short risk section covering volatility, weak confirmation, or missing data.
- If learning memory exists, a short note describing whether similar setups have historically worked well in this workspace.

## Strategy Mix

Use the built-in engine as the baseline. It blends the following methods:

- Trend following with SMA20, SMA50, SMA200, EMA12, and EMA26.
- Momentum analysis with RSI14 and MACD.
- Mean reversion with Bollinger Bands and oversold or overbought thresholds.
- Breakout and breakdown confirmation with support, resistance, and volume expansion.
- Risk sizing hints from ATR percent and volatility warnings.
- Simple walk-forward scoring to show whether recent bullish or bearish signals would have worked on the same asset.

Read [references/methods.md](references/methods.md) when you need the exact definitions or want to explain the methodology in more detail.

## Monitoring

Use `scripts/monitor_asset.py` when the user wants continuous watching, alerting, or a watchlist.

Monitoring rules can trigger on:

- Composite score crossing above or below a threshold.
- Price crossing above or below a user-defined level.
- Recommendation label changing.

Notifications support:

- `stdout` for local terminal output.
- `webhook` for generic HTTP integrations.
- `openclaw` for OpenClaw-installed channels such as Telegram, Slack, Discord, Feishu, WhatsApp, and others supported by the user's local OpenClaw setup.

Only set up recurring monitoring or automations when the user explicitly asks for it.

## Market Data Routing

- US stocks default to Twelve Data, with HTTP and Yahoo Finance fallback.
- A-shares route to Tushare Pro when the query looks like a mainland China ticker or name, such as `600519`, `000858`, `贵州茅台`, or `宁德时代`.
- A-shares support `http` mode by default and an optional `sdk` mode via `--tushare-mode sdk` when the official `tushare` Python package is installed.
- If Tushare is unavailable or permission-limited, the A-share flow falls back to `AkShare` and then `BaoStock`.
- Crypto continues to use Binance public market data.

For A-share analysis and monitoring, require `TUSHARE_TOKEN` to be configured. Prefer `--market cn-stock` when the input could be ambiguous.

## Learning Memory

This skill does not invent black-box theories. It learns only from explicit evidence:

- Prior analysis reports saved from `analyze_asset.py`.
- User-labeled outcomes recorded through `update_learning.py`.
- Realized return and notes supplied by the user.

The memory file stores which setup tags performed well or poorly in this workspace. Use that memory to enrich future explanations, not to override current market data.

## Guardrails

- Treat all outputs as research support, not guaranteed investing outcomes.
- Ask for risk tolerance, holding period, and market if the request is ambiguous and the answer would materially change the recommendation.
- State assumptions when resolving an asset name to a ticker.
- Prefer explainable signals over opaque confidence claims.
- If live market access fails, say so clearly and do not fabricate prices or levels.

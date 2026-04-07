# Daily Recap

`quant-trading-analyst` can produce a strategy-brief report for a watchlist instead of a raw notebook-style dump.

## What The Recap Includes

- watchlist summary with buy, watch, and sell counts
- market overview sections for US equities, A-shares, and crypto
- per-asset strategy cards with current price, score, and trade levels
- fallback notes when live data is unavailable and cache is used instead

## Core Commands

Generate a recap from the example config:

```bash
cd scripts
python3 generate_daily_recap.py --config ../assets/daily_recap.example.json
```

Generate a recap and send it through OpenClaw:

```bash
cd scripts
python3 generate_daily_recap.py --config ../assets/daily_recap.openclaw.discord.json
```

Run the full workflow that refreshes market context first:

```bash
cd scripts
python3 run_daily_recap_workflow.py --stdout-only
```

## Market Context Workflow

There are two ways to populate the market-overview section:

1. Derived context only
   The recap summarizes the benchmark basket technically from the analyzed assets.
2. Derived context plus macro overlay
   Build a market-context JSON and inject current macro or event notes on top.

Example:

```bash
cd scripts
python3 build_market_context.py \
  --config ../assets/market_context_builder.example.json \
  --output /tmp/market-context.json

python3 generate_daily_recap.py \
  --config ../assets/daily_recap.example.json \
  --market-context-file /tmp/market-context.json
```

## Sample Recap Excerpt

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

## Notes

- tracked example configs should use placeholders, not live delivery targets
- local delivery settings should live in ignored files such as `*.local.json`
- for reproducible automated runs, refresh the market-context file shortly before recap generation

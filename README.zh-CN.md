# Quant Trading Analyst 中文说明

可解释的股票与数字货币量化分析、监控和策略型每日复盘工具。

[Back to English README](./README.md)

- [快速开始](#快速开始)
- [每日复盘](#每日复盘)
- [监控与提醒](#监控与提醒)
- [作为 Skill 使用](#作为-skill-使用)
- [详细文档](./docs/README.md)
- [贡献指南](./CONTRIBUTING.md)
- [安全说明](./SECURITY.md)
- [更新记录](./CHANGELOG.md)

## 项目定位

`quant-trading-analyst` 是一个面向命令行、自动化和 agent 工作流的开源工具包，核心目标是：

- 分析美股、A 股和数字货币
- 输出可解释的交易结论和交易位，而不是只给方向判断
- 生成适合频道推送的每日策略复盘
- 支持监控、提醒、结果标注和命中率回顾

## 项目状态

项目当前处于持续维护中，重点方向包括：

- 提高多数据源下的稳定性和回退能力
- 增强 daily recap 的市场总览和上下文生成
- 保持公开示例可运行、可复用、且不泄露个人信息

## 为什么做这个项目

很多“智能荐股”工具会直接给结论，但很难解释：

- 为什么现在是买点
- 为什么更适合等确认，而不是直接追
- 风险来自技术面、宏观面，还是市场流动性

这个仓库的目标，是把这些信息拆开说清楚，并让结果能直接进入监控和推送流程。

## 主要能力

- 量化指标栈：SMA、EMA、RSI、MACD、布林带、ATR、支撑阻力、成交量
- 多市场数据路由：
  美股走 Twelve Data
  A 股优先走 Tushare，失败时自动回退到 AkShare、BaoStock
  数字货币走 Binance
- 每日复盘：
  输出“策略建议”风格的每日复盘，并按美股、A股、数字货币分别做市场总览
- 上下文注入：
  支持把利率路径、地缘风险、政策、ETF 资金流等信息注入复盘总览
- 上下文生成：
  支持先生成一份市场上下文 JSON，再注入到 daily recap
- 告警能力：
  支持 stdout、webhook、OpenClaw
- 历史评估：
  支持交易结果标注和命中率报告

## 适合谁用

- 想看清楚量化逻辑，而不是只要黑箱结论的人
- 需要把分析结果接进自动化、机器人或通知流程的人
- 需要每日复盘、定时提醒、监控任务的人
- 想给这个项目补数据源、回测或工作流能力的开发者

## 快速开始

安装依赖：

```bash
python3 -m pip install --user --break-system-packages -r requirements.txt
```

设置密钥：

```bash
export TWELVEDATA_API_KEY="你的 Twelve Data Key"
export TUSHARE_TOKEN="你的 Tushare Token"
```

如果是自动化跑 daily recap，建议把本地密钥放到忽略文件里：

```bash
cp assets/runtime.env.example .env.local
```

`scripts/run_daily_recap_workflow.py` 会在启动 market context 和 recap 子进程前，自动加载 `.env.local` 或 `assets/runtime.env.local`。

单次分析：

```bash
cd scripts
python3 analyze_asset.py --asset NVDA --market us-stock --timeframe 1d --format markdown
python3 analyze_asset.py --asset 002594 --market cn-stock --timeframe 1d --format markdown
python3 analyze_asset.py --asset ETH --market crypto --timeframe 4h --format markdown
python3 scan_crypto_movers.py --config ../assets/crypto_movers.example.json
python3 generate_crypto_trade_plan.py --config ../assets/crypto_trade_plan.example.json
python3 generate_crypto_anomaly_plan.py --config ../assets/crypto_anomaly_plan.example.json
python3 report_crypto_anomaly_factors.py
```

一条命令跑完整 daily recap 工作流：

```bash
cd scripts
python3 run_daily_recap_workflow.py --stdout-only
```

示例输出片段：

```text
2026-04-07 策略建议
共分析5个标的 | 🟢买入:0 🟡观望:4 🔴卖出:1

📊 分析结果摘要
⚪ 英伟达 (NVDA): 观望 | 评分 0 | 震荡｜建议第一观察买点：177.61；确认买点：189.26 |
⚪ 礼来 (LLY): 观望 | 评分 -8 | 震荡｜建议第一观察买点：877.11；确认买点：938.12 |
⚪ 比亚迪 (002594.SZ): 观望 | 评分 8 | 震荡｜建议第一观察买点：96.34；确认买点：102.55 |
🔴 SOL (SOLUSDT): 卖出 | 评分 -52 | 看空｜反弹修复观察位：80.65 |
⚪ ETH (ETHUSDT): 观望 | 评分 16 | 震荡｜建议第一观察买点：2021.5；确认买点：2091.08 |
```

## 每日复盘

默认复盘：

```bash
cd scripts
python3 generate_daily_recap.py --config ../assets/daily_recap.example.json
```

发到 Discord：

```bash
cd scripts
python3 generate_daily_recap.py --config ../assets/daily_recap.openclaw.discord.json
```

### 市场总览增强

复盘支持可选的市场级上下文，用来补充：

- 美股：加息/降息预期、非农、通胀、地缘局势
- A 股：政策、流动性、北向资金、产业催化
- 数字货币：美元流动性、ETF 资金流、监管、链上事件

在配置里加入：

```json
{
  "market_context_file": "../assets/market_context.example.json"
}
```

如果没有提供上下文文件，系统会自动按各市场的技术信号生成总览；如果你希望复盘里明确写出“中东局势”“加息/降息预期”“北向资金”“ETF 资金流”这类信息，建议在自动化运行前刷新这个上下文文件。

仓库里的 [`assets/market_context.example.json`](./assets/market_context.example.json) 是模板，不建议直接把其中的示例文字原样发到频道。

你也可以先生成一份新的市场上下文 JSON：

```bash
cd scripts
python3 build_market_context.py \
  --config ../assets/market_context_builder.example.json \
  --output /tmp/market-context.json
```

然后在生成 recap 时直接覆盖上下文文件：

```bash
cd scripts
python3 generate_daily_recap.py \
  --config ../assets/daily_recap.openclaw.discord.json \
  --market-context-file /tmp/market-context.json
```

## 监控与提醒

运行一次监控：

```bash
cd scripts
python3 monitor_asset.py --config ../assets/monitor_config.example.json --once
```

macOS 后台任务：

```bash
cd scripts
python3 install_launchd_monitor.py \
  --config ../assets/monitor_config.openclaw.example.json \
  --label ai.quant.trading.sample \
  --load
```

### 数字货币涨幅榜追踪

如果你想让策略自动盯 Binance 数字货币涨幅榜，并抓出最近疯涨、但量化上还值得继续看的币种，可以直接用：

```bash
cd scripts
python3 scan_crypto_movers.py --config ../assets/crypto_movers.example.json
```

这个扫描器会做四步：

- 抓 Binance `24h` 涨幅榜
- 过滤稳定币类符号和杠杆代币
- 按最小成交额、最小涨幅筛掉噪音币
- 对筛出来的前几名再跑现有量化引擎，输出更像“涨幅榜里哪些还值得看”

默认示例适合拿来追踪像 `ORDI` 这种突然爆发的币种，但不会只看涨幅，还会一起看：

- 当前评分
- 是继续追踪、等确认，还是已经不适合追
- 观察买点、确认位、第一卖点

示例配置在这里：

- [`assets/crypto_movers.example.json`](./assets/crypto_movers.example.json)

如果你要发到 Discord、Telegram 或别的渠道，建议复制成你自己的本地忽略文件，再把 `notifier` 改成 OpenClaw 或 webhook 版本。

### 数字货币交易计划

如果你不想直接自动下单，而是希望系统像 OpenAlice 那样先生成一份“计划单”，再发到频道里给你确认，可以直接用：

```bash
cd scripts
python3 generate_crypto_trade_plan.py --config ../assets/crypto_trade_plan.example.json
```

这套计划单能力会：

- 先扫 Binance 现货涨幅榜
- 用你现有的量化引擎复核这些强势币
- 不直接给执行指令，而是生成 staged trade plan
- 只把计划推到频道，不自动下单
- 可以只在“新强势币第一次进入合格计划集合”时才推送

每份计划里会包含：

- 当前适合试探仓、等突破、等回踩，还是只观察
- 观察买点和确认位
- 第一卖点
- 防守线和止损失效位

如果你只想在发现“新强势币且符合计划条件”时推送，把配置里的 `"notify_new_only"` 设成 `true`。这样同一个币只会在首次进入合格计划集合时提醒，后面只要它还一直待在集合里，就不会重复刷屏；等它掉出去、以后又重新进入时，才会再提醒。

### 山寨币异动雷达

如果你想比单纯的 `24h` 涨幅榜更早抓到异动山寨币，可以直接用这层“异动雷达”：

```bash
cd scripts
python3 generate_crypto_anomaly_plan.py --config ../assets/crypto_anomaly_plan.example.json
```

这层能力借鉴了更强的开源扫描器思路，但仍然保持你的项目风格：

- 同时看 `15m` 和 `1h` 动量
- 看短周期相对成交量是否突然放大
- 能取到的话，再叠加 Binance 合约的 `funding` 和 `open interest`
- 最后仍然要通过你本地量化引擎过滤，才会生成计划单
- 配上 `"notify_new_only": true` 后，只会在“新异动币第一次进入合格集合”时推送

示例配置：

- [`assets/crypto_anomaly_plan.example.json`](./assets/crypto_anomaly_plan.example.json)

这层雷达每次运行时，还会自动记录一份轻量级“因子快照”。你可以像 `finhack` 一样，回头看哪些异动特征更靠谱：

```bash
cd scripts
python3 report_crypto_anomaly_factors.py
```

这份报告会基于后续快照，估算合格信号在未来 `6h / 24h` 的平均收益和胜率，并按这些维度拆开看：

- 异动分数区间
- 15 分钟量比
- 1 小时动量
- OI 是否同步增长
- 资金费率是否过热
- 最终生成的计划动作类型
- 初始仓位建议和最大仓位上限

示例配置在这里：

- [`assets/crypto_trade_plan.example.json`](./assets/crypto_trade_plan.example.json)

如果你要直接发到自己的 Discord 频道，可以像现在其他本地配置一样，复制成 `.local.json` 文件再改通知目标。

## 命中率报告

记录结果：

```bash
cd scripts
python3 update_learning.py \
  --analysis /tmp/sample-analysis.json \
  --outcome win \
  --realized-return 6.8 \
  --notes "突破确认后延续上涨。"
```

查看命中率报告：

```bash
cd scripts
python3 report_accuracy.py --format markdown
```

## 说明

- 这是研究和自动化辅助工具，不是收益保证
- 默认策略是技术分析优先，不替代人工研究
- 不依赖某一个特定助手产品，直接运行脚本即可使用
- 仓库内置 `SKILL.md` 和 `agents/openai.yaml` 等适配文件，但它们只是可选接入层，不是项目本体

## 安全与隐私

- 仓库里的示例配置使用占位符，不提交真实通知目标
- 个人通知配置建议放在 `*.local.json` 这类被忽略的文件里
- token 和密钥应通过环境变量传入，而不是写进仓库
- 如果发现泄漏或隐私问题，建议先看 [SECURITY.md](./SECURITY.md)

## 详细文档

- [docs/README.md](./docs/README.md)
- [docs/daily-recap.md](./docs/daily-recap.md)
- [docs/data-sources.md](./docs/data-sources.md)
- [docs/monitoring.md](./docs/monitoring.md)
- [docs/privacy.md](./docs/privacy.md)
- [docs/skill-usage.md](./docs/skill-usage.md)

## 作为 Skill 使用

这个仓库不仅可以直接当脚本工具跑，也可以作为一个可复用的 Skill 包接入到支持仓库技能或提示词适配的 agent/runtime 里。

仓库里已经包含：

- `SKILL.md`
- `agents/openai.yaml`
- `scripts/` 下的实际执行入口

通用接入方式：

1. 克隆仓库
2. 安装依赖
3. 配置所需环境变量
4. 把仓库或 `SKILL.md` 暴露给你的 runtime
5. 让 runtime 能调用 `scripts/` 下的脚本

如果你的 runtime 不支持 `SKILL.md`，也没关系，直接把这些脚本当成 skill 的执行入口来调用就可以。

更完整的说明见 [docs/skill-usage.md](./docs/skill-usage.md)。

# Quant Trading Analyst 中文说明

可解释的股票与数字货币量化分析、监控和策略型每日复盘工具。

[Back to English README](./README.md)

- [快速开始](#快速开始)
- [每日复盘](#每日复盘)
- [监控与提醒](#监控与提醒)
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

单次分析：

```bash
cd scripts
python3 analyze_asset.py --asset NVDA --market us-stock --timeframe 1d --format markdown
python3 analyze_asset.py --asset 002594 --market cn-stock --timeframe 1d --format markdown
python3 analyze_asset.py --asset ETH --market crypto --timeframe 4h --format markdown
```

一条命令跑完整 daily recap 工作流：

```bash
cd scripts
python3 run_daily_recap_workflow.py --stdout-only
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

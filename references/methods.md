# Quant Methods

This skill uses a compact, explainable signal stack rather than a black-box model.

## Core Inputs

- Price candles: open, high, low, close, volume.
- Market type: stock via Twelve Data time series with Yahoo chart fallback, crypto via Binance klines.
- Timeframe: `1h`, `4h`, or `1d`, with stocks currently supporting `1h` and `1d`.

## Indicators

- `SMA20`, `SMA50`, `SMA200`: trend structure and pullback zones.
- `EMA12`, `EMA26`: momentum and MACD components.
- `RSI14`: oversold, neutral, and overbought states.
- `MACD histogram`: directional momentum and acceleration.
- `Bollinger Bands (20, 2)`: stretch and mean-reversion framing.
- `ATR14`: volatility and stop placement context.
- `Volume ratio`: current volume divided by 20-bar average volume.
- `Support / resistance`: rolling 20-bar low and high levels.

## Composite Logic

The skill combines trend, momentum, mean reversion, breakout, and volatility filters into one score from `-100` to `100`.

- Positive scores favor long exposure or buy confirmation.
- Negative scores favor risk reduction, selling, or avoiding fresh long exposure.
- The skill does not assume every market can be shorted. Bearish scores mainly mean risk-off unless the user explicitly wants short ideas.

## Buy / Sell Level Construction

- Bullish setups use pullback levels near support or moving averages, or breakout triggers just above resistance.
- Bearish setups use current price, support failures, and reclaim levels to define defensive exits and invalidation points.
- Stop-loss levels combine support and ATR to avoid overly tight placement.

## Walk-Forward Check

The script also runs a simple walk-forward sanity check:

- If the composite score was strongly bullish in the recent past, how often did the asset rise after a short horizon?
- If the composite score was strongly bearish, how often did the asset fall after a short horizon?

This is not a full institutional backtest. It is a quick evidence layer that helps the user judge whether the current signal regime has been working lately.

## Learning Memory

Learning is outcome-driven:

- Save an analysis report from `analyze_asset.py`.
- Record an outcome with `update_learning.py`.
- The memory file aggregates win, loss, and invalidated counts by setup tag such as `trend-following`, `mean-reversion`, `breakout`, and `risk-off`.

Future analyses read that memory and summarize whether similar tagged setups have worked well in the same workspace.

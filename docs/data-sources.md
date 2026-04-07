# Data Sources

This project is built around fallback-first routing rather than a single provider dependency.

## Routing Matrix

| Market | Primary | Fallbacks |
| --- | --- | --- |
| US equities | Twelve Data SDK | Twelve Data HTTP, Yahoo Finance |
| A-shares | Tushare (`http` or `sdk`) | AkShare, BaoStock |
| Crypto | Binance | None |

## Why This Matters

- market-data APIs rate-limit, change quota rules, or fail intermittently
- not every open-source user has the same provider credentials
- recap and monitoring jobs are more useful when they degrade gracefully instead of failing hard

## Provider Notes

### US Equities

- best experience comes from `TWELVEDATA_API_KEY`
- if Twelve Data is unavailable, the project falls back to HTTP and then Yahoo Finance
- cached recap behavior reduces impact when the live request path is temporarily unavailable

### A-Shares

- `TUSHARE_TOKEN` is recommended when available
- `http` mode is lighter for deployment
- `sdk` mode is useful when you prefer the official Python package
- if Tushare is unavailable or permission-limited, the project falls back to AkShare and then BaoStock

### Crypto

- Binance public market data is used for price candles
- current focus is on liquid spot-style benchmark pairs such as `BTCUSDT`, `ETHUSDT`, and `SOLUSDT`

## Operational Advice

- expect live market requests to fail sometimes
- keep automation workflows tolerant of cache fallback
- treat provider quotas and terms as your own operational responsibility

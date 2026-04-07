# Contributing

Thanks for your interest in improving `quant-trading-analyst`.

## What To Contribute

- data-provider adapters and fallback improvements
- better recap and monitoring workflows
- evaluation and backtesting enhancements
- clearer docs, examples, and configuration templates
- bug fixes around reliability, parsing, and alert delivery

## Development Guidelines

1. Keep the project explainable.
   Changes should preserve transparent signals, readable outputs, and explicit risk levels.
2. Prefer operationally useful improvements.
   Reliability, fallback behavior, and clear output are usually more valuable than adding opaque complexity.
3. Avoid committing private credentials or live delivery targets.
   Use placeholders in tracked example files and keep personal configs in ignored local files.
4. Keep examples runnable.
   If a command is documented in the README, it should still work after your change.

## Before Opening A PR

Please run relevant checks locally when possible:

```bash
python3 -m py_compile scripts/*.py
python3 -m json.tool assets/daily_recap.example.json >/dev/null
python3 -m json.tool assets/market_context_builder.example.json >/dev/null
```

If your change touches recap or monitoring flows, include:

- what changed
- how to run it
- any new environment variables, files, or provider assumptions

## Security And Privacy

- Do not commit API keys, tokens, channel IDs, webhook URLs, or personal paths.
- Keep live delivery targets in ignored local config files such as `*.local.json`.
- If you discover a privacy or secret-leak issue, open a private report when possible instead of posting the secret in a public issue.

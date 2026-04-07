# Skill Usage

This repository can be used in two ways:

1. as a standalone CLI toolkit
2. as a reusable skill package inside an agent runtime that supports repository-backed skills or prompt adapters

## What Makes It A Skill

The repository includes:

- `SKILL.md` for prompt-level skill instructions
- `agents/openai.yaml` as optional adapter metadata
- executable scripts under `scripts/` for the actual analysis, recap, and monitoring workflows

In practice, the skill layer is just a thin wrapper around the same CLI entry points.

## Generic Setup Flow

1. Clone the repository.
2. Install dependencies.
3. Export the data-provider credentials you plan to use.
4. Register or expose the repository to your agent runtime.
5. Ensure the runtime can execute the scripts in `scripts/`.

Example:

```bash
git clone https://github.com/sswxx616/quant-trading-analyst.git
cd quant-trading-analyst
python3 -m pip install --user --break-system-packages -r requirements.txt

export TWELVEDATA_API_KEY="your_twelve_data_key"
export TUSHARE_TOKEN="your_tushare_token"
```

## If Your Runtime Supports `SKILL.md`

Point the runtime at this repository and expose:

- `SKILL.md`
- the `scripts/` directory
- the `assets/` directory for example configs

Typical usage then looks like:

- ask for a stock or crypto analysis
- ask for a daily recap
- ask to start or test monitoring

## If Your Runtime Does Not Support `SKILL.md`

You can still use this repository as a de facto skill by invoking the scripts directly from your automation layer.

Common entry points:

```bash
python3 scripts/analyze_asset.py --asset NVDA --market us-stock --timeframe 1d --format markdown
python3 scripts/generate_daily_recap.py --config assets/daily_recap.example.json
python3 scripts/run_daily_recap_workflow.py --stdout-only
python3 scripts/monitor_asset.py --config assets/monitor_config.example.json --once
```

## Example Agent Tasks

- "Analyze NVDA and explain the buy and confirmation levels."
- "Generate a daily recap for my watchlist."
- "Refresh market context first, then send the recap."
- "Monitor BTC and alert me if the score turns risk-off."

## Runtime-Agnostic Advice

- keep personal delivery targets in ignored local config files
- pass keys through environment variables
- treat `SKILL.md` and `agents/openai.yaml` as optional integration metadata, not as the core implementation
- if your runtime needs a single command, prefer `scripts/run_daily_recap_workflow.py` for recap automation

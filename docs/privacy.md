# Privacy And Secrets

This repository is designed to keep public examples reusable without exposing personal operational data.

## Do Not Commit

- API keys and tokens
- webhook URLs
- personal or private channel IDs
- account-specific watchlists if they reveal private strategy information
- local machine paths that expose identity or workstation details

## Recommended Pattern

- keep tracked example files generic
- pass secrets through environment variables
- use ignored local files such as `*.local.json` for personal notification targets
- rotate any secret immediately if it was ever committed or sent publicly

## Relevant Files

- [SECURITY.md](../SECURITY.md)
- [CONTRIBUTING.md](../CONTRIBUTING.md)
- [README.md](../README.md)

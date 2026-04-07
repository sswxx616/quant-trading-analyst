# Security Policy

## Supported Versions

Security and privacy fixes are applied to the latest version on `main`.

## Reporting A Vulnerability

If you find a credential leak, privacy issue, unsafe default, or delivery-target exposure:

1. Do not publish the secret or sensitive value in a public issue.
2. Share only the minimum context needed to reproduce the problem safely.
3. Rotate any exposed credential immediately if it was ever committed or transmitted.

Examples of sensitive material that should never be posted publicly:

- API keys and tokens
- webhook URLs
- chat or channel IDs tied to personal accounts
- local machine paths that reveal personal identity
- private watchlists or account-specific delivery targets

## Operational Guidance

- Keep personal delivery targets in ignored local files such as `*.local.json`.
- Use placeholders in tracked example files.
- Treat generated recap content as market research support, not trading guarantees.

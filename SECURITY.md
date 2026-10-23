# Security Policy

## Reporting a vulnerability

Please open a private security advisory on GitHub (Security → Advisories → Report a vulnerability). Do not open public issues for security problems.

## Practices in this repository

- Secrets live only in local `.env` files (git-ignored) or in the hosting provider's secret store. Every service ships a `.env.example` with placeholders.
- A versioned pre-commit hook (`.githooks/pre-commit`) blocks env files, keys, model weights, oversized files and anything gitleaks flags.
- CI runs gitleaks, CodeQL and dependency review; GitHub secret scanning with push protection is enabled.
- The public chat API is rate limited per client, bounded in input and output size, and never forwards client-supplied tool results to the model.
- Model outputs are rendered as sanitized Markdown; raw HTML from the model is never trusted.
- The inference worker authenticates to the gateway with a bearer token over TLS and only dials out; no inbound ports are opened on the owner's machine.

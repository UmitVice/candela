# 0006 — Local quality gates instead of hosted CI

- Status: accepted
- Date: 2026-10-23

## Context

The owner does not want GitHub Actions or other hosted CI minutes consumed, and Netlify production deploys draw from a limited credit budget.

## Decision

- Every area exposes `make <area>-check` (format, lint, type-check, build). Agents run it before each push.
- A versioned pre-commit hook (`.githooks/pre-commit`) blocks secrets (gitleaks), env files, keys, model weights, databases and files over 5 MiB.
- GitHub-native security features that need no Actions minutes stay on: secret scanning with push protection and Dependabot alerts.
- Deploys are manual, from locally built artifacts, at named milestones only: Netlify receives a prebuilt `dist` via the CLI (no Netlify builds); the Hugging Face Space is rebuilt only when the gateway image changes.

## Consequences

- No CI badge; the README documents how to run the gates locally.
- Discipline lives in the agent handbook (`CLAUDE.md`) and the hook rather than in a pipeline.

## Alternatives considered

- GitHub Actions on a public repository (free minutes): rejected by the owner.

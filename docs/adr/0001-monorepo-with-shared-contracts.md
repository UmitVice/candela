# 0001 — Monorepo with shared contracts

- Status: accepted
- Date: 2026-10-23

## Context

Candela spans four runtimes (Angular, Go, two Python projects) that are built in parallel by independent agent sessions. They meet at a handful of interfaces: the public HTTP/SSE API, the worker WebSocket protocol, the LLM tool schemas and result shapes, and the Observatory artifacts.

## Decision

One repository with one directory per deployable (`apps/web`, `services/gateway`, `services/worker`, `ml`) and a top-level `contracts/` directory that is the single source of truth for every cross-component interface. Components copy or embed contract files at build time; a drift check is part of each area's `make <area>-check`. Tool execution has exactly one implementation (the gateway); training data is generated through the gateway's loopback-only internal tool API so the model sees identical tool outputs in training and production.

## Consequences

- Parallel work needs only the contracts, not each other's code.
- Contract changes are deliberate, reviewed in one place and land with the code that implements them.
- Each runtime keeps its native tooling (pnpm, Go modules, uv) without a polyglot build system.

## Alternatives considered

- Polyrepo: cleaner ownership but contract changes become multi-repo releases. Rejected for a single-owner portfolio project.
- Code generation from OpenAPI/JSON Schema for every language: worthwhile later; today the surface is small and hand-written types stay readable.

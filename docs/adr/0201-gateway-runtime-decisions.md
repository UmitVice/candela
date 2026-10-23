# 0201 — Gateway runtime decisions

- Status: accepted
- Date: 2026-10-23

## Context

Implementing `p1-gateway` raised choices the contracts leave open.

## Decision

- **Route on retry.** When a worker fails before its first token, the gateway retries once on the fallback and emits a second `meta` event (same `messageId`) carrying the fallback model and `route: "fallback"`. Clients must treat a later `meta` as an update of the model label.
- **Fallback is a dev/cloud adapter.** There is no lite product model; the OpenAI-compatible fallback is on by default in development and off in production unless `CANDELA_FALLBACK_ENABLED=true`. Its `ModelInfo` keeps the contract's `tier: "lite"`.
- **llama.cpp schemas.** Tool schemas sent to OpenAI-compatible upstreams drop `pattern`, because llama.cpp's schema-to-grammar converter rejects the symbol regex; the gateway still validates arguments against the full `tools.json`. Workers receive `tools.json` unchanged.
- **System prompt.** `{{today}}` renders as the UTC date `YYYY-MM-DD`, and the file is trimmed of surrounding whitespace. `GET /internal/v1/system-prompt?date=` returns the exact text for training data.
- **Tool rounds.** Up to 6 rounds; a 7th request for tools ends with `finishReason: "tool_limit"`. Tool calls of a round run concurrently (8 s each); results are emitted in call order.
- **Caps.** Client history is trimmed oldest-first to `CANDELA_MAX_INPUT_CHARS` (24 000) before generation; rounds stop once the whole prompt exceeds `CANDELA_MAX_CONTEXT_CHARS` (64 000); completion tokens across all rounds are capped by `CANDELA_MAX_OUTPUT_TOKENS` (2 048). `CANDELA_MEMORY_LIMIT` (512 MiB) sets the Go soft memory limit unless `GOMEMLIMIT` is set.
- **Egress.** Market-data fetches use an HTTPS-only client limited to `CANDELA_EGRESS_ALLOW` whose dialer refuses non-public addresses after DNS resolution (ADR 0008). The fallback upstream is operator configuration (usually loopback) and uses its own client.
- **Errors and privacy.** Upstream and worker error texts are logged, never forwarded; clients get fixed messages per error code. `/status` shows opaque worker ids (`w-<session>`), not the worker-supplied id, which is often a hostname. Access logs store client IPs as HMACs with an in-memory salt that rotates every UTC day.
- **HTTP status for uncovered symbols.** Market endpoints answer `404 not_found` both for unknown symbols and for listed symbols outside the snapshot (message says which); tool model views distinguish `not_found` from `data_unavailable`.
- **Model views** are encoded by a dedicated ordered writer with shortest round-trip number formatting (`186` rather than `186.0`); training data must copy them verbatim from the internal tool API.

## Consequences

- The PWA and the worker (p2) must accept a repeated `meta`, and training data generation must call the internal API instead of re-encoding views.

## Alternatives considered

- Delaying `meta` until a slot is acquired would violate "meta always first".
- Rejecting over-long histories outright: trimming keeps long conversations usable.

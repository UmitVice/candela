# 0008 — Public exposure threat model and hardening

- Status: accepted
- Date: 2026-10-23

## Context

The live site sends chat requests from anonymous visitors to the owner's personal MacBook (ADR 0002). The owner's requirement: visitors can talk to the model and nothing else — no access to files, credentials, other local services, the LAN, or the ability to degrade the machine.

Assets: the owner's files and credentials (`gh`, `hf`, Netlify tokens, SSH keys, Keychain, browser profiles), other local services (PostgreSQL on 5432, the owner's `llama-server` on 8080, dev servers), devices on the LAN, and the machine's availability.

## Decision

Defense in depth, each layer sufficient on its own for the most likely attacks:

1. **Single, narrow ingress.** `cloudflared` opens only outbound connections and forwards to `127.0.0.1:8710` (gateway public listener). No router ports, no LAN binding: every Candela listener binds to loopback. Internal routes (tool execution, metrics, worker connect) live on a separate loopback listener that the tunnel never targets.
2. **No dangerous capabilities exist.** The gateway serves no files, executes no processes, takes no file paths or URLs from clients, deserializes only size-limited JSON, and the client can never supply system prompts or tool results. LLM tools are read-only market-data lookups with strict JSON-schema validation (symbols match `^[A-Z][A-Z0-9.\-]{0,9}$`); prompt injection can at worst produce a wrong answer.
3. **Egress allowlist.** The gateway's HTTP client resolves and dials only allowlisted hosts (market-data providers) and refuses loopback, private, link-local and unique-local addresses after DNS resolution, so even a bug cannot reach PostgreSQL, the owner's `llama-server`, the router or other LAN devices (SSRF).
4. **OS sandbox.** Gateway, worker and `cloudflared` run under macOS Seatbelt profiles (`sandbox-exec`) that deny reading the home directory except the exact paths each needs (binary, snapshot and data directories, model directory and Python environment read-only for the worker), deny writes outside their data/log directories, deny process execution for gateway and worker, and restrict network binding/connecting to the ports above. If Seatbelt is unavailable on this macOS version, the fallback is a dedicated unprivileged macOS user created by the owner (documented, never done automatically).
5. **Resource protection.** Per-client rate limits (client IP from `CF-Connecting-IP`, which Cloudflare overwrites at the edge), a global generation semaphore and bounded queue, request/frame/message size limits, prompt-token and output-token caps (bounded KV-cache memory), deadlines on every call, `GOMEMLIMIT` for the gateway, memory-based admission control and idle unload in the worker, and an automatic kill switch in the supervisor that closes the tunnel and publishes `offline` for 15 minutes when abuse thresholds are exceeded.
6. **No information leaks.** Generic error bodies (no stack traces, paths, hostnames or usernames); `/status` reveals only model metadata and a generic device label ("Apple M5 Pro · 24 GB"); logs contain no message content or secrets and store client IPs as salted daily hashes.
7. **Supply chain.** Pinned lockfiles; `govulncheck` in `gateway-check`, `pip-audit` in Python checks; model weights as safetensors only, never pickles; `trust_remote_code` always false; datasets pinned to Hugging Face commit revisions with checksums.
8. **Client-side integrity.** The PWA accepts a gateway URL from the discovery Gist only if it matches `^https://[a-z0-9-]+\.trycloudflare\.com$` (or a configured stable host), so a tampered Gist cannot redirect visitors elsewhere; strict CSP and sanitized Markdown protect visitors.

## Verification (part of `p3-deploy`)

Adversarial checks through the tunnel and locally: path traversal and URL injection in every parameter, oversized bodies and WebSocket frames, forged `X-Forwarded-For`/`CF-Connecting-IP`, disallowed origins, WebSocket origin bypass, SSRF attempts via symbols and tool arguments, `/internal/*` and `/metrics` on the public listener, prompt-injection attempts to invoke non-existent tools, a burst test for rate limits and the kill switch, and `lsof` proof that nothing listens on non-loopback interfaces. A security review of the gateway and worker code is run before the first public exposure.

## Consequences

- The blast radius of a full gateway compromise is limited to its sandbox: read-only market data and its own SQLite file.
- Some convenience is lost (no remote admin endpoints); operations happen locally through `make` targets.

## Alternatives considered

- Exposing the worker or `llama-server` directly: far larger attack surface.
- Running everything in Docker: Docker is not installed and would cost several GB of RAM on a shared laptop; Seatbelt provides comparable file-system isolation for these processes.

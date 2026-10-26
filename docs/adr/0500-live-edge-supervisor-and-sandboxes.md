# 0500 — Live edge supervisor and Seatbelt sandboxes

- Status: accepted
- Date: 2026-10-26

## Context

ADR 0002 puts the gateway and the GPU worker on the owner's Mac behind a Cloudflare quick tunnel, published through a Gist. ADR 0008 requires OS sandboxes, an internal listener that is never tunnelled, and a kill switch before anything goes public. Facts measured on macOS 27.0.1 with cloudflared 2026.10.3:

- `sandbox-exec` with `(deny default)` and `(import "system.sb")` works. Profiles take `-D KEY=value` parameters, and the last matching rule wins.
- With QUIC, cloudflared binds UDP on all interfaces. With `--protocol http2` it only dials out: TCP to :7844 and :443.
- Cloudflare's edge rejects requests that carry a client-supplied `CF-Connecting-IP` (403, error 1000).
- macOS negative-caches a brand-new trycloudflare hostname. Probing it through the system resolver delayed "online" by about 75 s.
- MLX JIT kernels are compiled by `MTLCompilerService`. It writes `…/C/org.python.python/com.apple.metalfe` through a sandbox extension that the worker must be allowed to issue. Homebrew's framework Python re-executes itself as `Python.app`.

## Decision

- **`services/gateway/cmd/edge`** (Go, stdlib plus `caarlos0/env`) supervises three children. Each runs under `sandbox-exec` with its own profile in `deploy/sandbox/`.
  - **Gateway:** public listener 8710, internal 8719, production mode forced, no fallback upstream.
  - **Worker:** `python -m candela_worker.cli connect`.
  - **cloudflared:** `tunnel --protocol http2 --url http://127.0.0.1:8710 --metrics 127.0.0.1:8717`.

  Restart behaviour:
  - Crashed children restart with exponential backoff (1 s up to 60 s, reset after 2 min of uptime).
  - A tunnel session that ends is always a new hostname.
- **Child environments are built from scratch.** Only `CANDELA_*` variables for the right child, plus fixed overrides, reach the children. The supervisor's own environment never does. The edge reads `deploy/.env` itself (required mode 0600), and variables already set in the environment win.
- **Going online:**
  1. Wait for local `/readyz`.
  2. Wait for cloudflared's `/ready`.
  3. Read the hostname from `/quicktunnel` and validate it.
  4. Wait for `/readyz` through the tunnel, resolving via 1.1.1.1/1.0.0.1/8.8.8.8 to avoid the negative cache.
  5. Publish the endpoint document with `gh api --method PATCH gists/<id>` and a minimal `gh` environment.

  The heartbeat republishes every 10 min. Any exit path, including SIGTERM, publishes `offline` before the tunnel closes.
- **Kill switch:** the gateway counts public rejections in `candela_abuse_total{kind=oversized|origin|protocol|invalid}`. The edge scrapes these and `candela_rate_limited_total` from the internal `/metrics` every 15 s, with the bearer token.
  - A counter rising above its threshold within the window (default 2 min) closes the tunnel and publishes `offline` for 15 min.
  - Three trips in 6 h halt the edge until it is restarted manually.
- **Profiles:**
  - All three: default deny, fork denied, exec only of the target binary (and `Python.app` for the worker), explicit denials of `~/.ssh`, `~/.config`, Hugging Face tokens, Keychains and `.env*`.
  - **Gateway:** reads its binary, the snapshot and the Spark status file. Writes only `services/gateway/data/live/`. Binds loopback 8710/8719. Dials out only to :443 and :53; loopback is denied.
  - **Worker:** reads its interpreter, the needed Homebrew libraries, the venv, the worker directory, `ml/configs/models.yaml` and up to six model, adapter or blob directories. Writes leases, a temp dir and the Metal caches. Dials only 127.0.0.1:8719.
  - **cloudflared:** dials :443, :7844, :53 and 127.0.0.1:8710 only. Binds 127.0.0.1:8717.
- Production web configuration is rendered at deploy time from `deploy/netlify/production.env` and the Gist URL in `deploy/local/endpoint.json` (`make live-web-deploy`), without touching `apps/web`.

## Consequences

- A compromised gateway, worker or cloudflared cannot read the owner's credentials, spawn processes, or reach PostgreSQL, the owner's `llama-server`, the internal listener (gateway and cloudflared) or the LAN, apart from :443 for the gateway. The Go egress allowlist still blocks that case for the gateway.
- Seatbelt cannot filter by CIDR or hostname, so port-level egress is the sandbox's limit. Its parameters are Homebrew-specific: the paths for Python and its libraries are listed in `worker.sb` and need updating when Python's dependencies change.
- Cold start to "online" takes about 10 s. The model still loads lazily on the first chat.
- `sandbox-exec` is deprecated API surface. If a future macOS removes it, the fallback in ADR 0008 (a dedicated unprivileged user) needs the owner.

## Alternatives considered

- A shell or launchd-only supervisor: harder to get correct readiness, backoff and kill-switch logic in.
- QUIC tunnels: they bind UDP on all interfaces, and the measured WebSocket latency gain was not needed.
- Parsing cloudflared's log for the hostname: `/quicktunnel` on its loopback metrics port is structured and needs no log scraping.
- `gh gist edit`: it opens an editor or needs temporary files. `gh api PATCH` replaces the file content atomically.

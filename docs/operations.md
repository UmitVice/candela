# Operations — Candela live from the Mac

How the live setup works, how to run it, and what to do when it misbehaves. Decisions: ADR 0002 (topology), ADR 0008 (threat model), ADR 0500 (supervisor and sandboxes). Verification record: `docs/security/verification-2026-10-26.md`.

## Architecture

```
visitor ── https://candela-terminal.netlify.app (static PWA, Netlify)
   │  1. GET discovery Gist (gist.githubusercontent.com) → { status, gatewayUrl, chatTransport: "ws" }
   │  2. wss://<random>.trycloudflare.com/api/v1/chat/ws, https://…/api/v1/*
   ▼
Cloudflare edge ── quick tunnel (outbound HTTP/2 from the Mac, no open ports)
   ▼
cloudflared [sandbox]  ──►  127.0.0.1:8710  gateway public listener [sandbox]
                                gateway internal listener 127.0.0.1:8719 (never tunnelled)
                                  ▲ worker connect (token)       ▲ /metrics (token)
                         worker [sandbox] (MLX, Gemma 4 12B + LoRA)   edge supervisor
```

- `services/gateway/bin/edge` (the supervisor, unsandboxed, no listener) starts the three children, publishes the endpoint document, keeps the Mac awake (`caffeinate -i -w`), and runs the kill switch.
- Every Candela socket is loopback or outbound. `cloudflared` may reach only `127.0.0.1:8710`. The worker may reach only `127.0.0.1:8719`. The gateway dials only HTTPS (egress allowlist: Nasdaq symbol directory, Hugging Face).
- Logs go to `~/Library/Logs/Candela/{edge,gateway,worker,cloudflared}.log` and rotate at 20 MB at child start. State is in `~/.candela/edge/state.json`. Live gateway data (SQLite, optional recordings) is in `services/gateway/data/live/`.
- Configuration: `deploy/.env` (git-ignored, 0600, tokens) on top of the defaults in `deploy/.env.example`. The public Gist id is in `deploy/local/endpoint.json`.

## Runbook

| Task | Command |
|---|---|
| First setup (tokens + Gist, once) | `make live-init` |
| Start everything | `make live-up` (prints the tunnel URL; online in about 10 s) |
| Stop and publish `offline` | `make live-down` |
| State, URL, RSS per process, route | `make live-status` |
| Follow logs | `make live-logs` |
| Prove the sandboxes | `make live-sandbox-proof` |
| Adversarial checks against the tunnel | `make live-adversarial` |
| Production web deploy (once per milestone) | `make live-web-deploy` |
| Optional login agent (owner decision) | `make live-agent-install` / `make live-agent-uninstall` |
| Area checks | `make deploy-check` (profiles compile, shellcheck, plist, JSON, gitleaks) and `make gateway-check` |

Notes:
- Local runs without the public edge: `CANDELA_EDGE_TUNNEL=false make live-up` keeps the sandboxes and publishes nothing. `CANDELA_EDGE_PUBLISH=false` opens a tunnel without announcing it. The edge refuses `CANDELA_EDGE_SANDBOX=false` while the tunnel is on.
- **Only one chat model session at a time.** While a Candela Pro training holds about 11 GB, the worker's admission control declines Gemma jobs after 30 s. The gateway answers `overloaded` and the site offers replay. Do not demo live during training.

### Rotating tokens

1. `make live-down`.
2. Delete `deploy/.env` and run `make live-tokens`. It generates new `CANDELA_WORKER_TOKEN` and `CANDELA_METRICS_TOKEN` values with `openssl rand -base64 32`. Tuning values come back from `.env.example`; copy over any you changed.
3. `make live-up`.

The tokens never leave the Mac: they are passed only to the gateway and the worker, never to `gh`, `cloudflared` or the Gist. The Gist is updated with the owner's existing `gh` login. To revoke that access, use `gh auth logout` (this stops publishing).

### Changing the model version

- Set `CANDELA_WORKER_MODEL` (an id from `services/worker/served-models.yaml`) and, if its adapter path differs, `CANDELA_PRO_ADAPTER` in `deploy/.env`.
- Make sure the adapter directory is listed in `CANDELA_EDGE_WORKER_READ` (at most 6 entries). Anything else stays unreadable to the worker.
- Then `make live-down && make live-up`. The model loads on the first chat and unloads after `CANDELA_WORKER_IDLE_UNLOAD_SEC` (default 900 s).

### When the Mac sleeps or goes offline

- `caffeinate -i` prevents idle sleep while the edge runs. Closing the lid on battery still sleeps the Mac.
- During sleep the tunnel drops. Visitors' WebSockets fail, and the PWA switches to replay. The Gist may still say `online`, but the PWA probes `/api/v1/status` at the published URL, and when that fails it shows replay. `heartbeatAt` (refreshed every 10 min) tells a reader how stale the document is.
- After wake, `cloudflared` reconnects or exits. On exit the edge publishes `offline`, starts a new tunnel (new hostname) and publishes it again once `/readyz` answers through the tunnel. If the network is gone, it retries with backoff up to 2 min.
- Shutting down cleanly with `make live-down` publishes `offline` immediately.

### Kill switch

- Rejections are counted per 2-minute window. Defaults: 300 rate-limited, 30 oversized, 120 bad-origin, 60 WebSocket protocol violations, 300 invalid requests. Any one of them over its limit closes the tunnel, publishes `offline` and waits 15 min. Then a new tunnel with a new hostname opens.
- Three trips in 6 h halt the public edge: state `halted`, while the gateway and worker keep running locally. Look at `make live-logs` (gateway access logs carry daily-salted client hashes, never IPs), then `make live-down && make live-up`.
- Thresholds are the `CANDELA_EDGE_KILL_*` variables.

## Troubleshooting

| Symptom | Check |
|---|---|
| `live-up` says "run make live-init first" | `deploy/.env` is missing (`make live-tokens`) |
| edge exits at start with a config error | the message names the variable; tokens must hold ≥ 32 random bytes; `deploy/.env` must be 0600 |
| `worker not running`, restarts with backoff | `worker.log`. A `PermissionError` or "file system sandbox blocked open()" means the worker needs a path outside `worker.sb` (a new Homebrew dependency of Python: `otool -L`; a model directory: `CANDELA_EDGE_WORKER_READ`) |
| chats answer `overloaded` | memory headroom. A training or another model holds the GPU (`make worker-doctor`, `~/.candela/leases/`) |
| state `connecting` for long | `cloudflared.log`. Quick-tunnel API outages happen; the edge retries with backoff |
| site stays on replay while online | the Gist raw URL is cached up to 5 min by GitHub's CDN; the PWA's discovery cache adds its own window |
| `halted` | kill switch, see above |
| port already in use | another gateway runs on 8710/8719 (`lsof -nP -iTCP:8710`). Stop it, or stop the live stack before running a dev gateway |

## Upgrade paths (ADR 0002)

- **Stable hostname:** a named Cloudflare tunnel on an owner domain (`cloudflared tunnel run` with a credentials file readable only by the cloudflared profile), then point `discoveryUrl` at a static document or drop discovery.
- **Always-on gateway:** run the gateway container on a small host, and set `CANDELA_WORKER_ON_PUBLIC=true` there with TLS. The worker dials it over `wss://`; its sandbox rule changes from `localhost:8719` to that host's :443.
- **Hugging Face PRO:** a Docker Space for the gateway plus a CPU fallback model (`CANDELA_FALLBACK_ENABLED=true`).
- **If `sandbox-exec` disappears:** run the stack as a dedicated unprivileged macOS user created by the owner (ADR 0008), with the same loopback and egress rules enforced by `pf`.

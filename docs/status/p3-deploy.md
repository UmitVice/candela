# p3-deploy — status

STATUS: BLOCKED — Creating the public discovery Gist (`make live-init` → `gh gist create --public`) is refused by this session's auto-mode permission classifier ("Public Data-Sharing Upload"). It was refused again on 2026-10-26 after the Director relayed the owner's approval: an approval passed through another session does not change this session's permissions. The owner can run `make live-init` in their own terminal (it writes `deploy/local/endpoint.json`; commit that file), or add a Bash permission rule for it in an interactive `claude` terminal. Then run `make live-up` and `make live-web-deploy` (the single Netlify deploy), or re-run this session to do both.

Summary:
The Mac-side live stack is built, hardened and verified end to end through a real quick tunnel, with publishing turned off. What is missing is the public announcement: the Gist, the production web deploy with the discovery URL, and therefore the "site chats live" acceptance.

- **`services/gateway/cmd/edge` supervisor:**
  - Runs the gateway, the MLX worker and `cloudflared` (`--protocol http2`), each under its own Seatbelt profile.
  - Builds child environments from scratch and restarts crashed children with backoff.
  - Goes online only after `/readyz` answers through the tunnel. It resolves through public DNS to skip the macOS negative cache, then publishes the endpoint document with `gh api PATCH`, sends a heartbeat every 10 min, and publishes `offline` on every exit path.
  - Kill switch on abuse counters scraped from the internal `/metrics`: trip → `offline` for 15 min → new hostname; three trips in 6 h → halted.
- **Make targets:** `live-init`, `live-tokens`, `live-up`, `live-down`, `live-status`, `live-logs`, `live-agent-install`/`live-agent-uninstall` (LaunchAgent template, not installed), `live-web-deploy`, `live-sandbox-proof`, `live-adversarial`, `deploy-check`.
- **Gateway:**
  - New `GET /api/v1/lab/spark`: sanitized allowlist of fields, cached 10 s, rate-limited, 404 when no status file exists. Added to the OpenAPI spec.
  - `candela_abuse_total{kind}` counter.
  - cel-go bumped to v0.29.0; Dependabot alert #7 is now `fixed`.
- **Docs:** `docs/operations.md`, ADR 0500, `docs/security/verification-2026-10-26.md`, `deploy/recordings/README.md`.

Commits: 800aea4 fix(gateway): bump cel-go to v0.29.0 for the Dependabot advisory; 943e1eb feat(gateway): serve sanitized Spark trainer status at /api/v1/lab/spark; 9ba6c56 feat(gateway): add edge supervisor and abuse counters for the kill switch; 7b23690 feat(deploy): add Seatbelt profiles, live make targets and security probes; ed6a37e fix(gateway): drop parenthesized details from Spark pause reasons; plus the docs commit with this report.

Verified:
- **Sandbox:** `sandbox-exec` works on macOS 27.0.1. `make live-sandbox-proof` passes every probe in all three profiles:
  - Reads are denied for `~/.ssh`, `~/.config/gh`, `~/.cache/huggingface/token`, `~/Library/Keychains`, every `.env` file and listing `~`.
  - Exec and fork are denied.
  - Connections are denied to PostgreSQL 5432, `llama-server` 8080, dev 8712, the internal listener 8719 (from the gateway and cloudflared), the LAN and port 80.
  - A worker bind on `0.0.0.0` is denied.
  - Controls are allowed: the snapshot, the model config, nasdaqtrader:443, and cloudflared → 8710.
- **Sandboxed inference (dev model):** `meta → tool_call → tool_result → token/telemetry → usage → done` at 97 tokens/s. Session recording writes v1 files from inside the sandbox.
- **`make live-up` from cold:** online through the tunnel in **10–11 s** (84 s before the DNS fix). Local-only mode starts in 3–5 s.
- **Adversarial list through the tunnel** (all pass, table in the verification doc):
  - `/internal/*`, `/metrics` and worker connect → 404.
  - Traversal and injection in every parameter → 400/404 without leaks.
  - Oversized bodies → 413, 40 kB header → 431 (the edge drops it), WebSocket 200 kB frame → 1009, non-start or binary frame → 1008.
  - Bad, look-alike, http, uppercase or `null` origins → 403 for CORS and WebSocket; missing subprotocol → 400.
  - Forged `CF-Connecting-IP` is rejected by Cloudflare itself (403/1000). Forged XFF/X-Real-IP/True-Client-IP still get limited (429 with `Retry-After` and `RateLimit-*`).
  - Client `system`/`tool` messages → 400. Unknown tools and URL symbols → `invalid_arguments`. PUT/DELETE/TRACE/PATCH → 405. CRLF and oversized request ids are not reflected.
- **Kill switch** at test thresholds: 20 bad origins → `cooldown` within one scrape; the old host answers 530; a new hostname 60 s later; second trip → `halted`.
- **`lsof`:** only `127.0.0.1:8710`, `127.0.0.1:8719` (gateway) and `127.0.0.1:8717` (cloudflared metrics) listen. There are no UDP sockets.
- **Idle footprint, model unloaded (RSS):**

  | Process | RSS |
  |---|---|
  | edge | 13–18 MB |
  | gateway | 22–33 MB |
  | worker | 54–113 MB |
  | cloudflared | 42 MB |

- **Checks:** `make gateway-check` (lint 0 issues, govulncheck clean) and `make deploy-check` pass. The `security-review` skill found no HIGH or MEDIUM issues; its single LOW item is fixed (ed6a37e).
- **Not verified:**
  - Publishing to the Gist and `live-down` → site switches to replay. The code path exists; the Gist itself is blocked.
  - The production site chatting with Candela Pro. This also needs the training to finish, because admission declines Gemma beside it, as designed.
- **Cleanup:** the live stack is stopped (`make live-down`); ports 8710/8717/8719 are free. Training, the Spark daemon, `~/models` and the owner's processes were not touched.

Decisions:
- **ADR 0500:**
  - Go supervisor; `sandbox-exec` profiles with parameters.
  - HTTP/2 tunnel transport, because QUIC binds UDP on all interfaces.
  - Hostname read from cloudflared's `/quicktunnel`; tunnel probes resolve through 1.1.1.1.
  - Abuse-counter kill switch; `gh api PATCH` instead of `gh gist edit`.
  - The edge loads `deploy/.env` itself (0600 enforced, the environment wins).
  - Worker reads limited to six directories, including the HF blob store for the dev model.
  - `file-issue-extension` for the Metal JIT cache; Homebrew Python libraries listed explicitly.
- **Deviations:**
  - The Gist and the Netlify deploy are not done (blocked, see above).
  - Recordings are deferred: Candela Pro v0.1 is still training and Gemma cannot be admitted beside it. The tooling is verified and the curation list is in `deploy/recordings/README.md`.
  - Production never enables the dev fallback.

Open issues / risks:
- The Seatbelt port rules cannot filter CIDRs: the gateway may dial any host on :443. The Go egress allowlist covers that case.
- `sandbox-exec` is deprecated API; the ADR 0008 fallback needs the owner.
- `worker.sb` hard-codes Homebrew paths for Python 3.14 and its libraries.
- **Web (p4/web owner):** `gateway.service.ts` `safeGatewayUrl` accepts any `https:` origin. ADR 0008 layer 8 requires `^https://[a-z0-9-]+\.trycloudflare\.com$`. The CSP limits the damage, but `deploy/netlify/production.env` adds `api.github.com` and `huggingface.co` to `connect-src`, so the check should be tightened.
- The WebSocket chat rate limit runs before the origin check, so a flood of bad-origin WebSocket upgrades shows up as `rate_limited`, not `origin` (the kill switch still counts both).

Notes for the next phases:
- **After the Gist exists:**
  1. `make live-up` prints the tunnel URL; `make live-status` shows state, RSS and the route.
  2. Run `make live-web-deploy` once. It renders `mode: auto`, `chatTransport: ws`, the Gist raw URL, and a `connect-src` with `*.trycloudflare.com` (https/wss), `gist.githubusercontent.com`, `api.github.com`, `huggingface.co` and `*.hf.co`.
  3. Then check that the site goes live and that `make live-down` brings back replay within about 5 min (CDN cache).
- **p4-polish:** record the ten sessions in `deploy/recordings/README.md` once v0.1 is trained and memory is free; serve `candela-pro-v0.1` only.
- **Director proposals:**
  - Document `GET /api/v1/lab/spark` (schema `candela.spark.status.v1`, sanitized fields as in `internal/httpapi/lab.go`) in `contracts/api.md`.
  - Document the `candela_abuse_total` metric.
  - p2-web's proposal to send `rate_limited` as a WebSocket error event after the upgrade (browsers cannot read a 429 upgrade) still stands. It is a contract change, so I left it.

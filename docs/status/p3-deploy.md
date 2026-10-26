# p3-deploy — status

STATUS: done

Summary:
Candela is live from the Mac. https://candela-terminal.netlify.app discovers the gateway through the public Gist and chats with Candela Pro v0.1 over WebSocket. The stack is built, hardened and verified through the tunnel, and it is left running. The Director created the Gist (`236f53f0313131e3c2ad11ecb75d46d3`) with the owner's direct approval, because this session's permission classifier refused `gh gist create --public` twice. The edge updates that Gist with `gh api PATCH`.

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

Commits: 800aea4 fix(gateway): bump cel-go to v0.29.0 for the Dependabot advisory; 943e1eb feat(gateway): serve sanitized Spark trainer status at /api/v1/lab/spark; 9ba6c56 feat(gateway): add edge supervisor and abuse counters for the kill switch; 7b23690 feat(deploy): add Seatbelt profiles, live make targets and security probes; ed6a37e fix(gateway): drop parenthesized details from Spark pause reasons; 29c6605 docs(deploy): operations guide, ADR 0500, security verification and p3-deploy status; 51d4846 docs(deploy): record the repeated Gist permission refusal; 547ddc1 chore(deploy): record the public discovery Gist id; plus the commit with this report.

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
- **Live publication (2026-10-26 04:41 UTC):**
  - `make live-up` went online in 12–13 s. The Gist API showed `online` with the tunnel URL at once; the raw URL followed within about 4 min (GitHub's CDN cache).
  - `make live-web-deploy` (netlify-cli 27.14.2, `--no-build`) produced deploy `6adeda00e0633a87e20c817f`. The live `config.json` has `mode: auto`, `chatTransport: ws` and the Gist raw URL. The live CSP `connect-src` is `'self' https://gist.githubusercontent.com https://*.trycloudflare.com wss://*.trycloudflare.com https://api.github.com https://huggingface.co https://*.hf.co`.
  - The tunnel answers with `Access-Control-Allow-Origin: https://candela-terminal.netlify.app`.
  - On the production site (fresh service worker), the status panel read "gateway online · WS" and "inference candela-pro-v0.1 · PRO · mlx 4bit". "What was the latest close of NVDA?" ran live: `get_quote` card, then an answer citing $212.21 (2026-10-22) at 17.7 tokens/s, TTFT 5.8 s.
  - The training was paused by its own memory guard at that moment, so admission succeeded. Live inference then held the GPU, as the lease priority intends.
  - To hand memory back quickly, I restarted the stack with `CANDELA_WORKER_IDLE_UNLOAD_SEC=300` in `deploy/.env`. The model unloaded and the trainer's guard saw 12.7 GB available. The restart published the new hostname to the Gist.
- **Offline path:** every `make live-down` printed "published offline" in `edge.log`, and the Gist API showed `offline` between runs. The site's switch to replay after `live-down` follows from the discovery code (`status !== 'online'` → replay) and the earlier p2-web verification; it was not re-run on production, so the stack stays up.
- **Running state:** the live stack is left running and verified: only loopback listeners, the worker serving `candela-pro-v0.1` only, the model unloaded when idle. Training, the Spark daemon, `~/models` and the owner's processes were not touched, apart from the designed lease priority during the one live chat.

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
  - The Gist was created by the Director's session, because this session's classifier refused it.
  - Recordings are deferred: Candela Pro v0.1 is still training and Gemma cannot be admitted beside it. The tooling is verified and the curation list is in `deploy/recordings/README.md`.
  - Production never enables the dev fallback.

Open issues / risks:
- **Returning visitors are stuck in replay (web area, needs one more deploy).** Browsers that installed the Angular service worker under an earlier deploy keep that worker's CSP (`connect-src 'self'`). The SW proxies the page's `fetch` to the Gist and to the gateway, and the old CSP blocks it: NGSW answers 504 and the site says "Gateway discovery is unreachable".
  - The worker script is byte-identical across deploys, so browsers never replace it.
  - Verified in the browser pane: the old worker gave 504; after unregistering it, the site went live.
  - New visitors are fine.
  - Fix: append a per-deploy stamp to `dist/ngsw-worker.js` in `render-dist.mjs`, so browsers install a fresh worker with the current headers. Also send cross-origin discovery and gateway fetches with `ngsw-bypass` (query parameter, to avoid a preflight). Then do one web deploy.
- **Model quality (ml):** in the live NVDA answer the v0.1 interim adapter wrote "+3.95% on the day, down 4.4% on the day", while the tool said −4.4 %.
- The Seatbelt port rules cannot filter CIDRs: the gateway may dial any host on :443. The Go egress allowlist covers that case.
- `sandbox-exec` is deprecated API; the ADR 0008 fallback needs the owner.
- `worker.sb` hard-codes Homebrew paths for Python 3.14 and its libraries.
- **Web (p4/web owner):** `gateway.service.ts` `safeGatewayUrl` accepts any `https:` origin. ADR 0008 layer 8 requires `^https://[a-z0-9-]+\.trycloudflare\.com$`. The CSP limits the damage, but `deploy/netlify/production.env` adds `api.github.com` and `huggingface.co` to `connect-src`, so the check should be tightened.
- The WebSocket chat rate limit runs before the origin check, so a flood of bad-origin WebSocket upgrades shows up as `rate_limited`, not `origin` (the kill switch still counts both).

Notes for the next phases:
- **Operating:** `make live-status` / `make live-logs` / `make live-down`; the runbook is `docs/operations.md`. Expect `overloaded` (site BUSY, replay offered) whenever a training holds the memory.
- **p4-polish:** record the ten sessions in `deploy/recordings/README.md` once v0.1 is trained and memory is free; serve `candela-pro-v0.1` only.
- **Director proposals:**
  - Document `GET /api/v1/lab/spark` (schema `candela.spark.status.v1`, sanitized fields as in `internal/httpapi/lab.go`) in `contracts/api.md`.
  - Document the `candela_abuse_total` metric.
  - p2-web's proposal to send `rate_limited` as a WebSocket error event after the upgrade (browsers cannot read a 429 upgrade) still stands. It is a contract change, so I left it.

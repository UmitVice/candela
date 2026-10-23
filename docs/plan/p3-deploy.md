# Phase 3 · Deploy — Go live from the Mac (`p3-deploy`)

- Area you own: `deploy/**`, `services/gateway/cmd/edge/**` (new), small deployment-related changes elsewhere in `services/gateway` and `services/worker` (no other session works there in this phase), `make/deploy.mk`, `docs/operations.md`, `docs/status/p3-deploy.md`, new ADRs.
- Runs in parallel with `p3-observatory` (owns `apps/web`). Do not edit `apps/web`; production web configuration is rendered into `dist` at deploy time.
- Inputs: `CLAUDE.md`, ADR 0002, `contracts/api.md` (endpoint document, recordings), status reports of phases 1–2.

## Goal

One command makes Candela live from the owner's Mac: gateway, GPU worker and a Cloudflare quick tunnel start together, the public endpoint is published for the PWA, and everything stops cleanly. The deployment is secure, observable and gentle on resources.

## Deliverables

1. `cmd/edge` supervisor (Go): starts and supervises the gateway (public + internal listeners), the worker (`candela-worker connect`) and `cloudflared tunnel --url http://127.0.0.1:8710`; parses the tunnel hostname; waits for `/readyz` through the tunnel; publishes the endpoint document (`contracts/api.md`) to a public Gist with `gh gist edit` (create it once with `gh gist create --public`; the Gist id is public configuration stored in `deploy/local/endpoint.json`); refreshes `heartbeatAt` at most every 10 minutes; restarts crashed children with backoff; on SIGINT/SIGTERM drains, publishes `offline`, and exits. Logs to `~/Library/Logs/Candela/`.
2. `make live-up`, `make live-down`, `make live-status`, `make live-logs`. Optional `deploy/local/com.candela.edge.plist` LaunchAgent template plus `make live-agent-install` / `live-agent-uninstall`; do not install it, the owner decides.
3. Implement ADR 0008 end to end before the first public exposure:
   - Seatbelt profiles in `deploy/sandbox/` (`gateway.sb`, `worker.sb`, `cloudflared.sb`) applied by the supervisor via `sandbox-exec`: default-deny file reads outside each process's exact needs (binary, snapshot/data dirs; for the worker its Python environment and the model directory read-only), writes only to its data and log directories, no process execution for gateway and worker, network restricted to the loopback ports and required outbound hosts. Prove denial by attempting to read `~/.ssh`, `~/.config/gh`, `~/.cache/huggingface/token`, `~/Library/Keychains` from inside each sandbox. If `sandbox-exec` is unusable on this macOS version, stop and report BLOCKED with the evidence (the fallback needs the owner).
   - CORS allowlist (`https://candela-terminal.netlify.app`, localhost dev), `CANDELA_TRUSTED_PROXY=cloudflare`, worker connect and internal APIs only on the internal listener, tokens generated with `openssl rand` into git-ignored `.env` files, nothing secret in logs or the Gist.
   - Kill switch in the supervisor: sustained abuse (rate-limit rejections, oversized requests, origin violations above thresholds) closes the tunnel, publishes `offline` for 15 minutes, then restarts with a new hostname.
   - Run the adversarial verification list from ADR 0008 through the tunnel and record every result in `docs/security/verification-<date>.md`; then run the `security-review` skill over `services/gateway`, `services/worker` and `deploy` and fix every finding before the go-live.
4. Production web configuration rendered at deploy time: `discoveryUrl` (Gist raw URL or Gists API URL), `chatTransport: "ws"`, `mode: "auto"`, CSP `connect-src` including `https://*.trycloudflare.com wss://*.trycloudflare.com https://gist.githubusercontent.com https://api.github.com https://huggingface.co https://*.hf.co`. Extend `make web-deploy` inputs through `deploy/netlify/` files rather than editing `apps/web`. One production deploy at the end, after the Observatory phase has finished its own deploy if possible (coordinate through the timing of your final deploy; if the Observatory deploy has not happened yet, deploy anyway and report it).
5. Real recordings: with the fine-tuned Candela Pro model live, record 8–10 curated sessions (single-stock analysis, comparison, fundamentals with and without SEC data, forecast interpretation, unknown company, refusal of personalized advice, follow-up question) with telemetry enabled, using `CANDELA_RECORD_SESSIONS=true`. Store them in `deploy/recordings/` (JSON, reviewed for quality and for any secret or personal data) for `p4-polish` to bundle into the web app.
6. `docs/operations.md`: architecture of the live setup, runbook (start/stop, logs, rotating tokens, changing the model version, what happens when the Mac sleeps), troubleshooting, upgrade paths from ADR 0002.

## Acceptance (verify by running; no automated tests)

- `make live-up` from a cold state brings everything up in < 60 s (model loads lazily on first chat) and `https://candela-terminal.netlify.app` chats with the pro model over the tunnel, with tool cards and Observatory telemetry.
- `make live-down` publishes `offline`; the production site switches to replay within the discovery cache window.
- Public listener refuses `/internal/*`, `/metrics` and worker connect; origin checks, rate limits and the kill switch verified; sandbox denials proven; `lsof` shows no non-loopback listeners; the security review has no open findings.
- Idle footprint with the model unloaded reported (RSS of each process).
- Report written to `docs/status/p3-deploy.md`.

## Out of scope

Web UI changes, model training, tests.

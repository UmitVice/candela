# Phase 1 · Gateway — Go API foundation (`p1-gateway`)

- Area you own: `services/gateway/**`, `make/gateway.mk`, `docs/status/p1-gateway.md`, new ADRs.
- Runs in parallel with `p1-web` and `p1-ml`. Do not touch their paths.
- Inputs: `CLAUDE.md`, `docs/plan/00-master-plan.md`, everything in `contracts/`.

## Goal

The production backend of Candela: a single Go binary that serves the public API in `contracts/api.md`, streams chat over SSE, runs the tool loop against deterministic market-data tools, routes generation to a reverse-connected GPU worker or to an OpenAI-compatible fallback (llama.cpp), and stays safe on modest hardware. In production it runs on the owner's Mac behind a Cloudflare quick tunnel (see ADR 0002); it must also run unchanged in a container on any small cloud host later.

## Deliverables

1. Module `github.com/UmitVice/candela/services/gateway`, Go 1.27, layout:
   - `cmd/gateway` (server), `cmd/snapshot` (builds the market snapshot), `cmd/workerctl` (dev helper: generates a worker token, prints a sample `hello`).
   - `internal/config` (env via `caarlos0/env`, validated, secrets never logged), `internal/httpapi` (router, handlers, middleware, SSE writer), `internal/chat` (orchestrator, tool loop, system prompt rendering, reasoning splitter), `internal/llm` (`Upstream` interface; `openai` adapter for OpenAI-compatible streaming with tool-call delta assembly; `workerhub` adapter), `internal/workerhub` (WebSocket hub implementing `contracts/worker-protocol.md`, routing, heartbeats, fair FIFO queue), `internal/tools` (registry from `tools.json`; model and UI views exactly as in `contracts/tools.md`), `internal/market` (providers, indicators, baseline forecast), `internal/store` (SQLite, goose migrations, sqlc queries), `internal/ratelimit`, `internal/observability` (slog JSON, Prometheus).
   - `internal/contracts/` holds copies of `contracts/tools.json` and `contracts/system-prompt.md` for `go:embed`, refreshed by `make gateway-contracts`; `gateway-check` fails if they drift.
2. HTTP: chi router, middleware for request id, real client IP (trust `X-Forwarded-For` only from configured proxy CIDRs), panic recovery, access log, CORS allowlist, security headers, body limits, gzip for JSON only, read-header timeout, per-route deadlines; graceful shutdown that drains SSE streams and sends `drain` to workers.
3. Two listeners: public (`CANDELA_ADDR`, default `127.0.0.1:8710`) and internal (`CANDELA_INTERNAL_ADDR`, default `127.0.0.1:8719`, never tunnelled). Behind cloudflared every public request arrives from loopback, so trust is never derived from the remote address: client IP comes from `CF-Connecting-IP` only when `CANDELA_TRUSTED_PROXY=cloudflare`, otherwise from the socket.
4. Endpoints from `contracts/api.md`: status, models, chat stream (SSE) and chat WebSocket (`/api/v1/chat/ws`, primary in production), market (search, quote, history, indicators, fundamentals, forecast), feedback, worker connect, health, readiness, metrics. Also `api/openapi.yaml` (OpenAPI 3.1, hand-written from the contract) served at `/api/v1/openapi.yaml`.
5. Chat orchestrator: renders the system prompt with today's date, keeps only `user`/`assistant` text from the client, max 6 tool rounds, tools in a round run concurrently with an 8 s per-tool timeout, tool results go to the model as model views and to the client as `tool_result` UI views, usage and metrics recorded, client disconnect cancels everything. Reasoning split supports both `<think>…</think>` text and a separate `reasoning_content` delta field.
6. Routing: `auto` → a healthy idle worker (pro) else the fallback upstream (lite); explicit model ids route to their upstream. Generation concurrency is bounded (`CANDELA_MAX_CONCURRENT_GENERATIONS`, default 1 per worker + 1 fallback); excess requests wait in a bounded FIFO (`maxDepth` 16) and receive `queue` events; overflow returns `overloaded`. If a worker drops before the first token, retry once on the fallback.
7. Rate limiting with `golang.org/x/time/rate` per client IP in an LRU (chat 6/min burst 3, market 60/min burst 20, feedback 20/min), standard rate-limit headers.
8. Market data:
   - Symbol directory from Nasdaq Trader (`nasdaqlisted.txt`, `otherlisted.txt`), refreshed daily, cached in SQLite; search ranks exact ticker, ticker prefix, then name tokens.
   - **Snapshot provider**: `cmd/snapshot` builds a read-only SQLite file (`bars`, `symbols`, `meta(asOf, source, license)`) for the S&P 500, Nasdaq-100 and major ETFs (SPY, QQQ, DIA, IWM, sector SPDRs), ≥ 5 years of daily OHLCV, from a public Hugging Face dataset. Evaluate candidates (for example `vessel888/us-stocks-daily-all`, `younginpiniti/us-stocks-daily-all`, others you find) for license clarity, provenance, coverage and recency; record the choice in an ADR. Read parquet with a maintained pure-Go library. Output path from `CANDELA_SNAPSHOT_PATH` (default `services/gateway/data/market.sqlite`, git-ignored); optional `CANDELA_SNAPSHOT_URL` to download a prebuilt file at startup.
   - Indicators and the `baseline` forecast exactly as defined in `contracts/api.md`.
   - SEC fundamentals provider using company facts, enabled only when `SEC_USER_AGENT` is set (it must contain a contact email, so leave it unset; the owner may configure it later). When disabled, `get_fundamentals` returns `{"error":"data_unavailable",…}`. If you find a permissively licensed public dataset of SEC financial statements, add it to the snapshot instead and record that in the ADR.
   - Provider interfaces ready for `live` (keyed EOD API) and `vaniras` adapters; both return "disabled" for now.
9. Storage: SQLite through `modernc.org/sqlite` (no CGO), WAL, goose migrations embedded, sqlc-generated queries: feedback, market response cache with TTL, symbol directory.
10. Internal tool API for training-data generation: `POST /internal/v1/tools/execute` `{ "name": "...", "arguments": {...} }` → `{ "modelView": "<string>", "uiView": {...} }`, served only on the internal listener. `p2-train` uses it so training data and production share one tool implementation.
11. Observability: Prometheus metrics (HTTP, chat requests by route and outcome, TTFT and tokens/s histograms, queue depth, connected workers, tool latency and errors, rate-limit rejections), `/metrics` on the internal listener, also behind `CANDELA_METRICS_TOKEN`.
12. Dev workflow in `make/gateway.mk`: `gateway-contracts`, `gateway-snapshot`, `gateway-lite-up` (downloads a small GGUF of the lite base model with `hf download` and runs the local `llama-server` on `127.0.0.1:8712` with `--jinja`, tool calling and low threads; never touch port 8080), `gateway-run` (port 8710, loads `services/gateway/.env`), `gateway-check` (gofmt, go vet, golangci-lint, build).
13. `services/gateway/Dockerfile`: multi-stage, static binary, non-root user (UID 1000), listens on `$PORT` when set, small final image, so the gateway can move to a cloud host without code changes. Docker is not installed locally; keep it correct by inspection.
14. `services/gateway/.env.example` documenting every variable with safe placeholders.

## Behaviour details

- Tool argument validation against the JSON schema before execution; invalid arguments return an `invalid_arguments` model view so the model can recover.
- Model-view JSON is produced by a dedicated encoder that guarantees key order, rounding and the 2 500-character cap from `contracts/tools.md`.
- Untrusted text never becomes instructions: tool results are data, and nothing from the client reaches the system role.
- All upstream calls have deadlines; SSE writes flush per event; heartbeats every 15 s.
- Log one structured line per chat request (route, model, rounds, tools, tokens, TTFT, outcome) without message content.

## Acceptance (verify by running; no automated tests)

- `make gateway-check` passes.
- With the snapshot built and the dev lite model running: `curl -N` against `/api/v1/chat/stream` (and a small WebSocket client against `/api/v1/chat/ws`) streams `meta → reasoning? → tool_call → tool_result → token… → usage → done` for "Analyze NVDA"; market endpoints return contract-shaped JSON for NVDA, AAPL, SPY; unknown symbol → 404; rate limits trigger with headers; `/metrics` rejects without token.
- `cmd/workerctl` plus a scripted fake worker (a tiny Go program under `cmd/fakeworker` that speaks the protocol and streams canned tokens) proves registration, heartbeats, job dispatch, cancel and fallback when it disconnects.
- Public listener does not serve `/internal/*`, `/metrics` or worker connect (unless configured); internal tool API returns model views byte-identical to what the chat loop sends to the model.
- Report written to `docs/status/p1-gateway.md`, including the chosen snapshot dataset, its license and `asOf`.

## Out of scope

Tunnel supervision and discovery publishing (`p3-deploy`), the Python worker, authentication for end users, tests.

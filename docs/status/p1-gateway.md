# p1-gateway — status

STATUS: done

Summary:
Go 1.27 gateway in `services/gateway` serves `contracts/api.md`: status, models, chat over SSE and WebSocket with the tool loop (≤ 6 rounds, concurrent tools, 8 s timeout, reasoning split for `<think>` and `reasoning_content`), market endpoints, feedback, OpenAPI 3.1, health/readiness. The internal loopback listener holds `POST /internal/v1/tools/execute`, `GET /internal/v1/tools`, `GET /internal/v1/system-prompt`, `/metrics` (bearer token) and worker connect. Worker hub implements `candela.worker.v1` (hello/welcome, 15 s ping/pong, 2 missed pongs drop, job/cancel/drain, seq dedup) with a bounded FIFO scheduler (`queue` events, `overloaded`) and one fallback retry when a worker fails before its first token. Market snapshot built by `cmd/snapshot` from pinned Hugging Face datasets; SQLite state (goose migrations, sqlc queries) for symbols, cache and feedback. Dev tools: `cmd/workerctl`, `cmd/fakeworker`, `make gateway-lite-up`. Director security additions are in: egress allowlist with public-address-only dialing, generic errors with request ids and no host/user/path leaks (opaque worker ids in `/status`), input/context/output caps, `CANDELA_MEMORY_LIMIT`/`GOMEMLIMIT`, `govulncheck` in `gateway-check`, client IPs as HMACs with a daily-rotating in-memory salt. The fallback upstream is a dev/cloud adapter only (off in production unless enabled).

Snapshot: asOf **2026-10-22**, 533 symbols (S&P 500 + Nasdaq-100 + 15 ETFs), 505 with ≥ 5 years; fundamentals asOf 2026-09-29.
- Prices: `defeatbeta/yahoo-finance-data@2afd3723f8e9`, **ODC-By-1.0**.
- ETF gaps (sector SPDRs since 2025-01-02, QQQ after 2026-09-11): `AlphaDojo/dojo_stock_kline@432b00444c20`, **Apache-2.0**.
- Fundamentals (SEC XBRL as filed): `ZipLime/company-fundamentals@57acd842023b`, **Apache-2.0**.

Commits: a2f3751 feat(gateway): add Go gateway with chat loop, tools, market data and worker hub; 7bbc559 feat(gateway): add snapshot builder, fake worker, workerctl and hardening; 7ec0bcf fix(gateway): strip schema patterns for llama.cpp and order middlewares; e00ba51 docs(adr): record snapshot datasets and gateway runtime decisions; plus this report.

Verified:
- `make gateway-check` (contract drift, gofmt, vet, golangci-lint 0 issues, build, govulncheck: no vulnerabilities).
- `make gateway-snapshot`: 10 m 36 s, ~540 MB downloaded via range reads.
- Dev model: `unsloth/Qwen3-1.7B-GGUF` Q4_K_M on `llama-server` 127.0.0.1:8712 (CPU, 4 threads). SSE `curl -N` ("latest close of AAPL"): `meta → tool_call → tool_result → reasoning → token… → usage → done`; "Analyze NVDA" ran 6 parallel tools then hit the 1 536/2 048-token budget in reasoning (`finishReason: length`, the base model over-thinks). WebSocket client: `meta → reasoning → tool_call → tool_result → reasoning → token → usage → done`, close 1000.
- Model views sent to the model (sha256 logged at debug) are byte-identical to `/internal/v1/tools/execute` output for all six tools; AAPL FY2025 fundamentals match the `contracts/tools.md` example exactly.
- Market: NVDA/AAPL/SPY quote, history, indicators, fundamentals, forecast return contract-shaped JSON; unknown symbol → 404; SPY fundamentals → 404 with explanation; invalid tool args → `invalid_arguments` view.
- Rate limits: market 21st request → 429 with `Retry-After`, `RateLimit-*`; chat burst 3 → 429; forged `CF-Connecting-IP`/`X-Forwarded-For` ignored (same client hash). CORS allowlist; WS bad origin → 403; oversized body → 413.
- Public listener: `/internal/v1/tools/execute`, `/metrics`, `/api/v1/worker/connect` → 404. Internal `/metrics`: 401 without token, 200 with it.
- Fake worker: registration and `/status` worker entry; auto route → worker; telemetry throttled; WS cancel → worker `cancel`, `done: cancelled`; `-crash-on-job` → second `meta` with `route: fallback`, answer completed on llama-server; `-mute-pongs` → dropped after two missed pongs; queue depth 1 → `queue` event then success, third request `overloaded`; SIGTERM during a stream → worker got `drain`, chat finished, "active chats drained", clean exit.
- All listeners bound to 127.0.0.1; the owner's `llama-server` on 8080 untouched; my gateway, fake workers and `llama-server` 8712 are stopped.

Decisions: ADR 0200 (snapshot datasets, universe, SEC snapshot instead of a live SEC adapter), ADR 0201 (second `meta` on fallback retry, dev-only fallback, `pattern` stripped for llama.cpp, `{{today}}` = UTC `YYYY-MM-DD` and trimmed prompt, caps, egress, privacy, 404 for uncovered symbols, model-view number formatting). Deviations: no live SEC provider (snapshot fundamentals cover it; `SEC_USER_AGENT` reserved); `live`/`vaniras` providers are disabled stubs; Dockerfile uses `distroless/static-debian13` with UID 1000 (not built: Docker absent).

Open issues / risks:
- The base Qwen3-1.7B hallucinates numbers and over-thinks; expected before fine-tuning. Thinking mode easily consumes the 2 048-token budget.
- Sector SPDRs have only ~1.8 years of history; QQQ splices two sources at 2026-09-11 (≈ 0.1 % seam).
- Dataset licenses are as declared by their publishers; all prices derive from Yahoo Finance.
- Proposal for the Director: `contracts/api.md` could document the repeated `meta` on fallback retry and the extra `ok`/`summary`/`error` fields of the internal tool API.

Notes for the next phases:
- p2-train / ml: run a gateway on 8730/8739 with `CANDELA_ADDR=127.0.0.1:8730 CANDELA_INTERNAL_ADDR=127.0.0.1:8739 CANDELA_DB_PATH=services/gateway/data/ml.sqlite` (shared `market.sqlite`); `POST /internal/v1/tools/execute {"name","arguments"}` → `{modelView, uiView, ok, summary, error?}`; get the exact system prompt from `GET /internal/v1/system-prompt?date=YYYY-MM-DD` and tool schemas from `GET /internal/v1/tools`. Copy model views verbatim.
- p2-worker: connect to `ws://127.0.0.1:8719/api/v1/worker/connect` with `CANDELA_WORKER_TOKEN` (`services/gateway/bin/workerctl token -env services/gateway/.env`); `cmd/fakeworker` is a reference client. Error events before the first token make the gateway fall back; tool-call `arguments` may be an object or a JSON string.
- p2-web: expect a second `meta` when a worker fails over; WS needs `Origin` in `CANDELA_ALLOWED_ORIGINS` and subprotocol `candela.chat.v1`.
- p3-deploy: set `CANDELA_ENV=production`, `CANDELA_TRUSTED_PROXY=cloudflare`, a metrics token; fallback stays off in production unless `CANDELA_FALLBACK_ENABLED=true`.

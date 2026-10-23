# Phase 2 · Worker — MLX inference worker (`p2-worker`)

- Area you own: `services/worker/**`, `make/worker.mk`, `docs/status/p2-worker.md`, new ADRs.
- Runs in parallel with `p2-train` (which owns `ml/` and uses the GPU heavily) and `p2-web`.
- Inputs: `CLAUDE.md`, `docs/plan/00-master-plan.md` (model strategy), `contracts/worker-protocol.md`, `contracts/api.md` (event shapes, `TelemetryFrame`), `contracts/tools.json`, the running gateway from `p1-gateway`.

## Goal

A resource-aware Python service that turns the owner's Mac into Candela's GPU node for **Candela Pro** (Gemma 4 12B on Google's QAT int4 weights plus the Candela LoRA adapter, never merged): it loads the model with MLX only when needed, dials out to the gateway over the worker protocol, streams reasoning/answer/tool-call events with optional per-token interpretability telemetry, and also exposes an OpenAI-compatible HTTP API for local work.

## Deliverables

1. uv project `services/worker` (`candela-worker`, Python 3.14, ruff, pyright, `pip-audit` in `worker-check`), Typer CLI: `candela-worker connect` (worker protocol client), `candela-worker serve` (OpenAI-compatible HTTP on `127.0.0.1:8711`), `candela-worker bench` (TTFT, tokens/s, peak memory), `candela-worker doctor`.
2. Model manager: registry read from `ml/configs/models.yaml` (QAT int4 base path, adapter path, chat-template options); lazy load on first job, unload after `CANDELA_WORKER_IDLE_UNLOAD_SEC` (default 900); admission control that declines jobs (the gateway then answers `overloaded` and the web app offers replay) when memory headroom is below the inference budget; MLX memory and cache limits set at start; GPU lease (`contracts/gpu-lease.md`, priority 100) held only while a job runs; KV-cache quantization for long prompts if it measurably saves memory without quality loss (measure and record).
3. Generation: chat template applied with tools and the thinking switch, streaming via mlx-lm with temperature/top-p, stop on EOS or `maxTokens`, reasoning split, robust tool-call parsing for the chosen model family (malformed calls become an `error` event the gateway can surface), `usage` accounting, cancellation within 250 ms, prompt KV-cache reuse across tool rounds of the same conversation (bounded LRU).
4. Telemetry (only when `params.telemetry`): per decoder layer residual-stream L2 norm at the generated position, final-distribution entropy and top-5, logit lens (final norm + LM head) on every 4th layer with top-3, throttled to ≤ 20 frames/s. Implement by wrapping the model's layer modules, not by forking mlx-lm. Measure and report the overhead.
5. Worker protocol client per `contracts/worker-protocol.md`: auth header, `hello` with `ModelInfo`, heartbeats, `status` updates, job execution, `cancel`, `drain` on SIGTERM, reconnect with jittered exponential backoff. Uses `websockets`.
6. OpenAI-compatible HTTP (`fastapi` + `uvicorn`) for development only, bound to 127.0.0.1 and disabled in production (`connect` mode opens no listening socket): `GET /v1/models`, `POST /v1/chat/completions` (stream and non-stream, tools), telemetry in an extra `candela_telemetry` chunk field when requested.
7. `make/worker.mk`: `worker-sync`, `worker-serve`, `worker-connect` (reads `services/worker/.env`: gateway URL, token, model id), `worker-bench`, `worker-check` (ruff format check, ruff lint, pyright).
8. `deploy/worker/` docs and an optional `launchd` plist template for running the worker in the background on login. Do not install it; the owner decides.
9. `services/worker/.env.example`.

## Development model

Develop against the untouched QAT base (`~/models/gemma-4-12b-it-qat-mlx-q4`, read-only) or the `p1-ml` pilot adapter; switch to the v0.1 adapter by configuration when `p2-train` produces it and mention it in your report. For quick iteration you may also use a tiny public MLX model, but the deliverable is verified with Gemma.

## Acceptance (verify by running; no automated tests)

- `make worker-check` passes.
- `candela-worker serve` + `curl` streaming chat with tools works; `bench` prints TTFT, tokens/s and peak memory for the dev model (and for v0.1 if available).
- With the local gateway (`make gateway-run`) and `candela-worker connect`, `/api/v1/status` shows the worker; a chat through the gateway routes to `worker`, runs tool rounds, streams telemetry when requested, and cancels cleanly when the client disconnects; killing the worker mid-request triggers the gateway fallback path.
- After the idle timeout the model unloads and memory drops back (report numbers).
- Report written to `docs/status/p2-worker.md`.

## Out of scope

Training, exporting or publishing models; gateway changes (propose them in your report); tests. Your ADR numbers: 0300–0399. Security constraints from ADR 0008 apply: the `hello` device label is generic ("Apple M5 Pro · 24 GB", never hostname or username), the worker reads only its Python environment, the model and adapter paths, and needs no other file access (it will run inside a Seatbelt sandbox in `p3-deploy`).

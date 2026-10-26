# p2-worker — status

STATUS: done

Summary:
`services/worker` (`candela-worker`: Python 3.14.6, mlx 0.32.4, mlx-lm 0.32.2, websockets 17.3, fastapi 0.161.1, uvicorn 0.54.0) turns the Mac into Candela Pro's GPU node. It has four Typer commands:
- `connect`: the `candela.worker.v1` client. It dials out to the gateway and opens no listening socket.
- `serve`: an OpenAI-compatible API on 127.0.0.1:8711, for development only.
- `bench` and `doctor`.

Main parts:
- **Model manager.** The registry is `services/worker/served-models.yaml` on top of `ml/configs/models.yaml`. The model loads on the first job and unloads when idle. Admission control writes a GPU-lease reservation (priority 100), and the lease exists only while a job waits or runs. MLX memory and cache limits are set.
- **Decode loop.** Built on mlx-lm with chunked prefill and one-step lookahead. It handles reasoning split, Gemma 4 and JSON tool-call parsing, usage accounting, cancel and deadline checks, and a bounded prompt-KV LRU for tool rounds.
- **Telemetry.** Decoder layers are wrapped, not forked from mlx-lm. Each frame carries per-layer residual norms, entropy and top 5, and a logit lens on every 4th layer and the last.
- **Supporting files.** `make/worker.mk`, `deploy/worker/` (guide plus a launchd template, not installed), `.env.example`, ADR 0300.

Gemma items were verified with Gemma 4 12B QAT int4 and the pilot adapter (`candela-pro-pilot`). The bench also ran on the v0.1 interim adapter (`ml/runs/candela-pro-v0.1-lr5e5/adapter`, saved 2026-10-24 during the paused run). Serving the final v0.1 adapter needs no code change: `CANDELA_WORKER_MODEL=candela-pro-v0.1` (default), with `CANDELA_PRO_ADAPTER` if its path differs.

Commits: cb35087 feat(worker): add MLX inference worker with protocol client, HTTP API and telemetry; 8703f66 fix(worker): match Gemma's thought channel as one marker, log cancel latency; 14691c3 feat(worker): report KV-cache size in job stats and bench; 9634a66 docs(worker): add runtime ADR, deploy guide and launchd template; 4682fc5 fix(worker): cancel HTTP streams as soon as the client disconnects; 38bafb1 docs(worker): interim p2-worker status; cdcb4dd perf(worker): cheaper telemetry top-k, suppress multimodal tokens; 7aa2a5d fix(worker): apply the token suppression bias to the logit lens; plus the commit adding this report.

Verified:
- **`make worker-check`**: ruff format check, ruff lint, pyright (0 errors) and pip-audit ("No known vulnerabilities found") all pass. `doctor` reports the versions, "Apple M5 Pro · 24 GB", applegpu_g17s with a 17.8 GB working set, memory headroom, live leases, and the model and adapter paths.
- **`serve` + curl** (dev model `mlx-community/Qwen3-0.6B-4bit@73e3e38d`):
  - Streaming with tools returns `tool_calls` chunks and `finish_reason: tool_calls`.
  - A second round (assistant `tool_calls` with string arguments plus a `tool` message), sent non-streaming with `reasoning` and `candela_telemetry`, returns `reasoning_content`, a grounded answer, usage and 18 frames.
  - In those frames, the logit lens converges across layers 3 → 27, for example "latter → following → … → response".
  - When the client disconnects, the job is cancelled; the GPU stopped 0 ms after the cancel.
- **Gateway + `connect`**: own gateway on 127.0.0.1:8720/8729. The worker connects on the internal listener. The gateway's fallback was pointed at the worker's own `serve` on 8711 for the fallback tests. Results:
  - `/api/v1/status` showed `route: worker` and the worker entry (opaque id, device "Apple M5 Pro · 24 GB").
  - **Gemma 4 12B (pilot), "NVIDIA latest close and 1-year move":** `meta`, then two parallel `tool_call`s (`get_quote`, `get_price_history` with range 1Y), two `tool_result`s, then 204 `token` events with 240 telemetry frames interleaved (48 layers, lens on 12 layers, about 2.9 KB per frame), then `usage` and `done: stop`. The answer quotes the tool numbers ($212.21, +4.4 %, 52-week range, +17.71 %, volatility 37.5 %, max drawdown −20.22 %). Round 2 reused 806 cached tokens and prefilled 736 new ones (prompt 1 542 tokens).
  - **Cancel:** the client disconnected during a reasoning stream. The worker sent `done: cancelled` at once, and the GPU stopped 44 ms later on Gemma (7 ms on the dev model).
  - **Kill before the first token:** SIGKILL during admission wait, and an admission decline (`overloaded`). In both cases the gateway logged "worker failed before the first token; retrying on the fallback", sent a second `meta` with `route: fallback`, and the answer completed.
  - **Kill mid-stream:** the client got an `error` event (`upstream_unavailable`) after partial output.
  - **Gateway restart:** the gateway sent `drain` and closed with 1001. The worker reconnected with full-jitter backoff (0.6 s, 0.56 s, 3.5 s, 5.5 s) and came back `idle`. SIGTERM to the worker: "draining", then a clean exit, with the lease file removed.
- **Bench, Gemma 4 12B QAT + pilot adapter** (192 tokens, greedy):

| Metric | Value |
|---|---|
| Load | 3.1 s |
| Cold TTFT (includes load) | 4.6 s |
| Warm TTFT | 0.51 s |
| Decode | 15.9 tokens/s |
| Prefill, 5 k-token prompt | 326 tokens/s |
| Peak MLX memory, short prompt | 7.45 GB (7.59 GB cold) |
| Peak MLX memory, 5 k prompt | 8.22 GB |
| Telemetry, a frame on every token | 11.2 tokens/s (−30 %), 11 frames/s, identical text |
| 8-bit KV at 5 040 prompt tokens | KV 404 → 365 MB, peak unchanged, 15.3 vs 15.0 tokens/s, identical text |

  The v0.1 interim adapter: load 2.6 s, cold TTFT 3.4 s, warm TTFT 0.50 s, decode 16.4 tokens/s, peak 7.59 GB.
- **Bench, dev model:** decode 164 tokens/s, warm TTFT 42 ms, telemetry overhead 6.4 % at 17 frames/s. 8-bit KV at 7.7 k tokens: KV 868 → 461 MB, peak unchanged, decode −33 %, and greedy output diverged after 71 % of the words.
- **Idle unload, Gemma, 60 s timeout:**
  - MLX active memory 7 182 → 0 MB;
  - process RSS 3 783 → 292 MB;
  - system available memory 8.58 → 13.48 GB.

  Dev model: 459 → 0 MB, available memory +0.9 GB. The bench measured 5.3–5.4 GB available with Gemma loaded and 12.4–13.1 GB after unload.
- **Resource etiquette:**
  - The Gemma run started only when at least 9 GB was available, pressure was normal and no `lab-train` lease was active.
  - Every job wrote `worker.json` as `waiting`, switched to `active` and deleted it on exit. A SIGKILLed worker's stale file was cleaned up.
  - My gateway, worker, serve and wait script are stopped; ports 8711/8720/8729 are free.
  - `~/models`, the trainers and the owner's processes were not touched.

Decisions:
- **ADR 0300 (worker runtime):**
  - Own decode loop on mlx-lm instead of `generate_step`, and one dedicated MLX thread.
  - Admission control with a lease reservation: wait up to 30 s for the inference budget plus 1 GB available (free + inactive + purgeable + speculative, the same measure the Lab guard uses), otherwise `overloaded`.
  - MLX memory limit = inference budget, cache limit 512 MB, no wired limit.
  - Move-semantics prompt-KV LRU (4 entries, 1 GB).
  - 8-bit KV off by default, based on the measurements above.
  - Telemetry by wrapping layers, with one batched lens matmul and repeated argmax instead of argpartition.
  - Gemma's template stops added as stop tokens. The generation config's `suppress_tokens` and multimodal placeholders get a −∞ bias; before that fix an answer contained `<audio|>`.
  - ctypes `host_statistics64`/`sysctlbyname` instead of spawning `vm_stat`/`sysctl`, ready for the Seatbelt sandbox.
- **Deviations from the brief:**
  - The dev model is Qwen3-0.6B, not a tiny Gemma: the smallest MLX Gemma 4 builds are 3.6–4.4 GB. Gemma-specific parsing was checked offline against the real tokenizer and template, then end to end on the 12B.
  - `worker-check` also includes pip-audit (the brief lists it in deliverable 1).
  - Extra targets: `worker-doctor`, `worker-format`.
  - The frame rate is configurable (`CANDELA_WORKER_TELEMETRY_FPS`, default 18, capped at 20).

Open issues / risks:
- **Telemetry overhead on Gemma** was measured before the top-k optimization: −30 % decode with a frame on every token. A microbenchmark shows argpartition took 11–18 ms of the ≈ 26 ms per frame, and repeated argmax takes ≈ 2 ms. The Gemma re-measurement could not run: Candela Pro training resumed (step 282+, about 10.6 GB), and a Gemma job cannot be admitted beside it. Re-run when training is idle: `make worker-bench WORKER_BENCH_ARGS="--model candela-pro-pilot --runs 2 --max-tokens 192"`. The `<audio|>` suppression fix also has no Gemma run yet; it is unit-checked and verified with the dev model.
- **Decode speed is 16 tokens/s on Gemma 12B** with the unmerged rank-16 LoRA on 16 layers and no wired memory. The machine was also busy: about 13 GB of swap, the owner's other projects. A 1 000-token answer takes about a minute.
- **Admission needs about 9 GB available.** While Candela Pro trains (about 10.6 GB), Gemma jobs are declined with `overloaded` after 30 s, because the trainer keeps its memory for 10 minutes before releasing. The gateway then uses its fallback or the web app offers replay. This is by design, but live demos should not overlap training.
- **Prompt-cache reuse on Gemma** works only while the re-rendered prompt extends the cached tokens exactly, because sliding-window caches cannot be trimmed past 1 024 tokens. With thinking on, the next round re-prefills from scratch, since the gateway does not send reasoning back.
- `make worker-*` targets source `services/worker/.env`, which overrides variables already set in the shell.

Notes for the next phases:
- **p3-deploy:**
  - Run `make worker-connect` (or the launchd template) with `CANDELA_ENV=production` and `HF_HUB_OFFLINE=1`.
  - The worker needs read access to `services/worker/.venv` and its Python, `services/worker/served-models.yaml`, `ml/configs/models.yaml`, `~/models/gemma-4-12b-it-qat-mlx-q4` and the adapter directory; write access to `~/.candela/leases/`; and an outbound connection to the gateway's internal port. It spawns no processes and opens no listening socket.
  - SIGTERM drains the worker (up to 150 s); the plist sets `ExitTimeOut` 150.
  - For local fallback tests, the gateway's `CANDELA_FALLBACK_URL` can point at `candela-worker serve` (`http://127.0.0.1:8711/v1`).
- **p2-web / Observatory:** real frames carry 48 layers, `logitLens` for layers 3, 7, …, 47 (top 3) and `topK` (5), about 2.9 KB each, at up to 18 frames/s. On Gemma that means one frame per token, because decode is slower than the frame rate. The Observatory note "record a real telemetry trace for replay" can use `services/worker/runs/gemma-verify/sse-tools.txt` (git-ignored, local) as raw material.
- **Director:**
  - Proposal for `contracts/worker-protocol.md`: document `loadedModelId: ""` when no model is loaded, and that a malformed tool call is reported as `error` `internal`.
  - Proposal for the gateway: forward `reasoning` on assistant tool-call messages, so Gemma can keep its thought block and the prompt cache can extend exactly in thinking mode.

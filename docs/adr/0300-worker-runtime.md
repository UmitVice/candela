# 0300 — Worker runtime: own decode loop, single MLX thread, admission and telemetry

- Status: accepted
- Date: 2026-10-26

## Context

`p2-worker` turns the owner's Mac into the GPU node for Candela Pro: Gemma 4 12B on Google's QAT int4 weights with an unmerged LoRA adapter. The Mac is shared with the owner's own work, with Candela Pro training (lease priority 80) and with Spark pretraining (20), so the worker must load lazily, take memory only when it is available, give the GPU back right after a job, and stop within 250 ms on cancel. The Observatory needs per-token interpretability frames. The production sandbox (ADR 0008) denies process execution.

## Decision

1. **Own decode loop on top of mlx-lm, not `generate_step`.** The loop prefills in chunks of 256 tokens, then decodes with one step of lookahead (`async_eval` of step n+1 before step n is read), like `generate_step`. A custom loop is needed for three reasons:
   - Telemetry must be tied to the forward pass that produced each token. `generate_step` runs prefill calls and the lookahead step in a fixed order, which makes this ambiguous.
   - Cancellation and the job deadline are checked between prefill chunks and between tokens.
   - The prompt cache must record exactly which tokens it has consumed.

   Sampling uses `mlx_lm.sample_utils.make_sampler`, detokenization uses the tokenizer's streaming detokenizer, and tool-call bodies are parsed by `mlx_lm.tool_parsers` (`gemma4`, `json_tools`). mlx-lm itself is unchanged.
2. **One dedicated MLX thread.** Loading, generation and unloading run on a single-thread executor. Heartbeats, cancels and status updates run on the asyncio loop and never wait for the GPU. On `cancel`, the worker sends `done: cancelled` at once and the GPU thread stops at the next token or prefill chunk. Measured: 7 ms with the dev model; Gemma numbers are in `docs/status/p2-worker.md`.
3. **Admission control with a lease reservation.** For each job the worker:
   - writes `worker.json` (priority 100) as `waiting` (gpu-lease v1.1, rules 7–9);
   - waits up to `CANDELA_WORKER_ADMISSION_WAIT_SEC` (30 s) until available memory covers the model's inference budget plus `CANDELA_WORKER_RESERVE_GB` (1 GB), or 1 GB plus the reserve if the model is already resident, with memory pressure not critical. Available memory is free + inactive + purgeable + speculative pages, the same measure the Lab and Spark guards use;
   - switches the lease to `active` and runs the job;
   - deletes the lease when the job ends.

   If memory never comes, the job is declined with `overloaded` before any token. The gateway treats this as retryable and uses its fallback, or reports `overloaded`. The worker never forces memory.
4. **Memory settings.** MLX's memory limit is the model's inference budget (8 GB for Candela Pro), set at load. The buffer cache is capped at 512 MB. There is no wired-memory limit: wiring 7 GB on a shared laptop would make the owner's processes swap first. The model unloads after `CANDELA_WORKER_IDLE_UNLOAD_SEC` (900 s) without jobs, which releases all MLX memory.
5. **Prompt cache.** A bounded LRU (4 entries, 1 GB) of KV caches, keyed by the exact token sequence fed into each one. A job takes the entry with the longest common prefix out of the LRU (no copy). Where the cache type allows, it trims the entry to that prefix. After a clean finish it puts the cache back with prompt + generated tokens. Tool rounds then re-prefill only the tool response; with the dev model, round 2 reused 1 164 of 1 332 prompt tokens.

   Gemma's sliding-window caches cannot be trimmed once a prompt exceeds the 1 024-token window. Reuse therefore needs an exact extension, which tool rounds without thinking are. Otherwise the worker prefills from scratch.
6. **KV-cache quantization is off by default** (`CANDELA_WORKER_KV_BITS=0`). mlx-lm can quantize only full-attention `KVCache` layers; rotating sliding-window caches raise `NotImplementedError`, so the worker quantizes only `KVCache` instances. Measured with the dev model at 7.7 k prompt tokens:
   - steady-state KV shrank from 868 to 461 MB;
   - peak memory did not change, because prefill dominates it;
   - decode was 33 % slower;
   - greedy output diverged after 71 % of the words.

   On Gemma only 8 of 48 layers have full attention, and the gateway caps prompts at about 16 k tokens. The saving does not justify the quality and speed cost (Gemma numbers in the status report). The option stays available for long-context experiments, and ADR 0010's TurboQuant evaluation remains open.
7. **Telemetry by wrapping layers.** `TappedLayer` wraps each decoder layer module, passes attribute access through (Gemma's mask builder reads `layer_type`), and records `h[0, -1]` only on steps chosen for a frame (at most one per 55 ms, so ≤ 20 frames/s with margin for the gateway's own 50 ms throttle). For a chosen step, the MLX graph computes:
   - the L2 norms for every layer;
   - entropy and top 5 of the final log-probabilities;
   - a logit lens on every 4th layer and the last layer. The 12–13 hidden states are stacked, so the lens costs one extra LM-head pass rather than twelve, and the final norm and Gemma's logit soft-cap are applied.

   Everything is evaluated together with the sampled token. Overhead with the dev model: 6.4 % decode tokens/s at 17 frames/s, identical greedy text.
8. **Model registry.** `services/worker/served-models.yaml` maps served ids to a base in `ml/configs/models.yaml` (path, architecture, chat-template stops, inference budget) and an optional adapter path with an env override (`CANDELA_PRO_ADAPTER`). A tiny pinned `mlx-community/Qwen3-0.6B-4bit` exercises the second tool-call format and fast iteration. Gemma 4's generation config lists `<turn|>` and `<|tool_response>` as EOS but its tokenizer does not, so the worker adds the template stops itself.
9. **Reasoning split by text markers.** Gemma's `<|channel>thought` … `<channel|>`, Qwen's `<think>` … `</think>`, and tool-call markers are matched on detokenized text. A tail that could still become a marker is held back. The splitter starts in reasoning mode when the rendered prompt ends inside a thought block (Gemma with thinking after a tool response). An unparsable or unterminated tool call becomes `error` `internal` ("malformed tool call"). Before any token this is retryable at the gateway.
10. **Sandbox readiness.** Memory statistics and the chip name come from `host_statistics64` and `sysctlbyname` through ctypes, so `connect` spawns no process and opens no listening socket. The `hello` device label is the chip and memory size only ("Apple M5 Pro · 24 GB"), and the default worker id is the generic `candela-worker`.

## Consequences

- Telemetry costs a few percent of decode speed only while the Observatory asks for it.
- A job can wait up to 30 s for memory before the gateway falls back, and the gateway's own job deadline (120 s) bounds the whole job.
- The custom loop must follow mlx-lm cache API changes on upgrades (`make_prompt_cache`, `trim_prompt_cache`, `KVCache.to_quantized`).
- `serve` exists only for development and refuses `CANDELA_ENV=production`.

## Alternatives considered

- `mlx_lm.server` or `stream_generate`: no hooks for per-step telemetry or prompt-cache bookkeeping, and an extra HTTP hop for the protocol client.
- Forking mlx-lm's Gemma model to return hidden states: the brief forbids it, and it would break on every mlx-lm update.
- Twelve separate logit-lens matmuls: each one reads the 262 k × 3 840 embedding matrix, so the cost would be close to doubling decode.
- Waiting for memory indefinitely: a chat request would hang. A bounded wait followed by `overloaded` lets the gateway fall back or the web app offer replay.

# candela-worker

MLX inference worker for **Candela Pro** (Gemma 4 12B on Google's QAT int4 weights plus the unmerged Candela LoRA adapter). It dials out to the gateway over `candela.worker.v1`, streams reasoning, answer, tool-call and telemetry events, and serves an OpenAI-compatible API on `127.0.0.1` for local development. Operations: [`deploy/worker/README.md`](../../deploy/worker/README.md). Decisions: ADR 0300.

```text
candela-worker connect   # worker protocol client (production; no listening socket)
candela-worker serve     # OpenAI-compatible HTTP on 127.0.0.1:8711 (development only)
candela-worker bench     # TTFT, tokens/s, peak memory, telemetry overhead, 8-bit KV comparison
candela-worker doctor    # versions, Metal device, memory headroom, leases, model paths
```

## Models

`served-models.yaml` lists the servable ids. Gemma-based entries take their base path, architecture, chat-template stops and inference budget from `ml/configs/models.yaml`:

| id | base | adapter |
|---|---|---|
| `candela-pro-v0.1` (default) | `~/models/gemma-4-12b-it-qat-mlx-q4` (`CANDELA_PRO_BASE`) | `ml/runs/candela-pro-v0.1-lr5e5/adapter` (`CANDELA_PRO_ADAPTER`) |
| `candela-pro-pilot` | same | `ml/runs/pilot-candela-pro/adapter` (`CANDELA_PRO_PILOT_ADAPTER`) |
| `gemma-4-12b-qat-base` | same | none |
| `qwen3-0.6b-dev` | `mlx-community/Qwen3-0.6B-4bit` at a pinned revision | none (fast iteration) |

`CANDELA_WORKER_MODEL` picks the ids announced in `hello`. Switching to a newer adapter only needs `CANDELA_PRO_ADAPTER`.

## HTTP API (development)

- `GET /v1/models`: OpenAI model list; each entry carries the contract `ModelInfo` under `candela`.
- `POST /v1/chat/completions`: `stream` true or false, `tools`, `temperature`, `top_p`, `max_tokens`, `seed`. Extensions: `reasoning` (or `chat_template_kwargs.enable_thinking`) switches thinking on, and `candela_telemetry: true` adds a `candela_telemetry` field (a contract `TelemetryFrame`) to stream chunks, or a list of frames to the non-stream response. Reasoning arrives as `delta.reasoning_content`.

```bash
curl -sN 127.0.0.1:8711/v1/chat/completions -H 'content-type: application/json' -d '{
  "model": "qwen3-0.6b-dev", "stream": true, "candela_telemetry": true,
  "messages": [{"role": "user", "content": "What is the latest close of NVDA?"}],
  "tools": [{"type": "function", "function": {"name": "get_quote", "parameters": {"type": "object",
    "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]}}}]}'
```

## Telemetry

With `params.telemetry`, each decoder layer is wrapped (`telemetry.TappedLayer`; mlx-lm is not forked) and records the residual stream at the generated position. For sampled steps (at most one every 55 ms, so fewer than 20 frames/s), the graph also computes the L2 norm per layer, the entropy and top 5 of the final distribution, and a logit lens (final norm + LM head, including Gemma's logit soft-cap) on every 4th layer and the last layer. All of it is batched into one extra LM-head matmul and evaluated with the sampled token.

# Inference worker protocol — `candela.worker.v1`

The GPU worker (`services/worker`, MLX on the owner's Mac) sits behind NAT and never accepts inbound connections. It dials **out** to the gateway over WebSocket, registers its models and receives generation jobs. The gateway owns queueing, the tool loop and client streaming; the worker is a stateless token generator with an optional prefix KV cache.

## Connection

- `GET wss://<gateway>/api/v1/worker/connect`, subprotocol `candela.worker.v1`, header `Authorization: Bearer $CANDELA_WORKER_TOKEN` (≥ 32 random bytes, base64url). Wrong or missing token → HTTP 401 before upgrade.
- JSON text frames only, one message per frame, max 1 MiB.
- Reconnect with exponential backoff 1 s → 60 s, full jitter. Reset backoff after 60 s of healthy connection.
- Heartbeat: gateway sends `ping` every 15 s; worker answers `pong` within 5 s. Two missed pongs → gateway drops the worker and fails its in-flight job with `upstream_unavailable` (or transparently retries on the fallback if no token was streamed yet).
- Both sides also answer WebSocket control pings; intermediaries (Hugging Face proxy) may close idle sockets, so heartbeats must never pause.

## Messages

Worker → gateway

```jsonc
{ "type": "hello", "protocol": "candela.worker.v1", "workerId": "mbp-m5pro", "version": "0.1.0",
  "device": "Apple M5 Pro · 24 GB", "maxConcurrency": 1,
  "models": [ /* ModelInfo from contracts/api.md, tier 'pro', host 'local-gpu-worker' */ ] }
{ "type": "pong", "ts": 1761228300123 }
{ "type": "status", "state": "idle" | "busy" | "draining", "loadedModelId": "candela-8b-v0.1", "memoryMb": 6120 }
{ "type": "event", "jobId": "j_…", "seq": 1, "event": "reasoning" | "token" | "tool_call" | "telemetry" | "usage" | "done" | "error", "data": { /* same shapes as the SSE events in contracts/api.md */ } }
```

Gateway → worker

```jsonc
{ "type": "welcome", "sessionId": "ws_…", "heartbeatSec": 15 }
{ "type": "ping", "ts": 1761228300123 }
{ "type": "job", "jobId": "j_…", "modelId": "candela-8b-v0.1",
  "messages": [ /* OpenAI chat format: system, user, assistant (with tool_calls), tool (with tool_call_id) */ ],
  "tools": [ /* contracts/tools.json */ ],
  "params": { "temperature": 0.6, "topP": 0.95, "maxTokens": 1024, "reasoning": true, "telemetry": false, "seed": null },
  "deadlineMs": 120000 }
{ "type": "cancel", "jobId": "j_…" }
{ "type": "drain" }   // finish current job, accept no more (deploys, shutdown)
```

## Job semantics

- One job = one model turn. When the model emits tool calls, the worker sends one `tool_call` event per call (`{ id, name, arguments }`), then `done` with `finishReason: "tool_calls"`. The gateway executes the tools and sends a **new** job containing the extended message list. Reuse the KV cache for the shared prefix when possible.
- Reasoning: if the chat template supports thinking, text inside the model's thinking block is streamed as `reasoning`, the rest as `token`. `params.reasoning=false` disables thinking in the template.
- `seq` is per job, starting at 1. The gateway drops duplicates and out-of-order frames.
- `usage` is sent once before `done`: `{ promptTokens, completionTokens, reasoningTokens, timeToFirstTokenMs, tokensPerSecond, totalMs }`.
- On `cancel`, stop within 250 ms and send `done` with `finishReason: "cancelled"`.
- Errors inside a job: `event: "error"`, `data: { code, message }`, then no further frames for that job.

## Local development

The worker also serves an OpenAI-compatible HTTP API (`POST /v1/chat/completions` with `stream: true`, `GET /v1/models`) on `127.0.0.1:${CANDELA_WORKER_HTTP_PORT}` so it can be exercised with curl and used by the gateway through its OpenAI-compatible upstream adapter. Telemetry rides in an extra `candela_telemetry` field on stream chunks when requested.

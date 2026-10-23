# Gateway HTTP API — v1 contract

Single source of truth shared by `apps/web` (client), `services/gateway` (server) and `services/worker`. Changing a shape here is a breaking change: update this file in the same commit as the code, and bump the affected component.

Conventions

- Base path `/api/v1`. JSON bodies, `camelCase` keys, UTF-8.
- Timestamps: ISO 8601 UTC (`2026-10-23T14:05:00Z`). Trading days: `YYYY-MM-DD`.
- Money values are numbers in USD, rounded to 4 decimals at most. Percentages are numbers where `12.5` means 12.5 %.
- Symbols are uppercase US tickers matching `^[A-Z][A-Z0-9.\-]{0,9}$` (class shares use a dot: `BRK.B`).
- Every response carries `X-Request-Id`. Clients may send their own `X-Request-Id` (≤ 64 chars, `[A-Za-z0-9-]`).
- Errors (non-2xx): `{ "error": { "code": ErrorCode, "message": string, "requestId": string, "retryAfterMs"?: number } }`.
- Rate limiting: `429` with `Retry-After` (seconds) and `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset` headers.
- CORS: only origins in `CANDELA_ALLOWED_ORIGINS` (prod Netlify origin, `http://localhost:4200`).

```ts
type ErrorCode =
  | 'invalid_request' | 'not_found' | 'rate_limited' | 'overloaded'
  | 'upstream_unavailable' | 'upstream_timeout' | 'data_unavailable'
  | 'unauthorized' | 'internal';
```

## Shared types

```ts
interface ModelInfo {
  id: string;                    // 'candela-8b-v0.1'
  displayName: string;           // 'Candela 8B'
  tier: 'pro' | 'lite';          // pro = GPU worker, lite = CPU fallback
  version: string;               // 'v0.1'
  baseModel: string;             // Hugging Face id of the base model
  runtime: 'mlx' | 'llama.cpp';
  host: 'local-gpu-worker' | 'cloud-cpu';
  quantization: string;          // '4bit' | 'Q4_K_M'
  contextLength: number;
  supportsReasoning: boolean;
  supportsTools: boolean;
  supportsTelemetry: boolean;
  architecture?: {
    layers: number; hiddenSize: number; attentionHeads: number;
    kvHeads: number; vocabSize: number; parameters: string;   // '8.2B'
  };
}

interface ChatMessage { role: 'user' | 'assistant'; content: string }
```

## GET /api/v1/status

```ts
interface StatusResponse {
  status: 'ok' | 'degraded';
  version: string;               // gateway semver
  commit: string;                // short git sha
  route: 'worker' | 'fallback' | 'unavailable';   // where 'auto' chat goes right now
  models: Array<ModelInfo & { available: boolean }>;
  workers: Array<{ id: string; modelId: string; state: 'idle' | 'busy' | 'draining'; connectedAt: string; device?: string }>;
  queue: { depth: number; maxDepth: number };
  dataProviders: Array<{ id: 'snapshot' | 'live-prices' | 'sec' | 'baseline-forecast' | 'vaniras'; status: 'ok' | 'degraded' | 'disabled'; asOf?: string }>;
  time: string;
}
```

## GET /api/v1/models

`{ models: Array<ModelInfo & { available: boolean }> }`

## POST /api/v1/chat/stream

Request (max body 64 KiB):

```ts
interface ChatRequest {
  conversationId: string;        // client-generated UUID v4
  messages: ChatMessage[];       // visible history, oldest first; 1..40 items; last item role 'user'; each content 1..8000 chars
  model?: 'auto' | string;       // default 'auto' → pro if a worker is online, else lite
  options?: {
    reasoning?: boolean;         // default true; emit 'reasoning' events when the model thinks
    telemetry?: boolean;         // default false; emit 'telemetry' events (Observatory open)
    temperature?: number;        // 0..1.2, default 0.6
    maxTokens?: number;          // 64..2048, default 1024 (answer + reasoning)
  };
}
```

The client never sends system prompts, tool calls or tool results; the gateway owns the system prompt and the tool loop (max 6 tool rounds per request).

Response: `200 text/event-stream`. Each frame has `id: <seq>` (monotonic from 1), `event: <type>`, `data: <json>`. The gateway writes `: keep-alive` comments every 15 s. Closing the HTTP request cancels generation end to end.

| event | data | notes |
|---|---|---|
| `meta` | `{ requestId, conversationId, messageId, model: ModelInfo, route: 'worker' \| 'fallback', createdAt }` | always first |
| `queue` | `{ position: number, etaMs?: number }` | zero or more, before generation starts |
| `reasoning` | `{ delta: string }` | thinking tokens, rendered dimmed and collapsible |
| `token` | `{ delta: string }` | answer tokens (Markdown) |
| `tool_call` | `{ id, name: ToolName, arguments: object }` | model requested a tool |
| `tool_result` | `{ id, name, ok: boolean, durationMs, summary: string, data?: ToolUiData, error?: string }` | see `contracts/tools.md` for `data` |
| `telemetry` | `TelemetryFrame` | only when `options.telemetry` and the model supports it; ≤ 20 frames/s |
| `usage` | `{ promptTokens, completionTokens, reasoningTokens, timeToFirstTokenMs, tokensPerSecond, totalMs }` | once, before `done` |
| `done` | `{ finishReason: 'stop' \| 'length' \| 'tool_limit' \| 'cancelled' }` | terminal |
| `error` | `{ code: ErrorCode, message, retryAfterMs? }` | terminal; may follow partial output |

```ts
interface TelemetryFrame {
  step: number;                                   // generated token index, 0-based
  token: string;                                  // decoded text of the sampled token
  phase: 'reasoning' | 'answer';
  entropy: number;                                // nats, final next-token distribution
  topK: Array<{ token: string; p: number }>;      // final layer, top 5
  layers: Array<{ layer: number; norm: number }>; // residual-stream L2 norm after each decoder layer
  logitLens?: Array<{ layer: number; top: Array<{ token: string; p: number }> }>; // sampled layers, top 3
}
```

## GET /api/v1/chat/ws — WebSocket chat (primary transport in production)

Same request, events and semantics as `/chat/stream`, carried over WebSocket because the production edge (Cloudflare quick tunnel) buffers streamed HTTP responses while WebSocket frames flow in real time (verified 2026-10-23).

- Subprotocol `candela.chat.v1`; `Origin` must be in the CORS allowlist; chat rate limits apply at upgrade time.
- One chat request per connection. Client → server: first frame within 10 s `{ "type": "start", "request": ChatRequest }`; optional `{ "type": "cancel" }`.
- Server → client: `{ "type": "event", "id": <seq>, "event": <name>, "data": { … } }` for each event in the table above; after `done` or `error` the server closes with code 1000. WebSocket pings every 15 s.
- Upgrade-time failures: HTTP 403 (origin), 429 (rate limit, `Retry-After`). Post-upgrade protocol violations close with 1008.

The web client selects the transport from runtime configuration (`chatTransport: "ws" | "sse"`); both share one event model.

## Market data

All market endpoints are cacheable (`Cache-Control: public, max-age=300` for quotes, `3600` otherwise) and return `404 not_found` for unknown symbols, `503 data_unavailable` when the provider fails.

- `GET /api/v1/market/search?q=<1..64>&limit=<1..20>` → `{ results: Array<{ symbol, name, exchange }> }`
- `GET /api/v1/market/{symbol}/quote` → `Quote`
- `GET /api/v1/market/{symbol}/history?range=1M|3M|6M|1Y|2Y|5Y` → `PriceHistory`
- `GET /api/v1/market/{symbol}/indicators?range=6M|1Y|2Y` → `IndicatorSet`
- `GET /api/v1/market/{symbol}/fundamentals?period=annual|quarterly&limit=1..8` → `Fundamentals`
- `GET /api/v1/market/{symbol}/forecast` → `Forecast`

```ts
interface Quote {
  symbol: string; name: string; exchange: string; currency: 'USD';
  asOf: string;                  // trading day of the close
  close: number; previousClose: number; change: number; changePct: number;
  open: number; high: number; low: number; volume: number;
  fiftyTwoWeekHigh: number; fiftyTwoWeekLow: number; avgVolume30d: number;
  source: 'snapshot' | 'live' | 'vaniras'; delayed: boolean;
}

interface Bar { t: string; o: number; h: number; l: number; c: number; v: number }
interface PriceHistory { symbol: string; range: string; interval: '1d'; bars: Bar[]; source: string; asOf: string }

interface IndicatorPoint {
  t: string;
  sma20?: number; sma50?: number; sma200?: number; ema12?: number; ema26?: number;
  rsi14?: number; macd?: number; macdSignal?: number; macdHist?: number;
  bbUpper?: number; bbMiddle?: number; bbLower?: number; atr14?: number;
}
interface Signal { id: string; label: string; tone: 'bullish' | 'bearish' | 'neutral'; detail: string }
interface IndicatorSet { symbol: string; range: string; asOf: string; latest: IndicatorPoint & { close: number }; series: IndicatorPoint[]; signals: Signal[] }

interface FundamentalPeriod {
  fiscalYear: number; fiscalPeriod: 'FY' | 'Q1' | 'Q2' | 'Q3' | 'Q4'; periodEnd: string;
  revenue?: number; grossProfit?: number; operatingIncome?: number; netIncome?: number; epsDiluted?: number;
  operatingCashFlow?: number; capitalExpenditure?: number; freeCashFlow?: number;
  totalAssets?: number; totalLiabilities?: number; cashAndEquivalents?: number; longTermDebt?: number; sharesOutstanding?: number;
}
interface Fundamentals {
  symbol: string; name: string; period: 'annual' | 'quarterly'; currency: 'USD';
  periods: FundamentalPeriod[];  // newest first
  ratios: { grossMarginPct?: number; operatingMarginPct?: number; netMarginPct?: number; fcfMarginPct?: number;
            revenueGrowthPct?: number; epsGrowthPct?: number; debtToAssets?: number };
  source: 'sec' | 'vaniras'; asOf: string;
}

interface Forecast {
  symbol: string; asOf: string; basePrice: number;
  source: 'vaniras' | 'baseline'; method: string;
  horizons: Array<{ months: 3 | 6 | 9 | 12; targetDate: string; p10: number; p50: number; p90: number }>;
  disclaimer: string;
}
```

Indicator definitions (identical in Go and Python): SMA = arithmetic mean of closes; EMA seeded with the SMA of the first N closes, α = 2/(N+1); RSI(14) and ATR(14) use Wilder smoothing; MACD = EMA12 − EMA26, signal = EMA9 of MACD; Bollinger = SMA20 ± 2·population σ; annualized volatility = σ(daily log returns)·√252; max drawdown = min over range of (close / running max − 1).

The `baseline` forecast is a block bootstrap of the last 5 years of daily log returns (20-day blocks, 5 000 paths, fixed seed per symbol and day) and must always be labelled as a statistical baseline, never as a Vaniras forecast.

## POST /api/v1/feedback

`{ conversationId, messageId, rating: 1 | -1, reason?: string (≤ 500), consentToStore: boolean, transcript?: ChatMessage[] }` → `202 { accepted: true }`. `transcript` is stored only when `consentToStore` is true; it feeds future preference tuning.

## Worker and operations

- `GET /api/v1/worker/connect` — WebSocket for inference workers, see `contracts/worker-protocol.md`. Served on the internal listener by default (`CANDELA_WORKER_ON_PUBLIC=false`); expose it publicly only when the worker runs on another machine.
- Internal listener (`CANDELA_INTERNAL_ADDR`, default `127.0.0.1:8719`, never tunnelled): worker connect (by default), `POST /internal/v1/tools/execute`, `/metrics`. Public routes never decide trust from the remote address, because a local tunnel makes every public request arrive from loopback.
- `GET /healthz` — liveness, `200 {"status":"ok"}`.
- `GET /readyz` — readiness (storage open, fallback model reachable or a worker connected).
- `GET /metrics` — Prometheus; requires `Authorization: Bearer $CANDELA_METRICS_TOKEN`.

## Data sources

- `snapshot`: daily OHLCV built offline from a permissively licensed public dataset and shipped to the gateway as a read-only SQLite file; every payload carries its `asOf` date and the UI labels it as a snapshot.
- `live`: optional keyed end-of-day provider, enabled only when its API key is configured.
- `sec`: SEC EDGAR company facts; enabled only when `SEC_USER_AGENT` (name and contact email, required by the SEC) is configured.
- `vaniras`: the owner's Vaniras platform (forecasts, scores, prices); adapter enabled when its data export or API is provided.
- `baseline-forecast`: statistical forecast computed by the gateway from the price series.

Provider precedence for prices: `vaniras` → `live` → `snapshot`. Symbol search uses the Nasdaq Trader symbol directory (`nasdaqlisted.txt`, `otherlisted.txt`).

## Gateway discovery document

The production gateway runs on the owner's Mac behind a Cloudflare quick tunnel whose hostname changes on every start. The tunnel supervisor publishes the current endpoint to a public GitHub Gist (file `candela-endpoint.json`); the web app reads it at startup (CORS-enabled raw URL or the Gists API) and falls back to replay mode when the gateway is offline or unreachable.

```ts
interface EndpointDocument {
  version: 1;
  status: 'online' | 'offline';
  gatewayUrl: string | null;         // 'https://<random>.trycloudflare.com'
  chatTransport: 'ws' | 'sse';
  updatedAt: string;                 // ISO 8601
  heartbeatAt?: string;              // refreshed at most every 10 minutes while online
}
```

## Recorded sessions (replay)

A recorded session is a JSON file `{ version: 1, title, recordedAt, model: ModelInfo, request: ChatRequest, events: Array<{ atMs: number, event: string, data: object }> }` whose events are exactly the stream events above with their relative timestamps. The web app replays them when no live gateway is available, clearly labelled with the model version and recording date. The gateway can record sessions to `services/gateway/data/recordings/` when `CANDELA_RECORD_SESSIONS=true` (owner-only, local).

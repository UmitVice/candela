export type ErrorCode =
  | 'invalid_request'
  | 'not_found'
  | 'rate_limited'
  | 'overloaded'
  | 'upstream_unavailable'
  | 'upstream_timeout'
  | 'data_unavailable'
  | 'unauthorized'
  | 'internal';

export interface ApiErrorBody {
  error: { code: ErrorCode; message: string; requestId: string; retryAfterMs?: number };
}

export interface ModelInfo {
  id: string;
  displayName: string;
  tier: 'pro' | 'lite';
  version: string;
  baseModel: string;
  runtime: 'mlx' | 'llama.cpp';
  host: 'local-gpu-worker' | 'cloud-cpu';
  quantization: string;
  contextLength: number;
  supportsReasoning: boolean;
  supportsTools: boolean;
  supportsTelemetry: boolean;
  architecture?: {
    layers: number;
    hiddenSize: number;
    attentionHeads: number;
    kvHeads: number;
    vocabSize: number;
    parameters: string;
  };
}

export interface ChatMessage {
  role: 'user' | 'assistant';
  content: string;
}

export type DataProviderId = 'snapshot' | 'live-prices' | 'sec' | 'baseline-forecast' | 'vaniras';

export interface StatusResponse {
  status: 'ok' | 'degraded';
  version: string;
  commit: string;
  route: 'worker' | 'fallback' | 'unavailable';
  models: (ModelInfo & { available: boolean })[];
  workers: {
    id: string;
    modelId: string;
    state: 'idle' | 'busy' | 'draining';
    connectedAt: string;
    device?: string;
  }[];
  queue: { depth: number; maxDepth: number };
  dataProviders: { id: DataProviderId; status: 'ok' | 'degraded' | 'disabled'; asOf?: string }[];
  time: string;
}

export type ModelPreference = 'auto' | 'pro' | 'lite';

export interface ChatRequest {
  conversationId: string;
  messages: ChatMessage[];
  model?: string;
  options?: {
    reasoning?: boolean;
    telemetry?: boolean;
    temperature?: number;
    maxTokens?: number;
  };
}

export type ToolName =
  | 'search_symbols'
  | 'get_quote'
  | 'get_price_history'
  | 'get_technical_indicators'
  | 'get_fundamentals'
  | 'get_forecast';

export interface Quote {
  symbol: string;
  name: string;
  exchange: string;
  currency: 'USD';
  asOf: string;
  close: number;
  previousClose: number;
  change: number;
  changePct: number;
  open: number;
  high: number;
  low: number;
  volume: number;
  fiftyTwoWeekHigh: number;
  fiftyTwoWeekLow: number;
  avgVolume30d: number;
  source: 'snapshot' | 'live' | 'vaniras';
  delayed: boolean;
}

export interface Bar {
  t: string;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export interface PriceHistory {
  symbol: string;
  range: string;
  interval: '1d';
  bars: Bar[];
  source: string;
  asOf: string;
}

export interface IndicatorPoint {
  t: string;
  sma20?: number;
  sma50?: number;
  sma200?: number;
  ema12?: number;
  ema26?: number;
  rsi14?: number;
  macd?: number;
  macdSignal?: number;
  macdHist?: number;
  bbUpper?: number;
  bbMiddle?: number;
  bbLower?: number;
  atr14?: number;
}

export interface Signal {
  id: string;
  label: string;
  tone: 'bullish' | 'bearish' | 'neutral';
  detail: string;
}

export interface IndicatorSet {
  symbol: string;
  range: string;
  asOf: string;
  latest: IndicatorPoint & { close: number };
  series: IndicatorPoint[];
  signals: Signal[];
}

export interface FundamentalPeriod {
  fiscalYear: number;
  fiscalPeriod: 'FY' | 'Q1' | 'Q2' | 'Q3' | 'Q4';
  periodEnd: string;
  revenue?: number;
  grossProfit?: number;
  operatingIncome?: number;
  netIncome?: number;
  epsDiluted?: number;
  operatingCashFlow?: number;
  capitalExpenditure?: number;
  freeCashFlow?: number;
  totalAssets?: number;
  totalLiabilities?: number;
  cashAndEquivalents?: number;
  longTermDebt?: number;
  sharesOutstanding?: number;
}

export interface Fundamentals {
  symbol: string;
  name: string;
  period: 'annual' | 'quarterly';
  currency: 'USD';
  periods: FundamentalPeriod[];
  ratios: {
    grossMarginPct?: number;
    operatingMarginPct?: number;
    netMarginPct?: number;
    fcfMarginPct?: number;
    revenueGrowthPct?: number;
    epsGrowthPct?: number;
    debtToAssets?: number;
  };
  source: 'sec' | 'vaniras';
  asOf: string;
}

export interface Forecast {
  symbol: string;
  asOf: string;
  basePrice: number;
  source: 'vaniras' | 'baseline';
  method: string;
  horizons: { months: 3 | 6 | 9 | 12; targetDate: string; p10: number; p50: number; p90: number }[];
  disclaimer: string;
}

export interface SymbolMatch {
  symbol: string;
  name: string;
  exchange: string;
}

export type ToolUiData =
  | { kind: 'symbols'; results: SymbolMatch[] }
  | { kind: 'quote'; quote: Quote }
  | { kind: 'price_history'; history: PriceHistory }
  | { kind: 'indicators'; indicators: IndicatorSet; history: PriceHistory }
  | { kind: 'fundamentals'; fundamentals: Fundamentals }
  | { kind: 'forecast'; forecast: Forecast };

export interface TelemetryFrame {
  step: number;
  token: string;
  phase: 'reasoning' | 'answer';
  entropy: number;
  topK: { token: string; p: number }[];
  layers: { layer: number; norm: number }[];
  logitLens?: { layer: number; top: { token: string; p: number }[] }[];
}

export interface MetaEvent {
  requestId: string;
  conversationId: string;
  messageId: string;
  model: ModelInfo;
  route: 'worker' | 'fallback';
  createdAt: string;
}

export interface ToolCallEvent {
  id: string;
  name: ToolName;
  arguments: Record<string, unknown>;
}

export interface ToolResultEvent {
  id: string;
  name: ToolName;
  ok: boolean;
  durationMs: number;
  summary: string;
  data?: ToolUiData;
  error?: string;
}

export interface UsageEvent {
  promptTokens: number;
  completionTokens: number;
  reasoningTokens: number;
  timeToFirstTokenMs: number;
  tokensPerSecond: number;
  totalMs: number;
}

export type FinishReason = 'stop' | 'length' | 'tool_limit' | 'cancelled';

export interface StreamErrorEvent {
  code: ErrorCode;
  message: string;
  retryAfterMs?: number;
}

export interface StreamEventMap {
  meta: MetaEvent;
  queue: { position: number; etaMs?: number };
  reasoning: { delta: string };
  token: { delta: string };
  tool_call: ToolCallEvent;
  tool_result: ToolResultEvent;
  telemetry: TelemetryFrame;
  usage: UsageEvent;
  done: { finishReason: FinishReason };
  error: StreamErrorEvent;
}

export type StreamEventName = keyof StreamEventMap;

export type ChatStreamEvent = {
  [K in StreamEventName]: { event: K; data: StreamEventMap[K] };
}[StreamEventName];

export const STREAM_EVENT_NAMES: readonly StreamEventName[] = [
  'meta',
  'queue',
  'reasoning',
  'token',
  'tool_call',
  'tool_result',
  'telemetry',
  'usage',
  'done',
  'error',
];

export function isStreamEventName(value: unknown): value is StreamEventName {
  return typeof value === 'string' && (STREAM_EVENT_NAMES as readonly string[]).includes(value);
}

export interface RecordedSession {
  version: 1;
  title: string;
  recordedAt: string;
  model: ModelInfo;
  request: ChatRequest;
  events: { atMs: number; event: StreamEventName; data: object }[];
}

export interface EndpointDocument {
  version: 1;
  status: 'online' | 'offline';
  gatewayUrl: string | null;
  chatTransport: 'ws' | 'sse';
  updatedAt: string;
  heartbeatAt?: string;
}

export interface FeedbackRequest {
  conversationId: string;
  messageId: string;
  rating: 1 | -1;
  reason?: string;
  consentToStore: boolean;
  transcript?: ChatMessage[];
}

import type {
  ChatRequest,
  ErrorCode,
  ModelInfo,
  RecordedSession,
  StreamEventMap,
  StreamEventName,
  ToolName,
  ToolUiData,
} from '../../api/types';

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export function seedFrom(text: string): number {
  let h = 2166136261;
  for (let i = 0; i < text.length; i++) {
    h ^= text.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

export function tokenize(text: string): string[] {
  const pieces = text.match(/\s*[^\s]+|\s+/g) ?? [];
  const tokens: string[] = [];
  for (const piece of pieces) {
    if (piece.trim().length <= 6) {
      tokens.push(piece);
      continue;
    }
    for (let i = 0; i < piece.length; i += 4) tokens.push(piece.slice(i, i + 4));
  }
  return tokens;
}

export interface ToolStep {
  name: ToolName;
  args: Record<string, unknown>;
  ok: boolean;
  summary: string;
  data?: ToolUiData;
  error?: string;
  durationMs: number;
}

/** Produces recorded sessions with realistic pacing (25–40 tok/s with jitter). */
export class SessionBuilder {
  private readonly rand: () => number;
  private readonly events: RecordedSession['events'] = [];
  private t = 0;
  private toolCount = 0;
  private reasoningTokens = 0;
  private answerTokens = 0;
  private firstTokenAt: number | null = null;
  private generationMs = 0;

  constructor(
    private readonly title: string,
    private readonly model: ModelInfo,
    private readonly request: ChatRequest,
    seed: number,
  ) {
    this.rand = mulberry32(seed);
  }

  private push<K extends StreamEventName>(event: K, data: StreamEventMap[K]): void {
    this.events.push({ atMs: Math.round(this.t), event, data });
  }

  private tokenDelay(): number {
    const rate = 25 + this.rand() * 15;
    const hiccup = this.rand() < 0.03 ? 60 + this.rand() * 120 : 0;
    return 1000 / rate + hiccup;
  }

  wait(ms: number): this {
    this.t += ms * (0.85 + this.rand() * 0.3);
    return this;
  }

  meta(messageId: string): this {
    this.t += 140 + this.rand() * 120;
    this.push('meta', {
      requestId: messageId.replace(/-/g, '').slice(0, 24),
      conversationId: this.request.conversationId,
      messageId,
      model: this.model,
      route: 'worker',
      createdAt: new Date().toISOString(),
    });
    return this;
  }

  private stream(kind: 'reasoning' | 'token', text: string): void {
    for (const delta of tokenize(text)) {
      const step = this.tokenDelay();
      this.t += step;
      this.generationMs += step;
      this.firstTokenAt ??= this.t;
      if (kind === 'reasoning') this.reasoningTokens++;
      else this.answerTokens++;
      this.push(kind, { delta });
    }
  }

  reasoning(text: string): this {
    if (this.request.options?.reasoning === false) return this;
    this.t += 180 + this.rand() * 220;
    this.stream('reasoning', text);
    return this;
  }

  tool(step: ToolStep): this {
    const id = `call_${(++this.toolCount).toString().padStart(2, '0')}`;
    this.t += 90 + this.rand() * 120;
    this.push('tool_call', { id, name: step.name, arguments: step.args });
    this.t += step.durationMs;
    this.push('tool_result', {
      id,
      name: step.name,
      ok: step.ok,
      durationMs: step.durationMs,
      summary: step.summary,
      ...(step.data ? { data: step.data } : {}),
      ...(step.error ? { error: step.error } : {}),
    });
    return this;
  }

  answer(text: string): this {
    this.t += 160 + this.rand() * 200;
    this.stream('token', text);
    return this;
  }

  finish(): RecordedSession {
    const completionTokens = this.reasoningTokens + this.answerTokens;
    const promptTokens =
      620 + this.request.messages.reduce((sum, m) => sum + Math.ceil(m.content.length / 4), 0);
    this.t += 40;
    this.push('usage', {
      promptTokens,
      completionTokens,
      reasoningTokens: this.reasoningTokens,
      timeToFirstTokenMs: Math.round(this.firstTokenAt ?? this.t),
      tokensPerSecond:
        this.generationMs > 0
          ? Math.round((completionTokens / (this.generationMs / 1000)) * 10) / 10
          : 0,
      totalMs: Math.round(this.t),
    });
    this.t += 10;
    this.push('done', { finishReason: 'stop' });
    return this.build();
  }

  fail(code: ErrorCode, message: string, retryAfterMs?: number): RecordedSession {
    this.t += 60;
    this.push(
      'error',
      retryAfterMs === undefined ? { code, message } : { code, message, retryAfterMs },
    );
    return this.build();
  }

  private build(): RecordedSession {
    return {
      version: 1,
      title: this.title,
      recordedAt: '2026-10-23T07:30:00Z',
      model: this.model,
      request: this.request,
      events: this.events,
    };
  }
}

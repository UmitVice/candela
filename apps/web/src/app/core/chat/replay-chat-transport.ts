import type { ChatRequest, ChatStreamEvent, ModelInfo, RecordedSession } from '../api/types';
import { uuid } from '../util/ids';
import type { ChatTransport } from './chat-transport';
import { CANCELLED_EVENT, abortableDelay } from './chat-transport';
import { DEMO_PRO_MODEL } from './mock/fixtures/models';
import { rateLimited, scenarioFor } from './mock/fixtures/scenarios';
import { classify } from './mock/intent';
import { toStreamEvent } from './stream-decoding';

const WINDOW_MS = 60_000;
const MAX_REQUESTS_PER_WINDOW = 8;

export class ReplayChatTransport implements ChatTransport {
  readonly kind = 'replay' as const;
  private readonly recent: number[] = [];

  pick(request: ChatRequest): RecordedSession {
    const now = Date.now();
    while (this.recent.length && (this.recent[0] ?? 0) < now - WINDOW_MS) this.recent.shift();
    const model: ModelInfo = DEMO_PRO_MODEL;
    const messageId = uuid();
    if (this.recent.length >= MAX_REQUESTS_PER_WINDOW) {
      const retryAfterMs = Math.max(1000, (this.recent[0] ?? now) + WINDOW_MS - now);
      return rateLimited(request, model, messageId, retryAfterMs);
    }
    this.recent.push(now);
    return scenarioFor(classify(request), request, model, messageId);
  }

  async *stream(request: ChatRequest, signal: AbortSignal): AsyncGenerator<ChatStreamEvent> {
    yield* this.play(this.pick(request), signal);
  }

  async *play(session: RecordedSession, signal: AbortSignal): AsyncGenerator<ChatStreamEvent> {
    const started = performance.now();
    for (const recorded of session.events) {
      const wait = recorded.atMs - (performance.now() - started);
      if (wait > 4 && !(await abortableDelay(wait, signal))) {
        yield CANCELLED_EVENT;
        return;
      }
      if (signal.aborted) {
        yield CANCELLED_EVENT;
        return;
      }
      const event = toStreamEvent(recorded.event, recorded.data);
      if (event) yield event;
    }
  }
}

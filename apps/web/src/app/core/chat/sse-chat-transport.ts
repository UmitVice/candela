import type { ChatRequest, ChatStreamEvent } from '../api/types';
import { requestId } from '../util/ids';
import type { ChatTransport } from './chat-transport';
import { CANCELLED_EVENT, errorEvent, isTerminal } from './chat-transport';
import { SseParser } from './sse-parser';
import { httpErrorEvent, parseJson, toStreamEvent } from './stream-decoding';

export class SseChatTransport implements ChatTransport {
  readonly kind = 'sse' as const;

  constructor(private readonly baseUrl: string) {}

  async *stream(request: ChatRequest, signal: AbortSignal): AsyncGenerator<ChatStreamEvent> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl}/api/v1/chat/stream`, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          accept: 'text/event-stream',
          'x-request-id': requestId(),
        },
        body: JSON.stringify(request),
        cache: 'no-store',
        credentials: 'omit',
        signal,
      });
    } catch {
      yield signal.aborted
        ? CANCELLED_EVENT
        : errorEvent('upstream_unavailable', 'Could not reach the Candela gateway.');
      return;
    }

    if (!response.ok || !response.body) {
      yield await httpErrorEvent(response);
      return;
    }

    const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
    const parser = new SseParser();
    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        for (const frame of parser.push(value)) {
          const event = toStreamEvent(frame.event, parseJson(frame.data));
          if (!event) continue;
          yield event;
          if (isTerminal(event)) return;
        }
      }
    } catch {
      yield signal.aborted
        ? CANCELLED_EVENT
        : errorEvent('upstream_unavailable', 'The stream was interrupted.');
      return;
    } finally {
      reader.cancel().catch(() => undefined);
    }
    yield signal.aborted
      ? CANCELLED_EVENT
      : errorEvent('upstream_unavailable', 'The stream ended before completion.');
  }
}

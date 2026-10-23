import type { ChatRequest, ChatStreamEvent } from '../api/types';
import type { ChatTransport } from './chat-transport';
import { AsyncQueue, CANCELLED_EVENT, errorEvent, isTerminal } from './chat-transport';
import { parseJson, toStreamEvent } from './stream-decoding';

export const CHAT_WS_SUBPROTOCOL = 'candela.chat.v1';

export function websocketUrl(baseUrl: string, path: string): string {
  const url = new URL(path, baseUrl || window.location.origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString();
}

export class WsChatTransport implements ChatTransport {
  readonly kind = 'ws' as const;

  constructor(private readonly baseUrl: string) {}

  async *stream(request: ChatRequest, signal: AbortSignal): AsyncGenerator<ChatStreamEvent> {
    if (signal.aborted) {
      yield CANCELLED_EVENT;
      return;
    }
    const queue = new AsyncQueue<ChatStreamEvent>();
    let socket: WebSocket;
    try {
      socket = new WebSocket(websocketUrl(this.baseUrl, '/api/v1/chat/ws'), CHAT_WS_SUBPROTOCOL);
    } catch {
      yield errorEvent('upstream_unavailable', 'Could not open a WebSocket to the gateway.');
      return;
    }

    let finished = false;
    const finish = (event: ChatStreamEvent) => {
      if (finished) return;
      finished = true;
      queue.push(event);
      queue.end();
    };

    socket.onopen = () => socket.send(JSON.stringify({ type: 'start', request }));
    socket.onmessage = (message: MessageEvent<unknown>) => {
      if (typeof message.data !== 'string') return;
      const frame = parseJson(message.data) as { type?: unknown; event?: unknown; data?: unknown };
      if (frame?.type !== 'event') return;
      const event = toStreamEvent(frame.event, frame.data);
      if (!event) return;
      if (isTerminal(event)) finish(event);
      else if (!finished) queue.push(event);
    };
    socket.onclose = (close) => {
      if (signal.aborted) finish(CANCELLED_EVENT);
      else if (close.code === 1008)
        finish(errorEvent('invalid_request', close.reason || 'The gateway rejected the request.'));
      else
        finish(errorEvent('upstream_unavailable', 'The connection to the gateway closed early.'));
    };

    const onAbort = () => {
      if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'cancel' }));
      finish(CANCELLED_EVENT);
    };
    signal.addEventListener('abort', onAbort, { once: true });

    try {
      yield* queue;
    } finally {
      signal.removeEventListener('abort', onAbort);
      socket.onmessage = null;
      socket.onclose = null;
      if (socket.readyState === WebSocket.CONNECTING || socket.readyState === WebSocket.OPEN) {
        socket.close(1000);
      }
    }
  }
}

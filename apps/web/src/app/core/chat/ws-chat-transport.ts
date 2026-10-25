import type { ChatRequest, ChatStreamEvent } from '../api/types';
import type { ChatTransport } from './chat-transport';
import {
  AsyncQueue,
  CANCELLED_EVENT,
  abortableDelay,
  errorEvent,
  isTerminal,
} from './chat-transport';
import { parseJson, toStreamEvent } from './stream-decoding';

export const CHAT_WS_SUBPROTOCOL = 'candela.chat.v1';
const RECONNECT_DELAY_MS = 600;
const DROPPED = Symbol('dropped');

export function websocketUrl(baseUrl: string, path: string): string {
  const url = new URL(path, baseUrl || window.location.origin);
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:';
  return url.toString();
}

export class WsChatTransport implements ChatTransport {
  readonly kind = 'ws' as const;

  constructor(private readonly baseUrl: string) {}

  // A socket that drops before the first reasoning, token or tool event is reopened once: the
  // gateway has not generated anything billable yet, and quick tunnels occasionally reset.
  async *stream(request: ChatRequest, signal: AbortSignal): AsyncGenerator<ChatStreamEvent> {
    for (let attempt = 0; ; attempt++) {
      let progressed = false;
      let dropped = false;
      for await (const event of this.attempt(request, signal)) {
        if (event === DROPPED) {
          dropped = true;
          break;
        }
        if (event.event === 'reasoning' || event.event === 'token' || event.event === 'tool_call')
          progressed = true;
        yield event;
      }
      if (!dropped) return;
      if (progressed || attempt > 0 || !(await abortableDelay(RECONNECT_DELAY_MS, signal))) {
        yield signal.aborted
          ? CANCELLED_EVENT
          : errorEvent('upstream_unavailable', 'The connection to the gateway closed early.');
        return;
      }
    }
  }

  private async *attempt(
    request: ChatRequest,
    signal: AbortSignal,
  ): AsyncGenerator<ChatStreamEvent | typeof DROPPED> {
    if (signal.aborted) {
      yield CANCELLED_EVENT;
      return;
    }
    const queue = new AsyncQueue<ChatStreamEvent | typeof DROPPED>();
    let socket: WebSocket;
    try {
      socket = new WebSocket(websocketUrl(this.baseUrl, '/api/v1/chat/ws'), CHAT_WS_SUBPROTOCOL);
    } catch {
      yield DROPPED;
      return;
    }

    let finished = false;
    const finish = (event: ChatStreamEvent | typeof DROPPED) => {
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
      else finish(DROPPED);
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

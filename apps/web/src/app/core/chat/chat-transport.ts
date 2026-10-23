import type { ChatRequest, ChatStreamEvent, ErrorCode } from '../api/types';

export type TransportKind = 'ws' | 'sse' | 'replay';

export interface ChatTransport {
  readonly kind: TransportKind;
  stream(request: ChatRequest, signal: AbortSignal): AsyncIterable<ChatStreamEvent>;
}

export function errorEvent(
  code: ErrorCode,
  message: string,
  retryAfterMs?: number,
): ChatStreamEvent {
  return {
    event: 'error',
    data: retryAfterMs === undefined ? { code, message } : { code, message, retryAfterMs },
  };
}

export const CANCELLED_EVENT: ChatStreamEvent = {
  event: 'done',
  data: { finishReason: 'cancelled' },
};

export function isTerminal(event: ChatStreamEvent): boolean {
  return event.event === 'done' || event.event === 'error';
}

export function abortableDelay(ms: number, signal: AbortSignal): Promise<boolean> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve(false);
      return;
    }
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort);
      resolve(true);
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      resolve(false);
    };
    signal.addEventListener('abort', onAbort, { once: true });
  });
}

export class AsyncQueue<T> implements AsyncIterable<T> {
  private readonly items: T[] = [];
  private waiters: ((result: IteratorResult<T>) => void)[] = [];
  private closed = false;

  push(item: T): void {
    if (this.closed) return;
    const waiter = this.waiters.shift();
    if (waiter) waiter({ value: item, done: false });
    else this.items.push(item);
  }

  end(): void {
    if (this.closed) return;
    this.closed = true;
    for (const waiter of this.waiters) waiter({ value: undefined, done: true });
    this.waiters = [];
  }

  [Symbol.asyncIterator](): AsyncIterator<T> {
    return {
      next: () => {
        const item = this.items.shift();
        if (item !== undefined) return Promise.resolve({ value: item, done: false });
        if (this.closed) return Promise.resolve({ value: undefined, done: true });
        return new Promise((resolve) => this.waiters.push(resolve));
      },
      return: () => {
        this.end();
        return Promise.resolve({ value: undefined, done: true });
      },
    };
  }
}

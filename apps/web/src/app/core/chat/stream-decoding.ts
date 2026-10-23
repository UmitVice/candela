import type { ApiErrorBody, ChatStreamEvent, ErrorCode } from '../api/types';
import { isStreamEventName } from '../api/types';
import { errorEvent } from './chat-transport';

const ERROR_CODES: readonly ErrorCode[] = [
  'invalid_request',
  'not_found',
  'rate_limited',
  'overloaded',
  'upstream_unavailable',
  'upstream_timeout',
  'data_unavailable',
  'unauthorized',
  'internal',
];

export function toStreamEvent(name: unknown, data: unknown): ChatStreamEvent | null {
  if (!isStreamEventName(name) || data === null || typeof data !== 'object') return null;
  return { event: name, data } as ChatStreamEvent;
}

export function parseJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

function retryAfterHeaderMs(response: Response): number | undefined {
  const header = response.headers.get('retry-after');
  if (!header) return undefined;
  const seconds = Number(header);
  if (Number.isFinite(seconds)) return Math.max(0, seconds * 1000);
  const date = Date.parse(header);
  return Number.isNaN(date) ? undefined : Math.max(0, date - Date.now());
}

export async function httpErrorEvent(response: Response): Promise<ChatStreamEvent> {
  const body = parseJson(await response.text().catch(() => '')) as Partial<ApiErrorBody> | null;
  const error = body?.error;
  const code: ErrorCode =
    error && ERROR_CODES.includes(error.code)
      ? error.code
      : response.status === 429
        ? 'rate_limited'
        : response.status >= 500
          ? 'upstream_unavailable'
          : 'invalid_request';
  const message =
    typeof error?.message === 'string' ? error.message : `Gateway responded ${response.status}`;
  const retryAfterMs =
    typeof error?.retryAfterMs === 'number' ? error.retryAfterMs : retryAfterHeaderMs(response);
  return errorEvent(code, message, retryAfterMs);
}

import type { ChatStreamEvent } from '../api/types';
import type { AssistantTurn, Segment } from '../state/conversation.model';

function closeReasoning(segments: Segment[], now: number): Segment[] {
  const last = segments[segments.length - 1];
  if (last?.type !== 'reasoning' || last.endedAt !== undefined) return segments;
  return [...segments.slice(0, -1), { ...last, endedAt: now }];
}

function appendText(
  segments: Segment[],
  type: 'reasoning' | 'answer',
  delta: string,
  now: number,
): Segment[] {
  const base = type === 'answer' ? closeReasoning(segments, now) : segments;
  const last = base[base.length - 1];
  if (last?.type === type) {
    return [...base.slice(0, -1), { ...last, text: last.text + delta }];
  }
  return [
    ...base,
    type === 'reasoning' ? { type, text: delta, startedAt: now } : { type, text: delta },
  ];
}

export function applyStreamEvent(
  turn: AssistantTurn,
  event: ChatStreamEvent,
  now = Date.now(),
): AssistantTurn {
  switch (event.event) {
    case 'meta':
      return {
        ...turn,
        status: 'streaming',
        messageId: event.data.messageId,
        model: event.data.model,
        route: event.data.route,
      };
    case 'queue':
      return { ...turn, status: 'queued', queue: event.data };
    case 'reasoning':
      return {
        ...turn,
        status: 'streaming',
        queue: undefined,
        segments: appendText(turn.segments, 'reasoning', event.data.delta, now),
      };
    case 'token':
      return {
        ...turn,
        status: 'streaming',
        queue: undefined,
        segments: appendText(turn.segments, 'answer', event.data.delta, now),
      };
    case 'tool_call':
      return {
        ...turn,
        status: 'streaming',
        segments: [
          ...closeReasoning(turn.segments, now),
          {
            type: 'tool',
            id: event.data.id,
            name: event.data.name,
            args: event.data.arguments,
            status: 'running',
          },
        ],
      };
    case 'tool_result':
      return {
        ...turn,
        segments: turn.segments.map((s) =>
          s.type === 'tool' && s.id === event.data.id
            ? {
                ...s,
                status: event.data.ok ? 'ok' : 'error',
                summary: event.data.summary,
                durationMs: event.data.durationMs,
                ...(event.data.data ? { data: event.data.data } : {}),
                ...(event.data.error ? { error: event.data.error } : {}),
              }
            : s,
        ),
      };
    case 'telemetry':
      return turn;
    case 'usage':
      return { ...turn, usage: event.data };
    case 'done':
      return {
        ...turn,
        status: event.data.finishReason === 'cancelled' ? 'cancelled' : 'done',
        finishReason: event.data.finishReason,
        queue: undefined,
        segments: finalizeSegments(closeReasoning(turn.segments, now)),
      };
    case 'error':
      return {
        ...turn,
        status: 'error',
        queue: undefined,
        error: { ...event.data, at: new Date(now).toISOString() },
        segments: finalizeSegments(closeReasoning(turn.segments, now)),
      };
  }
}

function finalizeSegments(segments: Segment[]): Segment[] {
  return segments.map((s) =>
    s.type === 'tool' && s.status === 'running'
      ? { ...s, status: 'error', summary: 'interrupted' }
      : s,
  );
}

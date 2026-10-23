import type {
  FinishReason,
  ModelInfo,
  StreamErrorEvent,
  ToolName,
  ToolUiData,
  UsageEvent,
} from '../api/types';

export interface ReasoningSegment {
  type: 'reasoning';
  text: string;
  startedAt: number;
  endedAt?: number;
}

export interface ToolSegment {
  type: 'tool';
  id: string;
  name: ToolName;
  args: Record<string, unknown>;
  status: 'running' | 'ok' | 'error';
  summary?: string;
  durationMs?: number;
  data?: ToolUiData;
  error?: string;
}

export interface AnswerSegment {
  type: 'answer';
  text: string;
}

export type Segment = ReasoningSegment | ToolSegment | AnswerSegment;

export type AssistantStatus = 'pending' | 'queued' | 'streaming' | 'done' | 'error' | 'cancelled';

export interface UserTurn {
  kind: 'user';
  id: string;
  content: string;
  command?: string;
  createdAt: string;
}

export interface AssistantTurn {
  kind: 'assistant';
  id: string;
  createdAt: string;
  status: AssistantStatus;
  messageId?: string;
  model?: ModelInfo;
  route?: 'worker' | 'fallback';
  transport?: 'ws' | 'sse' | 'replay';
  queue?: { position: number; etaMs?: number };
  segments: Segment[];
  usage?: UsageEvent;
  finishReason?: FinishReason;
  error?: StreamErrorEvent & { at: string };
  feedback?: 1 | -1;
}

export interface SystemTurn {
  kind: 'system';
  id: string;
  createdAt: string;
  variant: 'help' | 'about' | 'info' | 'warn';
  content: string;
}

export type Turn = UserTurn | AssistantTurn | SystemTurn;

export interface Conversation {
  id: string;
  title: string;
  createdAt: string;
  updatedAt: string;
  turns: Turn[];
}

export function answerText(turn: AssistantTurn): string {
  return turn.segments
    .filter((s): s is AnswerSegment => s.type === 'answer')
    .map((s) => s.text)
    .join('');
}

export function titleFrom(text: string): string {
  const clean = text.replace(/\s+/g, ' ').trim();
  return clean.length > 48 ? `${clean.slice(0, 47)}…` : clean || 'New session';
}

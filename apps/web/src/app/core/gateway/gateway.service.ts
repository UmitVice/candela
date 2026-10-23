import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';
import type { EndpointDocument, StatusResponse } from '../api/types';
import type { ChatTransport } from '../chat/chat-transport';
import { mockMarket } from '../chat/mock/mock-market';
import { ReplayChatTransport } from '../chat/replay-chat-transport';
import { SseChatTransport } from '../chat/sse-chat-transport';
import { WsChatTransport } from '../chat/ws-chat-transport';
import { RUNTIME_CONFIG } from '../config/runtime-config';

export type ConnectionMode = 'live' | 'replay';
export type ConnectionState = 'connecting' | 'online' | 'offline';

export interface Connection {
  mode: ConnectionMode;
  state: ConnectionState;
  baseUrl: string;
  transport: 'ws' | 'sse' | 'replay';
  reason: string;
  checkedAt: string | null;
}

const PROBE_TIMEOUT_MS = 3500;
const RECHECK_MS = 120_000;

async function fetchJson<T>(url: string, timeoutMs: number): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      signal: controller.signal,
      cache: 'no-store',
      credentials: 'omit',
      headers: { accept: 'application/json' },
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return (await response.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

function isEndpointDocument(value: unknown): value is EndpointDocument {
  const doc = value as Partial<EndpointDocument> | null;
  return (
    !!doc &&
    doc.version === 1 &&
    (doc.status === 'online' || doc.status === 'offline') &&
    (doc.gatewayUrl === null || typeof doc.gatewayUrl === 'string')
  );
}

function safeGatewayUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'https:' ? url.origin : null;
  } catch {
    return null;
  }
}

@Injectable({ providedIn: 'root' })
export class GatewayService {
  private readonly config = inject(RUNTIME_CONFIG);
  private readonly replay = new ReplayChatTransport();
  private recheckTimer: ReturnType<typeof setTimeout> | undefined;
  private probing: Promise<void> | null = null;

  readonly connection = signal<Connection>({
    mode: this.config.mode === 'replay' ? 'replay' : 'live',
    state: 'connecting',
    baseUrl: this.config.apiBaseUrl,
    transport: this.config.mode === 'replay' ? 'replay' : this.config.chatTransport,
    reason: '',
    checkedAt: null,
  });
  readonly status = signal<StatusResponse | null>(null);
  readonly ready = signal(false);

  readonly isReplay = computed(() => this.connection().mode === 'replay');
  readonly forcedReplay = this.config.mode === 'replay';
  readonly transport = computed<ChatTransport>(() => {
    const c = this.connection();
    if (c.mode === 'replay') return this.replay;
    return c.transport === 'sse' ? new SseChatTransport(c.baseUrl) : new WsChatTransport(c.baseUrl);
  });
  readonly snapshotAsOf = computed(
    () => this.status()?.dataProviders.find((p) => p.id === 'snapshot')?.asOf ?? null,
  );

  constructor() {
    const onOnline = () => void this.connect();
    window.addEventListener('online', onOnline);
    inject(DestroyRef).onDestroy(() => {
      window.removeEventListener('online', onOnline);
      clearTimeout(this.recheckTimer);
    });
  }

  connect(): Promise<void> {
    this.probing ??= this.runProbe().finally(() => {
      this.probing = null;
      this.ready.set(true);
    });
    return this.probing;
  }

  private async runProbe(): Promise<void> {
    clearTimeout(this.recheckTimer);
    if (this.config.mode === 'replay') {
      this.useReplay('Replay mode is configured for this deployment.');
      return;
    }
    this.connection.update((c) => ({ ...c, state: 'connecting' }));
    let baseUrl = this.config.apiBaseUrl;
    let transport = this.config.chatTransport;
    if (this.config.discoveryUrl) {
      try {
        const doc = await fetchJson<unknown>(this.config.discoveryUrl, PROBE_TIMEOUT_MS);
        if (!isEndpointDocument(doc)) throw new Error('invalid endpoint document');
        const url = safeGatewayUrl(doc.gatewayUrl);
        if (doc.status !== 'online' || !url) {
          this.useReplay('The Candela gateway is offline right now.');
          return;
        }
        baseUrl = url;
        transport = doc.chatTransport === 'sse' ? 'sse' : 'ws';
      } catch {
        if (!baseUrl) {
          this.useReplay('Gateway discovery is unreachable.');
          return;
        }
      }
    }
    try {
      const status = await fetchJson<StatusResponse>(`${baseUrl}/api/v1/status`, PROBE_TIMEOUT_MS);
      if (!status || !Array.isArray(status.models)) throw new Error('invalid status');
      this.status.set(status);
      this.connection.set({
        mode: 'live',
        state: 'online',
        baseUrl,
        transport,
        reason: status.route === 'unavailable' ? 'No model is available behind the gateway.' : '',
        checkedAt: new Date().toISOString(),
      });
    } catch {
      this.useReplay('The Candela gateway did not respond.');
    }
  }

  private useReplay(reason: string): void {
    this.status.set(mockMarket.status());
    this.connection.set({
      mode: 'replay',
      state: this.config.mode === 'replay' ? 'online' : 'offline',
      baseUrl: '',
      transport: 'replay',
      reason,
      checkedAt: new Date().toISOString(),
    });
    if (this.config.mode !== 'replay') {
      this.recheckTimer = setTimeout(() => void this.connect(), RECHECK_MS);
    }
  }

  apiUrl(path: string): string {
    return `${this.connection().baseUrl}${path}`;
  }
}

import { Injectable, inject, signal } from '@angular/core';
import type {
  FeedbackRequest,
  Forecast,
  Fundamentals,
  IndicatorSet,
  PriceHistory,
  Quote,
  SymbolMatch,
} from '../api/types';
import { mockMarket } from '../chat/mock/mock-market';
import { GatewayService } from './gateway.service';

const SYMBOL = /^[A-Z][A-Z0-9.-]{0,9}$/;
const QUOTE_TTL = 300_000;
const DATA_TTL = 3_600_000;
const SEARCH_TTL = 600_000;
const MAX_CACHE = 300;

export type HistoryRange = '1M' | '3M' | '6M' | '1Y' | '2Y' | '5Y';
export type IndicatorRange = '6M' | '1Y' | '2Y';
export const HISTORY_RANGES: readonly HistoryRange[] = ['1M', '3M', '6M', '1Y', '2Y', '5Y'];

export class MarketError extends Error {
  constructor(
    readonly status: number,
    readonly retryAfterMs?: number,
  ) {
    super(`market request failed with ${status}`);
  }
}

interface Entry {
  at: number;
  ttl: number;
  value: Promise<unknown>;
}

function retryAfter(response: Response): number | undefined {
  const seconds = Number(response.headers.get('retry-after'));
  return Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : undefined;
}

@Injectable({ providedIn: 'root' })
export class MarketService {
  private readonly gateway = inject(GatewayService);
  private readonly cache = new Map<string, Entry>();
  private pausedUntil = 0;

  readonly throttledUntil = signal(0);

  quote(symbol: string): Promise<Quote | null> {
    return this.load(symbol, 'quote', '/quote', QUOTE_TTL, (s) => mockMarket.quote(s));
  }

  history(symbol: string, range: HistoryRange): Promise<PriceHistory | null> {
    return this.load(symbol, `history:${range}`, `/history?range=${range}`, DATA_TTL, (s) =>
      mockMarket.history(s, range),
    );
  }

  indicators(symbol: string, range: IndicatorRange): Promise<IndicatorSet | null> {
    return this.load(symbol, `indicators:${range}`, `/indicators?range=${range}`, DATA_TTL, (s) =>
      mockMarket.indicators(s, range),
    );
  }

  fundamentals(symbol: string): Promise<Fundamentals | null> {
    return this.load(symbol, 'fundamentals', '/fundamentals?period=annual&limit=4', DATA_TTL, (s) =>
      mockMarket.fundamentals(s),
    );
  }

  forecast(symbol: string): Promise<Forecast | null> {
    return this.load(symbol, 'forecast', '/forecast', DATA_TTL, (s) => mockMarket.forecast(s));
  }

  async quotes(
    symbols: readonly string[],
  ): Promise<{ quotes: Map<string, Quote | null>; failed: boolean }> {
    let failed = false;
    const entries = await Promise.all(
      symbols.map(async (s) => {
        try {
          return [
            s,
            await this.loadOrThrow(s, 'quote', '/quote', QUOTE_TTL, (q) => mockMarket.quote(q)),
          ] as const;
        } catch {
          failed = true;
          return [s, null] as const;
        }
      }),
    );
    return { quotes: new Map(entries), failed };
  }

  async search(query: string, limit = 8): Promise<SymbolMatch[]> {
    const q = query.trim().slice(0, 64);
    if (!q) return [];
    if (this.gateway.isReplay()) return mockMarket.search(q, limit);
    const key = `search:${q.toLowerCase()}:${limit}`;
    const result = await this.cached(key, SEARCH_TTL, async () => {
      const body = await this.fetchJson<{ results?: SymbolMatch[] }>(
        `/api/v1/market/search?q=${encodeURIComponent(q)}&limit=${limit}`,
      );
      return Array.isArray(body?.results) ? body.results : [];
    }).catch(() => []);
    return result ?? [];
  }

  async feedback(body: FeedbackRequest): Promise<boolean> {
    if (this.gateway.isReplay()) return true;
    try {
      const response = await fetch(this.gateway.apiUrl('/api/v1/feedback'), {
        method: 'POST',
        credentials: 'omit',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(body),
      });
      return response.ok;
    } catch {
      return false;
    }
  }

  private async load<T>(
    symbol: string,
    kind: string,
    suffix: string,
    ttl: number,
    mock: (symbol: string) => T | null,
  ): Promise<T | null> {
    try {
      return await this.loadOrThrow(symbol, kind, suffix, ttl, mock);
    } catch {
      return null;
    }
  }

  private loadOrThrow<T>(
    symbol: string,
    kind: string,
    suffix: string,
    ttl: number,
    mock: (symbol: string) => T | null,
  ): Promise<T | null> {
    const upper = symbol.toUpperCase();
    if (!SYMBOL.test(upper)) return Promise.resolve(null);
    if (this.gateway.isReplay()) return Promise.resolve(mock(upper));
    return this.cached(`${upper}:${kind}`, ttl, () =>
      this.fetchJson<T>(`/api/v1/market/${encodeURIComponent(upper)}${suffix}`),
    );
  }

  private cached<T>(key: string, ttl: number, run: () => Promise<T | null>): Promise<T | null> {
    const fullKey = `${this.gateway.connection().baseUrl}|${key}`;
    const hit = this.cache.get(fullKey);
    if (hit && Date.now() - hit.at < hit.ttl) return hit.value as Promise<T | null>;
    const value = run();
    this.cache.set(fullKey, { at: Date.now(), ttl, value });
    value.catch(() => this.cache.delete(fullKey));
    if (this.cache.size > MAX_CACHE) {
      const oldest = this.cache.keys().next().value;
      if (oldest !== undefined) this.cache.delete(oldest);
    }
    return value;
  }

  // 404 (unknown symbol, no fundamentals for ETFs) is a stable answer and is cached as null;
  // throttling and transport failures throw so the cache entry is dropped and retried later.
  private async fetchJson<T>(path: string): Promise<T | null> {
    if (Date.now() < this.pausedUntil) throw new MarketError(429, this.pausedUntil - Date.now());
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 8000);
    try {
      const response = await fetch(this.gateway.apiUrl(path), {
        credentials: 'omit',
        headers: { accept: 'application/json' },
        signal: controller.signal,
      });
      if (response.ok) return (await response.json()) as T;
      if (response.status === 404) return null;
      const wait = retryAfter(response);
      if (response.status === 429) {
        this.pausedUntil = Date.now() + (wait ?? 10_000);
        this.throttledUntil.set(this.pausedUntil);
      }
      throw new MarketError(response.status, wait);
    } finally {
      clearTimeout(timer);
    }
  }
}

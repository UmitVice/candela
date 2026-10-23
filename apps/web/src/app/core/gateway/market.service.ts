import { Injectable, inject } from '@angular/core';
import type { FeedbackRequest, Quote } from '../api/types';
import { mockMarket } from '../chat/mock/mock-market';
import { GatewayService } from './gateway.service';

const SYMBOL = /^[A-Z][A-Z0-9.-]{0,9}$/;

@Injectable({ providedIn: 'root' })
export class MarketService {
  private readonly gateway = inject(GatewayService);
  private readonly cache = new Map<string, { at: number; quote: Quote | null }>();

  async quote(symbol: string): Promise<Quote | null> {
    const upper = symbol.toUpperCase();
    if (!SYMBOL.test(upper)) return null;
    if (this.gateway.isReplay()) return mockMarket.quote(upper);
    const cached = this.cache.get(upper);
    if (cached && Date.now() - cached.at < 300_000) return cached.quote;
    try {
      const response = await fetch(
        this.gateway.apiUrl(`/api/v1/market/${encodeURIComponent(upper)}/quote`),
        { credentials: 'omit', headers: { accept: 'application/json' } },
      );
      const quote = response.ok ? ((await response.json()) as Quote) : null;
      this.cache.set(upper, { at: Date.now(), quote });
      return quote;
    } catch {
      return null;
    }
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
}

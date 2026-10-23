import { Component, inject, output, resource, signal } from '@angular/core';
import { LucidePlus, LucideX } from '@lucide/angular';
import type { Quote } from '../core/api/types';
import { GatewayService } from '../core/gateway/gateway.service';
import { MarketService } from '../core/gateway/market.service';
import { PreferencesStore } from '../core/state/preferences.store';
import { fmtPct, fmtPrice, toneOf } from '../core/util/format';
import { ShellStateService } from './shell-state.service';

@Component({
  selector: 'cd-watchlist',
  imports: [LucidePlus, LucideX],
  template: `
    <div class="head">
      <h2 class="label">Watchlist</h2>
      <span class="count mono">{{ prefs.watchlist().length }}</span>
    </div>
    <ul class="rows" aria-label="Watchlist">
      @for (symbol of prefs.watchlist(); track symbol) {
        @let q = quoteOf(symbol);
        <li class="row" [class.focused]="shell.focusSymbol() === symbol">
          <button
            type="button"
            class="row-main"
            (click)="pick(symbol)"
            [attr.aria-label]="
              'Analyze ' + symbol + (q ? ', ' + fmtPrice(q.close) + ', ' + fmtPct(q.changePct) : '')
            "
          >
            <span class="sym mono">{{ symbol }}</span>
            <span class="name">{{ q?.name ?? '' }}</span>
            <span class="px mono">{{
              q ? fmtPrice(q.close) : quotes.isLoading() ? '…' : '—'
            }}</span>
            <span class="chg mono" [class]="toneOf(q?.changePct)">{{
              q ? fmtPct(q.changePct) : ''
            }}</span>
          </button>
          <button
            type="button"
            class="remove"
            [attr.aria-label]="'Remove ' + symbol + ' from watchlist'"
            (click)="prefs.unwatch(symbol)"
          >
            <svg lucideX [size]="12"></svg>
          </button>
        </li>
      } @empty {
        <li class="empty">Add a ticker below or type <code>/watch NVDA</code>.</li>
      }
    </ul>
    <form class="add" (submit)="add($event)">
      <label class="sr-only" for="watch-add">Add ticker</label>
      <svg lucidePlus [size]="12" class="add-icon"></svg>
      <input
        id="watch-add"
        class="mono"
        autocomplete="off"
        autocapitalize="characters"
        spellcheck="false"
        maxlength="10"
        placeholder="Add ticker"
        [value]="draft()"
        (input)="draft.set($any($event.target).value)"
      />
    </form>
    @if (error()) {
      <p class="error" role="alert">{{ error() }}</p>
    }
  `,
  styleUrl: './watchlist.css',
})
export class Watchlist {
  protected readonly prefs = inject(PreferencesStore);
  protected readonly shell = inject(ShellStateService);
  private readonly market = inject(MarketService);
  private readonly gateway = inject(GatewayService);

  readonly picked = output<string>();

  protected readonly draft = signal('');
  protected readonly error = signal('');
  protected readonly fmtPrice = fmtPrice;
  protected readonly fmtPct = fmtPct;
  protected readonly toneOf = toneOf;

  protected readonly quotes = resource({
    params: () => ({ symbols: this.prefs.watchlist(), mode: this.gateway.connection().mode }),
    loader: async ({ params }) => {
      const entries = await Promise.all(
        params.symbols.map(async (s) => [s, await this.market.quote(s)] as const),
      );
      return new Map<string, Quote | null>(entries);
    },
  });

  protected quoteOf(symbol: string): Quote | null {
    return this.quotes.hasValue() ? (this.quotes.value().get(symbol) ?? null) : null;
  }

  protected pick(symbol: string): void {
    this.shell.pinnedSymbol.set(symbol);
    this.shell.insert(`/analyze ${symbol}`);
    this.picked.emit(symbol);
  }

  protected add(event: Event): void {
    event.preventDefault();
    const symbol = this.draft().trim().replace(/^\$/, '').toUpperCase();
    if (!/^[A-Z][A-Z0-9.-]{0,9}$/.test(symbol)) {
      this.error.set('Enter a ticker such as NVDA or BRK.B.');
      return;
    }
    this.error.set('');
    this.prefs.watch(symbol);
    this.draft.set('');
  }
}

import { DialogRef } from '@angular/cdk/dialog';
import { Component, computed, inject, resource } from '@angular/core';
import { LucideX } from '@lucide/angular';
import { GatewayService } from '../core/gateway/gateway.service';
import { MarketService } from '../core/gateway/market.service';
import { fmtCompact, fmtPct, fmtPrice, toneOf } from '../core/util/format';
import { ShellStateService } from './shell-state.service';
import { StatusDetails } from './status-details';

@Component({
  selector: 'cd-context-panel',
  imports: [StatusDetails, LucideX],
  templateUrl: './context-panel.html',
  styleUrl: './context-panel.css',
  host: { role: 'complementary', 'aria-label': 'Context' },
})
export class ContextPanel {
  protected readonly shell = inject(ShellStateService);
  private readonly market = inject(MarketService);
  private readonly gateway = inject(GatewayService);
  private readonly dialogRef = inject(DialogRef, { optional: true });
  protected readonly inSheet = !!this.dialogRef;
  protected readonly variant =
    (this.dialogRef?.config.data as { variant?: 'status' } | undefined)?.variant ?? 'context';

  protected readonly fmtPrice = fmtPrice;
  protected readonly fmtPct = fmtPct;
  protected readonly fmtCompact = fmtCompact;
  protected readonly toneOf = toneOf;

  protected readonly quote = resource({
    params: () => ({ symbol: this.shell.focusSymbol(), mode: this.gateway.connection().mode }),
    loader: ({ params }) =>
      params.symbol ? this.market.quote(params.symbol) : Promise.resolve(null),
  });

  protected readonly rangePct = computed(() => {
    const q = this.quote.hasValue() ? this.quote.value() : null;
    if (!q) return 50;
    const span = q.fiftyTwoWeekHigh - q.fiftyTwoWeekLow;
    return span > 0 ? Math.min(100, Math.max(0, ((q.close - q.fiftyTwoWeekLow) / span) * 100)) : 50;
  });

  protected close(): void {
    this.dialogRef?.close();
  }

  protected analyze(symbol: string): void {
    this.shell.insert(`/analyze ${symbol}`);
    this.close();
  }
}

import { Component, computed, input } from '@angular/core';
import type { IndicatorSet, PriceHistory } from '../../core/api/types';
import { fmtNumber, fmtPrice } from '../../core/util/format';
import { IndicatorsChart } from '../charts/indicators-chart';

@Component({
  selector: 'cd-indicators-card',
  imports: [IndicatorsChart],
  template: `
    @let l = indicators().latest;
    <div class="headline">
      <span class="big">{{ indicators().symbol }} · technicals</span>
      <span class="muted">{{ indicators().range }} · as of {{ indicators().asOf }}</span>
    </div>
    <cd-indicators-chart [indicators]="indicators()" [history]="history()" />
    <div class="table-wrap spaced">
      <table>
        <thead>
          <tr>
            <th>Indicator</th>
            <th>Value</th>
            <th>vs close {{ fmtPrice(l.close) }}</th>
          </tr>
        </thead>
        <tbody>
          @for (row of rows(); track row.label) {
            <tr>
              <td>{{ row.label }}</td>
              <td>{{ row.value }}</td>
              <td [class]="row.tone">{{ row.note }}</td>
            </tr>
          }
        </tbody>
      </table>
    </div>
    @if (indicators().signals.length) {
      <div class="chips" role="list" aria-label="Signals">
        @for (s of indicators().signals; track s.id) {
          <span class="chip" role="listitem" [class]="s.tone" [title]="s.detail">
            {{ s.tone === 'bullish' ? '▲' : s.tone === 'bearish' ? '▼' : '◆' }} {{ s.label }}
          </span>
        }
      </div>
    }
  `,
  styleUrl: './cards.css',
  styles: `
    .spaced {
      margin-top: 12px;
    }
  `,
})
export class IndicatorsCard {
  readonly indicators = input.required<IndicatorSet>();
  readonly history = input<PriceHistory>();
  protected readonly fmtPrice = fmtPrice;

  protected readonly rows = computed(() => {
    const l = this.indicators().latest;
    const rel = (v: number | undefined) => {
      if (v === undefined) return { note: '—', tone: '' };
      const d = ((l.close - v) / v) * 100;
      return {
        note: `${d >= 0 ? '▲ above' : '▼ below'} ${Math.abs(d).toFixed(2)}%`,
        tone: d >= 0 ? 'up' : 'down',
      };
    };
    const rsiTone = l.rsi14 === undefined ? '' : l.rsi14 > 70 ? 'down' : l.rsi14 < 30 ? 'up' : '';
    return [
      { label: 'SMA 20', value: fmtPrice(l.sma20), ...rel(l.sma20) },
      { label: 'SMA 50', value: fmtPrice(l.sma50), ...rel(l.sma50) },
      { label: 'SMA 200', value: fmtPrice(l.sma200), ...rel(l.sma200) },
      {
        label: 'EMA 12 / 26',
        value: `${fmtPrice(l.ema12)} / ${fmtPrice(l.ema26)}`,
        note: (l.ema12 ?? 0) >= (l.ema26 ?? 0) ? 'fast above slow' : 'fast below slow',
        tone: '',
      },
      {
        label: 'RSI 14',
        value: fmtNumber(l.rsi14, 1),
        note:
          l.rsi14 === undefined
            ? '—'
            : l.rsi14 > 70
              ? 'overbought'
              : l.rsi14 < 30
                ? 'oversold'
                : 'neutral band',
        tone: rsiTone,
      },
      {
        label: 'MACD / signal',
        value: `${fmtNumber(l.macd)} / ${fmtNumber(l.macdSignal)}`,
        note: `hist ${fmtNumber(l.macdHist)}`,
        tone: (l.macdHist ?? 0) >= 0 ? 'up' : 'down',
      },
      {
        label: 'Bollinger 20,2',
        value: `${fmtPrice(l.bbLower)} – ${fmtPrice(l.bbUpper)}`,
        note: `mid ${fmtPrice(l.bbMiddle)}`,
        tone: '',
      },
      {
        label: 'ATR 14',
        value: fmtNumber(l.atr14),
        note: l.atr14 ? `${((l.atr14 / l.close) * 100).toFixed(2)}% of price` : '—',
        tone: '',
      },
    ];
  });
}

import { Component, computed, input } from '@angular/core';
import type { FundamentalPeriod, Fundamentals } from '../../core/api/types';
import { fmtPct } from '../../core/util/format';

const METRICS: { key: keyof FundamentalPeriod; label: string; kind: 'usd' | 'eps' }[] = [
  { key: 'revenue', label: 'Revenue', kind: 'usd' },
  { key: 'grossProfit', label: 'Gross profit', kind: 'usd' },
  { key: 'operatingIncome', label: 'Operating income', kind: 'usd' },
  { key: 'netIncome', label: 'Net income', kind: 'usd' },
  { key: 'epsDiluted', label: 'EPS (diluted)', kind: 'eps' },
  { key: 'operatingCashFlow', label: 'Operating cash flow', kind: 'usd' },
  { key: 'freeCashFlow', label: 'Free cash flow', kind: 'usd' },
  { key: 'cashAndEquivalents', label: 'Cash', kind: 'usd' },
  { key: 'longTermDebt', label: 'Long-term debt', kind: 'usd' },
  { key: 'totalAssets', label: 'Total assets', kind: 'usd' },
  { key: 'totalLiabilities', label: 'Total liabilities', kind: 'usd' },
];

function money(value: number | string | undefined, kind: 'usd' | 'eps'): string {
  if (typeof value !== 'number') return '—';
  if (kind === 'eps') return value.toFixed(2);
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  return value.toLocaleString('en-US');
}

@Component({
  selector: 'cd-fundamentals-card',
  template: `
    @let f = fundamentals();
    <div class="headline">
      <span class="big">{{ f.symbol }} · fundamentals</span>
      <span class="muted">{{ f.name }} · {{ f.period }} · {{ f.currency }}</span>
    </div>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Metric</th>
            @for (p of f.periods; track p.periodEnd) {
              <th>
                {{
                  p.fiscalPeriod === 'FY'
                    ? 'FY' + p.fiscalYear
                    : p.fiscalPeriod + ' ' + p.fiscalYear
                }}
              </th>
            }
          </tr>
        </thead>
        <tbody>
          @for (row of rows(); track row.label) {
            <tr>
              <td>{{ row.label }}</td>
              @for (v of row.values; track $index) {
                <td>{{ v }}</td>
              }
            </tr>
          }
        </tbody>
      </table>
    </div>
    <div class="chips">
      @for (r of ratios(); track r.label) {
        <span class="chip">{{ r.label }} {{ r.value }}</span>
      }
    </div>
    <div class="note">
      {{ f.source === 'sec' ? 'SEC EDGAR company facts' : f.source }} · as of {{ f.asOf }}
    </div>
  `,
  styleUrl: './cards.css',
})
export class FundamentalsCard {
  readonly fundamentals = input.required<Fundamentals>();

  protected readonly rows = computed(() =>
    METRICS.filter((m) => this.fundamentals().periods.some((p) => p[m.key] !== undefined)).map(
      (m) => ({
        label: m.label,
        values: this.fundamentals().periods.map((p) => money(p[m.key], m.kind)),
      }),
    ),
  );

  protected readonly ratios = computed(() => {
    const r = this.fundamentals().ratios;
    const out: { label: string; value: string }[] = [];
    const pct = (label: string, v: number | undefined) =>
      v !== undefined && out.push({ label, value: `${v.toFixed(2)}%` });
    pct('Gross margin', r.grossMarginPct);
    pct('Op margin', r.operatingMarginPct);
    pct('Net margin', r.netMarginPct);
    pct('FCF margin', r.fcfMarginPct);
    if (r.revenueGrowthPct !== undefined)
      out.push({ label: 'Revenue growth', value: fmtPct(r.revenueGrowthPct) });
    if (r.epsGrowthPct !== undefined)
      out.push({ label: 'EPS growth', value: fmtPct(r.epsGrowthPct) });
    if (r.debtToAssets !== undefined)
      out.push({ label: 'Debt/assets', value: r.debtToAssets.toFixed(3) });
    return out;
  });
}

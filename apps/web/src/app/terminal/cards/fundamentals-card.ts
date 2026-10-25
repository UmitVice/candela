import { Component, computed, input } from '@angular/core';
import type { FundamentalPeriod, Fundamentals } from '../../core/api/types';
import { arrowOf, fmtBig, fmtPct } from '../../core/util/format';

interface Row {
  label: string;
  values: string[];
  tones?: string[];
  highlight?: boolean;
}

function ratio(a: number | undefined, b: number | undefined): number | undefined {
  return a === undefined || b === undefined || b === 0 ? undefined : (a / b) * 100;
}

function pctCell(value: number | undefined, signed: boolean): string {
  if (value === undefined || !Number.isFinite(value)) return '—';
  return signed ? `${arrowOf(value)} ${fmtPct(value)}`.trim() : `${value.toFixed(1)}%`;
}

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
  return kind === 'eps' ? value.toFixed(2) : fmtBig(value);
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
            <tr [class.hl]="row.highlight">
              <td>{{ row.label }}</td>
              @for (v of row.values; track $index) {
                <td [class]="row.tones?.[$index] ?? ''">{{ v }}</td>
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

  protected readonly rows = computed<Row[]>(() => {
    const periods = this.fundamentals().periods;
    const base: Row[] = METRICS.filter((m) => periods.some((p) => p[m.key] !== undefined)).map(
      (m) => ({ label: m.label, values: periods.map((p) => money(p[m.key], m.kind)) }),
    );
    const prior = (p: FundamentalPeriod) =>
      periods.find((q) => q.fiscalPeriod === p.fiscalPeriod && q.fiscalYear === p.fiscalYear - 1);
    const growth = (key: 'revenue' | 'epsDiluted') =>
      periods.map((p) => {
        const before = prior(p)?.[key];
        const now = p[key];
        return now === undefined || before === undefined || before === 0
          ? undefined
          : ((now - before) / Math.abs(before)) * 100;
      });
    const margin = (key: keyof FundamentalPeriod) =>
      periods.map((p) => ratio(p[key] as number | undefined, p.revenue));
    const derived: { label: string; values: (number | undefined)[]; signed: boolean }[] = [
      { label: 'Gross margin', values: margin('grossProfit'), signed: false },
      { label: 'Operating margin', values: margin('operatingIncome'), signed: false },
      { label: 'Net margin', values: margin('netIncome'), signed: false },
      { label: 'FCF margin', values: margin('freeCashFlow'), signed: false },
      { label: 'Revenue growth YoY', values: growth('revenue'), signed: true },
      { label: 'EPS growth YoY', values: growth('epsDiluted'), signed: true },
    ];
    const highlighted = derived
      .filter((d) => d.values.some((v) => v !== undefined))
      .map((d) => ({
        label: d.label,
        highlight: true,
        values: d.values.map((v) => pctCell(v, d.signed)),
        tones: d.values.map((v) => (d.signed && v !== undefined ? (v >= 0 ? 'up' : 'down') : '')),
      }));
    return [...base, ...highlighted];
  });

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
      out.push({ label: 'Revenue growth', value: pctCell(r.revenueGrowthPct, true) });
    if (r.epsGrowthPct !== undefined)
      out.push({ label: 'EPS growth', value: pctCell(r.epsGrowthPct, true) });
    if (r.debtToAssets !== undefined)
      out.push({ label: 'Debt/assets', value: r.debtToAssets.toFixed(3) });
    return out;
  });
}

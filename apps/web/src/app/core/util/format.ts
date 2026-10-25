const usd = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct = new Intl.NumberFormat('en-US', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
  signDisplay: 'exceptZero',
});
const compact = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 2 });
const integer = new Intl.NumberFormat('en-US', { maximumFractionDigits: 0 });

export function fmtPrice(value: number | undefined): string {
  return value === undefined || !Number.isFinite(value) ? '—' : usd.format(value);
}

export function fmtPct(value: number | undefined): string {
  return value === undefined || !Number.isFinite(value) ? '—' : `${pct.format(value)}%`;
}

export function fmtCompact(value: number | undefined): string {
  return value === undefined || !Number.isFinite(value) ? '—' : compact.format(value);
}

export function fmtInt(value: number | undefined): string {
  return value === undefined || !Number.isFinite(value) ? '—' : integer.format(value);
}

export function fmtNumber(value: number | undefined, digits = 2): string {
  return value === undefined || !Number.isFinite(value) ? '—' : value.toFixed(digits);
}

export function fmtDuration(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function fmtClock(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? ''
    : date.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false });
}

export function toneOf(value: number | undefined): 'up' | 'down' | '' {
  if (value === undefined || value === 0) return '';
  return value > 0 ? 'up' : 'down';
}

export function arrowOf(value: number | undefined): '▲' | '▼' | '' {
  if (value === undefined || value === 0 || !Number.isFinite(value)) return '';
  return value > 0 ? '▲' : '▼';
}

export function fmtBig(value: number | undefined): string {
  if (value === undefined || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1e9) return `${(value / 1e9).toFixed(abs >= 1e11 ? 0 : 1)}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
  return integer.format(value);
}

export function compact(n: number): string {
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${(n / 1e9).toFixed(abs >= 1e10 ? 1 : 2)}B`;
  if (abs >= 1e6) return `${(n / 1e6).toFixed(abs >= 1e7 ? 1 : 2)}M`;
  if (abs >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return `${n}`;
}

export function pct(n: number, digits = 1): string {
  return `${(n * 100).toFixed(digits)}%`;
}

export function signed(n: number, digits = 3): string {
  return `${n >= 0 ? '+' : '−'}${Math.abs(n).toFixed(digits)}`;
}

export function shortDate(iso: string | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toISOString().slice(0, 16).replace('T', ' ');
}

import type {
  Bar,
  Forecast,
  IndicatorPoint,
  IndicatorSet,
  PriceHistory,
  Quote,
  Signal,
} from '../../../api/types';
import type { Instrument } from './universe';
import { SNAPSHOT_AS_OF } from './universe';

export type HistoryRange = '1M' | '3M' | '6M' | '1Y' | '2Y';

const RANGE_BARS: Record<HistoryRange, number> = {
  '1M': 21,
  '3M': 63,
  '6M': 126,
  '1Y': 252,
  '2Y': 504,
};
const FULL_BARS = 504 + 200;

function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function gaussian(rand: () => number): number {
  const u = Math.max(rand(), 1e-12);
  const v = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

const round = (value: number, digits = 2) => {
  const f = 10 ** digits;
  return Math.round(value * f) / f;
};

function tradingDays(endIso: string, count: number): string[] {
  const days: string[] = [];
  const date = new Date(`${endIso}T00:00:00Z`);
  while (days.length < count) {
    const dow = date.getUTCDay();
    if (dow !== 0 && dow !== 6) days.push(date.toISOString().slice(0, 10));
    date.setUTCDate(date.getUTCDate() - 1);
  }
  return days.reverse();
}

function bridge(
  rand: () => number,
  from: number,
  to: number,
  steps: number,
  sigma: number,
): number[] {
  const walk = [0];
  for (let i = 1; i <= steps; i++) walk.push((walk[i - 1] ?? 0) + gaussian(rand) * sigma);
  const endNoise = walk[steps] ?? 0;
  const a = Math.log(from);
  const b = Math.log(to);
  return walk.map((w, i) => Math.exp(a + ((b - a) * i) / steps + w - (endNoise * i) / steps));
}

const barCache = new Map<string, Bar[]>();

export function fullBars(inst: Instrument): Bar[] {
  const cached = barCache.get(inst.symbol);
  if (cached) return cached;
  const rand = mulberry32(inst.seed * 7919);
  const sigma = inst.annualVolPct / 100 / Math.sqrt(252);
  const anchors: [number, number][] = [
    [0, inst.closeAgo2Y * 0.92],
    [FULL_BARS - 1 - 504, inst.closeAgo2Y],
    [FULL_BARS - 1 - 252, inst.closeAgo1Y],
    [FULL_BARS - 1 - 126, inst.closeAgo6M],
    [FULL_BARS - 1, inst.close],
  ];
  const closes: number[] = [];
  for (let k = 0; k < anchors.length - 1; k++) {
    const [i0, p0] = anchors[k] ?? [0, inst.close];
    const [i1, p1] = anchors[k + 1] ?? [0, inst.close];
    const segment = bridge(rand, p0, p1, i1 - i0, sigma);
    closes.push(...(k === 0 ? segment : segment.slice(1)));
  }
  const days = tradingDays(SNAPSHOT_AS_OF, FULL_BARS);
  const bars = closes.map((close, i): Bar => {
    const prev = closes[i - 1] ?? close;
    const open = prev * (1 + gaussian(rand) * sigma * 0.25);
    const wick = () => Math.abs(gaussian(rand)) * sigma * 0.45;
    const volume = inst.avgVolume * Math.exp(gaussian(rand) * 0.28 - 0.04);
    return {
      t: days[i] ?? SNAPSHOT_AS_OF,
      o: round(open),
      h: round(Math.max(open, close) * (1 + wick())),
      l: round(Math.min(open, close) * (1 - wick())),
      c: round(close),
      v: Math.round(volume),
    };
  });
  barCache.set(inst.symbol, bars);
  return bars;
}

export function priceHistory(inst: Instrument, range: HistoryRange): PriceHistory {
  return {
    symbol: inst.symbol,
    range,
    interval: '1d',
    bars: fullBars(inst).slice(-RANGE_BARS[range]),
    source: 'snapshot',
    asOf: SNAPSHOT_AS_OF,
  };
}

export function quote(inst: Instrument): Quote {
  const bars = fullBars(inst);
  const last = bars[bars.length - 1];
  const prev = bars[bars.length - 2];
  const year = bars.slice(-252);
  if (!last || !prev) throw new Error(`no bars for ${inst.symbol}`);
  const change = last.c - prev.c;
  return {
    symbol: inst.symbol,
    name: inst.name,
    exchange: inst.exchange,
    currency: 'USD',
    asOf: last.t,
    close: last.c,
    previousClose: prev.c,
    change: round(change),
    changePct: round((change / prev.c) * 100),
    open: last.o,
    high: last.h,
    low: last.l,
    volume: last.v,
    fiftyTwoWeekHigh: round(Math.max(...year.map((b) => b.h))),
    fiftyTwoWeekLow: round(Math.min(...year.map((b) => b.l))),
    avgVolume30d: Math.round(bars.slice(-30).reduce((sum, b) => sum + b.v, 0) / 30),
    source: 'snapshot',
    delayed: true,
  };
}

export interface HistoryStats {
  start: Bar;
  end: Bar;
  returnPct: number;
  high: Bar;
  low: Bar;
  volatilityAnnualizedPct: number;
  maxDrawdownPct: number;
}

export function historyStats(history: PriceHistory): HistoryStats {
  const bars = history.bars;
  const start = bars[0];
  const end = bars[bars.length - 1];
  if (!start || !end) throw new Error('empty history');
  let high = start;
  let low = start;
  let peak = start.c;
  let maxDd = 0;
  const logReturns: number[] = [];
  bars.forEach((bar, i) => {
    if (bar.h > high.h) high = bar;
    if (bar.l < low.l) low = bar;
    peak = Math.max(peak, bar.c);
    maxDd = Math.min(maxDd, bar.c / peak - 1);
    const prev = bars[i - 1];
    if (prev) logReturns.push(Math.log(bar.c / prev.c));
  });
  const mean = logReturns.reduce((s, r) => s + r, 0) / logReturns.length;
  const variance = logReturns.reduce((s, r) => s + (r - mean) ** 2, 0) / logReturns.length;
  return {
    start,
    end,
    returnPct: round((end.c / start.c - 1) * 100),
    high,
    low,
    volatilityAnnualizedPct: round(Math.sqrt(variance) * Math.sqrt(252) * 100, 1),
    maxDrawdownPct: round(maxDd * 100),
  };
}

function sma(values: number[], period: number): (number | undefined)[] {
  let sum = 0;
  return values.map((value, i) => {
    sum += value;
    if (i >= period) sum -= values[i - period] ?? 0;
    return i >= period - 1 ? sum / period : undefined;
  });
}

function ema(values: (number | undefined)[], period: number): (number | undefined)[] {
  const out: (number | undefined)[] = [];
  const alpha = 2 / (period + 1);
  const seedWindow: number[] = [];
  let prev: number | undefined;
  for (const value of values) {
    if (value === undefined) {
      out.push(undefined);
      continue;
    }
    if (prev === undefined) {
      seedWindow.push(value);
      if (seedWindow.length === period) {
        prev = seedWindow.reduce((s, v) => s + v, 0) / period;
        out.push(prev);
      } else out.push(undefined);
      continue;
    }
    prev = alpha * value + (1 - alpha) * prev;
    out.push(prev);
  }
  return out;
}

function wilder(values: number[], period: number, startIndex: number): (number | undefined)[] {
  const out: (number | undefined)[] = values.map(() => undefined);
  let avg: number | undefined;
  for (let i = startIndex; i < values.length; i++) {
    const value = values[i] ?? 0;
    if (avg === undefined) {
      if (i - startIndex + 1 === period) {
        avg = values.slice(startIndex, i + 1).reduce((s, v) => s + v, 0) / period;
        out[i] = avg;
      }
      continue;
    }
    avg = (avg * (period - 1) + value) / period;
    out[i] = avg;
  }
  return out;
}

function computeSeries(bars: Bar[]): IndicatorPoint[] {
  const closes = bars.map((b) => b.c);
  const sma20 = sma(closes, 20);
  const sma50 = sma(closes, 50);
  const sma200 = sma(closes, 200);
  const ema12 = ema(closes, 12);
  const ema26 = ema(closes, 26);
  const macd = closes.map((_, i) => {
    const a = ema12[i];
    const b = ema26[i];
    return a !== undefined && b !== undefined ? a - b : undefined;
  });
  const macdSignal = ema(macd, 9);
  const gains = closes.map((c, i) => (i === 0 ? 0 : Math.max(0, c - (closes[i - 1] ?? c))));
  const losses = closes.map((c, i) => (i === 0 ? 0 : Math.max(0, (closes[i - 1] ?? c) - c)));
  const avgGain = wilder(gains, 14, 1);
  const avgLoss = wilder(losses, 14, 1);
  const trueRange = bars.map((b, i) => {
    const prevClose = bars[i - 1]?.c ?? b.c;
    return Math.max(b.h - b.l, Math.abs(b.h - prevClose), Math.abs(b.l - prevClose));
  });
  const atr = wilder(trueRange, 14, 1);
  return bars.map((bar, i) => {
    const point: IndicatorPoint = { t: bar.t };
    const set = (key: Exclude<keyof IndicatorPoint, 't'>, value: number | undefined) => {
      if (value !== undefined && Number.isFinite(value)) point[key] = round(value);
    };
    set('sma20', sma20[i]);
    set('sma50', sma50[i]);
    set('sma200', sma200[i]);
    set('ema12', ema12[i]);
    set('ema26', ema26[i]);
    set('macd', macd[i]);
    set('macdSignal', macdSignal[i]);
    const m = macd[i];
    const s = macdSignal[i];
    if (m !== undefined && s !== undefined) set('macdHist', m - s);
    const g = avgGain[i];
    const l = avgLoss[i];
    if (g !== undefined && l !== undefined) set('rsi14', l === 0 ? 100 : 100 - 100 / (1 + g / l));
    const mid = sma20[i];
    if (mid !== undefined) {
      const window = closes.slice(i - 19, i + 1);
      const sd = Math.sqrt(window.reduce((sum, c) => sum + (c - mid) ** 2, 0) / 20);
      set('bbUpper', mid + 2 * sd);
      set('bbMiddle', mid);
      set('bbLower', mid - 2 * sd);
    }
    set('atr14', atr[i]);
    return point;
  });
}

function crossIndex(
  series: IndicatorPoint[],
  a: (p: IndicatorPoint) => number | undefined,
  b: (p: IndicatorPoint) => number | undefined,
): { index: number; bullish: boolean } | null {
  for (let i = series.length - 1; i > 0; i--) {
    const cur = series[i];
    const prev = series[i - 1];
    if (!cur || !prev) continue;
    const ca = a(cur);
    const cb = b(cur);
    const pa = a(prev);
    const pb = b(prev);
    if (ca === undefined || cb === undefined || pa === undefined || pb === undefined) return null;
    if (pa <= pb && ca > cb) return { index: i, bullish: true };
    if (pa >= pb && ca < cb) return { index: i, bullish: false };
  }
  return null;
}

function signalsFor(series: IndicatorPoint[], close: number): Signal[] {
  const latest = series[series.length - 1];
  if (!latest) return [];
  const signals: Signal[] = [];
  const push = (id: string, label: string, tone: Signal['tone'], detail: string) =>
    signals.push({ id, label, tone, detail });
  const { rsi14, sma50, sma200, bbUpper, bbLower, atr14 } = latest;
  if (rsi14 !== undefined && rsi14 > 70)
    push('rsi_overbought', 'RSI overbought', 'bearish', `RSI14 ${rsi14.toFixed(1)} is above 70`);
  if (rsi14 !== undefined && rsi14 < 30)
    push('rsi_oversold', 'RSI oversold', 'bullish', `RSI14 ${rsi14.toFixed(1)} is below 30`);
  if (sma50 !== undefined) {
    const diff = ((close - sma50) / sma50) * 100;
    if (close >= sma50)
      push(
        'price_above_sma50',
        'Above SMA50',
        'bullish',
        `Close ${close.toFixed(2)} is ${diff.toFixed(2)}% above SMA50 ${sma50.toFixed(2)}`,
      );
    else
      push(
        'price_below_sma50',
        'Below SMA50',
        'bearish',
        `Close ${close.toFixed(2)} is ${Math.abs(diff).toFixed(2)}% below SMA50 ${sma50.toFixed(2)}`,
      );
  }
  if (sma200 !== undefined) {
    const diff = ((close - sma200) / sma200) * 100;
    if (close >= sma200)
      push(
        'price_above_sma200',
        'Above SMA200',
        'bullish',
        `Close ${close.toFixed(2)} is ${diff.toFixed(2)}% above SMA200 ${sma200.toFixed(2)}`,
      );
    else
      push(
        'price_below_sma200',
        'Below SMA200',
        'bearish',
        `Close ${close.toFixed(2)} is ${Math.abs(diff).toFixed(2)}% below SMA200 ${sma200.toFixed(2)}`,
      );
  }
  const cross = crossIndex(
    series,
    (p) => p.sma50,
    (p) => p.sma200,
  );
  if (cross) {
    const since = series[cross.index]?.t ?? '';
    const recent = series.length - 1 - cross.index <= 20;
    if (cross.bullish)
      push(
        recent ? 'golden_cross_recent' : 'golden_cross_active',
        recent ? 'Golden cross (recent)' : 'Golden cross active',
        'bullish',
        `SMA50 above SMA200 since ${since}`,
      );
    else
      push(
        recent ? 'death_cross_recent' : 'death_cross_active',
        recent ? 'Death cross (recent)' : 'Death cross active',
        'bearish',
        `SMA50 below SMA200 since ${since}`,
      );
  } else if (sma50 !== undefined && sma200 !== undefined) {
    if (sma50 > sma200)
      push(
        'golden_cross_active',
        'Golden cross active',
        'bullish',
        'SMA50 above SMA200 across the whole range',
      );
    else
      push(
        'death_cross_active',
        'Death cross active',
        'bearish',
        'SMA50 below SMA200 across the whole range',
      );
  }
  const macdCross = crossIndex(
    series,
    (p) => p.macd,
    (p) => p.macdSignal,
  );
  if (macdCross && series.length - 1 - macdCross.index <= 5) {
    if (macdCross.bullish)
      push(
        'macd_bullish_cross',
        'MACD bullish cross',
        'bullish',
        'MACD crossed above its signal line in the last 5 sessions',
      );
    else
      push(
        'macd_bearish_cross',
        'MACD bearish cross',
        'bearish',
        'MACD crossed below its signal line in the last 5 sessions',
      );
  }
  if (bbUpper !== undefined && close > bbUpper)
    push(
      'bb_upper_break',
      'Upper band break',
      'neutral',
      `Close above the upper Bollinger Band ${bbUpper.toFixed(2)}`,
    );
  if (bbLower !== undefined && close < bbLower)
    push(
      'bb_lower_break',
      'Lower band break',
      'neutral',
      `Close below the lower Bollinger Band ${bbLower.toFixed(2)}`,
    );
  if (atr14 !== undefined && (atr14 / close) * 100 > 4)
    push(
      'high_volatility',
      'High volatility',
      'neutral',
      `ATR14 is ${((atr14 / close) * 100).toFixed(2)}% of price`,
    );
  return signals;
}

export function indicatorSet(inst: Instrument, range: '6M' | '1Y' | '2Y'): IndicatorSet {
  const bars = fullBars(inst);
  const series = computeSeries(bars);
  const count = RANGE_BARS[range];
  const visible = series.slice(-count);
  const latest = visible[visible.length - 1] ?? { t: SNAPSHOT_AS_OF };
  const close = bars[bars.length - 1]?.c ?? inst.close;
  return {
    symbol: inst.symbol,
    range,
    asOf: SNAPSHOT_AS_OF,
    latest: { ...latest, close },
    series: visible,
    signals: signalsFor(series, close),
  };
}

function addMonths(iso: string, months: number): string {
  const date = new Date(`${iso}T00:00:00Z`);
  date.setUTCMonth(date.getUTCMonth() + months);
  return date.toISOString().slice(0, 10);
}

export function forecast(inst: Instrument): Forecast {
  const base = quote(inst).close;
  const sigma = inst.annualVolPct / 100;
  const mu = inst.forecastDriftPct / 100;
  const z = 1.2816;
  return {
    symbol: inst.symbol,
    asOf: SNAPSHOT_AS_OF,
    basePrice: base,
    source: 'baseline',
    method: 'block bootstrap of 5y daily log returns',
    horizons: ([3, 6, 9, 12] as const).map((months) => {
      const t = months / 12;
      const drift = (mu - (sigma * sigma) / 2) * t;
      const spread = z * sigma * Math.sqrt(t);
      return {
        months,
        targetDate: addMonths(SNAPSHOT_AS_OF, months),
        p10: round(base * Math.exp(drift - spread)),
        p50: round(base * Math.exp(mu * t)),
        p90: round(base * Math.exp(drift + spread)),
      };
    }),
    disclaimer:
      'Statistical baseline from historical returns, not a prediction or investment advice. Ranges are wide by design.',
  };
}

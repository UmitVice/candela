import type { ChatRequest } from '../../api/types';
import { UNIVERSE, findInstrument } from './fixtures/universe';

export type Intent =
  | { kind: 'analysis'; symbol: string }
  | { kind: 'compare'; symbols: string[] }
  | { kind: 'chart'; symbol: string; range: '1M' | '3M' | '6M' | '1Y' | '2Y' }
  | { kind: 'fundamentals'; symbol: string }
  | { kind: 'forecast'; symbol: string }
  | { kind: 'resolve'; query: string; symbol: string; then: 'analysis' }
  | { kind: 'unknown_symbol'; symbol: string }
  | { kind: 'rate_limited' }
  | { kind: 'general' };

const STOPWORDS = new Set([
  'A',
  'I',
  'AI',
  'US',
  'USA',
  'USD',
  'CEO',
  'CFO',
  'EPS',
  'RSI',
  'MACD',
  'SMA',
  'EMA',
  'ATR',
  'ETF',
  'IPO',
  'P',
  'PE',
  'EV',
  'FCF',
  'YOY',
  'QOQ',
  'TTM',
  'OK',
  'IT',
  'AND',
  'OR',
  'THE',
  'VS',
  'FY',
  'Q',
  'GDP',
  'CPI',
  'FED',
  'SEC',
  'LLM',
  'API',
  'PRO',
  'LITE',
  'NOT',
  'IS',
  'TO',
  'IN',
  'ON',
  'OF',
  'ME',
  'MY',
  'DO',
  'AM',
  'BE',
  'BY',
  'AT',
  'IF',
  'SO',
  'UP',
  'NO',
  'WE',
  'HOW',
  'WHY',
  'WHAT',
]);

const RANGE_PATTERN = /\b(1M|3M|6M|1Y|2Y|5Y)\b/i;

export function tickersIn(text: string): string[] {
  const found: string[] = [];
  for (const match of text.matchAll(/\$?\b([A-Z][A-Z0-9]{0,4}(?:\.[A-Z])?)\b/g)) {
    const symbol = match[1] ?? '';
    const explicit = match[0].startsWith('$');
    if (!explicit && STOPWORDS.has(symbol)) continue;
    if (!explicit && !findInstrument(symbol) && symbol.length < 2) continue;
    if (!found.includes(symbol)) found.push(symbol);
  }
  for (const match of text.matchAll(/\b([a-z]{2,5})\b/g)) {
    const symbol = (match[1] ?? '').toUpperCase();
    if (findInstrument(symbol) && !found.includes(symbol)) found.push(symbol);
  }
  return found;
}

function companyIn(text: string): { query: string; symbol: string } | null {
  const lower = text.toLowerCase();
  for (const inst of UNIVERSE) {
    for (const alias of inst.aliases) {
      if (new RegExp(`\\b${alias.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\b`).test(lower)) {
        return { query: alias, symbol: inst.symbol };
      }
    }
  }
  return null;
}

function lastMentionedSymbol(request: ChatRequest): string | null {
  for (let i = request.messages.length - 2; i >= 0; i--) {
    const message = request.messages[i];
    if (!message) continue;
    const known = tickersIn(message.content).find((s) => findInstrument(s));
    if (known) return known;
    const company = companyIn(message.content);
    if (company) return company.symbol;
  }
  return null;
}

export function classify(request: ChatRequest): Intent {
  const text = request.messages[request.messages.length - 1]?.content ?? '';
  const lower = text.toLowerCase();
  if (/\brate[- ]?limit/.test(lower)) return { kind: 'rate_limited' };

  const tickers = tickersIn(text);
  const known = tickers.filter((s) => findInstrument(s));
  const unknown = tickers.filter((s) => !findInstrument(s) && s.length >= 2);
  const company = known.length === 0 ? companyIn(text) : null;
  const contextual =
    known.length === 0 && !company && unknown.length === 0 ? lastMentionedSymbol(request) : null;
  const primary = known[0] ?? company?.symbol ?? contextual;

  if (known.length >= 2) {
    return { kind: 'compare', symbols: known.slice(0, 3) };
  }
  if (!primary && unknown[0]) return { kind: 'unknown_symbol', symbol: unknown[0] };
  if (!primary) return { kind: 'general' };

  if (/^\s*(analy[sz]e|analysis|full read)\b/.test(lower)) {
    return company && known.length === 0
      ? { kind: 'resolve', query: company.query, symbol: company.symbol, then: 'analysis' }
      : { kind: 'analysis', symbol: primary };
  }
  if (
    /\b(fundamental|revenue|margin|earnings|income|balance sheet|cash flow|eps|10-k|filing)/.test(
      lower,
    )
  ) {
    return { kind: 'fundamentals', symbol: primary };
  }
  if (
    /\b(forecast|outlook|target|predict|projection|p50|p10|p90|next (year|12 months))/.test(lower)
  ) {
    return { kind: 'forecast', symbol: primary };
  }
  if (/\b(chart|history|price action|performance|trend|plot)\b/.test(lower)) {
    const range = (RANGE_PATTERN.exec(text)?.[1]?.toUpperCase() ?? '6M') as
      '1M' | '3M' | '6M' | '1Y' | '2Y' | '5Y';
    return { kind: 'chart', symbol: primary, range: range === '5Y' ? '2Y' : range };
  }
  if (company && known.length === 0) {
    return { kind: 'resolve', query: company.query, symbol: company.symbol, then: 'analysis' };
  }
  return { kind: 'analysis', symbol: primary };
}

export function asksForPersonalAdvice(request: ChatRequest): boolean {
  const text = request.messages[request.messages.length - 1]?.content.toLowerCase() ?? '';
  return /\b(should i (buy|sell|hold|invest)|is it a good (buy|investment)|my portfolio|all in)\b/.test(
    text,
  );
}

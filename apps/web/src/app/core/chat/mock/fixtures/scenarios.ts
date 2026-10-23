import type { ChatRequest, ModelInfo, RecordedSession } from '../../../api/types';
import { fmtCompact, fmtPct, fmtPrice } from '../../../util/format';
import type { Intent } from '../intent';
import { asksForPersonalAdvice } from '../intent';
import type { ToolStep } from '../session-builder';
import { SessionBuilder, seedFrom } from '../session-builder';
import type { HistoryRange } from './market-data';
import { forecast, historyStats, indicatorSet, priceHistory, quote } from './market-data';
import type { Instrument } from './universe';
import {
  FUNDAMENTALS,
  SNAPSHOT_AS_OF,
  UNIVERSE,
  findInstrument,
  searchInstruments,
} from './universe';

const DISCLAIMER = `*Illustrative replay data as of ${SNAPSHOT_AS_OF} (delayed snapshot). Not financial advice.*`;

const ADVICE_PREFACE =
  "I can't tell you whether to buy or sell. That depends on your goals, horizon and risk tolerance, which only you or a licensed adviser can weigh. What I can do is lay out what the data shows.\n\n";

const money = (v: number) => `$${fmtPrice(v)}`;

function quoteStep(inst: Instrument): ToolStep {
  const q = quote(inst);
  return {
    name: 'get_quote',
    args: { symbol: inst.symbol },
    ok: true,
    summary: `${money(q.close)} · ${fmtPct(q.changePct)}`,
    data: { kind: 'quote', quote: q },
    durationMs: 18 + (inst.seed % 17),
  };
}

function historyStep(inst: Instrument, range: HistoryRange): ToolStep {
  const history = priceHistory(inst, range);
  const stats = historyStats(history);
  return {
    name: 'get_price_history',
    args: { symbol: inst.symbol, range },
    ok: true,
    summary: `${history.bars.length} bars · ${fmtPct(stats.returnPct)}`,
    data: { kind: 'price_history', history },
    durationMs: 34 + (inst.seed % 23),
  };
}

function indicatorStep(inst: Instrument): ToolStep {
  const indicators = indicatorSet(inst, '6M');
  const history = priceHistory(inst, '6M');
  return {
    name: 'get_technical_indicators',
    args: { symbol: inst.symbol, range: '6M' },
    ok: true,
    summary: `RSI ${indicators.latest.rsi14?.toFixed(1) ?? '—'} · ${indicators.signals.length} signals`,
    data: { kind: 'indicators', indicators, history },
    durationMs: 51 + (inst.seed % 29),
  };
}

function forecastStep(inst: Instrument): ToolStep {
  const f = forecast(inst);
  const h12 = f.horizons[3];
  return {
    name: 'get_forecast',
    args: { symbol: inst.symbol },
    ok: true,
    summary: `12M P50 ${h12 ? money(h12.p50) : '—'} · baseline`,
    data: { kind: 'forecast', forecast: f },
    durationMs: 88 + (inst.seed % 41),
  };
}

function rsiRead(rsi: number | undefined): string {
  if (rsi === undefined) return 'n/a';
  if (rsi > 70) return 'overbought';
  if (rsi < 30) return 'oversold';
  if (rsi >= 55) return 'firm momentum';
  if (rsi <= 45) return 'soft momentum';
  return 'neutral';
}

function rangePosition(q: ReturnType<typeof quote>): number {
  const span = q.fiftyTwoWeekHigh - q.fiftyTwoWeekLow;
  return span > 0 ? Math.round(((q.close - q.fiftyTwoWeekLow) / span) * 100) : 50;
}

function builder(title: string, request: ChatRequest, model: ModelInfo, messageId: string) {
  const last = request.messages[request.messages.length - 1]?.content ?? '';
  return new SessionBuilder(title, model, request, seedFrom(`${title}|${last}`)).meta(messageId);
}

function analysisBody(inst: Instrument): string {
  const q = quote(inst);
  const stats = historyStats(priceHistory(inst, '6M'));
  const ind = indicatorSet(inst, '6M');
  const f = forecast(inst);
  const l = ind.latest;
  const h12 = f.horizons[3];
  const fromHigh = ((q.close / q.fiftyTwoWeekHigh - 1) * 100).toFixed(1);
  const above50 = l.sma50 !== undefined && q.close >= l.sma50;
  const above200 = l.sma200 !== undefined && q.close >= l.sma200;
  const trend =
    above50 && above200
      ? 'The primary trend is up: price sits above both the 50- and 200-day averages.'
      : !above50 && above200
        ? 'The longer-term trend is intact (above the 200-day), but price has slipped under the 50-day, so the near-term picture is a pullback inside an uptrend.'
        : above50 && !above200
          ? 'Price has reclaimed the 50-day average but remains below the 200-day, so this is a recovery attempt rather than an established uptrend.'
          : 'Price is below both the 50- and 200-day averages, which describes a downtrend until proven otherwise.';
  const signalLines = ind.signals.map(
    (s) => `- ${s.tone === 'bullish' ? '▲' : s.tone === 'bearish' ? '▼' : '◆'} ${s.detail}`,
  );
  return [
    `**${inst.name} (${inst.symbol})** closed at **${money(q.close)}** on ${q.asOf} (${fmtPct(q.changePct)} on the day), ${Math.abs(Number(fromHigh))}% below its 52-week high of ${money(q.fiftyTwoWeekHigh)}.`,
    '',
    '### Price action · 6M',
    `- Return **${fmtPct(stats.returnPct)}**, from ${money(stats.start.c)} to ${money(stats.end.c)}`,
    `- Range ${money(stats.low.l)} (${stats.low.t}) to ${money(stats.high.h)} (${stats.high.t})`,
    `- Annualized volatility **${stats.volatilityAnnualizedPct}%**, max drawdown **${fmtPct(stats.maxDrawdownPct)}**`,
    '',
    '### Technicals',
    '| Indicator | Value | Read |',
    '|---|---:|---|',
    `| SMA20 / 50 / 200 | ${fmtPrice(l.sma20)} / ${fmtPrice(l.sma50)} / ${fmtPrice(l.sma200)} | ${above50 ? 'above' : 'below'} 50d, ${above200 ? 'above' : 'below'} 200d |`,
    `| RSI14 | ${l.rsi14?.toFixed(1) ?? '—'} | ${rsiRead(l.rsi14)} |`,
    `| MACD / signal | ${l.macd?.toFixed(2) ?? '—'} / ${l.macdSignal?.toFixed(2) ?? '—'} | ${(l.macdHist ?? 0) >= 0 ? 'positive' : 'negative'} histogram |`,
    `| ATR14 | ${l.atr14?.toFixed(2) ?? '—'} | ${l.atr14 ? ((l.atr14 / q.close) * 100).toFixed(2) : '—'}% of price per day |`,
    '',
    ...(signalLines.length ? ['Rule-based signals:', ...signalLines, ''] : []),
    '### Baseline forecast · 12M',
    h12
      ? `P10 **${money(h12.p10)}** · P50 **${money(h12.p50)}** · P90 **${money(h12.p90)}** (${f.method}). The width of that band is the main message: a statistical baseline says little about direction.`
      : 'No forecast available.',
    '',
    '### Bottom line',
    `${trend} With ${stats.volatilityAnnualizedPct}% annualized volatility, a ${Math.abs(stats.maxDrawdownPct)}% drawdown already happened inside six months, so position sizing matters more than precision on entry. Watch the 50-day (${fmtPrice(l.sma50)}) as the first line that decides whether momentum resumes.`,
    '',
    DISCLAIMER,
  ].join('\n');
}

function analysis(
  inst: Instrument,
  request: ChatRequest,
  model: ModelInfo,
  id: string,
): RecordedSession {
  const advice = asksForPersonalAdvice(request);
  return builder(`Single-stock analysis · ${inst.symbol}`, request, model, id)
    .reasoning(
      `The user wants an analysis of ${inst.symbol}. ${advice ? 'They are also asking for a personal buy/sell call, which I must not give; I will stay descriptive. ' : ''}I need the latest quote, a 6-month price history for trend and drawdown, the technical indicators for momentum, and the baseline forecast for the range of outcomes. Every number in the answer must come from these tool results.`,
    )
    .tool(quoteStep(inst))
    .tool(historyStep(inst, '6M'))
    .tool(indicatorStep(inst))
    .tool(forecastStep(inst))
    .reasoning(
      `Close is ${quote(inst).close}. I will summarise price action, technicals and the forecast band, then give a balanced bottom line with the main risk.`,
    )
    .answer((advice ? ADVICE_PREFACE : '') + analysisBody(inst))
    .finish();
}

function compare(
  insts: Instrument[],
  request: ChatRequest,
  model: ModelInfo,
  id: string,
): RecordedSession {
  const b = builder(
    `Comparison · ${insts.map((i) => i.symbol).join(' vs ')}`,
    request,
    model,
    id,
  ).reasoning(
    `Comparing ${insts.map((i) => i.symbol).join(' and ')}. I need a quote and a 1-year history for each so the return, volatility and drawdown are measured over the same window.`,
  );
  for (const inst of insts) b.tool(quoteStep(inst));
  for (const inst of insts) b.tool(historyStep(inst, '1Y'));
  const rows = insts.map((inst) => {
    const q = quote(inst);
    const s = historyStats(priceHistory(inst, '1Y'));
    return { inst, q, s, pos: rangePosition(q) };
  });
  const header = `| Metric | ${rows.map((r) => r.inst.symbol).join(' | ')} |`;
  const align = `|---|${rows.map(() => '---:').join('|')}|`;
  const line = (label: string, f: (r: (typeof rows)[number]) => string) =>
    `| ${label} | ${rows.map(f).join(' | ')} |`;
  const best = [...rows].sort((a, z) => z.s.returnPct - a.s.returnPct)[0];
  const calm = [...rows].sort(
    (a, z) => a.s.volatilityAnnualizedPct - z.s.volatilityAnnualizedPct,
  )[0];
  const answer = [
    `Here is how ${rows.map((r) => `**${r.inst.symbol}**`).join(' and ')} compare over the last year.`,
    '',
    header,
    align,
    line('Close', (r) => money(r.q.close)),
    line('Day', (r) => fmtPct(r.q.changePct)),
    line('1Y return', (r) => fmtPct(r.s.returnPct)),
    line('Volatility (ann.)', (r) => `${r.s.volatilityAnnualizedPct}%`),
    line('Max drawdown', (r) => fmtPct(r.s.maxDrawdownPct)),
    line('52W range position', (r) => `${r.pos}%`),
    line('Avg volume 30d', (r) => fmtCompact(r.q.avgVolume30d)),
    '',
    best && calm
      ? `**${best.inst.symbol}** delivered the stronger 1-year return (${fmtPct(best.s.returnPct)}), while **${calm.inst.symbol}** did it with the lower volatility (${calm.s.volatilityAnnualizedPct}%). ${best.inst.symbol === calm.inst.symbol ? 'Leading on both counts is unusual; check whether the gap comes from one event before extrapolating it.' : 'Return per unit of risk is closer than the headline returns suggest.'}`
      : '',
    '',
    'Different business mixes mean these numbers describe the stocks, not which company is better. Ask for `/fundamentals` or `/forecast` on either symbol to go deeper.',
    '',
    DISCLAIMER,
  ].join('\n');
  return b.answer(answer).finish();
}

function chart(
  inst: Instrument,
  range: HistoryRange,
  request: ChatRequest,
  model: ModelInfo,
  id: string,
): RecordedSession {
  const s = historyStats(priceHistory(inst, range));
  return builder(`Price history · ${inst.symbol} · ${range}`, request, model, id)
    .reasoning(
      `A ${range} price history for ${inst.symbol} answers this. I will report return, range, volatility and drawdown.`,
    )
    .tool(historyStep(inst, range))
    .answer(
      [
        `**${inst.symbol} · ${range}** — ${fmtPct(s.returnPct)} from ${money(s.start.c)} (${s.start.t}) to ${money(s.end.c)} (${s.end.t}).`,
        '',
        `- High ${money(s.high.h)} on ${s.high.t}; low ${money(s.low.l)} on ${s.low.t}`,
        `- Annualized volatility ${s.volatilityAnnualizedPct}%`,
        `- Max drawdown ${fmtPct(s.maxDrawdownPct)}`,
        '',
        'Expand the tool line above to see the bars. Interactive candlestick charts arrive in the next release.',
        '',
        DISCLAIMER,
      ].join('\n'),
    )
    .finish();
}

function forecastScenario(
  inst: Instrument,
  request: ChatRequest,
  model: ModelInfo,
  id: string,
): RecordedSession {
  const f = forecast(inst);
  const rows = f.horizons.map(
    (h) =>
      `| ${h.months}M | ${h.targetDate} | ${fmtPrice(h.p10)} | **${fmtPrice(h.p50)}** | ${fmtPrice(h.p90)} |`,
  );
  return builder(`Forecast · ${inst.symbol}`, request, model, id)
    .reasoning(
      `The user asks about the outlook for ${inst.symbol}. I will fetch the quote for the base price and the baseline forecast, and make clear it is statistical, not a call.`,
    )
    .tool(quoteStep(inst))
    .tool(forecastStep(inst))
    .answer(
      [
        `Baseline forecast for **${inst.symbol}** from ${money(f.basePrice)} (${f.asOf}):`,
        '',
        '| Horizon | Date | P10 | P50 | P90 |',
        '|---|---|---:|---:|---:|',
        ...rows,
        '',
        `Method: ${f.method}. Read it as: in 8 of 10 historical-style paths the price lands between P10 and P90. The spread widens with the horizon because uncertainty compounds; the P50 is not a price target.`,
        '',
        `> ${f.disclaimer}`,
        '',
        DISCLAIMER,
      ].join('\n'),
    )
    .finish();
}

function fundamentalsScenario(
  inst: Instrument,
  request: ChatRequest,
  model: ModelInfo,
  id: string,
): RecordedSession {
  const data = FUNDAMENTALS[inst.symbol];
  const b = builder(`Fundamentals · ${inst.symbol}`, request, model, id).reasoning(
    `Fundamentals for ${inst.symbol} come from SEC filings. I will request the annual statements and derived ratios.`,
  );
  if (!data) {
    return b
      .tool({
        name: 'get_fundamentals',
        args: { symbol: inst.symbol, period: 'annual', limit: 4 },
        ok: false,
        summary: 'data_unavailable',
        error: 'SEC fundamentals are not available for this symbol in the snapshot.',
        durationMs: 212,
      })
      .reasoning(
        'The fundamentals provider has no data for this symbol. I should say so plainly and offer what I can measure instead, without inventing figures.',
      )
      .tool(quoteStep(inst))
      .answer(
        [
          `I couldn't retrieve reported financials for **${inst.symbol}**: the SEC fundamentals provider returned \`data_unavailable\`. I won't estimate revenue or margins without filings behind them.`,
          '',
          `What I can confirm from market data: ${inst.symbol} closed at ${money(quote(inst).close)} on ${quote(inst).asOf}. Try \`/analyze ${inst.symbol}\` for price action and technicals, or \`/fundamentals AAPL\` to see the fundamentals view.`,
          '',
          DISCLAIMER,
        ].join('\n'),
      )
      .finish();
  }
  const [cur, prev] = data.periods;
  const r = data.ratios;
  const bn = (v: number | undefined) => (v === undefined ? '—' : `$${(v / 1e9).toFixed(1)}B`);
  return b
    .tool({
      name: 'get_fundamentals',
      args: { symbol: inst.symbol, period: 'annual', limit: 4 },
      ok: true,
      summary: `${data.periods.length} periods · FY${cur?.fiscalYear ?? ''}`,
      data: { kind: 'fundamentals', fundamentals: data },
      durationMs: 164,
    })
    .answer(
      [
        `**${data.name}** · fiscal ${cur?.fiscalYear} (period ending ${cur?.periodEnd}), from SEC filings:`,
        '',
        `| | FY${cur?.fiscalYear} | FY${prev?.fiscalYear} |`,
        '|---|---:|---:|',
        `| Revenue | ${bn(cur?.revenue)} | ${bn(prev?.revenue)} |`,
        `| Operating income | ${bn(cur?.operatingIncome)} | ${bn(prev?.operatingIncome)} |`,
        `| Net income | ${bn(cur?.netIncome)} | ${bn(prev?.netIncome)} |`,
        `| EPS (diluted) | ${cur?.epsDiluted ?? '—'} | ${prev?.epsDiluted ?? '—'} |`,
        `| Free cash flow | ${bn(cur?.freeCashFlow)} | ${bn(prev?.freeCashFlow)} |`,
        '',
        `- Gross margin **${r.grossMarginPct}%**, operating margin **${r.operatingMarginPct}%**, net margin **${r.netMarginPct}%**`,
        `- Revenue growth **${fmtPct(r.revenueGrowthPct)}** vs EPS growth **${fmtPct(r.epsGrowthPct)}**: earnings grew much faster than sales, so margin expansion (and buybacks) did most of the work`,
        `- Free cash flow fell year over year while net income rose, worth checking in the cash flow statement`,
        `- Debt to assets ${r.debtToAssets}`,
        '',
        DISCLAIMER,
      ].join('\n'),
    )
    .finish();
}

function resolve(
  query: string,
  inst: Instrument,
  request: ChatRequest,
  model: ModelInfo,
  id: string,
): RecordedSession {
  const results = searchInstruments(query).map((i) => ({
    symbol: i.symbol,
    name: i.name,
    exchange: i.exchange,
  }));
  return builder(`Symbol resolution · ${query}`, request, model, id)
    .reasoning(
      `The user named "${query}" without a ticker. I should resolve it with search_symbols before fetching any data.`,
    )
    .tool({
      name: 'search_symbols',
      args: { query, limit: 5 },
      ok: true,
      summary: `${results.length} match${results.length === 1 ? '' : 'es'} · ${results[0]?.symbol ?? '—'}`,
      data: { kind: 'symbols', results },
      durationMs: 26,
    })
    .reasoning(
      `"${query}" resolves to ${inst.symbol} (${inst.name}). Now the regular analysis tools.`,
    )
    .tool(quoteStep(inst))
    .tool(historyStep(inst, '6M'))
    .tool(indicatorStep(inst))
    .tool(forecastStep(inst))
    .answer(`"${query}" maps to **${inst.symbol}** on ${inst.exchange}.\n\n${analysisBody(inst)}`)
    .finish();
}

function unknownSymbol(
  symbol: string,
  request: ChatRequest,
  model: ModelInfo,
  id: string,
): RecordedSession {
  return builder(`Data unavailable · ${symbol}`, request, model, id)
    .reasoning(
      `The user asked about ${symbol}. I will try to fetch a quote; if it fails I will search for the symbol rather than guess.`,
    )
    .tool({
      name: 'get_quote',
      args: { symbol },
      ok: false,
      summary: 'not_found',
      error: `No US-listed symbol ${symbol} in the snapshot.`,
      durationMs: 14,
    })
    .tool({
      name: 'search_symbols',
      args: { query: symbol, limit: 5 },
      ok: true,
      summary: '0 matches',
      data: { kind: 'symbols', results: [] },
      durationMs: 22,
    })
    .answer(
      [
        `I couldn't find **${symbol}** among US-listed symbols in the data snapshot, so I have no prices or filings to analyse, and I won't make numbers up.`,
        '',
        'A few things to check:',
        '- Is the ticker spelled correctly? Class shares use a dot, as in `BRK.B`.',
        '- Recently listed or delisted companies may be missing from the snapshot.',
        '- You can type a company name and I will search for it.',
        '',
        `In this replay demo, recorded data covers ${UNIVERSE.map((i) => `\`${i.symbol}\``).join(', ')}.`,
      ].join('\n'),
    )
    .finish();
}

function general(request: ChatRequest, model: ModelInfo, id: string): RecordedSession {
  return builder('General · replay help', request, model, id)
    .reasoning(
      'This request does not name a stock I can look up. In replay mode I should explain what the demo covers and suggest concrete prompts.',
    )
    .answer(
      [
        "I'm **Candela**, an open financial-analysis model that answers with numbers from deterministic market tools rather than memory.",
        '',
        'You are watching **replay mode**: the gateway on the Mac that serves the fine-tuned model is offline, so answers are scripted demo recordings shaped exactly like the live stream. Try:',
        '',
        '- `/analyze NVDA`, a full single-stock read with tools',
        '- `/compare AAPL MSFT`, side-by-side metrics',
        '- `how is nvidia doing?`, which resolves a company name to its ticker',
        '- `/fundamentals AAPL` or `/forecast TSLA`',
        '- `/analyze ZZZZ`, to see how missing data is handled',
        '',
        'Type `/help` for every command. Not financial advice.',
      ].join('\n'),
    )
    .finish();
}

export function rateLimited(
  request: ChatRequest,
  model: ModelInfo,
  id: string,
  retryAfterMs: number,
): RecordedSession {
  return builder('Rate limited', request, model, id).fail(
    'rate_limited',
    'Too many requests. The gateway allows 8 chat requests per minute per visitor.',
    retryAfterMs,
  );
}

export function scenarioFor(
  intent: Intent,
  request: ChatRequest,
  model: ModelInfo,
  id: string,
): RecordedSession {
  const inst = (symbol: string) => findInstrument(symbol);
  switch (intent.kind) {
    case 'analysis': {
      const i = inst(intent.symbol);
      return i ? analysis(i, request, model, id) : unknownSymbol(intent.symbol, request, model, id);
    }
    case 'compare': {
      const list = intent.symbols.map(inst).filter((i): i is Instrument => !!i);
      return list.length >= 2 ? compare(list, request, model, id) : general(request, model, id);
    }
    case 'chart': {
      const i = inst(intent.symbol);
      return i
        ? chart(i, intent.range, request, model, id)
        : unknownSymbol(intent.symbol, request, model, id);
    }
    case 'forecast': {
      const i = inst(intent.symbol);
      return i
        ? forecastScenario(i, request, model, id)
        : unknownSymbol(intent.symbol, request, model, id);
    }
    case 'fundamentals': {
      const i = inst(intent.symbol);
      return i
        ? fundamentalsScenario(i, request, model, id)
        : unknownSymbol(intent.symbol, request, model, id);
    }
    case 'resolve': {
      const i = inst(intent.symbol);
      return i ? resolve(intent.query, i, request, model, id) : general(request, model, id);
    }
    case 'unknown_symbol':
      return unknownSymbol(intent.symbol, request, model, id);
    case 'rate_limited':
      return rateLimited(request, model, id, 12_000);
    case 'general':
      return general(request, model, id);
  }
}

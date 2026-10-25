import type {
  Forecast,
  Fundamentals,
  IndicatorSet,
  PriceHistory,
  Quote,
  StatusResponse,
  SymbolMatch,
} from '../../api/types';
import { demoStatus } from './fixtures/models';
import type { HistoryRange } from './fixtures/market-data';
import { forecast, indicatorSet, priceHistory, quote } from './fixtures/market-data';
import { FUNDAMENTALS, findInstrument, searchInstruments } from './fixtures/universe';

export const mockMarket = {
  status(): StatusResponse {
    return demoStatus();
  },
  quote(symbol: string): Quote | null {
    const inst = findInstrument(symbol);
    return inst ? quote(inst) : null;
  },
  history(symbol: string, range: string): PriceHistory | null {
    const inst = findInstrument(symbol);
    if (!inst) return null;
    const known: HistoryRange = (['1M', '3M', '6M', '1Y', '2Y'] as const).includes(
      range as HistoryRange,
    )
      ? (range as HistoryRange)
      : '2Y';
    return { ...priceHistory(inst, known), range };
  },
  indicators(symbol: string, range: '6M' | '1Y' | '2Y'): IndicatorSet | null {
    const inst = findInstrument(symbol);
    return inst ? indicatorSet(inst, range) : null;
  },
  fundamentals(symbol: string): Fundamentals | null {
    return FUNDAMENTALS[symbol] ?? null;
  },
  forecast(symbol: string): Forecast | null {
    const inst = findInstrument(symbol);
    return inst ? forecast(inst) : null;
  },
  search(query: string, limit = 8): SymbolMatch[] {
    return searchInstruments(query, limit).map((i) => ({
      symbol: i.symbol,
      name: i.name,
      exchange: i.exchange,
    }));
  },
};

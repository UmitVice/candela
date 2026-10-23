import type { Quote, StatusResponse, SymbolMatch } from '../../api/types';
import { demoStatus } from './fixtures/models';
import { quote } from './fixtures/market-data';
import { findInstrument, searchInstruments } from './fixtures/universe';

export const mockMarket = {
  status(): StatusResponse {
    return demoStatus();
  },
  quote(symbol: string): Quote | null {
    const inst = findInstrument(symbol);
    return inst ? quote(inst) : null;
  },
  search(query: string, limit = 8): SymbolMatch[] {
    return searchInstruments(query, limit).map((i) => ({
      symbol: i.symbol,
      name: i.name,
      exchange: i.exchange,
    }));
  },
};

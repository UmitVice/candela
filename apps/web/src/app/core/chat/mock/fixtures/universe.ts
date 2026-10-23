import type { Fundamentals } from '../../../api/types';

export const SNAPSHOT_AS_OF = '2026-10-22';

export interface Instrument {
  symbol: string;
  name: string;
  exchange: 'NASDAQ' | 'NYSE';
  sector: string;
  aliases: string[];
  close: number;
  closeAgo6M: number;
  closeAgo1Y: number;
  closeAgo2Y: number;
  annualVolPct: number;
  avgVolume: number;
  forecastDriftPct: number;
  seed: number;
}

/**
 * Illustrative demo data for the scripted replay; it is not market data. Real snapshot values come
 * from the gateway in live mode.
 */
export const UNIVERSE: readonly Instrument[] = [
  {
    symbol: 'NVDA',
    name: 'NVIDIA Corporation',
    exchange: 'NASDAQ',
    sector: 'Semiconductors',
    aliases: ['nvidia'],
    close: 182.41,
    closeAgo6M: 141.2,
    closeAgo1Y: 136.9,
    closeAgo2Y: 118.6,
    annualVolPct: 41.7,
    avgVolume: 187_650_432,
    forecastDriftPct: 8,
    seed: 11,
  },
  {
    symbol: 'AAPL',
    name: 'Apple Inc.',
    exchange: 'NASDAQ',
    sector: 'Consumer Electronics',
    aliases: ['apple', 'iphone maker'],
    close: 262.8,
    closeAgo6M: 204.6,
    closeAgo1Y: 236.5,
    closeAgo2Y: 230.8,
    annualVolPct: 24.3,
    avgVolume: 51_204_118,
    forecastDriftPct: 6,
    seed: 23,
  },
  {
    symbol: 'MSFT',
    name: 'Microsoft Corporation',
    exchange: 'NASDAQ',
    sector: 'Software',
    aliases: ['microsoft'],
    close: 518.36,
    closeAgo6M: 387.4,
    closeAgo1Y: 427.5,
    closeAgo2Y: 418.2,
    annualVolPct: 22.1,
    avgVolume: 19_884_201,
    forecastDriftPct: 7,
    seed: 37,
  },
  {
    symbol: 'AMD',
    name: 'Advanced Micro Devices, Inc.',
    exchange: 'NASDAQ',
    sector: 'Semiconductors',
    aliases: ['amd', 'advanced micro devices'],
    close: 236.12,
    closeAgo6M: 96.4,
    closeAgo1Y: 158.3,
    closeAgo2Y: 152.9,
    annualVolPct: 52.4,
    avgVolume: 61_007_934,
    forecastDriftPct: 9,
    seed: 41,
  },
  {
    symbol: 'TSLA',
    name: 'Tesla, Inc.',
    exchange: 'NASDAQ',
    sector: 'Automobiles',
    aliases: ['tesla'],
    close: 438.69,
    closeAgo6M: 241.4,
    closeAgo1Y: 213.7,
    closeAgo2Y: 218.9,
    annualVolPct: 58.9,
    avgVolume: 98_420_650,
    forecastDriftPct: 10,
    seed: 53,
  },
  {
    symbol: 'GOOGL',
    name: 'Alphabet Inc.',
    exchange: 'NASDAQ',
    sector: 'Interactive Media',
    aliases: ['alphabet', 'google'],
    close: 251.34,
    closeAgo6M: 155.2,
    closeAgo1Y: 163.4,
    closeAgo2Y: 163.9,
    annualVolPct: 29.6,
    avgVolume: 36_118_552,
    forecastDriftPct: 7,
    seed: 67,
  },
  {
    symbol: 'AMZN',
    name: 'Amazon.com, Inc.',
    exchange: 'NASDAQ',
    sector: 'Internet Retail',
    aliases: ['amazon'],
    close: 221.09,
    closeAgo6M: 167.3,
    closeAgo1Y: 189.7,
    closeAgo2Y: 186.4,
    annualVolPct: 31.2,
    avgVolume: 42_773_016,
    forecastDriftPct: 7,
    seed: 71,
  },
  {
    symbol: 'META',
    name: 'Meta Platforms, Inc.',
    exchange: 'NASDAQ',
    sector: 'Interactive Media',
    aliases: ['meta', 'facebook', 'meta platforms'],
    close: 733.27,
    closeAgo6M: 501.5,
    closeAgo1Y: 563.1,
    closeAgo2Y: 554.2,
    annualVolPct: 35.8,
    avgVolume: 12_604_473,
    forecastDriftPct: 8,
    seed: 89,
  },
];

export function findInstrument(symbol: string): Instrument | undefined {
  return UNIVERSE.find((item) => item.symbol === symbol.toUpperCase());
}

export function searchInstruments(query: string, limit = 5): Instrument[] {
  const q = query.trim().toLowerCase();
  if (!q) return [];
  return UNIVERSE.filter(
    (item) =>
      item.symbol.toLowerCase() === q ||
      item.symbol.toLowerCase().startsWith(q) ||
      item.name.toLowerCase().includes(q) ||
      item.aliases.some((alias) => alias.includes(q) || q.includes(alias)),
  ).slice(0, limit);
}

export const FUNDAMENTALS: Readonly<Record<string, Fundamentals>> = {
  AAPL: {
    symbol: 'AAPL',
    name: 'Apple Inc.',
    period: 'annual',
    currency: 'USD',
    periods: [
      {
        fiscalYear: 2025,
        fiscalPeriod: 'FY',
        periodEnd: '2025-09-27',
        revenue: 416_161_000_000,
        grossProfit: 195_201_000_000,
        operatingIncome: 133_050_000_000,
        netIncome: 112_010_000_000,
        epsDiluted: 7.46,
        operatingCashFlow: 111_482_000_000,
        freeCashFlow: 98_767_000_000,
        totalAssets: 359_241_000_000,
        totalLiabilities: 285_508_000_000,
        cashAndEquivalents: 35_934_000_000,
        longTermDebt: 78_328_000_000,
      },
      {
        fiscalYear: 2024,
        fiscalPeriod: 'FY',
        periodEnd: '2024-09-28',
        revenue: 391_035_000_000,
        grossProfit: 180_683_000_000,
        operatingIncome: 123_216_000_000,
        netIncome: 93_736_000_000,
        epsDiluted: 6.08,
        operatingCashFlow: 118_254_000_000,
        freeCashFlow: 108_807_000_000,
        totalAssets: 364_980_000_000,
        totalLiabilities: 308_030_000_000,
        cashAndEquivalents: 29_943_000_000,
        longTermDebt: 85_750_000_000,
      },
    ],
    ratios: {
      grossMarginPct: 46.91,
      operatingMarginPct: 31.97,
      netMarginPct: 26.92,
      fcfMarginPct: 23.73,
      revenueGrowthPct: 6.43,
      epsGrowthPct: 22.7,
      debtToAssets: 0.218,
    },
    source: 'sec',
    asOf: '2025-10-31',
  },
};

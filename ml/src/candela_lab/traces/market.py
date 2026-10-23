import hashlib
import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import numpy as np

UNIVERSE: list[tuple[str, str, str, str]] = [
    ("NVDA", "NVIDIA Corporation", "NASDAQ", "tech"),
    ("AAPL", "Apple Inc.", "NASDAQ", "tech"),
    ("MSFT", "Microsoft Corporation", "NASDAQ", "tech"),
    ("AMZN", "Amazon.com, Inc.", "NASDAQ", "consumer"),
    ("GOOGL", "Alphabet Inc.", "NASDAQ", "tech"),
    ("META", "Meta Platforms, Inc.", "NASDAQ", "tech"),
    ("TSLA", "Tesla, Inc.", "NASDAQ", "consumer"),
    ("AMD", "Advanced Micro Devices, Inc.", "NASDAQ", "tech"),
    ("AVGO", "Broadcom Inc.", "NASDAQ", "tech"),
    ("NFLX", "Netflix, Inc.", "NASDAQ", "media"),
    ("ADBE", "Adobe Inc.", "NASDAQ", "tech"),
    ("CRM", "Salesforce, Inc.", "NYSE", "tech"),
    ("ORCL", "Oracle Corporation", "NYSE", "tech"),
    ("INTC", "Intel Corporation", "NASDAQ", "tech"),
    ("JPM", "JPMorgan Chase & Co.", "NYSE", "financials"),
    ("BAC", "Bank of America Corporation", "NYSE", "financials"),
    ("GS", "The Goldman Sachs Group, Inc.", "NYSE", "financials"),
    ("V", "Visa Inc.", "NYSE", "financials"),
    ("MA", "Mastercard Incorporated", "NYSE", "financials"),
    ("BRK.B", "Berkshire Hathaway Inc.", "NYSE", "financials"),
    ("JNJ", "Johnson & Johnson", "NYSE", "health"),
    ("UNH", "UnitedHealth Group Incorporated", "NYSE", "health"),
    ("LLY", "Eli Lilly and Company", "NYSE", "health"),
    ("PFE", "Pfizer Inc.", "NYSE", "health"),
    ("MRK", "Merck & Co., Inc.", "NYSE", "health"),
    ("XOM", "Exxon Mobil Corporation", "NYSE", "energy"),
    ("CVX", "Chevron Corporation", "NYSE", "energy"),
    ("KO", "The Coca-Cola Company", "NYSE", "staples"),
    ("PEP", "PepsiCo, Inc.", "NASDAQ", "staples"),
    ("PG", "The Procter & Gamble Company", "NYSE", "staples"),
    ("WMT", "Walmart Inc.", "NYSE", "staples"),
    ("COST", "Costco Wholesale Corporation", "NASDAQ", "staples"),
    ("HD", "The Home Depot, Inc.", "NYSE", "consumer"),
    ("MCD", "McDonald's Corporation", "NYSE", "consumer"),
    ("NKE", "NIKE, Inc.", "NYSE", "consumer"),
    ("DIS", "The Walt Disney Company", "NYSE", "media"),
    ("BA", "The Boeing Company", "NYSE", "industrials"),
    ("CAT", "Caterpillar Inc.", "NYSE", "industrials"),
    ("GE", "GE Aerospace", "NYSE", "industrials"),
    ("UPS", "United Parcel Service, Inc.", "NYSE", "industrials"),
    ("QCOM", "QUALCOMM Incorporated", "NASDAQ", "tech"),
    ("TXN", "Texas Instruments Incorporated", "NASDAQ", "tech"),
    ("IBM", "International Business Machines Corporation", "NYSE", "tech"),
    ("SBUX", "Starbucks Corporation", "NASDAQ", "consumer"),
    ("PYPL", "PayPal Holdings, Inc.", "NASDAQ", "financials"),
    ("UBER", "Uber Technologies, Inc.", "NYSE", "tech"),
    ("PLTR", "Palantir Technologies Inc.", "NASDAQ", "tech"),
    ("SPY", "SPDR S&P 500 ETF Trust", "NYSE ARCA", "etf"),
    ("QQQ", "Invesco QQQ Trust", "NASDAQ", "etf"),
    ("XLE", "Energy Select Sector SPDR Fund", "NYSE ARCA", "etf"),
]

# Tool-use evaluation uses these tickers only; training traces never mention them.
HELDOUT_SYMBOLS = {"AMD", "JPM", "LLY", "COST", "CAT", "QCOM", "SBUX", "XLE"}

ETF = {s for s, *_ in UNIVERSE if s in {"SPY", "QQQ", "XLE"}}
NAMES = {s: n for s, n, *_ in UNIVERSE}
EXCHANGES = {s: e for s, _, e, _ in UNIVERSE}
RANGE_DAYS = {"1M": 21, "3M": 63, "6M": 126, "1Y": 252, "2Y": 504, "5Y": 1260}
MAX_VIEW_CHARS = 2500


def dumps(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


def r2(x: float) -> float:
    return round(float(x), 2)


def r3(x: float) -> float:
    return round(float(x), 3)


def _seed(*parts: str) -> int:
    return int.from_bytes(hashlib.sha256("|".join(parts).encode()).digest()[:8], "big")


def business_days(end: date, n: int) -> list[date]:
    days: list[date] = []
    d = end
    while len(days) < n:
        if d.weekday() < 5:
            days.append(d)
        d -= timedelta(days=1)
    return days[::-1]


@dataclass
class Series:
    dates: list[date]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray


def make_series(symbol: str, as_of: date, n: int = 1300) -> Series:
    rng = np.random.default_rng(_seed("series", symbol, as_of.isoformat()))
    vol = rng.uniform(0.012, 0.035) if symbol not in ETF else rng.uniform(0.008, 0.014)
    drift = rng.uniform(-0.0003, 0.0008)
    target = float(np.exp(rng.uniform(np.log(15), np.log(900))))
    regime = np.repeat(rng.normal(0, 0.0015, size=n // 60 + 1), 60)[:n]
    rets = rng.standard_t(5, size=n) * vol / np.sqrt(5 / 3) + drift + regime
    path = np.exp(np.cumsum(rets))
    close = target * path / path[-1]
    prev = np.concatenate([[close[0]], close[:-1]])
    gap = rng.normal(0, vol / 3, size=n)
    open_ = prev * np.exp(gap)
    span = np.abs(rng.normal(0, vol, size=n)) * close
    high = np.maximum(open_, close) + span * rng.uniform(0.2, 0.8, size=n)
    low = np.minimum(open_, close) - span * rng.uniform(0.2, 0.8, size=n)
    base_vol = rng.uniform(2e6, 9e7)
    volume = (base_vol * np.exp(rng.normal(0, 0.35, size=n) + np.abs(rets) * 12)).astype(np.int64)
    return Series(business_days(as_of, n), open_, high, low, close, volume)


def sma(x: np.ndarray, n: int) -> float:
    return float(np.mean(x[-n:]))


def ema_series(x: np.ndarray, n: int) -> np.ndarray:
    alpha = 2 / (n + 1)
    out = np.empty(len(x) - n + 1)
    out[0] = np.mean(x[:n])
    for i in range(1, len(out)):
        out[i] = alpha * x[n - 1 + i] + (1 - alpha) * out[i - 1]
    return out


def wilder(x: np.ndarray, n: int) -> np.ndarray:
    out = np.empty(len(x) - n + 1)
    out[0] = np.mean(x[:n])
    for i in range(1, len(out)):
        out[i] = (out[i - 1] * (n - 1) + x[n - 1 + i]) / n
    return out


def rsi(close: np.ndarray, n: int = 14) -> float:
    delta = np.diff(close)
    gain = wilder(np.clip(delta, 0, None), n)[-1]
    loss = wilder(np.clip(-delta, 0, None), n)[-1]
    if loss == 0:
        return 100.0
    return float(100 - 100 / (1 + gain / loss))


def atr(s: Series, n: int = 14) -> float:
    prev = s.close[:-1]
    tr = np.maximum.reduce([s.high[1:] - s.low[1:], np.abs(s.high[1:] - prev), np.abs(s.low[1:] - prev)])
    return float(wilder(tr, n)[-1])


def _quarter_end(as_of: date, back: int) -> date:
    q = (as_of.year * 4 + (as_of.month - 1) // 3) - back
    year, quarter = divmod(q, 4)
    month = quarter * 3 + 3
    nxt = date(year + (month == 12), month % 12 + 1, 1)
    return nxt - timedelta(days=1)


class SyntheticMarket:
    """Contract-shaped synthetic model views (`contracts/tools.md`) for offline trace generation."""

    def __init__(self, as_of: str) -> None:
        self.as_of = date.fromisoformat(as_of)
        self._cache: dict[str, Series] = {}

    def series(self, symbol: str) -> Series:
        if symbol not in self._cache:
            self._cache[symbol] = make_series(symbol, self.as_of)
        return self._cache[symbol]

    def known(self, symbol: str) -> bool:
        return symbol in NAMES

    def search(self, query: str, limit: int = 5) -> dict[str, Any]:
        q = query.lower().strip()
        hits = []
        for sym, name, exch, _ in UNIVERSE:
            score = (
                3 if sym.lower() == q else 2 if sym.lower().startswith(q) else 1 if q in name.lower() else 0
            )
            if score:
                hits.append((score, sym, name, exch))
        hits.sort(key=lambda h: (-h[0], h[1]))
        return {
            "query": query,
            "results": [{"symbol": s, "name": n, "exchange": e} for _, s, n, e in hits[:limit]],
        }

    def quote(self, symbol: str) -> dict[str, Any]:
        s = self.series(symbol)
        c = s.close
        year = slice(-252, None)
        return {
            "symbol": symbol,
            "name": NAMES[symbol],
            "asOf": s.dates[-1].isoformat(),
            "close": r2(c[-1]),
            "changePct": r2((c[-1] / c[-2] - 1) * 100),
            "open": r2(s.open[-1]),
            "high": r2(s.high[-1]),
            "low": r2(s.low[-1]),
            "volume": int(s.volume[-1]),
            "fiftyTwoWeekHigh": r2(np.max(s.high[year])),
            "fiftyTwoWeekLow": r2(np.min(s.low[year])),
            "avgVolume30d": int(np.mean(s.volume[-30:])),
            "source": "snapshot",
            "delayed": True,
        }

    def history(self, symbol: str, range_: str = "1Y") -> dict[str, Any]:
        s = self.series(symbol)
        n = RANGE_DAYS[range_]
        c, h, lo, d = s.close[-n - 1 :], s.high[-n:], s.low[-n:], s.dates[-n - 1 :]
        rets = np.diff(np.log(c))
        running = np.maximum.accumulate(c)
        hi_i, lo_i = int(np.argmax(h)), int(np.argmin(lo))
        dates_n = s.dates[-n:]
        view: dict[str, Any] = {
            "symbol": symbol,
            "range": range_,
            "asOf": d[-1].isoformat(),
            "start": {"t": d[0].isoformat(), "c": r2(c[0])},
            "end": {"t": d[-1].isoformat(), "c": r2(c[-1])},
            "returnPct": r2((c[-1] / c[0] - 1) * 100),
            "high": {"t": dates_n[hi_i].isoformat(), "h": r2(h[hi_i])},
            "low": {"t": dates_n[lo_i].isoformat(), "l": r2(lo[lo_i])},
            "volatilityAnnualizedPct": r2(np.std(rets) * np.sqrt(252) * 100),
            "maxDrawdownPct": r2(np.min(c / running - 1) * 100),
            "avgVolume": int(np.mean(s.volume[-n:])),
        }
        key = "monthlyCloses" if range_ in ("2Y", "5Y") else "weeklyCloses"
        closes = self._period_closes(s, n, monthly=key == "monthlyCloses")
        view[key] = closes
        view["source"] = "snapshot"
        while len(dumps(view)) > MAX_VIEW_CHARS and view[key]:
            view[key] = view[key][1:]
        return view

    @staticmethod
    def _period_closes(s: Series, n: int, monthly: bool) -> list[float]:
        out: dict[tuple[int, int], float] = {}
        for d, c in zip(s.dates[-n:], s.close[-n:], strict=True):
            key = (d.year, d.month) if monthly else tuple(d.isocalendar()[:2])
            out[key] = r2(c)  # type: ignore[index]
        return list(out.values())[-60:]

    def indicators(self, symbol: str, range_: str = "1Y") -> dict[str, Any]:
        s = self.series(symbol)
        c = s.close
        close = float(c[-1])
        sma20, sma50, sma200 = sma(c, 20), sma(c, 50), sma(c, 200)
        e12, e26 = ema_series(c, 12), ema_series(c, 26)
        macd_line = e12[-len(e26) :] - e26
        signal_line = ema_series(macd_line, 9)
        macd, macd_sig = float(macd_line[-1]), float(signal_line[-1])
        sd = float(np.std(c[-20:]))
        bb_u, bb_l = sma20 + 2 * sd, sma20 - 2 * sd
        a14 = atr(s)
        rsi14 = rsi(c)
        signals = self._signals(s, close, rsi14, sma50, sma200, macd_line, signal_line, bb_u, bb_l, a14)
        return {
            "symbol": symbol,
            "asOf": s.dates[-1].isoformat(),
            "close": r2(close),
            "sma20": r2(sma20),
            "sma50": r2(sma50),
            "sma200": r2(sma200),
            "ema12": r2(e12[-1]),
            "ema26": r2(e26[-1]),
            "rsi14": round(rsi14, 1),
            "macd": r2(macd),
            "macdSignal": r2(macd_sig),
            "macdHist": r2(macd - macd_sig),
            "bbUpper": r2(bb_u),
            "bbMiddle": r2(sma20),
            "bbLower": r2(bb_l),
            "bbPercentB": r2((close - bb_l) / (bb_u - bb_l)) if bb_u > bb_l else 0.5,
            "atr14": r2(a14),
            "atrPct": r2(a14 / close * 100),
            "signals": signals,
            "source": "snapshot",
        }

    def _signals(
        self,
        s: Series,
        close: float,
        rsi14: float,
        sma50: float,
        sma200: float,
        macd_line: np.ndarray,
        signal_line: np.ndarray,
        bb_u: float,
        bb_l: float,
        a14: float,
    ) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        if rsi14 > 70:
            out.append(
                {"id": "rsi_overbought", "tone": "bearish", "detail": f"RSI14 {rsi14:.1f} is above 70"}
            )
        elif rsi14 < 30:
            out.append({"id": "rsi_oversold", "tone": "bullish", "detail": f"RSI14 {rsi14:.1f} is below 30"})
        for name, level in (("sma50", sma50), ("sma200", sma200)):
            pct = abs(close / level - 1) * 100
            side = "above" if close >= level else "below"
            out.append(
                {
                    "id": f"price_{side}_{name}",
                    "tone": "bullish" if side == "above" else "bearish",
                    "detail": f"Close {close:.2f} is {pct:.2f}% {side} {name.upper()} {level:.2f}",
                }
            )
        c = s.close
        sma50s = np.convolve(c, np.ones(50) / 50, mode="valid")
        sma200s = np.convolve(c, np.ones(200) / 200, mode="valid")
        diff = sma50s[-len(sma200s) :] - sma200s
        cross = np.where(np.diff(np.sign(diff)) != 0)[0]
        if len(cross):
            ago = len(diff) - 1 - (int(cross[-1]) + 1)
            since = s.dates[-1 - ago].isoformat()
            golden = diff[-1] > 0
            kind = "golden" if golden else "death"
            if ago <= 20:
                out.append(
                    {
                        "id": f"{kind}_cross_recent",
                        "tone": "bullish" if golden else "bearish",
                        "detail": f"SMA50 crossed {'above' if golden else 'below'} SMA200 on {since}",
                    }
                )
            else:
                out.append(
                    {
                        "id": f"{kind}_cross_active",
                        "tone": "bullish" if golden else "bearish",
                        "detail": f"SMA50 {'above' if golden else 'below'} SMA200 since {since}",
                    }
                )
        mdiff = macd_line[-len(signal_line) :] - signal_line
        mcross = np.where(np.diff(np.sign(mdiff[-6:])) != 0)[0]
        if len(mcross):
            bull = mdiff[-1] > 0
            out.append(
                {
                    "id": "macd_bullish_cross" if bull else "macd_bearish_cross",
                    "tone": "bullish" if bull else "bearish",
                    "detail": f"MACD crossed {'above' if bull else 'below'} its signal line in the last 5 sessions",
                }
            )
        if close > bb_u:
            out.append(
                {
                    "id": "bb_upper_break",
                    "tone": "bearish",
                    "detail": "Close is above the upper Bollinger Band",
                }
            )
        elif close < bb_l:
            out.append(
                {
                    "id": "bb_lower_break",
                    "tone": "bullish",
                    "detail": "Close is below the lower Bollinger Band",
                }
            )
        if a14 / close * 100 > 4:
            out.append(
                {
                    "id": "high_volatility",
                    "tone": "neutral",
                    "detail": f"ATR14 is {a14 / close * 100:.2f}% of price",
                }
            )
        return out

    def forecast(self, symbol: str) -> dict[str, Any]:
        s = self.series(symbol)
        rng = np.random.default_rng(_seed("forecast", symbol, self.as_of.isoformat()))
        rets = np.diff(np.log(s.close[-1261:]))
        base = float(s.close[-1])
        horizons = []
        blocks = len(rets) // 20
        paths = 2000
        for m in (3, 6, 9, 12):
            days = 21 * m
            nb = days // 20 + 1
            starts = rng.integers(0, len(rets) - 20, size=(paths, nb))
            idx = (starts[:, :, None] + np.arange(20)).reshape(paths, -1)[:, :days]
            total = rets[idx].sum(axis=1)
            p10, p50, p90 = np.percentile(base * np.exp(total), [10, 50, 90])
            horizons.append(
                {
                    "m": m,
                    "p10": round(float(p10), 1),
                    "p50": round(float(p50), 1),
                    "p90": round(float(p90), 1),
                }
            )
        del blocks
        return {
            "symbol": symbol,
            "asOf": s.dates[-1].isoformat(),
            "basePrice": r2(base),
            "source": "baseline",
            "method": "block bootstrap of 5y daily log returns",
            "horizons": horizons,
        }

    def fundamentals(self, symbol: str, period: str = "annual", limit: int = 4) -> dict[str, Any]:
        rng = np.random.default_rng(_seed("fund", symbol))
        revenue = rng.uniform(8e9, 4.5e11)
        gross_m, op_m = rng.uniform(0.25, 0.75), rng.uniform(0.05, 0.4)
        growth = rng.uniform(-0.08, 0.35)
        last_fy = self.as_of.year - 1 if self.as_of.month < 11 else self.as_of.year
        periods = []
        steps = limit if period == "annual" else limit + 4
        for k in range(steps + 1):
            g = growth + rng.normal(0, 0.03)
            if period == "annual":
                rev = revenue / (1 + g) ** k
                fy, fp = last_fy - k, "FY"
                end = date(fy, 12, 31) - timedelta(days=int(rng.integers(0, 4)))
            else:
                rev = revenue / 4 / (1 + g / 4) ** k
                q_end = _quarter_end(self.as_of, k + 1)
                fy, fp, end = q_end.year, f"Q{(q_end.month - 1) // 3 + 1}", q_end
            gp = rev * (gross_m + rng.normal(0, 0.01))
            op = rev * (op_m + rng.normal(0, 0.01))
            ni = op * rng.uniform(0.7, 0.85)
            shares = revenue / rng.uniform(20, 60) / 1e1
            ocf = ni * rng.uniform(1.0, 1.3)
            assets = revenue * rng.uniform(0.8, 2.2)
            periods.append(
                {
                    "fy": fy,
                    "fp": fp,
                    "end": end.isoformat(),
                    "revenue": int(rev),
                    "grossProfit": int(gp),
                    "operatingIncome": int(op),
                    "netIncome": int(ni),
                    "epsDiluted": r2(ni / shares),
                    "operatingCashFlow": int(ocf),
                    "freeCashFlow": int(ocf * rng.uniform(0.6, 0.9)),
                    "totalAssets": int(assets),
                    "totalLiabilities": int(assets * rng.uniform(0.3, 0.8)),
                    "cash": int(assets * rng.uniform(0.05, 0.2)),
                    "longTermDebt": int(assets * rng.uniform(0.05, 0.3)),
                }
            )
        newest = periods[0]
        prior = periods[4] if period == "quarterly" and len(periods) > 4 else periods[1]
        ratios = {
            "grossMarginPct": r2(newest["grossProfit"] / newest["revenue"] * 100),
            "operatingMarginPct": r2(newest["operatingIncome"] / newest["revenue"] * 100),
            "netMarginPct": r2(newest["netIncome"] / newest["revenue"] * 100),
            "fcfMarginPct": r2(newest["freeCashFlow"] / newest["revenue"] * 100),
            "revenueGrowthPct": r2((newest["revenue"] / prior["revenue"] - 1) * 100),
            "epsGrowthPct": r2((newest["epsDiluted"] / prior["epsDiluted"] - 1) * 100),
            "debtToAssets": r3(newest["longTermDebt"] / newest["totalAssets"]),
        }
        view = {
            "symbol": symbol,
            "name": NAMES[symbol],
            "period": period,
            "currency": "USD",
            "periods": periods[:limit],
            "ratios": ratios,
            "source": "sec",
            "asOf": (self.as_of - timedelta(days=int(rng.integers(20, 80)))).isoformat(),
        }
        while len(dumps(view)) > MAX_VIEW_CHARS and len(view["periods"]) > 1:
            view["periods"] = view["periods"][:-1]
        return view

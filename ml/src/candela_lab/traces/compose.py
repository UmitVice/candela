import random
from dataclasses import dataclass, field
from typing import Any

DISCLAIMER = [
    "This is educational analysis, not personalized financial advice.",
    "Educational analysis only — not a recommendation to buy, sell or hold.",
    "Not personalized advice; consider your own situation or a licensed professional.",
]

INDICATOR_EXPLAIN = {
    "rsi": [
        "RSI(14) (a 0–100 momentum gauge)",
        "The 14-day RSI, which flags overbought above 70 and oversold below 30,",
        "RSI(14), which compares recent gains with recent losses,",
    ],
    "macd": [
        "MACD (the gap between the 12- and 26-day EMAs)",
        "The MACD line (EMA12 minus EMA26)",
    ],
    "bb": [
        "Bollinger %B (0 = lower band, 1 = upper band)",
        "%B, which places the close inside the 20-day Bollinger Bands,",
    ],
    "atr": [
        "ATR(14), the average daily trading range,",
        "the 14-day average true range (a volatility gauge)",
    ],
}

SOURCE_LABELS = {
    "snapshot": "snapshot prices (end-of-day, delayed)",
    "sec": "SEC filings",
    "baseline": "baseline forecast",
    "vaniras": "Vaniras",
    "live": "live end-of-day prices",
}


@dataclass
class Writer:
    rng: random.Random
    derived: list[str] = field(default_factory=list)

    def pick(self, options: list[str]) -> str:
        return self.rng.choice(options)

    def derive(self, value: float, fmt: str = "{:.2f}") -> str:
        text = fmt.format(value)
        self.derived.append(text)
        return text


def num(v: Any) -> str:
    if isinstance(v, float):
        return repr(v) if abs(v) < 1e15 else f"{v:.0f}"
    return str(v)


def pct(v: Any) -> str:
    return f"{num(v)}%"


def signed_pct(v: Any) -> str:
    s = num(v)
    return f"+{s}%" if not s.startswith("-") else f"{s}%"


def money(v: Any) -> str:
    return f"${num(v)}"


def big(w: Writer, v: int | float) -> str:
    av = abs(float(v))
    for div, unit in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if av >= div:
            return w.derive(float(v) / div, "{:.2f}") + unit
    return num(v)


def snapshot_section(w: Writer, q: dict[str, Any]) -> str:
    direction = "up" if q["changePct"] >= 0 else "down"
    lines = [
        f"- **Close:** {money(q['close'])} ({signed_pct(q['changePct'])} on the day, {direction}), "
        f"range {money(q['low'])}–{money(q['high'])}",
        f"- **52-week range:** {money(q['fiftyTwoWeekLow'])} – {money(q['fiftyTwoWeekHigh'])}",
        f"- **Volume:** {big(w, q['volume'])} vs a 30-day average of {big(w, q['avgVolume30d'])}",
    ]
    off_high = (q["close"] / q["fiftyTwoWeekHigh"] - 1) * 100
    if off_high < -1:
        lines.append(f"- Trading {w.derive(abs(off_high))}% below its 52-week high")
    return "\n".join(lines)


def trend_section(w: Writer, ind: dict[str, Any] | None, hist: dict[str, Any] | None) -> tuple[str, int]:
    lines: list[str] = []
    score = 0
    if hist:
        lines.append(
            f"- Over {hist['range']} the stock returned {signed_pct(hist['returnPct'])} "
            f"(from {money(hist['start']['c'])} on {hist['start']['t']} to {money(hist['end']['c'])}), "
            f"with annualized volatility of {pct(hist['volatilityAnnualizedPct'])} and a maximum drawdown of "
            f"{pct(hist['maxDrawdownPct'])}."
        )
        score += 1 if hist["returnPct"] > 0 else -1
    if ind:
        above50 = ind["close"] >= ind["sma50"]
        above200 = ind["close"] >= ind["sma200"]
        lines.append(
            f"- Price {money(ind['close'])} is {'above' if above50 else 'below'} the 50-day average "
            f"({money(ind['sma50'])}) and {'above' if above200 else 'below'} the 200-day average "
            f"({money(ind['sma200'])})."
        )
        score += (1 if above50 else -1) + (1 if above200 else -1)
        rsi = ind["rsi14"]
        zone = "overbought" if rsi > 70 else "oversold" if rsi < 30 else "neutral"
        lines.append(f"- {w.pick(INDICATOR_EXPLAIN['rsi'])} is at {num(rsi)} ({zone} territory).")
        macd_pos = ind["macdHist"] >= 0
        lines.append(
            f"- {w.pick(INDICATOR_EXPLAIN['macd'])} is {num(ind['macd'])} vs a signal of "
            f"{num(ind['macdSignal'])}; the histogram ({num(ind['macdHist'])}) is "
            f"{'positive, a sign of improving momentum' if macd_pos else 'negative, a sign of fading momentum'}."
        )
        score += 1 if macd_pos else -1
        if w.rng.random() < 0.6:
            lines.append(
                f"- {w.pick(INDICATOR_EXPLAIN['bb'])} is {num(ind['bbPercentB'])}, and "
                f"{w.pick(INDICATOR_EXPLAIN['atr'])} is {money(ind['atr14'])} ({pct(ind['atrPct'])} of price)."
            )
        notable = [
            s for s in ind.get("signals", []) if s["id"].endswith(("cross_recent", "cross_active", "break"))
        ]
        for s in notable[:2]:
            lines.append(f"- Signal: {s['detail']} ({s['tone']}).")
    return "\n".join(lines), score


def _join(parts: list[str]) -> str:
    return ", ".join(p for p in parts if p)


def fundamentals_section(w: Writer, f: dict[str, Any]) -> str:
    p = f["periods"][0] if f.get("periods") else {}
    r = f.get("ratios", {})
    rows = []
    if p:
        label = f"FY{p['fy']}" if p.get("fp") == "FY" else f"{p.get('fp', '')} {p.get('fy', '')}".strip()
        items = _join(
            [
                f"revenue {big(w, p['revenue'])}" if "revenue" in p else "",
                f"net income {big(w, p['netIncome'])}" if "netIncome" in p else "",
                f"diluted EPS {money(p['epsDiluted'])}" if "epsDiluted" in p else "",
            ]
        )
        if items:
            rows.append(f"- **{label}** (period ending {p.get('end', 'n/a')}): {items}.")
    margins = _join(
        [
            f"gross {pct(r['grossMarginPct'])}" if "grossMarginPct" in r else "",
            f"operating {pct(r['operatingMarginPct'])}" if "operatingMarginPct" in r else "",
            f"net {pct(r['netMarginPct'])}" if "netMarginPct" in r else "",
            f"free-cash-flow {pct(r['fcfMarginPct'])}" if "fcfMarginPct" in r else "",
        ]
    )
    if margins:
        rows.append(f"- Margins: {margins}.")
    growth = _join(
        [
            f"revenue {signed_pct(r['revenueGrowthPct'])}" if "revenueGrowthPct" in r else "",
            f"EPS {signed_pct(r['epsGrowthPct'])}" if "epsGrowthPct" in r else "",
        ]
    )
    if growth:
        rows.append(f"- Growth vs a year earlier: {growth}.")
    balance = _join(
        [
            f"cash {big(w, p['cash'])}" if "cash" in p else "",
            f"long-term debt {big(w, p['longTermDebt'])}" if "longTermDebt" in p else "",
            f"debt-to-assets {num(r['debtToAssets'])} (long-term debt as a share of total assets)"
            if "debtToAssets" in r
            else "",
        ]
    )
    if balance:
        rows.append(f"- Balance sheet: {balance}.")
    return "\n".join(rows) or "- The filing data returned no comparable line items."


def forecast_section(w: Writer, fc: dict[str, Any]) -> str:
    h = {x["m"]: x for x in fc["horizons"]}
    h12 = h.get(12) or fc["horizons"][-1]
    h3 = h.get(3) or fc["horizons"][0]
    rows = [
        f"- The {fc['source']} forecast ({fc['method']}) starts from {money(fc['basePrice'])}.",
        f"- 3 months: P10 {money(h3['p10'])}, median {money(h3['p50'])}, P90 {money(h3['p90'])}.",
        f"- 12 months: P10 {money(h12['p10'])}, median {money(h12['p50'])}, P90 {money(h12['p90'])}.",
    ]
    width = (h12["p90"] - h12["p10"]) / fc["basePrice"] * 100
    rows.append(
        f"- The 12-month P10–P90 band spans about {w.derive(width, '{:.0f}')}% of today's price, "
        "so the range of outcomes is wide. These bands are statistical estimates from past returns, not analyst targets."
    )
    return "\n".join(rows)


def risks_section(w: Writer, score: int, ind: dict[str, Any] | None, f: dict[str, Any] | None) -> str:
    bull, bear = [], []
    if score > 0:
        bull.append("price trend and momentum are constructive")
    elif score < 0:
        bear.append("price trend and momentum are weak")
    if ind:
        if ind["rsi14"] > 70:
            bear.append("RSI is stretched, which often precedes consolidation")
        if ind["rsi14"] < 30:
            bull.append("RSI is oversold, which sometimes precedes a rebound")
        if ind["atrPct"] > 4:
            bear.append("daily swings are large, so position risk is elevated")
    if f:
        r = f.get("ratios", {})
        if "revenueGrowthPct" in r:
            (bull if r["revenueGrowthPct"] > 0 else bear).append(
                "revenue is growing" if r["revenueGrowthPct"] > 0 else "revenue is shrinking"
            )
        if "operatingMarginPct" in r:
            (bull if r["operatingMarginPct"] > 20 else bear).append(
                "operating margins are healthy"
                if r["operatingMarginPct"] > 20
                else "operating margins are thin"
            )
    if not bull:
        bull.append("a turn in momentum or better fundamentals would change the picture")
    if not bear:
        bear.append("strong runs can reverse quickly, and the snapshot data is end-of-day and delayed")
    uncertainty = w.pick(
        [
            "Key uncertainties: the next earnings report, guidance and the broader market tone.",
            "Watch the next earnings release and sector news, which can move the stock more than these indicators.",
            "Indicators describe the past; macro conditions and company news can change the setup quickly.",
        ]
    )
    return f"- **Bull case:** {'; '.join(bull)}.\n- **Bear case:** {'; '.join(bear)}.\n- {uncertainty}"


def bottom_line(w: Writer, name: str, score: int, has_fund: bool) -> str:
    tone = "constructive" if score >= 2 else "mixed" if score > -2 else "weak"
    fund = " Fundamentals add context above." if has_fund else ""
    return f"Technically, the setup for {name} looks {tone} on this data.{fund} {w.pick(DISCLAIMER)}"


def source_line(views: list[dict[str, Any]]) -> str:
    by_source: dict[str, set[str]] = {}
    for v in views:
        if v.get("asOf"):
            by_source.setdefault(str(v.get("source")), set()).add(str(v["asOf"]))
    if not by_source:
        return ""
    parts = [
        f"{SOURCE_LABELS.get(src, src)} as of {' and '.join(sorted(dates))}"
        for src, dates in sorted(by_source.items())
    ]
    return f"*Sources: {'; '.join(parts)}.*"


def section(title: str, body: str) -> str:
    return f"### {title}\n{body}"


def analysis(
    w: Writer,
    name: str,
    symbol: str,
    q: dict[str, Any] | None,
    hist: dict[str, Any] | None,
    ind: dict[str, Any] | None,
    fund: dict[str, Any] | None,
    fc: dict[str, Any] | None,
    notes: list[str],
) -> str:
    intro = w.pick(
        [
            f"Here is an overview of **{name} ({symbol})**.",
            f"**{name} ({symbol})** — analysis based on the latest available data.",
            f"Let's look at **{symbol}** ({name}).",
        ]
    )
    parts = [intro]
    if q:
        parts.append(section("Snapshot", snapshot_section(w, q)))
    trend, score = trend_section(w, ind, hist)
    if trend:
        parts.append(section("Trend & Momentum", trend))
    if fund:
        parts.append(section("Fundamentals", fundamentals_section(w, fund)))
    outlook = []
    if fc:
        outlook.append(forecast_section(w, fc))
    outlook.append(risks_section(w, score, ind, fund))
    parts.append(section("Outlook & Risks", "\n".join(outlook)))
    parts.extend(notes)
    parts.append(section("Bottom line", bottom_line(w, symbol, score, fund is not None)))
    views = [v for v in (q, hist, ind, fund, fc) if v]
    parts.append(source_line(views))
    return "\n\n".join(p for p in parts if p)


def comparison(w: Writer, items: list[dict[str, Any]], notes: list[str]) -> str:
    symbols = [it["symbol"] for it in items]
    header = "| Metric | " + " | ".join(symbols) + " |"
    sep = "|---|" + "---:|" * len(items)
    rows = []

    def row(label: str, fn: Any) -> None:
        cells = []
        for it in items:
            try:
                cells.append(fn(it))
            except KeyError, TypeError:
                cells.append("n/a")
        rows.append(f"| {label} | " + " | ".join(cells) + " |")

    row("Close", lambda it: money(it["quote"]["close"]))
    row("Day change", lambda it: signed_pct(it["quote"]["changePct"]))
    row("1Y return", lambda it: signed_pct(it["history"]["returnPct"]))
    row("Volatility (ann.)", lambda it: pct(it["history"]["volatilityAnnualizedPct"]))
    row("Max drawdown", lambda it: pct(it["history"]["maxDrawdownPct"]))
    row("Revenue growth", lambda it: signed_pct(it["fundamentals"]["ratios"]["revenueGrowthPct"]))
    row("Operating margin", lambda it: pct(it["fundamentals"]["ratios"]["operatingMarginPct"]))
    table = "\n".join([header, sep, *rows])
    ranked = sorted(
        (it for it in items if it.get("history")), key=lambda it: it["history"]["returnPct"], reverse=True
    )
    takeaways = []
    if len(ranked) >= 2:
        best, worst = ranked[0], ranked[-1]
        takeaways.append(
            f"- **{best['symbol']}** has the stronger 1-year return ({signed_pct(best['history']['returnPct'])} vs "
            f"{signed_pct(worst['history']['returnPct'])} for {worst['symbol']})."
        )
        calm = min(ranked, key=lambda it: it["history"]["volatilityAnnualizedPct"])
        takeaways.append(
            f"- **{calm['symbol']}** has been the less volatile of the group "
            f"({pct(calm['history']['volatilityAnnualizedPct'])} annualized)."
        )
    missing = [it["symbol"] for it in items if not it.get("fundamentals")]
    if missing:
        takeaways.append(
            f"- Fundamentals were unavailable for {', '.join(missing)}, so the comparison leans on price data."
        )
    takeaways.append(
        "- Higher past returns came with their own risks; neither column says which stock will do better next."
    )
    views = [v for it in items for v in (it.get("quote"), it.get("history"), it.get("fundamentals")) if v]
    return "\n\n".join(
        [
            w.pick(
                [
                    f"Side-by-side comparison of {', '.join(symbols)}:",
                    f"Here is how {' and '.join(symbols)} compare on the latest data:",
                ]
            ),
            table,
            section("Takeaways", "\n".join(takeaways)),
            *notes,
            section("Bottom line", w.pick(DISCLAIMER)),
            source_line(views),
        ]
    )

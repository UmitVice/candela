import json
import random
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from typing import Any

from candela_lab.traces import compose, market
from candela_lab.traces.executor import ToolResult

Call = tuple[str, dict[str, Any]]
TurnScript = Generator[list[Call], list[ToolResult], str]


@dataclass
class Turn:
    user: str
    script: Callable[[compose.Writer], TurnScript]


@dataclass
class Plan:
    intent: str
    symbols: list[str]
    turns: list[Turn]
    failures: dict[tuple[str, str], str] = field(default_factory=dict)


def views(results: list[ToolResult]) -> list[dict[str, Any] | None]:
    return [None if r.is_error else r.parsed for r in results]


def errors(results: list[ToolResult]) -> list[dict[str, Any]]:
    return [r.parsed for r in results if r.is_error]


def name_of(symbol: str) -> str:
    return market.NAMES.get(symbol, symbol)


def mention(rng: random.Random, symbol: str) -> str:
    name = name_of(symbol)
    short = name.split(",")[0].replace(" Inc.", "").replace(" Corporation", "").replace("The ", "")
    return rng.choice([symbol, symbol, short, f"{short} ({symbol})", f"${symbol}"])


def unavailable_note(errs: list[dict[str, Any]], what: str) -> str:
    if not errs:
        return ""
    msg = errs[0].get("message", "unavailable")
    return f"> **Note:** {what} could not be retrieved ({msg}), so that part of the analysis is skipped."


ANALYSIS_ASKS = [
    "Analyze {s}",
    "Give me a full analysis of {s}.",
    "What's your take on {s} right now?",
    "Can you break down {s} for me — price, technicals, fundamentals and outlook?",
    "Run a complete equity research overview on {s}",
    "how is {s} looking?",
    "I'd like an analysis of {s} please",
    "Deep dive on {s}",
]
COMPARE_ASKS = [
    "Compare {a} and {b}",
    "{a} vs {b} — which has performed better?",
    "How do {a} and {b} stack up against each other?",
    "Put {a}, {b} side by side for me",
]
TECH_ASKS = [
    "What do the technicals say about {s}?",
    "Is {s} overbought?",
    "Show me the RSI and MACD for {s}",
    "Technical picture for {s}?",
    "Where is {s} relative to its moving averages?",
]
FUND_ASKS = [
    "What do {s}'s fundamentals look like?",
    "How profitable is {s}?",
    "Show me the latest financials for {s}",
    "Revenue growth and margins for {s}?",
    "Is {s}'s balance sheet healthy?",
]
FORECAST_ASKS = [
    "What's the forecast for {s}?",
    "Where could {s} be in a year?",
    "Explain the P10/P50/P90 bands for {s}",
    "Give me the price outlook for {s} over the next 12 months",
]
QUOTE_ASKS = [
    "What's {s} trading at?",
    "Quote for {s}",
    "How did {s} close today?",
    "{s} price?",
]
UNKNOWN_ASKS = [
    "How is {q} doing?",
    "Can you look up {q} for me?",
    "What's the stock price of {q}?",
    "Tell me about {q} shares",
]
ADVICE_ASKS = [
    "Should I put my savings into {s}?",
    "Is {s} a buy right now? I'm 30 and have $20k to invest.",
    "Tell me honestly, should I sell my {s} shares?",
    "I'm retiring next year — should I move everything into {s}?",
]
OFF_TOPIC = [
    ("Write me a poem about the ocean", "creative writing"),
    ("What's a good recipe for banana bread?", "cooking"),
    ("Who won the football game last night?", "sports results"),
    ("Can you help me fix my Python code?", "programming help"),
    ("What's the weather like in Paris?", "weather"),
    ("Plan a 3-day trip to Rome for me", "travel planning"),
]
FOLLOW_UPS = [
    ("And how has it done over 5 years?", "history5y"),
    ("What about the forecast?", "forecast"),
    ("Can you show just the technicals?", "technicals"),
    ("How does that compare with {b}?", "compare"),
    ("What are the main risks?", "risks"),
]
UNKNOWN_COMPANIES = [
    ("Acme Robotics", None),
    ("Zentrix Biotech", None),
    ("Northwind Traders", None),
    ("micro devices", "AMD"),
    ("coca cola", "KO"),
    ("home depot", "HD"),
    ("berkshire", "BRK.B"),
    ("goldman", "GS"),
    ("palantir", "PLTR"),
    ("boeing", "BA"),
]


def analysis_script(symbol: str, history_range: str = "1Y") -> Callable[[compose.Writer], TurnScript]:
    def script(w: compose.Writer) -> TurnScript:
        calls: list[Call] = [
            ("get_quote", {"symbol": symbol}),
            ("get_price_history", {"symbol": symbol, "range": history_range}),
            ("get_technical_indicators", {"symbol": symbol}),
            ("get_fundamentals", {"symbol": symbol}),
            ("get_forecast", {"symbol": symbol}),
        ]
        results = yield calls
        q, hist, ind, fund, fc = views(results)
        if q is None and hist is None and ind is None:
            return failure_answer(w, symbol, errors(results))
        notes = []
        if fund is None:
            notes.append(unavailable_note(errors(results[3:4]), "Fundamentals"))
        return compose.analysis(w, name_of(symbol), symbol, q, hist, ind, fund, fc, [n for n in notes if n])

    return script


def failure_answer(w: compose.Writer, symbol: str, errs: list[dict[str, Any]]) -> str:
    codes = {e.get("error") for e in errs}
    if "not_found" in codes:
        return w.pick(
            [
                f"I couldn't find a US-listed ticker **{symbol}**. Could you double-check the symbol, or tell me the "
                "company name so I can search for it?",
                f"There is no data for **{symbol}** — the symbol was not found. If you meant a different company, "
                "give me its name and I'll look it up.",
            ]
        )
    msg = (
        errs[0].get("message", "the data service did not respond")
        if errs
        else "the data service did not respond"
    )
    return w.pick(
        [
            f"I wasn't able to retrieve market data for **{symbol}** right now ({msg}). Please try again in a "
            "moment; I won't guess at the numbers in the meantime.",
            f"The data request for **{symbol}** failed ({msg}). Without it I can't give you reliable figures, so "
            "let's retry shortly.",
        ]
    )


def technical_script(symbol: str) -> Callable[[compose.Writer], TurnScript]:
    def script(w: compose.Writer) -> TurnScript:
        results = yield [("get_technical_indicators", {"symbol": symbol})]
        (ind,) = views(results)
        if ind is None:
            return failure_answer(w, symbol, errors(results))
        trend, score = compose.trend_section(w, ind, None)
        tone = "constructive" if score >= 2 else "mixed" if score > -2 else "weak"
        return "\n\n".join(
            [
                f"Technical picture for **{symbol}** (close {compose.money(ind['close'])}):",
                compose.section("Trend & Momentum", trend),
                compose.section(
                    "Bottom line",
                    f"On these indicators the short-term setup looks {tone}. Indicators summarize past prices and "
                    "can flip quickly. " + w.pick(compose.DISCLAIMER),
                ),
                compose.source_line([ind]),
            ]
        )

    return script


def fundamentals_script(symbol: str, period: str) -> Callable[[compose.Writer], TurnScript]:
    def script(w: compose.Writer) -> TurnScript:
        args: dict[str, Any] = {"symbol": symbol}
        if period != "annual":
            args["period"] = period
        results = yield [("get_fundamentals", args)]
        (fund,) = views(results)
        if fund is None:
            errs = errors(results)
            if errs and errs[0].get("error") == "not_found":
                return failure_answer(w, symbol, errs)
            msg = errs[0].get("message", "unavailable") if errs else "unavailable"
            follow = yield [("get_quote", {"symbol": symbol})]
            (q,) = views(follow)
            parts = [
                f"Reported financial statements for **{symbol}** aren't available right now ({msg}), so I can't "
                "quote revenue, margins or earnings without guessing."
            ]
            if q:
                parts.append(compose.section("What I can show", compose.snapshot_section(w, q)))
                parts.append(compose.source_line([q]))
            parts.append(
                "Once filings data is available I can walk through growth, profitability and the balance sheet."
            )
            return "\n\n".join(parts)
        return "\n\n".join(
            [
                f"Latest reported fundamentals for **{name_of(symbol)} ({symbol})**:",
                compose.section("Fundamentals", compose.fundamentals_section(w, fund)),
                compose.section(
                    "Bottom line",
                    "These figures describe past periods; the next report can change the picture. "
                    + w.pick(compose.DISCLAIMER),
                ),
                compose.source_line([fund]),
            ]
        )

    return script


def forecast_script(symbol: str) -> Callable[[compose.Writer], TurnScript]:
    def script(w: compose.Writer) -> TurnScript:
        results = yield [("get_forecast", {"symbol": symbol})]
        (fc,) = views(results)
        if fc is None:
            return failure_answer(w, symbol, errors(results))
        explain = w.pick(
            [
                "P10 means one in ten simulated paths ended below that level, P50 is the median, and P90 means nine "
                "in ten ended below it.",
                "Read the bands as a range of plausible outcomes: roughly four in five simulated paths land between "
                "P10 and P90.",
            ]
        )
        return "\n\n".join(
            [
                f"Here is the statistical price outlook for **{symbol}**.",
                compose.section("Outlook", compose.forecast_section(w, fc)),
                explain,
                compose.section("Bottom line", w.pick(compose.DISCLAIMER)),
                compose.source_line([fc]),
            ]
        )

    return script


def quote_script(symbol: str) -> Callable[[compose.Writer], TurnScript]:
    def script(w: compose.Writer) -> TurnScript:
        results = yield [("get_quote", {"symbol": symbol})]
        (q,) = views(results)
        if q is None:
            return failure_answer(w, symbol, errors(results))
        return "\n\n".join(
            [
                f"**{name_of(symbol)} ({symbol})** closed at {compose.money(q['close'])}, "
                f"{compose.signed_pct(q['changePct'])} on the day.",
                compose.snapshot_section(w, q),
                compose.source_line([q]),
            ]
        )

    return script


def history_script(symbol: str, range_: str) -> Callable[[compose.Writer], TurnScript]:
    def script(w: compose.Writer) -> TurnScript:
        results = yield [("get_price_history", {"symbol": symbol, "range": range_})]
        (hist,) = views(results)
        if hist is None:
            return failure_answer(w, symbol, errors(results))
        trend, _ = compose.trend_section(w, None, hist)
        hi, lo = hist["high"], hist["low"]
        return "\n\n".join(
            [
                f"Over the {range_} window, **{symbol}**:",
                trend,
                f"- The high was {compose.money(hi['h'])} on {hi['t']} and the low {compose.money(lo['l'])} on {lo['t']}.",
                compose.source_line([hist]),
            ]
        )

    return script


def compare_script(symbols: list[str]) -> Callable[[compose.Writer], TurnScript]:
    def script(w: compose.Writer) -> TurnScript:
        calls: list[Call] = []
        for s in symbols:
            calls += [
                ("get_quote", {"symbol": s}),
                ("get_price_history", {"symbol": s, "range": "1Y"}),
                ("get_fundamentals", {"symbol": s}),
            ]
        results = yield calls
        vs = views(results)
        items = []
        for i, s in enumerate(symbols):
            q, h, f = vs[3 * i : 3 * i + 3]
            items.append({"symbol": s, "quote": q, "history": h, "fundamentals": f})
        return compose.comparison(w, items, [])

    return script


def risks_script(symbol: str) -> Callable[[compose.Writer], TurnScript]:
    def script(w: compose.Writer) -> TurnScript:
        results = yield [
            ("get_technical_indicators", {"symbol": symbol}),
            ("get_forecast", {"symbol": symbol}),
        ]
        ind, fc = views(results)
        parts = [f"Main risks to keep in mind for **{symbol}**:"]
        parts.append(compose.risks_section(w, 0, ind, None))
        if fc:
            h12 = fc["horizons"][-1]
            parts.append(
                f"- The baseline forecast's 12-month P10 of {compose.money(h12['p10'])} vs a base of "
                f"{compose.money(fc['basePrice'])} shows how large a downside scenario has been historically."
            )
        parts.append(w.pick(compose.DISCLAIMER))
        parts.append(compose.source_line([v for v in (ind, fc) if v]))
        return "\n\n".join(parts)

    return script


def search_script(query: str) -> Callable[[compose.Writer], TurnScript]:
    def script(w: compose.Writer) -> TurnScript:
        results = yield [("search_symbols", {"query": query})]
        (found,) = views(results)
        hits = (found or {}).get("results", [])
        if not hits:
            return w.pick(
                [
                    f"I couldn't find a US-listed company matching **{query}**. It may be private, listed abroad, "
                    "or spelled differently — can you share the ticker or the exact name?",
                    f"No US-listed stock matched **{query}**. If it trades under another name or on a foreign "
                    "exchange, tell me more and I'll try again.",
                ]
            )
        top = hits[0]
        quote = yield [("get_quote", {"symbol": top["symbol"]})]
        (q,) = views(quote)
        others = ", ".join(f"{h['symbol']} ({h['name']})" for h in hits[1:3])
        lead = f"**{query}** matches **{top['name']} ({top['symbol']}, {top['exchange']})**."
        if others:
            lead += f" Other matches: {others}."
        if q is None:
            return lead + " " + failure_answer(w, top["symbol"], errors(quote))
        return "\n\n".join([lead, compose.snapshot_section(w, q), compose.source_line([q])])

    return script


def advice_script(symbol: str, with_data: bool) -> Callable[[compose.Writer], TurnScript]:
    def script(w: compose.Writer) -> TurnScript:
        parts = [
            w.pick(
                [
                    "I can't tell you whether to buy or sell — that depends on your goals, time horizon, other "
                    "holdings and risk tolerance, which only you (ideally with a licensed financial adviser) can weigh.",
                    "I don't give personal buy/sell/hold recommendations, but I can lay out the factors that matter "
                    "for a decision like this.",
                ]
            )
        ]
        views_used: list[dict[str, Any]] = []
        if with_data:
            results = yield [("get_quote", {"symbol": symbol}), ("get_forecast", {"symbol": symbol})]
            q, fc = views(results)
            if q:
                views_used.append(q)
                parts.append(compose.section("Where the stock stands", compose.snapshot_section(w, q)))
            if fc:
                views_used.append(fc)
                h12 = fc["horizons"][-1]
                parts.append(
                    f"The statistical baseline puts the 12-month range between {compose.money(h12['p10'])} (P10) "
                    f"and {compose.money(h12['p90'])} (P90) — a reminder of how uncertain single-stock outcomes are."
                )
        parts.append(
            compose.section(
                "Factors to weigh",
                "- **Diversification:** concentrating savings in one stock raises the risk of large losses.\n"
                "- **Time horizon:** money you need within a few years is usually kept away from volatile assets.\n"
                "- **Emergency fund and debt:** most guidance puts these before investing.\n"
                "- **Costs and taxes:** trading and capital-gains taxes affect real returns.",
            )
        )
        parts.append(
            "A licensed financial professional can look at your full situation. I'm happy to walk through the "
            f"data on {symbol} in more detail if that helps."
        )
        if views_used:
            parts.append(compose.source_line(views_used))
        return "\n\n".join(parts)

    return script


def off_topic_script(topic: str) -> Callable[[compose.Writer], TurnScript]:
    def script(w: compose.Writer) -> TurnScript:
        if False:
            yield []
        return w.pick(
            [
                f"I'm Candela, an equity research assistant, so {topic} is outside what I can help with. I can "
                "analyze US-listed stocks — quotes, trends, technicals, fundamentals and forecasts. Want me to look "
                "at a ticker?",
                f"That's outside my lane — I focus on US-listed stocks and can't help with {topic}. Try asking me "
                'something like "Analyze AAPL" or "Compare MSFT and GOOGL".',
            ]
        )

    return script


INTENT_WEIGHTS = {
    "analysis": 0.17,
    "analysis_follow_up": 0.17,
    "comparison": 0.09,
    "technical": 0.10,
    "fundamentals": 0.07,
    "fundamentals_missing": 0.05,
    "forecast": 0.07,
    "quote": 0.05,
    "unknown_company": 0.07,
    "tool_failure": 0.06,
    "personal_advice": 0.06,
    "off_topic": 0.04,
}


def plan(rng: random.Random, symbols: list[str], fund_ok: Callable[[str], bool]) -> Plan:
    intent = rng.choices(list(INTENT_WEIGHTS), weights=list(INTENT_WEIGHTS.values()))[0]
    s = rng.choice(symbols)
    stocks = [x for x in symbols if x not in market.ETF]
    if intent in ("fundamentals", "fundamentals_missing"):
        pool = [x for x in stocks if fund_ok(x) == (intent == "fundamentals")] or stocks
        s = rng.choice(pool)
    m = mention(rng, s)
    if intent == "analysis":
        return Plan(intent, [s], [Turn(rng.choice(ANALYSIS_ASKS).format(s=m), analysis_script(s))])
    if intent == "analysis_follow_up":
        turns = [Turn(rng.choice(ANALYSIS_ASKS).format(s=m), analysis_script(s))]
        for text, kind in rng.sample(FOLLOW_UPS, k=rng.choice([1, 1, 2])):
            if kind == "history5y":
                turns.append(Turn(text, history_script(s, "5Y")))
            elif kind == "forecast":
                turns.append(Turn(text, forecast_script(s)))
            elif kind == "technicals":
                turns.append(Turn(text, technical_script(s)))
            elif kind == "risks":
                turns.append(Turn(text, risks_script(s)))
            else:
                b = rng.choice([x for x in symbols if x != s])
                turns.append(Turn(text.format(b=mention(rng, b)), compare_script([s, b])))
        return Plan(intent, [s], turns)
    if intent == "comparison":
        a, b = rng.sample(symbols, 2)
        ask = rng.choice(COMPARE_ASKS).format(a=mention(rng, a), b=mention(rng, b))
        turns = [Turn(ask, compare_script([a, b]))]
        if rng.random() < 0.25:
            turns.append(Turn(f"Zoom in on {b}'s technicals", technical_script(b)))
        return Plan(intent, [a, b], turns)
    if intent == "technical":
        turns = [Turn(rng.choice(TECH_ASKS).format(s=m), technical_script(s))]
        if rng.random() < 0.3:
            turns.append(Turn("And the forecast?", forecast_script(s)))
        return Plan(intent, [s], turns)
    if intent in ("fundamentals", "fundamentals_missing"):
        period = "quarterly" if rng.random() < 0.3 else "annual"
        return Plan(intent, [s], [Turn(rng.choice(FUND_ASKS).format(s=m), fundamentals_script(s, period))])
    if intent == "forecast":
        turns = [Turn(rng.choice(FORECAST_ASKS).format(s=m), forecast_script(s))]
        if rng.random() < 0.3:
            turns.append(Turn("What are the main risks?", risks_script(s)))
        return Plan(intent, [s], turns)
    if intent == "quote":
        return Plan(intent, [s], [Turn(rng.choice(QUOTE_ASKS).format(s=m), quote_script(s))])
    if intent == "unknown_company":
        query, _ = rng.choice(UNKNOWN_COMPANIES)
        return Plan(intent, [], [Turn(rng.choice(UNKNOWN_ASKS).format(q=query), search_script(query))])
    if intent == "tool_failure":
        if rng.random() < 0.4:
            bad = rng.choice(["XYZQ", "FOOB", "NVDQ", "APLE1", "QQQX"])
            return Plan(intent, [bad], [Turn(rng.choice(QUOTE_ASKS).format(s=bad), quote_script(bad))])
        tool = rng.choice(["get_quote", "get_technical_indicators", "get_forecast"])
        script = {
            "get_quote": quote_script,
            "get_technical_indicators": technical_script,
            "get_forecast": forecast_script,
        }[tool](s)
        asks = {
            "get_quote": QUOTE_ASKS,
            "get_technical_indicators": TECH_ASKS,
            "get_forecast": FORECAST_ASKS,
        }[tool]
        return Plan(
            intent, [s], [Turn(rng.choice(asks).format(s=m), script)], {(tool, s): "data_unavailable"}
        )
    if intent == "personal_advice":
        return Plan(
            intent,
            [s],
            [Turn(rng.choice(ADVICE_ASKS).format(s=m), advice_script(s, with_data=rng.random() < 0.6))],
        )
    text, topic = rng.choice(OFF_TOPIC)
    return Plan("off_topic", [], [Turn(text, off_topic_script(topic))])


def tool_call_message(calls: list[Call], start: int) -> dict[str, Any]:
    return {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"id": f"call_{start + i}", "type": "function", "function": {"name": n, "arguments": a}}
            for i, (n, a) in enumerate(calls)
        ],
    }


def tool_messages(calls: list[Call], results: list[ToolResult], start: int) -> list[dict[str, Any]]:
    return [
        {"role": "tool", "tool_call_id": f"call_{start + i}", "name": n, "content": r.model_view}
        for i, ((n, _), r) in enumerate(zip(calls, results, strict=True))
    ]


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)

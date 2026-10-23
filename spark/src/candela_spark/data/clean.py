import re
from dataclasses import dataclass

_STOPWORDS = frozenset(
    [
        "the",
        "of",
        "and",
        "to",
        "in",
        "a",
        "is",
        "that",
        "for",
        "it",
        "as",
        "was",
        "with",
        "be",
        "by",
        "on",
        "not",
        "he",
        "i",
        "this",
        "are",
        "or",
        "his",
        "from",
        "at",
        "which",
        "but",
        "have",
        "an",
        "they",
        "you",
        "were",
        "her",
        "she",
        "there",
        "their",
        "one",
        "all",
        "we",
        "can",
        "has",
        "been",
        "more",
        "if",
        "will",
        "its",
        "would",
        "who",
        "so",
        "also",
        "no",
        "other",
        "than",
        "into",
        "some",
        "these",
        "only",
        "may",
        "such",
    ]
)
_FINANCE_TERMS = frozenset(
    [
        "revenue",
        "revenues",
        "earnings",
        "profit",
        "profits",
        "stock",
        "stocks",
        "shares",
        "shareholder",
        "shareholders",
        "dividend",
        "dividends",
        "bond",
        "bonds",
        "equity",
        "equities",
        "asset",
        "assets",
        "liability",
        "liabilities",
        "investor",
        "investors",
        "investment",
        "investments",
        "inflation",
        "interest",
        "rates",
        "bank",
        "banks",
        "banking",
        "loan",
        "loans",
        "credit",
        "debt",
        "mortgage",
        "market",
        "markets",
        "economy",
        "economic",
        "economics",
        "gdp",
        "monetary",
        "fiscal",
        "tax",
        "taxes",
        "budget",
        "financial",
        "finance",
        "capital",
        "portfolio",
        "securities",
        "fund",
        "funds",
        "trading",
        "trader",
        "exchange",
        "currency",
        "balance",
        "cash",
        "accounting",
        "audit",
        "valuation",
        "price",
        "prices",
        "recession",
        "unemployment",
        "treasury",
        "federal",
        "reserve",
        "insurance",
        "premium",
        "yield",
        "yields",
        "income",
        "expenses",
        "margin",
    ]
)
_WS = re.compile("[ \t\u00a0]+")
_MANY_NL = re.compile(r"\n{3,}")
_EDGAR_NOISE = re.compile(
    r"^\s*(table of contents|index|page \d+|\d+|-+\s*\d+\s*-+|\(?continued\)?|part [ivx]+)\s*$", re.IGNORECASE
)


@dataclass(frozen=True)
class FilterResult:
    keep: bool
    reason: str


def normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = "\n".join(_WS.sub(" ", line).strip() for line in text.split("\n"))
    return _MANY_NL.sub("\n\n", text).strip()


def clean_edgar(text: str) -> str:
    lines = [ln for ln in normalize(text).split("\n") if not _EDGAR_NOISE.match(ln)]
    return "\n".join(lines).strip()


def quality(text: str, kind: str, source: str) -> FilterResult:
    n = len(text)
    if n < 300:
        return FilterResult(False, "short")
    words = text.split()
    if len(words) < 50:
        return FilterResult(False, "few_words")
    lower = [w.lower().strip(".,;:!?\"'()[]") for w in words[:3000]]
    stop_ratio = sum(1 for w in lower if w in _STOPWORDS) / len(lower)
    min_stop = 0.02 if source == "finemath" else 0.08
    if stop_ratio < min_stop:
        return FilterResult(False, "not_english_prose")
    alpha_ratio = sum(1 for w in lower if w.isalpha()) / len(lower)
    if source != "finemath" and alpha_ratio < 0.6:
        return FilterResult(False, "low_alpha")
    mean_len = sum(len(w) for w in lower) / len(lower)
    if not 2.5 <= mean_len <= 12:
        return FilterResult(False, "word_length")
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if len(lines) >= 10 and len(set(lines)) / len(lines) < 0.7:
        return FilterResult(False, "repeated_lines")
    if kind == "finance" and n < 1000:
        return FilterResult(False, "short_section")
    return FilterResult(True, "ok")


def finance_score(text: str) -> tuple[int, float]:
    words = [w.lower().strip(".,;:!?\"'()[]") for w in text.split()[:2000]]
    hits = [w for w in words if w in _FINANCE_TERMS]
    return len(set(hits)), len(hits) / max(1, len(words))


def is_finance(text: str) -> bool:
    distinct, density = finance_score(text)
    return distinct >= 8 and density >= 0.025

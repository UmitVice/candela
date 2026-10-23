import json
import re
from dataclasses import dataclass
from typing import Any

# A "data number" is a value a reader would take as a fact: it has a decimal point, a %, $ or K/M/B/T unit, or is an
# integer of at least 1000. Small bare integers are vocabulary ("14-day", "3 months", "RSI above 70") and are ignored.
NUMBER_RE = re.compile(
    r"(?<![\w.])(?P<sign>[+\-−])?(?P<cur>\$)?(?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)"
    r"(?P<unit>\s?[KMBT]\b)?(?P<pct>%)?(?![\w])"
)
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
IDENT_RE = re.compile(r"\b[A-Za-z]+\(?\d+\)?|\d+-(?:day|week|month|year|session)s?\b|\d+(?:st|nd|rd|th)\b")
UNITS = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}


@dataclass(frozen=True)
class Mention:
    text: str
    value: float
    decimals: int
    unit: float


def data_numbers(text: str) -> list[Mention]:
    cleaned = DATE_RE.sub(" ", IDENT_RE.sub(" ", text))
    cleaned = re.sub(r"^\s*\d+\.\s", " ", cleaned, flags=re.M)
    out = []
    for m in NUMBER_RE.finditer(cleaned):
        raw = m.group("num").replace(",", "")
        has_decimal = "." in raw
        unit = (m.group("unit") or "").strip()
        if not (has_decimal or unit or m.group("pct") or m.group("cur") or float(raw) >= 1000):
            continue
        if (
            not has_decimal
            and not unit
            and not m.group("pct")
            and not m.group("cur")
            and 1900 <= float(raw) <= 2100
        ):
            continue
        value = float(raw)
        if m.group("sign") in ("-", "−"):
            value = -value
        decimals = len(raw.split(".")[1]) if has_decimal else 0
        out.append(Mention(m.group(0).strip(), value, decimals, UNITS.get(unit, 1.0)))
    return out


def _walk(obj: Any, out: list[float], strings: list[str]) -> None:
    if isinstance(obj, bool):
        return
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, str):
        strings.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk(v, out, strings)
    elif isinstance(obj, list):
        for v in obj:
            _walk(v, out, strings)


def source_numbers(tool_contents: list[str]) -> tuple[list[float], set[str]]:
    nums: list[float] = []
    strings: list[str] = []
    for content in tool_contents:
        try:
            _walk(json.loads(content), nums, strings)
        except json.JSONDecodeError:
            strings.append(content)
    for s in strings:
        for m in NUMBER_RE.finditer(s):
            v = float(m.group("num").replace(",", ""))
            nums.append(-v if m.group("sign") in ("-", "−") else v)
    dates = {d for s in [*strings, *tool_contents] for d in DATE_RE.findall(s)}
    return nums, dates


def grounded(mention: Mention, nums: list[float], derived: set[str]) -> bool:
    if mention.text.lstrip("+-−$") in derived or mention.text in derived:
        return True
    for t in nums:
        for cand in (t, -t):
            if mention.unit != 1.0:
                if cand != 0 and abs(mention.value * mention.unit - cand) / abs(cand) <= 0.005:
                    return True
            elif round(cand, mention.decimals) == mention.value:
                return True
    stripped = re.sub(r"[^\d.]", "", mention.text)
    return stripped in derived


def grounding_report(
    answer: str, tool_contents: list[str], derived: list[str] | None = None
) -> dict[str, Any]:
    nums, dates = source_numbers(tool_contents)
    derived_set = set(derived or [])
    mentions = data_numbers(answer)
    ungrounded = [m.text for m in mentions if not grounded(m, nums, derived_set)]
    bad_dates = [d for d in DATE_RE.findall(answer) if d not in dates]
    total = len(mentions) + len(DATE_RE.findall(answer))
    bad = len(ungrounded) + len(bad_dates)
    return {
        "numbers": total,
        "ungrounded": ungrounded + bad_dates,
        "rate": 1.0 if total == 0 else (total - bad) / total,
    }

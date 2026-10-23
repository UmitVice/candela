import re
from collections import Counter
from typing import Any

from candela_lab.data.common import Example

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?<!\w)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}(?!\w)")
SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CARD_RE = re.compile(r"\b(?:\d[ -]?){13,19}\b")
IPV4_RE = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
REFUSAL_RE = re.compile(
    r"\bas an ai (language )?model\b|\bi cannot browse\b|\bi'm sorry, but i can't\b", re.I
)
REPEAT_RE = re.compile(r"(.{20,}?)\1{4,}", re.S)


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def scrub_text(text: str, counts: Counter[str]) -> str:
    def sub(pattern: re.Pattern[str], repl: str, kind: str, s: str) -> str:
        def _r(m: re.Match[str]) -> str:
            counts[kind] += 1
            return repl

        return pattern.sub(_r, s)

    text = sub(EMAIL_RE, "[email]", "email", text)
    text = sub(SSN_RE, "[ssn]", "ssn", text)

    def card(m: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", m.group(0))
        if 13 <= len(digits) <= 19 and _luhn(digits) and len(set(digits)) > 2:
            counts["card"] += 1
            return "[card]"
        return m.group(0)

    text = CARD_RE.sub(card, text)
    text = sub(PHONE_RE, "[phone]", "phone", text)
    return sub(IPV4_RE, "[ip]", "ip", text)


def scrub(example: Example, counts: Counter[str]) -> Example:
    for m in example["messages"]:
        if m["role"] in ("user", "assistant", "system") and isinstance(m.get("content"), str):
            m["content"] = scrub_text(m["content"], counts)
    return example


def quality_issue(example: Example) -> str | None:
    msgs: list[dict[str, Any]] = example["messages"]
    if not msgs or msgs[-1]["role"] != "assistant":
        return "no_final_assistant"
    if not any(m["role"] == "user" for m in msgs):
        return "no_user"
    for m in msgs:
        content = m.get("content")
        if m["role"] == "assistant":
            has_calls = bool(m.get("tool_calls"))
            if not has_calls and not (isinstance(content, str) and content.strip()):
                return "empty_assistant"
            if isinstance(content, str):
                if REFUSAL_RE.search(content):
                    return "boilerplate_refusal"
                if REPEAT_RE.search(content):
                    return "repetition"
            for tc in m.get("tool_calls") or []:
                if not isinstance(tc["function"].get("arguments"), dict):
                    return "bad_tool_arguments"
        elif m["role"] == "user" and not (isinstance(content, str) and content.strip()):
            return "empty_user"
    final = msgs[-1].get("content") or ""
    if isinstance(final, str) and final:
        letters = sum(c.isalpha() for c in final)
        ascii_letters = sum(c.isascii() and c.isalpha() for c in final)
        if letters > 50 and ascii_letters / letters < 0.8:
            return "non_english"
    return None

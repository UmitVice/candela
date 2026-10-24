"""Strict IFEval checkers (Zhou et al., 2023), re-implemented from the published instruction definitions.
`language:response_language` needs a language detector and is skipped; prompts that use it are excluded."""

import json
import re
from collections.abc import Callable
from typing import Any

SKIPPED = {"language:response_language"}
WORD_RE = re.compile(r"\b\w+\b")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])")


def _compare(count: int, relation: str | None, target: int) -> bool:
    return count < target if relation == "less than" else count >= target


def _words(text: str) -> list[str]:
    return WORD_RE.findall(text)


def _sentences(text: str) -> int:
    parts = [p for p in SENTENCE_RE.split(text.strip()) if p.strip()]
    return len(parts)


def _keywords_existence(r: str, kw: dict[str, Any]) -> bool:
    return all(re.search(re.escape(k), r, re.I) for k in kw["keywords"])


def _keywords_frequency(r: str, kw: dict[str, Any]) -> bool:
    return _compare(len(re.findall(re.escape(kw["keyword"]), r, re.I)), kw["relation"], kw["frequency"])


def _forbidden_words(r: str, kw: dict[str, Any]) -> bool:
    return not any(re.search(rf"\b{re.escape(w)}\b", r, re.I) for w in kw["forbidden_words"])


def _letter_frequency(r: str, kw: dict[str, Any]) -> bool:
    return _compare(r.lower().count(kw["letter"].lower()), kw["let_relation"], kw["let_frequency"])


def _number_sentences(r: str, kw: dict[str, Any]) -> bool:
    return _compare(_sentences(r), kw["relation"], kw["num_sentences"])


def _number_paragraphs(r: str, kw: dict[str, Any]) -> bool:
    parts = re.split(r"\s?\*\*\*\s?", r)
    if any(not p.strip() for p in parts[1:-1]):
        return False
    return len([p for p in parts if p.strip()]) == kw["num_paragraphs"]


def _number_words(r: str, kw: dict[str, Any]) -> bool:
    return _compare(len(_words(r)), kw["relation"], kw["num_words"])


def _nth_paragraph_first_word(r: str, kw: dict[str, Any]) -> bool:
    paragraphs = [p for p in re.split(r"\n\n", r) if p.strip()]
    nth = kw["nth_paragraph"]
    if len(paragraphs) != kw["num_paragraphs"] or nth > len(paragraphs):
        return False
    first = paragraphs[nth - 1].strip().split()
    word = re.sub(r"[^\w]", "", first[0]).lower() if first else ""
    return word == kw["first_word"].lower()


def _placeholders(r: str, kw: dict[str, Any]) -> bool:
    return len(re.findall(r"\[.*?\]", r)) >= kw["num_placeholders"]


def _postscript(r: str, kw: dict[str, Any]) -> bool:
    marker = kw["postscript_marker"].strip().lower()
    if marker == "p.s.":
        pattern = r"\s*p\.\s?s\..*$"
    elif marker == "p.p.s":
        pattern = r"\s*p\.\s?p\.\s?s.*$"
    else:
        pattern = r"\s*" + re.escape(marker) + r".*$"
    return bool(re.findall(pattern, r.lower(), flags=re.M))


def _bullets(r: str, kw: dict[str, Any]) -> bool:
    stars = re.findall(r"^\s*\*[^\*].*$", r, flags=re.M)
    dashes = re.findall(r"^\s*-.*$", r, flags=re.M)
    return len(stars) + len(dashes) == kw["num_bullets"]


def _constrained(r: str, _kw: dict[str, Any]) -> bool:
    return any(o in r.strip() for o in ("My answer is yes.", "My answer is no.", "My answer is maybe."))


def _highlights(r: str, kw: dict[str, Any]) -> bool:
    single = [h for h in re.findall(r"\*[^\n\*]*\*", r) if h.strip("*").strip()]
    double = [
        h for h in re.findall(r"\*\*[^\n\*]*\*\*", r) if h.removeprefix("**").removesuffix("**").strip()
    ]
    return len(single) + len(double) >= kw["num_highlights"]


def _sections(r: str, kw: dict[str, Any]) -> bool:
    parts = re.split(r"\s?" + re.escape(kw["section_spliter"]) + r"\s?\d+\s?", r)
    return len(parts) - 1 >= kw["num_sections"]


def _json(r: str, _kw: dict[str, Any]) -> bool:
    body = r.strip()
    for prefix in ("```json", "```Json", "```JSON", "```"):
        body = body.removeprefix(prefix)
    body = body.removesuffix("```").strip()
    try:
        json.loads(body)
    except ValueError:
        return False
    return True


def _title(r: str, _kw: dict[str, Any]) -> bool:
    return any(t.lstrip("<").rstrip(">").strip() for t in re.findall(r"<<[^\n]+>>", r))


def _two_responses(r: str, _kw: dict[str, Any]) -> bool:
    parts = [p.strip() for p in r.split("******")]
    valid = [p for p in parts if p]
    return len(parts) == 2 and len(valid) == 2 and valid[0] != valid[1]


def _repeat_prompt(r: str, kw: dict[str, Any]) -> bool:
    return r.strip().lower().startswith(kw["prompt_to_repeat"].strip().lower())


def _end_checker(r: str, kw: dict[str, Any]) -> bool:
    return r.strip().strip('"').lower().endswith(kw["end_phrase"].strip().lower())


def _quotation(r: str, _kw: dict[str, Any]) -> bool:
    s = r.strip()
    return len(s) > 1 and s[0] == '"' and s[-1] == '"'


def _capital_words(r: str, kw: dict[str, Any]) -> bool:
    count = sum(1 for w in _words(r) if w.isupper())
    return _compare(count, kw["capital_relation"], kw["capital_frequency"])


CHECKERS: dict[str, Callable[[str, dict[str, Any]], bool]] = {
    "keywords:existence": _keywords_existence,
    "keywords:frequency": _keywords_frequency,
    "keywords:forbidden_words": _forbidden_words,
    "keywords:letter_frequency": _letter_frequency,
    "length_constraints:number_sentences": _number_sentences,
    "length_constraints:number_paragraphs": _number_paragraphs,
    "length_constraints:number_words": _number_words,
    "length_constraints:nth_paragraph_first_word": _nth_paragraph_first_word,
    "detectable_content:number_placeholders": _placeholders,
    "detectable_content:postscript": _postscript,
    "detectable_format:number_bullet_lists": _bullets,
    "detectable_format:constrained_response": _constrained,
    "detectable_format:number_highlighted_sections": _highlights,
    "detectable_format:multiple_sections": _sections,
    "detectable_format:json_format": _json,
    "detectable_format:title": _title,
    "combination:two_responses": _two_responses,
    "combination:repeat_prompt": _repeat_prompt,
    "startend:end_checker": _end_checker,
    "startend:quotation": _quotation,
    "change_case:capital_word_frequency": _capital_words,
    "change_case:english_capital": lambda r, _kw: r.isupper(),
    "change_case:english_lowercase": lambda r, _kw: r.islower(),
    "punctuation:no_comma": lambda r, _kw: "," not in r,
}


def supported(instruction_ids: list[str]) -> bool:
    return not (set(instruction_ids) & SKIPPED) and all(i in CHECKERS for i in instruction_ids)


def check(response: str, instruction_ids: list[str], kwargs: list[dict[str, Any]]) -> list[bool]:
    out = []
    for iid, kw in zip(instruction_ids, kwargs, strict=True):
        clean = {k: v for k, v in (kw or {}).items() if v is not None}
        try:
            out.append(bool(response.strip()) and CHECKERS[iid](response, clean))
        except KeyError, TypeError, re.error:
            out.append(False)
    return out

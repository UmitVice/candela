import json
import re
from collections import Counter
from typing import Any

from sklearn.metrics import f1_score

ANSWER_RE = re.compile(r"answer\s*[:=]\s*\**\s*([^\n*]+)", re.I)
NUM_RE = re.compile(r"[-−]?\$?\d[\d,]*(?:\.\d+)?%?")
THINK_RE = re.compile(r"<think>.*?</think>|<\|channel>.*?<channel\|>", re.S)


def strip_reasoning(text: str) -> str:
    return THINK_RE.sub("", text).strip()


def parse_label(text: str, choices: list[str]) -> str:
    t = strip_reasoning(text).lower()
    positions = {c: m.start() for c in choices if (m := re.search(rf"\b{re.escape(c)}\b", t))}
    aliases = {"bullish": "positive", "bearish": "negative"}
    for alias, target in aliases.items():
        if target in choices and target not in positions and (m := re.search(rf"\b{alias}\b", t)):
            positions[target] = m.start()
    if not positions:
        return "unparsed"
    return min(positions, key=lambda c: positions[c])


def classification_scores(golds: list[str], preds: list[str], average: str) -> dict[str, float]:
    labels = sorted(set(golds))
    f1 = f1_score(golds, preds, labels=labels, average=average, zero_division=0)  # type: ignore[arg-type]
    acc = sum(g == p for g, p in zip(golds, preds, strict=True)) / max(len(golds), 1)
    return {"f1": float(f1), "accuracy": acc, "unparsed": preds.count("unparsed") / max(len(preds), 1)}


def to_number(text: str) -> float | None:
    s = text.strip().replace("−", "-").replace("$", "").replace(",", "").rstrip("%").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_numeric(text: str) -> float | None:
    t = strip_reasoning(text)
    m = ANSWER_RE.findall(t)
    candidates = NUM_RE.findall(m[-1]) if m else []
    if candidates:
        return to_number(candidates[0])
    candidates = NUM_RE.findall(t)
    return to_number(candidates[-1]) if candidates else None


def numeric_match(pred: float | None, gold: float | None, rel_tol: float = 0.01) -> bool:
    """Tolerant exact match: 1% relative (or 0.01 absolute for small values); a percentage may be stated as a ratio
    or as percent (FinQA stores 14.1% as 0.141), so both scalings are accepted."""
    if pred is None or gold is None:
        return False
    options = [gold, gold * 100, gold / 100]
    for g in options:
        if abs(pred - g) <= max(rel_tol * abs(g), 0.01) or abs(round(pred, 2) - round(g, 2)) < 1e-9:
            return True
    return False


def gold_number(answer: str) -> float | None:
    found = NUM_RE.findall(answer)
    return to_number(found[0]) if found else None


def extract_tool_calls(text: str, family: str) -> tuple[list[dict[str, Any]], int]:
    """Returns (calls, malformed) from raw generated text for the model family's tool-call syntax."""
    if family == "gemma4":
        from mlx_lm.tool_parsers import gemma4 as parser

        start, end = parser.tool_call_start, parser.tool_call_end
    else:
        from mlx_lm.tool_parsers import json_tools as parser

        start, end = parser.tool_call_start, parser.tool_call_end
    calls: list[dict[str, Any]] = []
    malformed = 0
    for seg in text.split(start)[1:]:
        body = seg.split(end, 1)[0]
        try:
            parsed = parser.parse_tool_call(body)
        except ValueError, json.JSONDecodeError, KeyError, TypeError:
            malformed += 1
            continue
        for p in parsed if isinstance(parsed, list) else [parsed]:
            if isinstance(p, dict) and "name" in p:
                args = p.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        malformed += 1
                        continue
                calls.append({"name": p["name"], "arguments": args})
            else:
                malformed += 1
    return calls, malformed


def tool_choice(gold: list[str], pred: list[str]) -> tuple[int, int, int]:
    g, p = Counter(gold), Counter(pred)
    tp = sum((g & p).values())
    return tp, sum(p.values()) - tp, sum(g.values()) - tp


def prf(tp: int, fp: int, fn: int) -> dict[str, float]:
    precision = tp / (tp + fp) if tp + fp else (1.0 if fn == 0 else 0.0)
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}

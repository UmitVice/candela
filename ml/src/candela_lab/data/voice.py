import math
import random
import re
from typing import Any

SENTIMENT_OPENERS = [
    "Here is how I read the tone of that text.",
    "Reading it as a market participant would:",
    "Short take on the sentiment:",
    "My read:",
]

SENTIMENT_REASONS = {
    "negative": [
        "it describes a development that is likely to weigh on the company or the market it mentions",
        "the wording points to downside risk, such as weaker demand, cuts or disappointing results",
        "the news is framed as a setback for the business or its shareholders",
    ],
    "positive": [
        "it describes a development that is likely to support the company or the market it mentions",
        "the wording points to upside, such as stronger demand, upgrades or better-than-expected results",
        "the news is framed as a win for the business or its shareholders",
    ],
    "neutral": [
        "it reports information without a clear positive or negative implication",
        "the text is mostly factual and does not tilt the outlook either way",
        "nothing in it clearly changes the outlook for the company or market",
    ],
}

SENTIMENT_QUESTIONS = [
    "What is the sentiment of this financial headline? Answer positive, negative or neutral.\n\n{text}",
    "Classify the market sentiment of the following text as positive, negative or neutral:\n{text}",
    'Is this news bullish, bearish or neutral for the stock it mentions?\n\n"{text}"',
    "Sentiment check (positive / negative / neutral):\n{text}",
]

TOPIC_QUESTIONS = [
    "Which topic best describes this financial news headline? Choose one of: {options}.\n\n{text}",
    "Categorise the headline below into one of these topics: {options}.\nHeadline: {text}",
    'What is this headline mainly about? Options: {options}.\n"{text}"',
]

NUMERIC_INTROS = [
    "Answer the question using the filing excerpt below.",
    "Use the financial statement excerpt to answer the question.",
    "Based on the following excerpt from a company's annual report, answer the question.",
    "Here is an excerpt from a 10-K. Please answer the question at the end.",
]

NUMERIC_CLOSERS = [
    "**Answer: {answer}**",
    "So the answer is **{answer}**.",
    "**{answer}**",
    "Result: **{answer}**.",
]

OPS = {
    "add": "+",
    "subtract": "−",
    "multiply": "×",
    "divide": "÷",
    "exp": "^",
    "greater": ">",
}


def sentiment_sample(text: str, label: str, rng: random.Random) -> tuple[str, str]:
    question = rng.choice(SENTIMENT_QUESTIONS).format(text=text.strip())
    reason = rng.choice(SENTIMENT_REASONS[label])
    alias = {"negative": "bearish", "positive": "bullish", "neutral": "neutral"}[label]
    head = f"**{label.capitalize()}**" + (f" ({alias})" if alias != label else "")
    answer = f"{rng.choice(SENTIMENT_OPENERS)} {head}: {reason}."
    if rng.random() < 0.3:
        answer += " This is a read of the wording only, not a view on the stock."
    return question, answer


def topic_sample(text: str, topic: str, options: list[str], rng: random.Random) -> tuple[str, str]:
    shown = options[:]
    rng.shuffle(shown)
    question = rng.choice(TOPIC_QUESTIONS).format(options=", ".join(shown), text=text.strip())
    answer = rng.choice(
        [
            f"**{topic}**.",
            f"The headline is best described as **{topic}**.",
            f"Topic: **{topic}**.",
        ]
    )
    return question, answer


def table_markdown(table: list[list[str]], max_rows: int = 40) -> str:
    rows = [[re.sub(r"\s+", " ", str(c)).strip() for c in r] for r in table[:max_rows] if r]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    header = "| " + " | ".join(rows[0]) + " |"
    sep = "|" + "---|" * width
    body = ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join([header, sep, *body])


def context_block(pre: list[str], table: list[list[str]], post: list[str]) -> str:
    parts = []
    pre_txt = " ".join(s.strip() for s in pre if s.strip() and s.strip() != ".")
    post_txt = " ".join(s.strip() for s in post if s.strip() and s.strip() != ".")
    if pre_txt:
        parts.append(pre_txt)
    if table:
        parts.append(table_markdown(table))
    if post_txt:
        parts.append(post_txt)
    return "\n\n".join(parts)


def fmt_number(x: float) -> str:
    if math.isnan(x) or math.isinf(x):
        return str(x)
    if abs(x) >= 1000:
        return f"{x:,.2f}".rstrip("0").rstrip(".")
    if float(x).is_integer():
        return str(int(x))
    return f"{x:.4f}".rstrip("0").rstrip(".")


def _arg(token: str, results: list[str]) -> str:
    token = token.strip()
    if token.startswith("#") and token[1:].isdigit():
        idx = int(token[1:])
        return results[idx] if idx < len(results) else token
    if token.startswith("const_"):
        value = token[6:]
        return "1000000" if value == "m1" else value.replace("_", ".")
    try:
        return fmt_number(float(token.replace(",", "")))
    except ValueError:
        return token


def program_steps(program: str) -> list[tuple[str, str, str]]:
    calls = re.findall(r"([a-z_]+)\(([^()]*)\)", program)
    return [(op, *(a.strip() for a in ([*args.split(","), ""])[:2])) for op, args in calls]  # type: ignore[misc]


def _evaluate(op: str, a: float, b: float) -> float | None:
    try:
        match op:
            case "add":
                return a + b
            case "subtract":
                return a - b
            case "multiply":
                return a * b
            case "divide":
                return a / b
            case "exp":
                return a**b
            case "greater":
                return float(a > b)
    except ZeroDivisionError, OverflowError:
        return None
    return None


def render_program(program: str) -> list[str]:
    lines: list[str] = []
    results: list[str] = []
    for op, a, b in program_steps(program):
        if op.startswith("table_"):
            lines.append(f"{op.removeprefix('table_')} of the '{a}' row")
            results.append(f"{op}({a})")
            continue
        sym = OPS.get(op)
        left, right = _arg(a, results), _arg(b, results)
        value: float | None = None
        try:
            value = _evaluate(op, float(left.replace(",", "")), float(right.replace(",", "")))
        except ValueError:
            value = None
        shown = fmt_number(value) if value is not None else "?"
        if sym is None:
            lines.append(f"{op}({left}, {right}) = {shown}")
        else:
            lines.append(f"{left} {sym} {right} = {shown}")
        results.append(shown)
    return lines


def numeric_answer(rationale_lines: list[str], answer: str, rng: random.Random) -> str:
    closer = rng.choice(NUMERIC_CLOSERS).format(answer=answer)
    if not rationale_lines:
        return closer
    if len(rationale_lines) == 1:
        return f"{rationale_lines[0]}.\n\n{closer}"
    steps = "\n".join(f"{i + 1}. {line}" for i, line in enumerate(rationale_lines))
    return f"Step by step:\n{steps}\n\n{closer}"


def numeric_question(context: str, question: str, rng: random.Random) -> str:
    return f"{rng.choice(NUMERIC_INTROS)}\n\n{context}\n\nQuestion: {question.strip()}"


def finqa_answer_text(qa: dict[str, Any]) -> str:
    answer = str(qa.get("answer") or "").strip()
    if answer:
        return answer
    exe = qa.get("exe_ans")
    if isinstance(exe, (int, float)):
        return fmt_number(float(exe))
    return str(exe or "").strip()

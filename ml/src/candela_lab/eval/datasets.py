import ast
import json
import random
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from candela_lab.config import load_yaml
from candela_lab.data import voice
from candela_lab.data.sources import hf_file, url_file
from candela_lab.eval import ifeval
from candela_lab.paths import CONFIGS_DIR, DATA_DIR, DATA_VERSION

EVAL_SEED = 1234
TOOL_USE_PATH = DATA_DIR / "eval" / f"tool_use-{DATA_VERSION}.jsonl"

SENTIMENT_PROMPT = (
    "Classify the sentiment of the following financial text. Reply with exactly one word: "
    "positive, negative or neutral.\n\nText: {text}"
)
NUMERIC_PROMPT = (
    "{context}\n\nQuestion: {question}\n\nShow the calculation in at most two short lines, then finish with a "
    "final line of the form 'Answer: <number>'."
)

FINANCEBENCH_PROMPT = (
    "Use the excerpts from {company}'s {doc} below to answer the question.\n\n{evidence}\n\nQuestion: {question}\n\n"
    "Answer in at most three sentences and state the key figure explicitly."
)


@dataclass
class EvalItem:
    id: str
    suite: str
    prompt: str
    answer: str
    choices: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


def _eval_sources() -> dict[str, dict[str, Any]]:
    cfg = load_yaml(CONFIGS_DIR / "data" / f"{DATA_VERSION}.yaml")
    return {e["id"]: e for e in cfg["eval"]}


def _path(suite: str, index: int = 0) -> Path:
    src = _eval_sources()[suite]
    if "url" in src:
        return url_file(src["url"])
    return hf_file(src["repo"], src["files"][index], src["revision"])


def fetch_all(pin: bool = False) -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = {}
    for suite, src in _eval_sources().items():
        if "url" in src:
            out[suite] = [url_file(src["url"], pin)]
        else:
            out[suite] = [hf_file(src["repo"], f, src["revision"], pin) for f in src["files"]]
    return out


def license_of(suite: str) -> str:
    return str(_eval_sources().get(suite, {}).get("license", "own (apache-2.0)"))


def _sample(items: list[EvalItem], n: int | None) -> list[EvalItem]:
    if n is None or n >= len(items):
        return items
    rng = random.Random(EVAL_SEED)
    return sorted(rng.sample(items, n), key=lambda x: x.id)


def _sentiment(suite: str) -> list[EvalItem]:
    df = pd.read_parquet(_path(suite))
    return [
        EvalItem(
            id=str(r["id"]),
            suite=suite,
            prompt=SENTIMENT_PROMPT.format(text=str(r["text"]).strip()),
            answer=str(r["answer"]).strip().lower(),
            choices=["positive", "negative", "neutral"],
            extra={"text": str(r["text"])},
        )
        for _, r in df.iterrows()
    ]


def _headlines() -> list[EvalItem]:
    df = pd.read_parquet(_path("headlines"))
    items = []
    for _, r in df.iterrows():
        query = str(r["query"]).strip()
        body = query.rsplit("\nAnswer:", 1)[0]
        items.append(
            EvalItem(
                id=str(r["id"]),
                suite="headlines",
                prompt=body + "\n\nReply with exactly one word: Yes or No.",
                answer=str(r["answer"]).strip().lower(),
                choices=["yes", "no"],
                extra={
                    "label_type": str(r.get("label_type", "")),
                    "text": body.rsplit("Text:", 1)[-1].strip(),
                },
            )
        )
    return items


def _finqa() -> list[EvalItem]:
    rows = json.loads(_path("finqa").read_text())
    items = []
    for row in rows:
        qa = row["qa"]
        context = voice.context_block(row.get("pre_text", []), row.get("table", []), row.get("post_text", []))
        exe = qa.get("exe_ans")
        items.append(
            EvalItem(
                id=row["id"],
                suite="finqa",
                prompt=NUMERIC_PROMPT.format(context=context, question=qa["question"]),
                answer=str(exe),
                extra={"text": context + "\n" + qa["question"], "answer_text": str(qa.get("answer", ""))},
            )
        )
    return items


def _convfinqa() -> list[EvalItem]:
    df = pd.read_parquet(_path("convfinqa"))
    items = []
    for _, r in df.iterrows():
        query = str(r["query"]).strip()
        body = query.rsplit("\nAnswer:", 1)[0]
        items.append(
            EvalItem(
                id=str(r["id"]),
                suite="convfinqa",
                prompt=body + "\n\nFinish with a final line of the form 'Answer: <number>'.",
                answer=str(r["answer"]).strip(),
                extra={"text": body},
            )
        )
    return items


def _tatqa() -> list[EvalItem]:
    docs = json.loads(_path("tatqa").read_text())
    items = []
    for doc in docs:
        table = doc["table"]["table"]
        paragraphs = [p["text"] for p in sorted(doc["paragraphs"], key=lambda p: p["order"])]
        context = voice.context_block(paragraphs, table, [])
        for q in doc["questions"]:
            if q.get("answer_type") not in ("arithmetic", "count"):
                continue
            items.append(
                EvalItem(
                    id=q["uid"],
                    suite="tatqa",
                    prompt=NUMERIC_PROMPT.format(context=context, question=q["question"]),
                    answer=str(q["answer"]),
                    extra={"scale": q.get("scale", ""), "text": context + "\n" + q["question"]},
                )
            )
    return items


def _ifeval() -> list[EvalItem]:
    items = []
    with _path("ifeval").open() as f:
        for line in f:
            row = json.loads(line)
            if not ifeval.supported(row["instruction_id_list"]):
                continue
            items.append(
                EvalItem(
                    id=str(row["key"]),
                    suite="ifeval",
                    prompt=row["prompt"],
                    answer="",
                    extra={"ids": row["instruction_id_list"], "kwargs": row["kwargs"]},
                )
            )
    return items


def _financebench() -> list[EvalItem]:
    items = []
    with _path("financebench").open() as f:
        for line in f:
            row = json.loads(line)
            evidence = row["evidence"]
            if isinstance(evidence, str):
                evidence = ast.literal_eval(evidence)
            text = "\n\n".join(str(e.get("evidence_text", "")).strip() for e in evidence)[:12000]
            items.append(
                EvalItem(
                    id=str(row["financebench_id"]),
                    suite="financebench",
                    prompt=FINANCEBENCH_PROMPT.format(
                        company=row["company"],
                        doc=row["doc_name"],
                        evidence=text,
                        question=row["question"].strip(),
                    ),
                    answer=str(row["answer"]).strip(),
                    extra={"type": row.get("question_type")},
                )
            )
    return items


def _financebench_texts() -> Iterator[str]:
    with _path("financebench").open() as f:
        for line in f:
            row = json.loads(line)
            yield f"{row.get('question', '')}\n{row.get('answer', '')}\n{row.get('evidence', '')}"


def _ifeval_texts() -> Iterator[str]:
    with _path("ifeval").open() as f:
        for line in f:
            yield json.loads(line)["prompt"]


def tool_use_items() -> list[EvalItem]:
    if not TOOL_USE_PATH.exists():
        return []
    items = []
    with TOOL_USE_PATH.open() as f:
        for line in f:
            row = json.loads(line)
            items.append(EvalItem(id=row["meta"]["id"], suite="tool_use", prompt="", answer="", extra=row))
    return items


LOADERS = {
    "fpb": lambda: _sentiment("fpb"),
    "fiqa_sa": lambda: _sentiment("fiqa_sa"),
    "headlines": _headlines,
    "finqa": _finqa,
    "convfinqa": _convfinqa,
    "tatqa": _tatqa,
    "ifeval": _ifeval,
    "financebench": _financebench,
    "tool_use": tool_use_items,
}


def load(suite: str, n: int | None = None) -> list[EvalItem]:
    return _sample(LOADERS[suite](), n)


def decontamination_texts() -> Iterator[tuple[str, str]]:
    for suite in ("fpb", "fiqa_sa", "headlines", "finqa", "convfinqa", "tatqa"):
        for item in LOADERS[suite]():
            yield suite, str(item.extra.get("text", item.prompt))
    for text in _financebench_texts():
        yield "financebench", text
    for text in _ifeval_texts():
        yield "ifeval", text

"""Base-model self-distillation for retention (ADR 0402): the frozen QAT base answers prompts built from the
permissive training splits; answers that are correct (numeric, sentiment, topic) or complete (general) become
training samples, so the adapter is pulled towards the base's own behaviour on classic and general tasks."""

import json
import random
import time
import zipfile
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import mlx.core as mx
import pandas as pd

from candela_lab import log
from candela_lab.data import voice
from candela_lab.data.common import Example, read_jsonl, stable_id, write_jsonl
from candela_lab.data.decontam import NGramIndex
from candela_lab.data.sources import SENTIMENT_LABELS, TOPIC_LABELS, fetch_source
from candela_lab.eval import metrics
from candela_lab.eval.datasets import NUMERIC_PROMPT, SENTIMENT_PROMPT
from candela_lab.paths import CONFIGS_DIR, DATA_DIR, DATA_VERSION

_log = log.get("data.distill")

DISTILL_DIR = DATA_DIR / "distill"
TEACHER = "gemma-4-12b-qat"
SOURCES = ("finqa", "tatqa", "convfinqa", "twitter-fin-sentiment", "twitter-fin-topic", "smoltalk")
DEFAULT_COUNTS = {"numeric": 1600, "sentiment": 900, "topic": 300, "general": 800}
MAX_TOKENS = {"numeric": 384, "label": 8, "open": 256, "general": 640}
BATCH = {"numeric": 4, "label": 8, "open": 8, "general": 8}
CHUNK = 96

NUMERIC_TAILS = [
    "",
    "\n\nKeep it brief and finish with 'Answer: <number>'.",
    "\n\nShow the key calculation, then give the final figure.",
]
LABEL_PROMPTS = [
    SENTIMENT_PROMPT,
    "What is the sentiment of this text for investors? Answer with one word: positive, negative or neutral.\n\n{text}",
    "Sentiment (positive, negative or neutral), one word only:\n{text}",
    "Label the tone of this financial news as positive, negative or neutral. Reply with the label only.\n\n{text}",
]
TOPIC_PROMPT = "Which topic best describes this financial headline? Options: {options}. Reply with the topic only.\n\n{text}"


@dataclass
class Prompt:
    id: str
    task: str
    source: str
    license: str
    messages: list[dict[str, Any]]
    kind: str
    gold: str = ""
    choices: list[str] = field(default_factory=list)


def _sources() -> dict[str, dict[str, Any]]:
    from candela_lab.config import load_yaml

    cfg = load_yaml(CONFIGS_DIR / "data" / f"{DATA_VERSION}.yaml")
    return {s["id"]: s for s in cfg["sources"] if s["id"] in SOURCES}


def _user(text: str) -> list[dict[str, Any]]:
    return [{"role": "user", "content": text}]


def _numeric_prompt(context: str, question: str, rng: random.Random) -> str:
    if rng.random() < 0.6:
        return NUMERIC_PROMPT.format(context=context, question=question.strip())
    return voice.numeric_question(context, question, rng) + rng.choice(NUMERIC_TAILS)


def _finqa(src: dict[str, Any], rng: random.Random) -> Iterator[Prompt]:
    for path in fetch_source(src):
        for row in json.loads(path.read_text()):
            qa = row.get("qa") or {}
            exe = qa.get("exe_ans")
            if not qa.get("question") or not isinstance(exe, (int, float)):
                continue
            context = voice.context_block(
                row.get("pre_text", []), row.get("table", []), row.get("post_text", [])
            )
            yield Prompt(
                stable_id("distill", src["id"], row["id"]),
                "numeric_qa",
                src["id"],
                src["license"],
                _user(_numeric_prompt(context, qa["question"], rng)),
                "numeric",
                str(exe),
            )


def _tatqa(src: dict[str, Any], rng: random.Random) -> Iterator[Prompt]:
    for path in fetch_source(src):
        for doc in json.loads(path.read_text()):
            paragraphs = [p["text"] for p in sorted(doc["paragraphs"], key=lambda p: p["order"])]
            context = voice.context_block(paragraphs, doc["table"]["table"], [])
            for q in doc["questions"]:
                if q.get("answer_type") not in ("arithmetic", "count"):
                    continue
                yield Prompt(
                    stable_id("distill", src["id"], q["uid"]),
                    f"numeric_qa:{q['answer_type']}",
                    src["id"],
                    src["license"],
                    _user(_numeric_prompt(context, q["question"], rng)),
                    "numeric",
                    str(q["answer"]),
                )


def _convfinqa(src: dict[str, Any], rng: random.Random) -> Iterator[Prompt]:
    with zipfile.ZipFile(fetch_source(src)[0]) as zf:
        rows = json.loads(zf.read("data/train.json"))
    for row in rows:
        ann = row.get("annotation") or {}
        questions = ann.get("dialogue_break") or []
        answers = ann.get("exe_ans_list") or []
        if not questions or len(questions) != len(answers) or not isinstance(answers[0], (int, float)):
            continue
        context = voice.context_block(row.get("pre_text", []), row.get("table", []), row.get("post_text", []))
        yield Prompt(
            stable_id("distill", src["id"], row["id"]),
            "numeric_qa_conversational",
            src["id"],
            src["license"],
            _user(_numeric_prompt(context, questions[0], rng)),
            "numeric",
            str(answers[0]),
        )


def _sentiment(src: dict[str, Any], rng: random.Random) -> Iterator[Prompt]:
    df = pd.read_csv(fetch_source(src)[0])
    for n, (text, label_id) in enumerate(zip(df["text"], df["label"], strict=True)):
        one_word = rng.random() < 0.6
        template = rng.choice(LABEL_PROMPTS if one_word else voice.SENTIMENT_QUESTIONS)
        yield Prompt(
            stable_id("distill", src["id"], str(n)),
            "sentiment",
            src["id"],
            src["license"],
            _user(template.format(text=str(text).strip())),
            "label" if one_word else "open",
            SENTIMENT_LABELS[int(label_id)],
            ["positive", "negative", "neutral"],
        )


def _topic(src: dict[str, Any], rng: random.Random) -> Iterator[Prompt]:
    df = pd.read_csv(fetch_source(src)[0])
    for n, (text, label_id) in enumerate(zip(df["text"], df["label"], strict=True)):
        topic = TOPIC_LABELS[int(label_id)]
        options = [*rng.sample([t for t in TOPIC_LABELS if t != topic], 5), topic]
        rng.shuffle(options)
        short = rng.random() < 0.5
        template = TOPIC_PROMPT if short else rng.choice(voice.TOPIC_QUESTIONS)
        yield Prompt(
            stable_id("distill", src["id"], str(n)),
            "headline_topic",
            src["id"],
            src["license"],
            _user(template.format(options=", ".join(options), text=str(text).strip())),
            "label" if short else "open",
            topic.lower(),
            [o.lower() for o in options],
        )


def _general(src: dict[str, Any], _rng: random.Random) -> Iterator[Prompt]:
    for path in fetch_source(src):
        subset = path.parent.name
        df = pd.read_parquet(path)
        for n, msgs in enumerate(df["messages"]):
            clean = [{"role": str(m["role"]), "content": str(m["content"])} for m in msgs]
            if clean and clean[0]["role"] == "system":
                clean = clean[1:]
            if len(clean) != 2 or clean[0]["role"] != "user" or len(clean[0]["content"]) > 6000:
                continue
            yield Prompt(
                stable_id("distill", src["id"], subset, str(n)),
                f"general:{subset}",
                src["id"],
                src["license"],
                clean[:1],
                "general",
            )


def _interleave_by_gold(items: list[Prompt]) -> list[Prompt]:
    """Balanced labels: Twitter sentiment is ~65 % neutral, and the pilot drifted towards 'neutral' on FPB."""
    by_gold: dict[str, list[Prompt]] = {}
    for p in items:
        by_gold.setdefault(p.gold, []).append(p)
    out: list[Prompt] = []
    for row in zip(*by_gold.values(), strict=False):
        out.extend(row)
    return out


def _pool(
    srcs: dict[str, dict[str, Any]], counts: dict[str, int], index: NGramIndex, seed: int
) -> list[Prompt]:
    groups = {
        "numeric": [("finqa", _finqa, 0.4), ("tatqa", _tatqa, 0.4), ("convfinqa", _convfinqa, 0.2)],
        "sentiment": [("twitter-fin-sentiment", _sentiment, 1.0)],
        "topic": [("twitter-fin-topic", _topic, 1.0)],
        "general": [("smoltalk", _general, 1.0)],
    }
    chosen: list[Prompt] = []
    for group, members in groups.items():
        for sid, loader, weight in members:
            rng = random.Random(f"{seed}:distill:{sid}")
            items = list(loader(srcs[sid], rng))
            rng.shuffle(items)
            if group == "sentiment":
                items = _interleave_by_gold(items)
            quota = round(counts[group] * weight)
            taken = dropped = 0
            for p in items:
                if taken >= quota:
                    break
                if index.hit(" ".join(m["content"] for m in p.messages)):
                    dropped += 1
                    continue
                chosen.append(p)
                taken += 1
            _log.info(
                "distill prompts", source=sid, available=len(items), taken=taken, decontaminated=dropped
            )
    return chosen


def _accept(p: Prompt, text: str, truncated: bool) -> str | None:
    out = metrics.strip_reasoning(text)
    for marker in ("<turn|>", "<|turn>", "<|tool_call>", "<eos>", "<end_of_turn>"):
        out = out.replace(marker, "")
    out = out.strip()
    if not out or "<|" in out or "|>" in out:
        return "special_tokens" if out else "empty"
    if truncated:
        return "truncated"
    if p.kind == "numeric":
        return (
            None
            if metrics.numeric_match(metrics.parse_numeric(out), metrics.gold_number(p.gold))
            else "wrong"
        )
    if p.kind in ("label", "open"):
        return None if metrics.parse_label(out, p.choices) == p.gold else "wrong"
    return None


def _clean(text: str) -> str:
    out = metrics.strip_reasoning(text)
    for marker in ("<turn|>", "<eos>", "<end_of_turn>"):
        out = out.replace(marker, "")
    return out.strip()


def run(counts: dict[str, int] | None = None, seed: int = 20261024, out_dir: Path | None = None) -> Path:
    from candela_lab.eval import datasets as evalsets
    from candela_lab.eval import runner

    counts = {**DEFAULT_COUNTS, **(counts or {})}
    target = out_dir or DISTILL_DIR / DATA_VERSION
    target.mkdir(parents=True, exist_ok=True)
    index = NGramIndex()
    for suite, text in evalsets.decontamination_texts():
        index.add(suite, [text])
    prompts = _pool(_sources(), counts, index, seed)
    started = time.time()
    raw_dir = target / "raw"
    raw_dir.mkdir(exist_ok=True)
    by_kind: dict[str, list[Prompt]] = {}
    for p in prompts:
        by_kind.setdefault(p.kind, []).append(p)
    with runner.engine_session(TEACHER, None, "distill retention answers") as engine:
        for kind, group in by_kind.items():
            encoded = sorted(((engine.prompt_ids(p.messages), p) for p in group), key=lambda x: len(x[0]))
            for c in range(0, len(encoded), CHUNK):
                chunk_path = raw_dir / f"{kind}-{c // CHUNK:03d}.jsonl"
                if chunk_path.exists():
                    continue
                part = encoded[c : c + CHUNK]
                t0 = time.time()
                outputs = engine.generate_full([ids for ids, _ in part], MAX_TOKENS[kind], BATCH[kind])
                write_jsonl(
                    chunk_path,
                    [
                        {"id": p.id, "text": text, "truncated": truncated}
                        for (_, p), (text, truncated) in zip(part, outputs, strict=True)
                    ],
                )
                _log.info(
                    "distill chunk",
                    kind=kind,
                    chunk=c // CHUNK,
                    n=len(part),
                    seconds=round(time.time() - t0, 1),
                    peak_gb=round(mx.get_peak_memory() / 1e9, 2),
                )
    raw = {r["id"]: r for f in sorted(raw_dir.glob("*.jsonl")) for r in read_jsonl(f)}
    stats: dict[str, Counter[str]] = {}
    for kind, group in by_kind.items():
        rows: list[Example] = []
        counter: Counter[str] = Counter()
        for p in group:
            r = raw.get(p.id)
            reason = "missing" if r is None else _accept(p, r["text"], r["truncated"])
            counter[reason or "kept"] += 1
            if reason or r is None:
                continue
            rows.append(
                {
                    "messages": [*p.messages, {"role": "assistant", "content": _clean(r["text"])}],
                    "meta": {
                        "source": p.source,
                        "license": p.license,
                        "task": f"retention:{p.task}",
                        "id": p.id,
                        "teacher": TEACHER,
                        "gold": p.gold,
                    },
                }
            )
        write_jsonl(target / f"{kind}.jsonl", rows)
        stats[kind] = counter
        _log.info("distill kind", kind=kind, **dict(counter))
    summary = {
        "teacher": TEACHER,
        "seed": seed,
        "counts": counts,
        "decoding": {"temperature": 0.0, "thinking": False, "maxTokens": MAX_TOKENS},
        "outcomes": {k: dict(v) for k, v in stats.items()},
        "seconds": round(time.time() - started, 1),
    }
    (target / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return target

import ast
import json
import random
import re
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pandas as pd
from huggingface_hub import hf_hub_download

from candela_lab import log
from candela_lab.data import voice
from candela_lab.data.common import Example, openai_tool, read_jsonl, sha256_file, stable_id, tool_call
from candela_lab.paths import CONFIGS_DIR, ML_DIR, RAW_DIR

_log = log.get("data.sources")

GENERIC_TOOL_SYSTEM = (
    "You are a helpful assistant with access to tools. Call a tool when it is needed to answer."
)

TOPIC_LABELS = [
    "Analyst Update",
    "Company or Product News",
    "Currencies",
    "Dividend News",
    "Earnings",
    "Energy | Oil",
    "Fed | Central Banks",
    "Financials",
    "General News | Opinion",
    "Gold | Metals | Materials",
    "IPO",
    "Legal | Regulation",
    "M&A | Investments",
    "Macro",
    "Markets",
    "Personnel Change",
    "Politics",
    "Stock Commentary",
    "Stock Movement",
    "Treasuries | Corporate Debt",
]
SENTIMENT_LABELS = {0: "negative", 1: "positive", 2: "neutral"}


ALLOWED_SUFFIXES = (".json", ".jsonl", ".csv", ".parquet", ".zip")
LOCK_PATH = CONFIGS_DIR / "data" / "d0.1.lock.json"


class IntegrityError(RuntimeError):
    pass


def _lock() -> dict[str, str]:
    return json.loads(LOCK_PATH.read_text()) if LOCK_PATH.exists() else {}


def _verify(key: str, path: Path, pin: bool) -> Path:
    if not path.name.endswith(ALLOWED_SUFFIXES):
        raise IntegrityError(f"{key}: file type not allowed")
    digest = sha256_file(path)
    lock = _lock()
    expected = lock.get(key)
    if expected is None:
        if not pin:
            raise IntegrityError(f"{key}: no pinned sha256; run `lab data fetch --pin` to record it")
        lock[key] = digest
        LOCK_PATH.write_text(json.dumps(dict(sorted(lock.items())), indent=2) + "\n")
        _log.info("pinned", key=key, sha256=digest[:16])
    elif expected != digest:
        raise IntegrityError(f"{key}: sha256 mismatch (expected {expected[:16]}, got {digest[:16]})")
    return path


def hf_file(repo: str, filename: str, revision: str, pin: bool = False) -> Path:
    path = Path(hf_hub_download(repo, filename, repo_type="dataset", revision=revision))
    return _verify(f"hf:{repo}@{revision}/{filename}", path, pin)


def url_file(url: str, pin: bool = False) -> Path:
    import httpx

    target = RAW_DIR / "url" / stable_id(url) / url.rsplit("/", 1)[-1]
    if target.exists():
        return _verify(f"url:{url}", target, pin)
    target.parent.mkdir(parents=True, exist_ok=True)
    _log.info("downloading", url=url)
    tmp = target.with_suffix(target.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    tmp.rename(target)
    return _verify(f"url:{url}", target, pin)


def fetch_source(src: dict[str, Any], pin: bool = False) -> list[Path]:
    kind = src["kind"]
    if kind == "hf":
        return [hf_file(src["repo"], f, src["revision"], pin) for f in src["files"]]
    if kind == "url":
        return [url_file(u, pin) for u in src["urls"].values()]
    if kind == "traces":
        root = ML_DIR / src["path"]
        return sorted(root.glob("*.jsonl")) if root.exists() else []
    raise ValueError(f"unknown source kind {kind}")


def _meta(src: dict[str, Any], key: str, task: str) -> dict[str, Any]:
    return {"source": src["id"], "license": src["license"], "task": task, "id": stable_id(src["id"], key)}


def load_traces(src: dict[str, Any], files: list[Path], rng: random.Random) -> Iterator[Example]:
    for path in files:
        for row in read_jsonl(path):
            meta = {
                **row.get("meta", {}),
                **_meta(src, row["meta"]["id"], row["meta"].get("task", "tool_use")),
            }
            meta["executor"] = row.get("meta", {}).get("executor", "unknown")
            yield {"messages": row["messages"], "tools": row["tools"], "meta": meta}


def load_nemotron(src: dict[str, Any], files: list[Path], rng: random.Random) -> Iterator[Example]:
    for path in files:
        for row in read_jsonl(path):
            msgs = [{"role": m["role"], "content": m["content"]} for m in row["messages"]]
            if not msgs or msgs[-1]["role"] != "assistant":
                continue
            key = row.get("metadata", {}).get("uuid") or msgs[0]["content"]
            task = "agentic_finance:" + str(row.get("metadata", {}).get("question_type", "qa"))
            yield {"messages": msgs, "meta": _meta(src, key, task)}


def _bracket_slice(text: str, start: int) -> str | None:
    depth, in_str, esc = 0, False, False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _parse_python_calls(text: str) -> list[tuple[str, dict[str, Any]]] | None:
    text = text.strip()
    if not (text.startswith("[") and text.endswith("]") and "(" in text):
        return None
    body = text[1:-1]
    calls: list[tuple[str, dict[str, Any]]] = []
    i = 0
    while i < len(body):
        while i < len(body) and body[i] in " ,\n":
            i += 1
        if i >= len(body):
            break
        paren = body.find("(", i)
        if paren < 0:
            return None
        name = body[i:paren].strip()
        depth, j, quote = 0, paren, ""
        while j < len(body):
            ch = body[j]
            if quote:
                if ch == "\\":
                    j += 2
                    continue
                if ch == quote:
                    quote = ""
            elif ch in "\"'":
                quote = ch
            elif ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        args_src = body[paren + 1 : j]
        try:
            node = ast.parse(f"f({args_src})", mode="eval").body
            if not isinstance(node, ast.Call) or node.args:
                return None
            args = {kw.arg: ast.literal_eval(kw.value) for kw in node.keywords if kw.arg}
        except SyntaxError, ValueError:
            return None
        calls.append((name, args))
        i = j + 1
    return calls or None


def load_toolace(src: dict[str, Any], files: list[Path], rng: random.Random) -> Iterator[Example]:
    for path in files:
        for n, row in enumerate(json.loads(path.read_text())):
            system = row["system"]
            start = system.find("[", system.find("invoke:"))
            raw_tools = _bracket_slice(system, start) if start >= 0 else None
            if not raw_tools:
                continue
            try:
                tools = [openai_tool(t) for t in json.loads(raw_tools)]
            except json.JSONDecodeError:
                continue
            msgs: list[dict[str, Any]] = [{"role": "system", "content": GENERIC_TOOL_SYSTEM}]
            pending: list[dict[str, Any]] = []
            ok = True
            counter = 0
            for turn in row["conversations"]:
                role, value = turn["from"], turn["value"]
                if role == "user":
                    msgs.append({"role": "user", "content": value})
                elif role == "assistant":
                    calls = _parse_python_calls(value)
                    if calls:
                        pending = [tool_call(counter + k, name, args) for k, (name, args) in enumerate(calls)]
                        counter += len(calls)
                        msgs.append({"role": "assistant", "content": "", "tool_calls": pending})
                    else:
                        msgs.append({"role": "assistant", "content": value})
                elif role == "tool":
                    try:
                        results = json.loads(value)
                    except json.JSONDecodeError:
                        ok = False
                        break
                    if not isinstance(results, list) or len(results) != len(pending):
                        ok = False
                        break
                    for tc, res in zip(pending, results, strict=True):
                        content = res.get("results", res) if isinstance(res, dict) else res
                        msgs.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "name": tc["function"]["name"],
                                "content": json.dumps(content, ensure_ascii=False),
                            }
                        )
                    pending = []
            if ok and msgs[-1]["role"] == "assistant":
                yield {
                    "messages": msgs,
                    "tools": tools,
                    "meta": _meta(src, f"{path.name}:{n}", "function_calling"),
                }


TOOL_CALL_RE = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.S)
TOOL_RESPONSE_RE = re.compile(r"<tool_response>\s*(.*?)\s*</tool_response>", re.S)


def _loose_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return ast.literal_eval(text)


def load_hermes(src: dict[str, Any], files: list[Path], rng: random.Random) -> Iterator[Example]:
    for path in files:
        for row in json.loads(path.read_text()):
            try:
                raw_tools = row.get("tools")
                tools_list = json.loads(raw_tools) if isinstance(raw_tools, str) else raw_tools
                tools = [openai_tool(t) for t in tools_list or []]
            except json.JSONDecodeError, TypeError:
                continue
            if not tools:
                continue
            msgs: list[dict[str, Any]] = [{"role": "system", "content": GENERIC_TOOL_SYSTEM}]
            pending: list[dict[str, Any]] = []
            counter = 0
            ok = True
            for turn in row["conversations"]:
                role, value = turn["from"], turn["value"]
                if role == "system":
                    continue
                if role == "human":
                    msgs.append({"role": "user", "content": value})
                elif role == "gpt":
                    blocks = TOOL_CALL_RE.findall(value)
                    if blocks:
                        try:
                            parsed = [_loose_json(b) for b in blocks]
                            pending = [
                                tool_call(counter + k, p["name"], p.get("arguments") or {})
                                for k, p in enumerate(parsed)
                            ]
                        except ValueError, SyntaxError, KeyError, TypeError:
                            ok = False
                            break
                        counter += len(pending)
                        text = TOOL_CALL_RE.sub("", value).strip()
                        msgs.append({"role": "assistant", "content": text, "tool_calls": pending})
                    else:
                        msgs.append({"role": "assistant", "content": value.strip()})
                elif role == "tool":
                    responses = TOOL_RESPONSE_RE.findall(value)
                    if len(responses) != len(pending):
                        ok = False
                        break
                    for tc, body in zip(pending, responses, strict=True):
                        try:
                            parsed_body = _loose_json(body)
                            content = parsed_body.get("content", parsed_body)
                        except ValueError, SyntaxError, AttributeError:
                            content = body
                        msgs.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc["id"],
                                "name": tc["function"]["name"],
                                "content": json.dumps(content, ensure_ascii=False)
                                if not isinstance(content, str)
                                else content,
                            }
                        )
                    pending = []
            if ok and msgs[-1]["role"] == "assistant":
                key = str(row.get("id") or row["conversations"][1]["value"][:200])
                yield {"messages": msgs, "tools": tools, "meta": _meta(src, key, "function_calling")}


def finqa_example(src: dict[str, Any], row: dict[str, Any], rng: random.Random) -> Example | None:
    qa = row.get("qa") or {}
    question = qa.get("question")
    if not question:
        return None
    context = voice.context_block(row.get("pre_text", []), row.get("table", []), row.get("post_text", []))
    answer = voice.finqa_answer_text(qa)
    if not answer:
        return None
    lines = voice.render_program(qa.get("program", ""))
    return {
        "messages": [
            {"role": "user", "content": voice.numeric_question(context, question, rng)},
            {"role": "assistant", "content": voice.numeric_answer(lines, answer, rng)},
        ],
        "meta": _meta(src, row["id"], "numeric_qa"),
    }


def load_finqa(src: dict[str, Any], files: list[Path], rng: random.Random) -> Iterator[Example]:
    for path in files:
        for row in json.loads(path.read_text()):
            ex = finqa_example(src, row, rng)
            if ex:
                yield ex


def load_convfinqa(src: dict[str, Any], files: list[Path], rng: random.Random) -> Iterator[Example]:
    with zipfile.ZipFile(files[0]) as zf:
        rows = json.loads(zf.read("data/train.json"))
    for row in rows:
        ann = row.get("annotation") or {}
        questions = ann.get("dialogue_break") or []
        programs = ann.get("turn_program") or []
        answers = ann.get("exe_ans_list") or []
        if not questions or len(questions) != len(answers):
            continue
        context = voice.context_block(row.get("pre_text", []), row.get("table", []), row.get("post_text", []))
        msgs: list[dict[str, Any]] = []
        for k, (q, a) in enumerate(zip(questions, answers, strict=True)):
            content = voice.numeric_question(context, q, rng) if k == 0 else q
            msgs.append({"role": "user", "content": content})
            ans = voice.fmt_number(float(a)) if isinstance(a, (int, float)) else str(a)
            prog = programs[k] if k < len(programs) else ""
            lines = voice.render_program(prog) if "(" in prog else []
            msgs.append({"role": "assistant", "content": voice.numeric_answer(lines, ans, rng)})
        yield {"messages": msgs, "meta": _meta(src, row["id"], "numeric_qa_conversational")}


def _tatqa_answer(q: dict[str, Any]) -> str:
    ans = q.get("answer")
    if isinstance(ans, list):
        text = ", ".join(str(a) for a in ans)
    elif isinstance(ans, float):
        text = voice.fmt_number(ans)
    else:
        text = str(ans)
    scale = q.get("scale") or ""
    if scale == "percent" and not text.endswith("%"):
        text += "%"
    elif scale in ("thousand", "million", "billion"):
        text += f" {scale}"
    return text


def load_tatqa(src: dict[str, Any], files: list[Path], rng: random.Random) -> Iterator[Example]:
    for path in files:
        for doc in json.loads(path.read_text()):
            table = doc["table"]["table"]
            paragraphs = [p["text"] for p in sorted(doc["paragraphs"], key=lambda p: p["order"])]
            context = voice.context_block(paragraphs, table, [])
            for q in doc["questions"]:
                answer = _tatqa_answer(q)
                derivation = (q.get("derivation") or "").strip()
                lines = (
                    [f"{derivation} = {answer}"]
                    if derivation and q.get("answer_type") == "arithmetic"
                    else []
                )
                yield {
                    "messages": [
                        {"role": "user", "content": voice.numeric_question(context, q["question"], rng)},
                        {"role": "assistant", "content": voice.numeric_answer(lines, answer, rng)},
                    ],
                    "meta": _meta(src, q["uid"], f"numeric_qa:{q.get('answer_type', 'span')}"),
                }


def load_twitter_sentiment(src: dict[str, Any], files: list[Path], rng: random.Random) -> Iterator[Example]:
    df = pd.read_csv(files[0])
    for n, (text, label_id) in enumerate(zip(df["text"], df["label"], strict=True)):
        q, a = voice.sentiment_sample(str(text), SENTIMENT_LABELS[int(label_id)], rng)
        yield {
            "messages": [{"role": "user", "content": q}, {"role": "assistant", "content": a}],
            "meta": _meta(src, f"{n}:{text}", "sentiment"),
        }


def load_twitter_topic(src: dict[str, Any], files: list[Path], rng: random.Random) -> Iterator[Example]:
    df = pd.read_csv(files[0])
    for n, (text, label_id) in enumerate(zip(df["text"], df["label"], strict=True)):
        topic = TOPIC_LABELS[int(label_id)]
        options = [*rng.sample([t for t in TOPIC_LABELS if t != topic], 5), topic]
        q, a = voice.topic_sample(str(text), topic, options, rng)
        yield {
            "messages": [{"role": "user", "content": q}, {"role": "assistant", "content": a}],
            "meta": _meta(src, f"{n}:{text}", "headline_topic"),
        }


def load_smoltalk(src: dict[str, Any], files: list[Path], rng: random.Random) -> Iterator[Example]:
    for path in files:
        subset = path.parent.name
        df = pd.read_parquet(path)
        for n, msgs in enumerate(df["messages"]):
            clean = [{"role": str(m["role"]), "content": str(m["content"])} for m in msgs]
            if not clean or clean[-1]["role"] != "assistant":
                continue
            yield {"messages": clean, "meta": _meta(src, f"{subset}:{n}", f"general:{subset}")}


LOADERS: dict[str, Callable[[dict[str, Any], list[Path], random.Random], Iterator[Example]]] = {
    "candela-traces": load_traces,
    "nemotron-agentic-finance": load_nemotron,
    "toolace": load_toolace,
    "hermes-fc": load_hermes,
    "finqa": load_finqa,
    "convfinqa": load_convfinqa,
    "tatqa": load_tatqa,
    "twitter-fin-sentiment": load_twitter_sentiment,
    "twitter-fin-topic": load_twitter_topic,
    "smoltalk": load_smoltalk,
}

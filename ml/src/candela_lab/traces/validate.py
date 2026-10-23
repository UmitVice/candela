import re
from collections import Counter
from pathlib import Path
from typing import Any

from rich.console import Console

from candela_lab import config, log
from candela_lab.data.common import read_jsonl
from candela_lab.traces.grounding import grounding_report
from candela_lab.traces.schema import validate_arguments

_log = log.get("traces.validate")

ADVICE_RE = re.compile(
    r"\byou should (buy|sell|hold)\b|\bi recommend (buying|selling)\b|\b(strong )?buy rating\b", re.I
)
SECTIONS = ["### Snapshot", "### Trend & Momentum", "### Outlook & Risks", "### Bottom line"]


def _schemas() -> dict[str, dict[str, Any]]:
    return {t["function"]["name"]: t["function"]["parameters"] for t in config.tools_schema()}


def validate_conversation(row: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    schemas = _schemas()
    msgs = row["messages"]
    if msgs[0]["role"] != "system" or "Candela" not in msgs[0]["content"]:
        problems.append("structure: missing Candela system prompt")
    if msgs[-1]["role"] != "assistant" or not msgs[-1].get("content"):
        problems.append("structure: conversation must end with an assistant answer")
    pending: dict[str, str] = {}
    tool_contents: list[str] = []
    derived = row.get("meta", {}).get("derived", [])
    for i, m in enumerate(msgs):
        if m["role"] == "assistant" and m.get("tool_calls"):
            for tc in m["tool_calls"]:
                fn = tc["function"]
                if fn["name"] not in schemas:
                    problems.append(f"schema: unknown tool {fn['name']}")
                    continue
                for p in validate_arguments(schemas[fn["name"]], fn["arguments"]):
                    problems.append(f"schema: {fn['name']} {p}")
                pending[tc["id"]] = fn["name"]
        elif m["role"] == "tool":
            if m.get("tool_call_id") not in pending:
                problems.append("structure: tool message without matching call")
            pending.pop(m.get("tool_call_id"), None)
            tool_contents.append(m["content"])
            if len(m["content"]) > 2500:
                problems.append("contract: model view longer than 2500 characters")
        elif m["role"] == "assistant":
            if pending:
                problems.append("structure: answer before every tool call has a result")
            content = m.get("content") or ""
            if '{"' in content:
                problems.append("structure: raw tool JSON in answer")
            if ADVICE_RE.search(content):
                problems.append("policy: personalized buy/sell language")
            report = grounding_report(content, tool_contents, derived)
            if report["ungrounded"]:
                problems.append(f"grounding: turn {i} ungrounded {report['ungrounded'][:5]}")
            used_data = any('"error"' not in c[:12] for c in tool_contents)
            if used_data and "as of" not in content and "Sources" not in content and tool_contents:
                last_tools = [c for c in tool_contents if '"asOf"' in c]
                if last_tools:
                    problems.append("citation: numbers without an asOf citation")
    intent = row.get("meta", {}).get("intent", "")
    if intent in ("analysis", "analysis_follow_up"):
        first_answer = next(
            (m["content"] for m in msgs if m["role"] == "assistant" and not m.get("tool_calls")), ""
        )
        has_data = "### Snapshot" in first_answer or "### Trend" in first_answer
        if has_data and not all(s in first_answer for s in SECTIONS if s != "### Snapshot"):
            problems.append("structure: analysis is missing required sections")
    return problems


def validate_file(path: Path) -> bool:
    console = Console()
    total, bad = 0, 0
    kinds: Counter[str] = Counter()
    intents: Counter[str] = Counter()
    turns = 0
    for row in read_jsonl(path):
        total += 1
        intents[row.get("meta", {}).get("intent", "?")] += 1
        turns += sum(1 for m in row["messages"] if m["role"] == "assistant")
        problems = validate_conversation(row)
        if problems:
            bad += 1
            for p in problems:
                kinds[p.split(":")[0]] += 1
            if bad <= 5:
                console.print(f"[red]{row['meta']['id']}[/red]: {problems[:3]}")
    multi = sum(1 for row in read_jsonl(path) if sum(1 for m in row["messages"] if m["role"] == "user") > 1)
    console.print(
        f"{path}: {total} conversations, {turns} supervised turns, {bad} invalid, "
        f"multi-turn {100 * multi / max(total, 1):.1f}%"
    )
    console.print(f"intents: {dict(intents.most_common())}")
    if kinds:
        console.print(f"problems by kind: {dict(kinds)}")
    return bad == 0 and total > 0

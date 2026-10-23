import hashlib
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

Example = dict[str, Any]


TOOL_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]+")


def stable_id(*parts: str) -> str:
    return hashlib.sha1("\x1f".join(parts).encode()).hexdigest()[:16]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open() as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def write_jsonl(path: Path, rows: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def sanitize_tool_name(name: str) -> str:
    cleaned = TOOL_NAME_RE.sub("_", name.strip()).strip("_")
    return cleaned[:64] or "tool"


def _fix_schema(node: Any) -> Any:
    if isinstance(node, dict):
        out = {k: _fix_schema(v) for k, v in node.items() if v is not None}
        t = out.get("type")
        if t == "dict":
            out["type"] = "object"
        elif t in ("float", "double"):
            out["type"] = "number"
        elif t in ("int", "long"):
            out["type"] = "integer"
        elif t in ("bool",):
            out["type"] = "boolean"
        elif t in ("list", "tuple"):
            out["type"] = "array"
        elif isinstance(t, str) and t not in {
            "object",
            "string",
            "number",
            "integer",
            "boolean",
            "array",
            "null",
        }:
            out["type"] = "string"
        if out.get("type") == "object" and "properties" not in out and "required" in out:
            out.pop("required")
        if isinstance(out.get("required"), bool) or out.get("required") is None:
            out.pop("required", None)
        return out
    if isinstance(node, list):
        return [_fix_schema(v) for v in node]
    return node


def openai_tool(fn: dict[str, Any]) -> dict[str, Any]:
    if fn.get("type") == "function" and "function" in fn:
        fn = fn["function"]
    params = _fix_schema(fn.get("parameters") or {"type": "object", "properties": {}})
    if params.get("type") != "object":
        params = {"type": "object", "properties": {}}
    params.setdefault("properties", {})
    return {
        "type": "function",
        "function": {
            "name": sanitize_tool_name(str(fn.get("name", "tool"))),
            "description": str(fn.get("description") or "")[:1024],
            "parameters": params,
        },
    }


def tool_call(index: int, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": f"call_{index}",
        "type": "function",
        "function": {"name": sanitize_tool_name(name), "arguments": arguments},
    }


def text_of(example: Example, roles: tuple[str, ...] = ("user", "assistant")) -> str:
    parts: list[str] = []
    for m in example["messages"]:
        if m["role"] in roles and isinstance(m.get("content"), str):
            parts.append(m["content"])
        if m["role"] == "assistant":
            for tc in m.get("tool_calls") or []:
                parts.append(json.dumps(tc["function"]["arguments"], sort_keys=True))
    return "\n".join(parts)


def supervised_turns(messages: list[dict[str, Any]]) -> list[int]:
    return [i for i, m in enumerate(messages) if m["role"] == "assistant"]


def expand_turns(example: Example) -> list[Example]:
    out: list[Example] = []
    meta = example["meta"]
    for k in supervised_turns(example["messages"]):
        sample: Example = {
            "messages": example["messages"][: k + 1],
            "meta": {**meta, "conversation": meta["id"], "turn": k, "id": f"{meta['id']}-{k}"},
        }
        if example.get("tools"):
            sample["tools"] = example["tools"]
        out.append(sample)
    return out

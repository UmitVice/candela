import json
import secrets
from dataclasses import dataclass, field
from typing import Any, Literal

from mlx_lm.tool_parsers import gemma4, json_tools

Phase = Literal["reasoning", "answer", "tool"]


@dataclass(frozen=True)
class Family:
    name: str
    think_start: str
    think_end: str
    tool_start: str
    tool_end: str
    stop: tuple[str, ...]


FAMILIES: dict[str, Family] = {
    # Gemma 4: thinking lives in a `<|channel>thought … <channel|>` block; a tool call is followed by the model
    # opening `<|tool_response>`, which is where generation must stop (ml/configs/models.yaml).
    "gemma4": Family(
        "gemma4",
        "<|channel>thought",
        "<channel|>",
        gemma4.tool_call_start,
        gemma4.tool_call_end,
        ("<turn|>", "<|tool_response>"),
    ),
    "qwen3": Family(
        "qwen3", "<think>", "</think>", json_tools.tool_call_start, json_tools.tool_call_end, ("<|im_end|>",)
    ),
}


class ToolCallError(ValueError):
    pass


def template_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OpenAI chat messages → chat-template messages: tool-call arguments become mappings (Gemma 4 requires it)."""
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        if role not in {"system", "user", "assistant", "tool"}:
            raise ValueError(f"unsupported role {role!r}")
        msg: dict[str, Any] = {"role": role, "content": m.get("content") or ""}
        if role == "assistant" and m.get("tool_calls"):
            calls = []
            for tc in m["tool_calls"]:
                fn = tc.get("function", {})
                args = fn.get("arguments") or {}
                if isinstance(args, str):
                    args = json.loads(args) if args.strip() else {}
                calls.append(
                    {
                        "id": tc.get("id"),
                        "type": "function",
                        "function": {"name": fn.get("name"), "arguments": args},
                    }
                )
            msg["tool_calls"] = calls
        if role == "tool":
            msg["tool_call_id"] = m.get("tool_call_id")
            if m.get("name"):
                msg["name"] = m["name"]
        out.append(msg)
    return out


def parse_tool_calls(family: Family, body: str) -> list[dict[str, Any]]:
    parser = gemma4 if family.name == "gemma4" else json_tools
    try:
        parsed = parser.parse_tool_call(body.strip())
    except (ValueError, KeyError, TypeError) as exc:
        raise ToolCallError(str(exc)) from exc
    calls = []
    for p in parsed if isinstance(parsed, list) else [parsed]:
        if not isinstance(p, dict) or not isinstance(p.get("name"), str) or not p["name"]:
            raise ToolCallError("tool call without a name")
        args = p.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args) if args.strip() else {}
            except json.JSONDecodeError as exc:
                raise ToolCallError("tool call arguments are not JSON") from exc
        if not isinstance(args, dict):
            raise ToolCallError("tool call arguments are not an object")
        calls.append({"id": "call_" + secrets.token_hex(6), "name": p["name"], "arguments": args})
    return calls


@dataclass
class Splitter:
    """Splits streamed model text into reasoning, answer and tool-call segments by the family's markers.

    Markers can span detokenizer chunks, so a tail that could still become a marker is held back."""

    family: Family
    phase: Phase = "answer"
    _buf: str = ""
    _tool: str = ""
    _strip_next: bool = False
    tool_bodies: list[str] = field(default_factory=list)

    def start_in_reasoning(self) -> None:
        self.phase = "reasoning"
        self._strip_next = True

    def _markers(self) -> list[tuple[str, Phase]]:
        f = self.family
        if self.phase == "reasoning":
            return [(f.think_end, "answer"), (f.tool_start, "tool")]
        if self.phase == "tool":
            return [(f.tool_end, "answer")]
        return [(f.think_start, "reasoning"), (f.tool_start, "tool")]

    def feed(self, text: str, final: bool = False) -> list[tuple[Phase, str]]:
        self._buf += text
        out: list[tuple[Phase, str]] = []
        while True:
            hits: list[tuple[int, str, Phase]] = [
                (self._buf.find(m), m, nxt) for m, nxt in self._markers() if m in self._buf
            ]
            if not hits:
                break
            idx, marker, nxt = min(hits)
            self._emit(out, self._buf[:idx])
            self._buf = self._buf[idx + len(marker) :]
            if self.phase == "tool":
                self.tool_bodies.append(self._tool)
                self._tool = ""
            self.phase = nxt
            self._strip_next = nxt in ("reasoning", "answer")
        hold = 0 if final else max((_partial_suffix(self._buf, m) for m, _ in self._markers()), default=0)
        self._emit(out, self._buf[: len(self._buf) - hold])
        self._buf = self._buf[len(self._buf) - hold :]
        return out

    def _emit(self, out: list[tuple[Phase, str]], text: str) -> None:
        if self._strip_next and text:
            text = text.lstrip()
            if text:
                self._strip_next = False
        if not text:
            return
        if self.phase == "tool":
            self._tool += text
        else:
            out.append((self.phase, text))

    def unterminated_tool(self) -> str | None:
        return self._tool if self.phase == "tool" else None


def _partial_suffix(text: str, marker: str) -> int:
    for n in range(min(len(marker) - 1, len(text)), 0, -1):
        if text.endswith(marker[:n]):
            return n
    return 0

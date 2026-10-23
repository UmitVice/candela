from dataclasses import dataclass
from typing import Any

import numpy as np

from candela_lab.data.common import Example


@dataclass(frozen=True)
class Encoded:
    tokens: np.ndarray
    prompt_len: int
    sample_id: str

    @property
    def supervised(self) -> int:
        return len(self.tokens) - self.prompt_len


def _render(
    tokenizer: Any, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None, gen: bool
) -> str:
    kwargs: dict[str, Any] = {"tokenize": False, "add_generation_prompt": gen, "enable_thinking": False}
    if tools:
        kwargs["tools"] = tools
    return tokenizer.apply_chat_template(messages, **kwargs)


def _common_prefix(a: str, b: str) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def encode(tokenizer: Any, sample: Example) -> Encoded:
    """Prompt = conversation before the final assistant message rendered with the generation prompt (exactly what the
    model sees at inference, e.g. Gemma's empty thought channel); completion = what the template renders for that
    message. Only completion tokens are supervised."""
    messages = sample["messages"]
    tools = sample.get("tools")
    prompt = _render(tokenizer, messages[:-1], tools, gen=True)
    full = _render(tokenizer, messages, tools, gen=False)
    completion = full[_common_prefix(prompt, full) :]
    if not completion.strip():
        raise ValueError(f"{sample['meta']['id']}: empty completion")
    prompt_ids = tokenizer.encode(prompt, add_special_tokens=False)
    completion_ids = tokenizer.encode(completion, add_special_tokens=False)
    tokens = np.asarray(prompt_ids + completion_ids, dtype=np.int32)
    return Encoded(tokens=tokens, prompt_len=len(prompt_ids), sample_id=sample["meta"]["id"])


def encode_all(tokenizer: Any, samples: list[Example], max_len: int) -> tuple[list[Encoded], int]:
    out: list[Encoded] = []
    dropped = 0
    for s in samples:
        try:
            enc = encode(tokenizer, s)
        except ValueError:
            dropped += 1
            continue
        if len(enc.tokens) > max_len + 1 or enc.supervised < 1:
            dropped += 1
            continue
        out.append(enc)
    return out, dropped

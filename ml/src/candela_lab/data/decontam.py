import hashlib
import re
from collections.abc import Iterable

WORD_RE = re.compile(r"[a-z0-9]+")
N = 13
MIN_SHORT = 6


def _h(words: list[str]) -> int:
    return int.from_bytes(hashlib.blake2b(" ".join(words).encode(), digest_size=8).digest(), "little")


class NGramIndex:
    """13-gram index over evaluation texts; texts shorter than 13 words are matched as whole word sequences."""

    def __init__(self, n: int = N) -> None:
        self.n = n
        self.grams: dict[int, str] = {}
        self.short: dict[int, dict[int, str]] = {}

    def add(self, suite: str, texts: Iterable[str]) -> int:
        added = 0
        for text in texts:
            words = WORD_RE.findall(text.lower())
            if len(words) < self.n:
                if len(words) >= MIN_SHORT:
                    self.short.setdefault(len(words), {}).setdefault(_h(words), suite)
                    added += 1
                continue
            for i in range(len(words) - self.n + 1):
                self.grams.setdefault(_h(words[i : i + self.n]), suite)
                added += 1
        return added

    def hit(self, text: str) -> str | None:
        words = WORD_RE.findall(text.lower())
        for i in range(len(words) - self.n + 1):
            suite = self.grams.get(_h(words[i : i + self.n]))
            if suite:
                return suite
        for length, table in self.short.items():
            for i in range(len(words) - length + 1):
                suite = table.get(_h(words[i : i + length]))
                if suite:
                    return suite
        return None

    def size(self) -> int:
        return len(self.grams) + sum(len(t) for t in self.short.values())

import hashlib
import re
from collections import defaultdict

import numpy as np

WORD_RE = re.compile(r"[a-z0-9]+")
_MERSENNE = np.uint64((1 << 61) - 1)


def normalize(text: str) -> str:
    return " ".join(WORD_RE.findall(text.lower()))


def exact_key(text: str) -> str:
    return hashlib.sha1(normalize(text).encode()).hexdigest()


def _hash64(s: str) -> int:
    return int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "little")


class MinHashLSH:
    def __init__(self, num_perm: int = 128, bands: int = 32, shingle: int = 5, seed: int = 1) -> None:
        if num_perm % bands:
            raise ValueError("num_perm must be divisible by bands")
        rng = np.random.default_rng(seed)
        self.a = rng.integers(1, int(_MERSENNE), size=num_perm, dtype=np.uint64)
        self.b = rng.integers(0, int(_MERSENNE), size=num_perm, dtype=np.uint64)
        self.bands = bands
        self.rows = num_perm // bands
        self.shingle = shingle
        self.buckets: list[dict[bytes, int]] = [defaultdict(int) for _ in range(bands)]
        self.signatures: dict[int, np.ndarray] = {}

    def signature(self, text: str) -> np.ndarray | None:
        words = WORD_RE.findall(text.lower())
        if len(words) < self.shingle:
            return None
        shingles = {
            _hash64(" ".join(words[i : i + self.shingle])) for i in range(len(words) - self.shingle + 1)
        }
        hv = np.fromiter(shingles, dtype=np.uint64, count=len(shingles))
        with np.errstate(over="ignore"):
            ph = (np.outer(hv, self.a) + self.b) % _MERSENNE
        return ph.min(axis=0)

    def query_insert(self, key: int, text: str, threshold: float = 0.85) -> int | None:
        sig = self.signature(text)
        if sig is None:
            return None
        candidates: set[int] = set()
        band_keys = []
        for i in range(self.bands):
            bk = sig[i * self.rows : (i + 1) * self.rows].tobytes()
            band_keys.append(bk)
            if bk in self.buckets[i]:
                candidates.add(self.buckets[i][bk])
        for c in candidates:
            if float(np.mean(self.signatures[c] == sig)) >= threshold:
                return c
        self.signatures[key] = sig
        for i, bk in enumerate(band_keys):
            self.buckets[i].setdefault(bk, key)
        return None

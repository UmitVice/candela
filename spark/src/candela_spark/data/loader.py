from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from candela_spark import paths
from candela_spark.data.config import DataConfig

_GOLDEN = 0x9E3779B97F4A7C15
_MASK = (1 << 64) - 1


def splitmix64(x: int) -> int:
    x = (x + _GOLDEN) & _MASK
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & _MASK
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & _MASK
    return x ^ (x >> 31)


class SourceStream:
    """One source's documents, in their frozen shuffled order, viewed as a single token stream."""

    def __init__(self, root: Path, source: str, split: str) -> None:
        with np.load(root / source / f"index-{split}.npz") as z:
            self.parts = z["parts"].astype(np.int64)
            self.offsets = z["offsets"]
            self.lengths = z["lengths"].astype(np.int64)
            part_names = [str(p) for p in z["part_names"]]
        self.bins = [np.memmap(root / source / f"{p}.bin", dtype=np.uint16, mode="r") for p in part_names]
        self.cum = np.concatenate([[0], np.cumsum(self.lengths)])
        self.total = int(self.cum[-1])
        self.name = source

    def read(self, start: int, n: int) -> np.ndarray:
        out = np.empty(n, dtype=np.int32)
        filled = 0
        pos = start % self.total
        doc = int(np.searchsorted(self.cum, pos, side="right") - 1)
        while filled < n:
            within = pos - int(self.cum[doc])
            take = min(int(self.lengths[doc]) - within, n - filled)
            base = int(self.offsets[doc]) + within
            out[filled : filled + take] = self.bins[int(self.parts[doc])][base : base + take]
            filled += take
            pos += take
            doc += 1
            if doc >= len(self.lengths):
                doc, pos = 0, 0
        return out


@dataclass
class Cursor:
    rows: int = 0
    per_source: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        return {"rows": self.rows, "perSource": dict(self.per_source)}

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> Cursor:
        per = raw.get("perSource", {})
        return cls(rows=int(raw.get("rows", 0)), per_source={str(k): int(v) for k, v in dict(per).items()})  # type: ignore[arg-type]


class MixtureLoader:
    """Deterministic, resumable mixture: row r picks a source from a hash of (seed, r); each source serves its
    next fixed-length window. The whole data position is the Cursor, so a checkpoint resumes exactly."""

    def __init__(self, cfg: DataConfig, seq_len: int, seed: int, cursor: Cursor | None = None) -> None:
        root = paths.TOKENIZED / cfg.version
        self.seq_len = seq_len
        self.seed = seed
        self.streams: dict[str, SourceStream] = {}
        weights: dict[str, float] = {}
        for name, mult in cfg.mixture.items():
            if mult <= 0 or not (root / name / "index-train.npz").exists():
                continue
            s = SourceStream(root, name, "train")
            self.streams[name] = s
            weights[name] = s.total * mult
        total = sum(weights.values())
        self.names = list(weights)
        self.probs = np.array([weights[n] / total for n in self.names])
        self.cdf = np.cumsum(self.probs)
        self.cursor = cursor or Cursor()
        for n in self.names:
            self.cursor.per_source.setdefault(n, 0)

    def _pick(self, row: int) -> str:
        u = splitmix64(self.seed * 1_000_003 + row) / 2**64
        return self.names[min(int(np.searchsorted(self.cdf, u, side="right")), len(self.names) - 1)]

    def window(self, name: str, index: int) -> np.ndarray:
        stream = self.streams[name]
        span = self.seq_len
        per_epoch = max(1, stream.total // span)
        epoch, i = divmod(index, per_epoch)
        # Each epoch shifts window boundaries by a different prime offset so repeated data is re-cut.
        shift = (epoch * 7919) % span
        return stream.read(i * span + shift, span + 1)

    def next_batch(self, batch: int) -> np.ndarray:
        rows = []
        for _ in range(batch):
            name = self._pick(self.cursor.rows)
            rows.append(self.window(name, self.cursor.per_source[name]))
            self.cursor.per_source[name] += 1
            self.cursor.rows += 1
        return np.stack(rows)

    def epochs(self) -> dict[str, float]:
        return {n: self.cursor.per_source[n] * self.seq_len / self.streams[n].total for n in self.names}


def validation_windows(cfg: DataConfig, seq_len: int, per_source: int) -> dict[str, np.ndarray]:
    root = paths.TOKENIZED / cfg.version
    out: dict[str, np.ndarray] = {}
    for d in sorted(p for p in root.iterdir() if (p / "index-val.npz").exists()):
        s = SourceStream(root, d.name, "val")
        n = min(per_source, max(1, s.total // (seq_len + 1)))
        out[d.name] = np.stack([s.read(i * (seq_len + 1), seq_len + 1) for i in range(n)])
    return out

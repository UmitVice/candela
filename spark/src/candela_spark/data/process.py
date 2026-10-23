import hashlib
import json
import os
import time
from collections import Counter
from collections.abc import Iterator
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow.parquet as pq

from candela_spark import log, paths
from candela_spark.data import clean, minhash
from candela_spark.data.config import DataConfig, Source

_log = log.get("data.process")
MAX_DOC_TOKENS = 32_768
BATCH = 256
# Dedup keeps the first copy, so sources earlier in this list win ties (curated text before web crawl).
PRIORITY = [
    "wikipedia-en",
    "edgar",
    "finemath",
    "cosmopedia-v2",
    "fineweb-edu-finance",
    "fineweb-edu-dedup",
    "fineweb-edu",
]


def iter_raw(src: Source, fname: str) -> Iterator[str]:
    path = paths.RAW / src.id / fname
    if src.format == "parquet":
        pf = pq.ParquetFile(path)
        for batch in pf.iter_batches(batch_size=1024, columns=[src.text_field]):
            for text in batch.column(0).to_pylist():
                if isinstance(text, str):
                    yield text
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            for field in src.text_fields:
                value = obj.get(field)
                if isinstance(value, str) and value:
                    yield clean.clean_edgar(value)


def route(src: Source, text: str) -> str:
    if src.finance_split and clean.is_finance(text):
        return f"{src.id}-finance"
    return src.id


def iter_kept(src: Source, fname: str, stats: Counter[str]) -> Iterator[tuple[str, str]]:
    for raw in iter_raw(src, fname):
        text = clean.normalize(raw)
        res = clean.quality(text, src.kind, src.id)
        stats[f"{src.id}:{res.reason}"] += 1
        if res.keep:
            yield route(src, text), text


def tokenizer_sample(cfg: DataConfig, mb_per_source: float = 24.0) -> Path:
    out_dir = paths.PROCESSED / "tokenizer-sample"
    out_dir.mkdir(parents=True, exist_ok=True)
    budgets = {s.id: mb_per_source for s in cfg.sources}
    budgets["edgar"] = mb_per_source * 1.5
    budgets["fineweb-edu-finance"] = mb_per_source * 0.75
    written: Counter[str] = Counter()
    stats: Counter[str] = Counter()
    handles: dict[str, Any] = {}
    try:
        for src in cfg.sources:
            for fname in src.files:
                for target, text in iter_kept(src, fname, stats):
                    if all(written[t] >= budgets.get(t, mb_per_source) * 1e6 for t in _targets(src)):
                        break
                    if written[target] >= budgets.get(target, mb_per_source) * 1e6:
                        continue
                    if target not in handles:
                        handles[target] = (out_dir / f"{target}.txt").open("w", encoding="utf-8")
                    handles[target].write(text.replace("\x00", "") + "\x00")
                    written[target] += len(text.encode())
    finally:
        for h in handles.values():
            h.close()
    _log.info("tokenizer sample", **{k: round(v / 1e6, 1) for k, v in written.items()})
    return out_dir


def _targets(src: Source) -> list[str]:
    return [src.id, f"{src.id}-finance"] if src.finance_split else [src.id]


def iter_sample_texts(sample_dir: Path) -> Iterator[str]:
    for f in sorted(sample_dir.glob("*.txt")):
        data = f.read_text(encoding="utf-8")
        for doc in data.split("\x00"):
            if doc:
                yield doc


class _PartWriter:
    def __init__(self, out_dir: Path, part: str) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        self.dir = out_dir
        self.part = part
        self.bin = (out_dir / f"{part}.bin.tmp").open("wb")
        self.offset = 0
        self.offsets: list[int] = []
        self.lengths: list[int] = []
        self.exact: list[int] = []
        self.bands: list[np.ndarray] = []

    def add(self, ids: list[int], exact: int, bands: np.ndarray) -> None:
        arr = np.asarray(ids, dtype=np.uint16)
        self.bin.write(arr.tobytes())
        self.offsets.append(self.offset)
        self.lengths.append(len(arr))
        self.offset += len(arr)
        self.exact.append(exact)
        self.bands.append(bands)

    def close(self) -> dict[str, Any]:
        self.bin.flush()
        os.fsync(self.bin.fileno())
        self.bin.close()
        os.replace(self.dir / f"{self.part}.bin.tmp", self.dir / f"{self.part}.bin")
        bands = np.stack(self.bands) if self.bands else np.zeros((0, minhash.BANDS), dtype=np.uint64)
        np.savez(
            self.dir / f"{self.part}.meta.npz",
            offsets=np.asarray(self.offsets, dtype=np.int64),
            lengths=np.asarray(self.lengths, dtype=np.int32),
            exact=np.asarray(self.exact, dtype=np.uint64),
            bands=bands,
        )
        return {"part": self.part, "docs": len(self.lengths), "tokens": int(self.offset)}


def _process_file(version: str, src: Source, fname: str, part: str, tokenizer_path: str) -> dict[str, Any]:
    os.environ.setdefault("RAYON_NUM_THREADS", "2")
    os.nice(10) if os.nice(0) < 10 else None
    from tokenizers import Tokenizer

    from candela_spark.tokenizer import spec

    tok = Tokenizer.from_file(tokenizer_path)
    bos, eos = tok.token_to_id(spec.BOS), tok.token_to_id(spec.EOS)
    root = paths.TOKENIZED / version
    writers: dict[str, _PartWriter] = {}
    stats: Counter[str] = Counter()
    t0 = time.time()
    pending: list[tuple[str, str]] = []

    def flush() -> None:
        encs = tok.encode_batch([t for _, t in pending], add_special_tokens=False)
        for (target, text), enc in zip(pending, encs, strict=True):
            ids = [bos, *enc.ids[: MAX_DOC_TOKENS - 2], eos]
            sig = minhash.signature(text)
            bands = minhash.band_hashes(sig[None, :])[0]
            if target not in writers:
                writers[target] = _PartWriter(root / target, part)
            writers[target].add(ids, minhash.exact_hash(text), bands)
        pending.clear()

    for target, text in iter_kept(src, fname, stats):
        pending.append((target, text))
        if len(pending) >= BATCH:
            flush()
    if pending:
        flush()
    parts = {target: w.close() for target, w in writers.items()}
    return {
        "source": src.id,
        "file": fname,
        "parts": parts,
        "filters": dict(stats),
        "sec": round(time.time() - t0, 1),
    }


def build(cfg: DataConfig, workers: int = 3) -> dict[str, Any]:
    tokenizer_path = str(paths.TOKENIZER_FILE)
    jobs = []
    for src in cfg.sources:
        for i, fname in enumerate(src.files):
            jobs.append((src, fname, f"part-{i:03d}"))
    jobs.sort(key=lambda j: -(paths.RAW / j[0].id / j[1]).stat().st_size)
    results: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futs = {
            pool.submit(_process_file, cfg.version, s, f, p, tokenizer_path): (s.id, f) for s, f, p in jobs
        }
        for fut in as_completed(futs):
            res = fut.result()
            results.append(res)
            _log.info(
                "file processed",
                source=res["source"],
                file=res["file"],
                sec=res["sec"],
                parts={k: v["tokens"] for k, v in res["parts"].items()},
            )
    report = {"version": cfg.version, "files": results}
    (paths.TOKENIZED / cfg.version / "build-report.json").write_text(json.dumps(report, indent=2))
    return report


def _seed_for(cfg: DataConfig, source: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{cfg.seed}:{source}".encode()).digest()[:8], "little")


def dedup_and_index(cfg: DataConfig) -> dict[str, Any]:
    root = paths.TOKENIZED / cfg.version
    sources = [p.name for p in root.iterdir() if p.is_dir()]
    ordered = [s for s in PRIORITY if s in sources] + sorted(s for s in sources if s not in PRIORITY)
    metas: list[tuple[str, str, dict[str, np.ndarray]]] = []
    for s in ordered:
        for meta in sorted((root / s).glob("part-*.meta.npz")):
            with np.load(meta) as z:
                metas.append((s, meta.name.split(".")[0], {k: z[k] for k in z.files}))
    exact = np.concatenate([m["exact"] for _, _, m in metas])
    bands = np.concatenate([m["bands"] for _, _, m in metas])
    n = len(exact)
    keep = np.zeros(n, dtype=bool)
    _, first = np.unique(exact, return_index=True)
    keep[first] = True
    exact_dups = int(n - keep.sum())
    near = np.zeros(n, dtype=bool)
    for b in range(bands.shape[1]):
        _, first_b = np.unique(bands[:, b], return_index=True)
        dup_b = np.ones(n, dtype=bool)
        dup_b[first_b] = False
        near |= dup_b
    near_dups = int((near & keep).sum())
    keep &= ~near
    stats: dict[str, Any] = {
        "docs": n,
        "exactDuplicates": exact_dups,
        "nearDuplicates": near_dups,
        "sources": {},
    }
    cursor = 0
    per_source: dict[str, list[tuple[str, np.ndarray, np.ndarray, np.ndarray]]] = {}
    for s, part, m in metas:
        k = keep[cursor : cursor + len(m["exact"])]
        cursor += len(m["exact"])
        per_source.setdefault(s, []).append((part, m["offsets"][k], m["lengths"][k], np.flatnonzero(k)))
    for s, parts in per_source.items():
        part_ids = np.concatenate(
            [np.full(len(o), i, dtype=np.int16) for i, (_, o, _, _) in enumerate(parts)]
        )
        offsets = np.concatenate([o for _, o, _, _ in parts])
        lengths = np.concatenate([ln for _, _, ln, _ in parts])
        order = np.random.default_rng(_seed_for(cfg, s)).permutation(len(offsets))
        part_ids, offsets, lengths = part_ids[order], offsets[order], lengths[order]
        n_val = min(cfg.validation_docs_per_source, max(1, len(order) // 50))
        splits = {"val": slice(0, n_val), "train": slice(n_val, None)}
        for split, sl in splits.items():
            np.savez(
                root / s / f"index-{split}.npz",
                parts=part_ids[sl],
                offsets=offsets[sl],
                lengths=lengths[sl],
                part_names=np.asarray([p for p, _, _, _ in parts]),
            )
        stats["sources"][s] = {
            "docs": len(order),
            "trainTokens": int(lengths[n_val:].sum()),
            "valTokens": int(lengths[:n_val].sum()),
            "valDocs": int(n_val),
        }
    stats["trainTokens"] = sum(v["trainTokens"] for v in stats["sources"].values())
    (root / "stats.json").write_text(json.dumps(stats, indent=2))
    _log.info(
        "dedup and index",
        docs=n,
        exact=exact_dups,
        near=stats["nearDuplicates"],
        train_tokens=stats["trainTokens"],
    )
    return stats

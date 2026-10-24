import hashlib
import json
import random
import statistics
import time
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.table import Table

from candela_lab import config, log, resources
from candela_lab.data import card, dedup, quality, sources
from candela_lab.data.common import Example, expand_turns, sha256_file, text_of, write_jsonl
from candela_lab.data.decontam import NGramIndex
from candela_lab.paths import CONFIGS_DIR, MANIFESTS_DIR, ML_DIR, PROCESSED_DIR, REPO_ROOT

_log = log.get("data.build")


def data_config(version: str) -> dict[str, Any]:
    return config.load_yaml(CONFIGS_DIR / "data" / f"{version}.yaml")


def fetch(version: str, only: list[str] | None = None, pin: bool = False) -> None:
    from candela_lab.eval import datasets as evalsets

    cfg = data_config(version)
    for src in cfg["sources"]:
        if only and src["id"] not in only:
            continue
        files = sources.fetch_source(src, pin=pin)
        _log.info("fetched source", source=src["id"], files=len(files))
    if not only:
        for suite, files in evalsets.fetch_all(pin=pin).items():
            _log.info("fetched eval set", suite=suite, files=len(files))


def load_tokenizer(model_id: str) -> Any:
    from huggingface_hub import snapshot_download
    from mlx_lm.utils import load_tokenizer as mlx_load_tokenizer

    path = config.model(model_id).base_path()
    local = (
        Path(path)
        if Path(path).exists()
        else Path(snapshot_download(path, allow_patterns=["*.json", "*.jinja"]))
    )
    return mlx_load_tokenizer(local)


def render_tokens(tokenizer: Any, sample: Example) -> int:
    kwargs: dict[str, Any] = {"tokenize": True, "enable_thinking": False}
    if sample.get("tools"):
        kwargs["tools"] = sample["tools"]
    ids = tokenizer.apply_chat_template(sample["messages"], **kwargs)
    if isinstance(ids, dict):
        ids = ids["input_ids"]
    return len(ids)


def _token_stats(lengths: list[int]) -> dict[str, float]:
    if not lengths:
        return {"total": 0, "mean": 0, "p50": 0, "p95": 0, "max": 0}
    ordered = sorted(lengths)
    return {
        "total": sum(ordered),
        "mean": round(statistics.fmean(ordered), 1),
        "p50": ordered[len(ordered) // 2],
        "p95": ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))],
        "max": ordered[-1],
    }


def dedup_text(conv: Example) -> str:
    if not conv["meta"]["task"].startswith("numeric_qa"):
        return text_of(conv)
    parts = []
    for m in conv["messages"]:
        content = m.get("content") or ""
        parts.append(content.rsplit("Question:", 1)[-1] if m["role"] == "user" else content)
    return "\n".join(parts)


def _is_valid(conversation_id: str, fraction: float, seed: int) -> bool:
    h = hashlib.sha256(f"{seed}:{conversation_id}".encode()).digest()
    return int.from_bytes(h[:8], "big") / 2**64 < fraction


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return f"hf-cache/{'/'.join(path.parts[-3:])}"


def build(version: str, tokenizer_model: str | None = None) -> dict[str, Any]:
    from candela_lab.eval import datasets as evalsets

    guard = resources.ResourceGuard(budget_gb=1.5)
    guard.wait_for_headroom(what=f"data build {version}")
    started = time.time()
    cfg = data_config(version)
    seed = int(cfg["seed"])
    max_tokens = int(cfg["maxTokens"])
    tok_model = tokenizer_model if tokenizer_model and tokenizer_model != "lite" else cfg["tokenizerModel"]
    tokenizer = load_tokenizer(tok_model)

    index = NGramIndex()
    eval_counts: Counter[str] = Counter()
    for suite, text in evalsets.decontamination_texts():
        index.add(suite, [text])
        eval_counts[suite] += 1
    _log.info("decontamination index", ngrams=index.size(), eval_texts=sum(eval_counts.values()))

    exact_seen: set[str] = set()
    lsh = dedup.MinHashLSH()
    pii: Counter[str] = Counter()
    decontam_hits: Counter[str] = Counter()
    per_source: dict[str, dict[str, Any]] = {}
    candidates: dict[str, list[list[Example]]] = defaultdict(list)
    key_counter = 0

    for src in cfg["sources"]:
        if src["bucket"] == "none":
            continue
        rng = random.Random(f"{seed}:{src['id']}")
        files = sources.fetch_source(src)
        stats: dict[str, Any] = {
            "id": src["id"],
            "bucket": src["bucket"],
            "license": src["license"],
            "origin": src.get("repo") or src.get("urls") or src.get("path") or ", ".join(src.get("files", [])),
            "files": [{"name": _rel(f), "sha256": sha256_file(f)} for f in files],
            "conversations": 0,
            "dropped": Counter(),
            "kept": 0,
        }
        loader = sources.loader_for(src)
        for conv in loader(src, files, rng) if files else []:
            stats["conversations"] += 1
            issue = quality.quality_issue(conv)
            if issue:
                stats["dropped"][f"quality:{issue}"] += 1
                continue
            quality.scrub(conv, pii)
            text = text_of(conv)
            hit = index.hit(text)
            if hit:
                stats["dropped"]["decontaminated"] += 1
                decontam_hits[hit] += 1
                continue
            key = dedup.exact_key(dedup_text(conv))
            if key in exact_seen:
                stats["dropped"]["exact_duplicate"] += 1
                continue
            exact_seen.add(key)
            key_counter += 1
            if src["kind"] != "traces" and lsh.query_insert(key_counter, dedup_text(conv)) is not None:
                stats["dropped"]["near_duplicate"] += 1
                continue
            stats["kept"] += 1
            candidates[src["id"]].append(expand_turns(conv))
        per_source[src["id"]] = stats
        _log.info(
            "source processed",
            source=src["id"],
            conversations=stats["conversations"],
            kept=stats["kept"],
            dropped=dict(stats["dropped"]),
        )

    selected: list[Example] = []
    buckets: dict[str, dict[str, Any]] = {}
    lengths_by_id: dict[str, int] = {}
    for bucket, target in cfg["mix"].items():
        members = [s for s in cfg["sources"] if s["bucket"] == bucket]
        total_weight = sum(float(s.get("weight", 1.0)) for s in members) or 1.0
        bucket_selected = 0
        for src in members:
            quota = round(target * float(src.get("weight", 1.0)) / total_weight)
            convs = candidates.get(src["id"], [])
            rng = random.Random(f"{seed}:mix:{src['id']}")
            order = list(range(len(convs)))
            rng.shuffle(order)
            taken, too_long = 0, 0
            for i in order:
                if taken >= quota:
                    break
                for sample in convs[i]:
                    if taken >= quota:
                        break
                    n_tok = render_tokens(tokenizer, sample)
                    if n_tok > max_tokens:
                        too_long += 1
                        continue
                    lengths_by_id[sample["meta"]["id"]] = n_tok
                    selected.append(sample)
                    taken += 1
            per_source[src["id"]].update(
                {
                    "samplesAvailable": sum(len(c) for c in convs),
                    "quota": quota,
                    "selected": taken,
                    "tooLong": too_long,
                }
            )
            bucket_selected += taken
        buckets[bucket] = {"target": target, "selected": bucket_selected}

    split_seed = seed
    train: list[Example] = []
    valid: list[Example] = []
    for sample in selected:
        conv_id = sample["meta"]["conversation"]
        (valid if _is_valid(conv_id, float(cfg["validFraction"]), split_seed) else train).append(sample)
    random.Random(f"{seed}:order").shuffle(train)
    valid.sort(key=lambda s: s["meta"]["id"])

    out_dir = PROCESSED_DIR / version
    write_jsonl(out_dir / "train.jsonl", train)
    write_jsonl(out_dir / "valid.jsonl", valid)

    licenses = Counter(s["meta"]["license"] for s in selected)
    tasks = Counter(s["meta"]["task"].split(":")[0] for s in selected)
    manifest = {
        "version": version,
        "createdAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "configHash": config.config_hash(cfg),
        "config": str((CONFIGS_DIR / "data" / f"{version}.yaml").relative_to(ML_DIR)),
        "seed": seed,
        "tokenizer": tok_model,
        "maxTokens": max_tokens,
        "sampleUnit": "one supervised assistant turn with its full prefix",
        "sources": [{**s, "dropped": dict(s["dropped"])} for s in per_source.values()],
        "buckets": buckets,
        "splits": {
            name: {
                "samples": len(rows),
                "conversations": len({r["meta"]["conversation"] for r in rows}),
                "sha256": sha256_file(out_dir / f"{name}.jsonl"),
                "tokens": _token_stats([lengths_by_id[r["meta"]["id"]] for r in rows]),
            }
            for name, rows in (("train", train), ("valid", valid))
        },
        "licenses": dict(licenses.most_common()),
        "tasks": dict(tasks.most_common()),
        "pii": dict(pii),
        "decontamination": {
            "n": index.n,
            "evalTexts": dict(eval_counts),
            "indexSize": index.size(),
            "hitsBySuite": dict(decontam_hits),
        },
        "buildSeconds": round(time.time() - started, 1),
    }
    MANIFESTS_DIR.mkdir(parents=True, exist_ok=True)
    (MANIFESTS_DIR / f"{version}.json").write_text(json.dumps(manifest, indent=2) + "\n")
    card.write(version, manifest=manifest, train=train)
    _log.info(
        "dataset built",
        version=version,
        train=len(train),
        valid=len(valid),
        seconds=manifest["buildSeconds"],
    )
    return manifest


def load_manifest(version: str) -> dict[str, Any]:
    return json.loads((MANIFESTS_DIR / f"{version}.json").read_text())


def print_stats(version: str) -> None:
    m = load_manifest(version)
    console = Console()
    t = Table(title=f"Dataset {version} ({m['configHash']})")
    for col in ("source", "bucket", "license", "conversations", "kept", "selected", "too long", "dropped"):
        t.add_column(col)
    for s in m["sources"]:
        dropped = ", ".join(f"{k}={v}" for k, v in s["dropped"].items())
        t.add_row(
            s["id"],
            s["bucket"],
            s["license"],
            str(s["conversations"]),
            str(s["kept"]),
            str(s.get("selected", 0)),
            str(s.get("tooLong", 0)),
            dropped,
        )
    console.print(t)
    for name, split in m["splits"].items():
        console.print(
            f"{name}: {split['samples']} samples, {split['conversations']} conversations, tokens {split['tokens']}"
        )
    console.print(f"licenses: {m['licenses']}")
    console.print(f"pii scrubbed: {m['pii']}")
    console.print(f"decontamination hits: {m['decontamination']['hitsBySuite']}")

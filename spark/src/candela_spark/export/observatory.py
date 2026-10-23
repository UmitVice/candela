import base64
import json
import time
from pathlib import Path
from typing import Any

import mlx.core as mx
import numpy as np

from candela_spark import paths
from candela_spark.eval.prompts import ATTENTION_SENTENCES
from candela_spark.model.config import PRESETS, param_counts
from candela_spark.model.generate import load_from_checkpoint
from candela_spark.ops.gpu import gpu_job
from candela_spark.tokenizer import spec
from candela_spark.tokenizer.train import frozen_hash
from candela_spark.tokenizer.train import load as load_tokenizer
from candela_spark.train import checkpoint

MAX_POINTS = 2000


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _downsample(rows: list[dict[str, Any]], n: int = MAX_POINTS) -> list[dict[str, Any]]:
    if len(rows) <= n:
        return rows
    idx = np.linspace(0, len(rows) - 1, n).round().astype(int)
    return [rows[i] for i in sorted(set(idx.tolist()))]


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":")))


def architecture(model_id: str) -> dict[str, Any]:
    cfg = PRESETS[model_id]
    counts = param_counts(cfg)
    return {
        "modelId": model_id,
        "family": "candela-spark",
        "layout": "gemma3-compatible decoder",
        "layers": [
            {
                "index": i,
                "attention": "global" if cfg.is_global(i) else "local",
                "window": None if cfg.is_global(i) else cfg.sliding_window,
                "ropeBase": cfg.rope_global_base if cfg.is_global(i) else cfg.rope_local_base,
            }
            for i in range(cfg.num_layers)
        ],
        "hiddenSize": cfg.hidden_size,
        "intermediateSize": cfg.intermediate_size,
        "attentionHeads": cfg.num_heads,
        "kvHeads": cfg.num_kv_heads,
        "headDim": cfg.head_dim,
        "vocabSize": cfg.vocab_size,
        "contextLength": cfg.max_seq_len,
        "tiedEmbeddings": True,
        "parameters": counts,
        "quantization": {
            "bits": cfg.quant.bits,
            "groupSize": cfg.quant.group_size,
            "mode": "affine",
            "qatFromStep": cfg.quant.start_step,
            "scope": "all matrices incl. tied embedding",
        },
        "tokenizer": {
            "type": "byte-level BPE",
            "vocabSize": cfg.vocab_size,
            "sha256": frozen_hash(),
            "specialTokens": len(spec.special_tokens()),
        },
        "familyPresets": [
            {
                "id": k,
                "parameters": param_counts(c)["total"],
                "hiddenSize": c.hidden_size,
                "layers": c.num_layers,
                "heads": c.num_heads,
                "kvHeads": c.num_kv_heads,
                "trained": k == model_id,
            }
            for k, c in PRESETS.items()
        ],
    }


def training(run: str, branch: str | None) -> dict[str, Any]:
    def series(run_id: str) -> dict[str, Any]:
        rows = _jsonl(paths.RUNS / run_id / "metrics.jsonl")
        events = _jsonl(paths.RUNS / run_id / "events.jsonl")
        train = [
            {k: r[k] for k in ("step", "tokens", "loss", "lr", "tokensPerSec", "peakMemGb", "elapsedSec")}
            for r in rows
            if r["type"] == "train"
        ]
        valid = [
            {
                "step": r["step"],
                "tokens": r["tokens"],
                "bf16": r["bf16"],
                "int4": r["int4"],
                "gapRel": r["gapRel"],
                "perSource": r["perSource"],
            }
            for r in rows
            if r["type"] == "val"
        ]
        pauses = [
            {"step": e["step"], "reason": e["reason"], "at": e["at"]} for e in events if e["type"] == "pause"
        ]
        ckpts = sorted({e["step"] for e in events if e["type"] == "checkpoint"})
        return {
            "runId": run_id,
            "train": _downsample(train),
            "valid": valid,
            "pauses": pauses[-200:],
            "checkpoints": ckpts,
        }

    out = {"modelId": "spark-35m", "main": series(run)}
    if branch and (paths.RUNS / branch).exists():
        out["branches"] = [series(branch)]
    return out


def attention(milestone: str) -> dict[str, Any]:
    ckpt = checkpoint.latest_valid(paths.RUNS / milestone / "checkpoints")
    if ckpt is None:
        raise RuntimeError(f"no checkpoint for {milestone}")
    tok = load_tokenizer()
    with gpu_job("spark-export", 60, "observatory attention maps"):
        model = load_from_checkpoint(ckpt)
        model.set_qat(True)
        sentences = []
        for text in ATTENTION_SENTENCES:
            ids = [tok.token_to_id(spec.BOS), *tok.encode(text, add_special_tokens=False).ids]
            _, probs = model.hidden(mx.array([ids]), capture=True)
            t = len(ids)
            tri = np.tril_indices(t)
            layers = []
            for p in probs:
                arr = np.asarray(p[0].astype(mx.float32))
                heads = [
                    base64.b64encode(np.round(h[tri] * 255).astype(np.uint8).tobytes()).decode() for h in arr
                ]
                layers.append(heads)
            sentences.append(
                {
                    "text": text,
                    "tokens": [tok.decode([i]) if i > 127 else tok.id_to_token(i) for i in ids],
                    "layers": layers,
                }
            )
    cfg = model.cfg
    return {
        "modelId": "spark-35m",
        "milestone": milestone,
        "encoding": "uint8-lower-triangular-base64",
        "description": "per layer, per head: row-major lower triangle of the T×T attention matrix, "
        "probability × 255 rounded, base64",
        "layers": cfg.num_layers,
        "heads": cfg.num_heads,
        "layerTypes": ["global" if cfg.is_global(i) else "local" for i in range(cfg.num_layers)],
        "sentences": sentences,
    }


def export(run: str, milestone: str) -> dict[str, Any]:
    out_dir = paths.OBSERVATORY
    model_dir = out_dir / "spark-35m"
    _write(model_dir / "architecture.json", architecture("spark-35m"))
    _write(model_dir / "training.json", training(run, milestone))
    milestones = []
    report = paths.REPORTS / f"{milestone}.json"
    export_meta = paths.ARTIFACTS / milestone / "export.json"
    if report.exists():
        r = json.loads(report.read_text())
        milestones.append(
            {
                "id": milestone,
                "step": r["step"],
                "tokens": r["tokens"],
                "evaluatedAt": r["evaluatedAt"],
                "validation": {
                    "meanBf16": r["validation"]["meanBf16"],
                    "meanInt4": r["validation"]["meanInt4"],
                    "gapRel": r["validation"]["gapRel"],
                },
                "zeroShot": r["zeroShot"],
                "samples": r["samples"][:6],
                "export": json.loads(export_meta.read_text()).get("check") if export_meta.exists() else None,
                "huggingFace": "UmitVice/candela-spark-35m",
            }
        )
    _write(model_dir / "milestones.json", {"modelId": "spark-35m", "milestones": milestones})
    if (paths.RUNS / milestone).exists():
        _write(model_dir / "attention.json", attention(milestone))
    manifest = {
        "schema": "candela.observatory.spark.v1",
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "current": "spark-35m",
        "models": [
            {
                "id": "spark-35m",
                "displayName": "Candela Spark 35M",
                "status": "training",
                "parameters": param_counts(PRESETS["spark-35m"])["total"],
                "files": {
                    "architecture": "spark-35m/architecture.json",
                    "training": "spark-35m/training.json",
                    "milestones": "spark-35m/milestones.json",
                    "attention": "spark-35m/attention.json",
                },
                "huggingFace": "UmitVice/candela-spark-35m",
            }
        ],
        "liveStatus": "~/.candela/spark/status.json (served by the gateway; schema candela.spark.status.v1)",
    }
    _write(out_dir / "manifest.json", manifest)
    sizes = {str(p.relative_to(out_dir)): p.stat().st_size for p in out_dir.rglob("*.json")}
    too_big = {k: v for k, v in sizes.items() if v > 2 * 1024 * 1024}
    if too_big:
        raise RuntimeError(f"observatory artifacts over 2 MB: {too_big}")
    return sizes

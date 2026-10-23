import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from candela_lab import config, log
from candela_lab.paths import ML_OBSERVATORY_DIR, RUNS_DIR, WEB_DIR, WEB_OBSERVATORY_DIR
from candela_lab.train.deltas import CONTRACT_MODULES

_log = log.get("observatory")
MAX_POINTS = 2000
MAX_BYTES = 2 * 1024 * 1024


def _dump(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    if len(text.encode()) > MAX_BYTES:
        raise ValueError(f"{path.name} exceeds 2 MB ({len(text.encode())} bytes)")
    path.write_text(text)


def _downsample(rows: list[dict[str, Any]], limit: int = MAX_POINTS) -> list[dict[str, Any]]:
    if len(rows) <= limit:
        return rows
    stride = len(rows) / limit
    picked = [rows[int(i * stride)] for i in range(limit - 1)]
    return [*picked, rows[-1]]


def _metrics(rd: Path) -> list[dict[str, Any]]:
    path = rd / "metrics.jsonl"
    return (
        [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
    )


def observatory_meta(run_cfg: dict[str, Any], run_id: str) -> dict[str, Any]:
    meta = run_cfg.get("observatory") or {}
    return {
        "modelId": meta.get("modelId", run_id),
        "displayName": meta.get("displayName", run_id),
        "version": meta.get("version", "dev"),
        "tier": "pro",
    }


def export_run(run_id: str) -> Path:
    rd = RUNS_DIR / run_id
    run = json.loads((rd / "run.json").read_text())
    state = json.loads((rd / "state.json").read_text())
    cfg = run["config"]
    spec = config.model(cfg["model"])
    meta = observatory_meta(cfg, run_id)
    model_id = meta["modelId"]
    out = ML_OBSERVATORY_DIR / "models" / model_id
    arch = spec.architecture
    lora = run["lora"]
    _dump(
        out / "architecture.json",
        {
            "modelId": model_id,
            "baseModel": spec.upstream,
            "family": spec.family,
            "layers": arch.get("layers"),
            "hiddenSize": arch.get("hiddenSize"),
            "intermediateSize": arch.get("intermediateSize"),
            "attentionHeads": arch.get("attentionHeads"),
            "kvHeads": arch.get("kvHeads"),
            "headDim": arch.get("headDim"),
            "vocabSize": arch.get("vocabSize"),
            "contextLength": spec.context_length,
            "parameters": int(run.get("totalParameters") or 0),
            "tiedEmbeddings": bool(arch.get("tiedEmbeddings", False)),
            "lora": {
                "rank": int(lora["rank"]),
                "scale": float(lora["scale"]),
                "dropout": float(lora["dropout"]),
                "layerIndices": run["layerIndices"],
                "modules": run["modules"],
                "trainableParameters": int(run["trainableParameters"]),
            },
        },
    )
    rows = _metrics(rd)
    train = [
        {k: r[k] for k in ("step", "loss", "lr", "tokensPerSec", "peakMemGb", "elapsedSec")}
        for r in rows
        if r["type"] == "train"
    ]
    valid = [{"step": r["step"], "loss": r["loss"]} for r in rows if r["type"] == "valid"]
    delta_rows = [r for r in rows if r["type"] == "deltas"]
    pauses = [{"step": r["step"], "reason": r["reason"], "at": r["at"]} for r in rows if r["type"] == "pause"]
    opt = cfg.get("optimizer", {})
    _dump(
        out / "training.json",
        {
            "modelId": model_id,
            "runId": run_id,
            "status": state["status"]
            if state["status"] in ("running", "paused", "completed", "failed")
            else "running",
            "startedAt": state.get("started_at"),
            "finishedAt": state.get("finished_at"),
            "hardware": {
                "device": run.get("device") or "Apple Silicon",
                "memoryLimitGb": run.get("memoryLimitGb"),
            },
            "config": {
                "iters": int(cfg.get("iters", 0)),
                "batchSize": int(cfg.get("batchSize", 1)),
                "gradAccumulation": int(cfg.get("gradAccumulation", 1)),
                "learningRate": float(opt.get("learningRate", 1e-4)),
                "schedule": f"cosine with {opt.get('warmup', 0)}-step linear warm-up",
                "maxSeqLength": int(cfg.get("maxSeqLength", 2048)),
                "datasetVersion": cfg.get("data", {}).get("version", "d0.1"),
                "trainExamples": int(run["trainExamples"]),
                "validExamples": int(run["validExamples"]),
            },
            "train": _downsample(train),
            "valid": _downsample(valid),
            "checkpoints": [r["step"] for r in delta_rows],
            "pauses": pauses,
        },
    )
    layers = int(arch.get("layers") or (len(delta_rows[0]["norms"]) if delta_rows else 0))
    _dump(
        out / "lora-deltas.json",
        {
            "modelId": model_id,
            "modules": CONTRACT_MODULES,
            "layers": layers,
            "checkpoints": [
                {
                    "step": r["step"],
                    "maxNorm": max((v for row in r["norms"] for v in row), default=0.0),
                    "norms": r["norms"],
                }
                for r in delta_rows
            ],
        },
    )
    entry = {
        "id": model_id,
        "displayName": meta["displayName"],
        "version": meta["version"],
        "tier": "pro",
        "baseModel": spec.upstream,
        "status": "evaluated" if (out / "eval.json").exists() else "training",
        "files": {
            "architecture": f"models/{model_id}/architecture.json",
            "training": f"models/{model_id}/training.json",
            "loraDeltas": f"models/{model_id}/lora-deltas.json",
        },
    }
    if (out / "eval.json").exists():
        entry["files"]["eval"] = f"models/{model_id}/eval.json"
    _dump(out / "entry.json", entry)
    _log.info("observatory artifacts exported", run_id=run_id, model_id=model_id, path=str(out))
    return out


def write_manifest(current: str | None = None) -> Path:
    entries = []
    for entry_path in sorted((ML_OBSERVATORY_DIR / "models").glob("*/entry.json")):
        entry = json.loads(entry_path.read_text())
        model_dir = entry_path.parent
        if (model_dir / "eval.json").exists():
            entry["files"]["eval"] = f"models/{entry['id']}/eval.json"
            entry["status"] = "evaluated" if entry["status"] == "training" else entry["status"]
        entries.append(entry)
    if not entries:
        raise RuntimeError("no exported models; run `lab observatory export <run-id>` first")
    manifest: dict[str, Any] = {
        "generatedAt": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "current": current or entries[-1]["id"],
        "models": entries,
    }
    if (ML_OBSERVATORY_DIR / "galaxy.json").exists():
        manifest["galaxy"] = "galaxy.json"
    path = ML_OBSERVATORY_DIR / "manifest.json"
    _dump(path, manifest)
    return path


def sync() -> Path | None:
    if not (WEB_DIR / "package.json").exists():
        _log.warning("apps/web is not scaffolded yet; artifacts stay in ml/artifacts/observatory")
        return None
    WEB_OBSERVATORY_DIR.mkdir(parents=True, exist_ok=True)
    copied = 0
    for src in ML_OBSERVATORY_DIR.rglob("*.json"):
        if src.name == "entry.json":
            continue
        dst = WEB_OBSERVATORY_DIR / src.relative_to(ML_OBSERVATORY_DIR)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied += 1
    _log.info("observatory synced", files=copied, target=str(WEB_OBSERVATORY_DIR))
    return WEB_OBSERVATORY_DIR

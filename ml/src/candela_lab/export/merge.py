"""Merged Candela Pro quant pack: the LoRA delta is added to the bf16 QAT reference weights in a copy of the
checkpoint, one tensor at a time through mmap (never the whole 22 GB in memory), then converted to GGUF (llama.cpp
`convert_hf_to_gguf.py` + `llama-quantize`) and MLX (`mlx_lm.convert`). Merging plus post-training quantization
loses part of the QAT advantage of the unmerged release (ADR 0403)."""

import hashlib
import json
import mmap
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

from candela_lab import config, gpu_lease, log, resources
from candela_lab.export.gguf import LLAMA_CPP_DIR, _hf_name
from candela_lab.paths import RUNS_DIR

_log = log.get("export.merge")

GGUF_QUANTS = ["Q4_K_M", "Q5_K_M", "Q6_K", "Q8_0"]
MLX_QUANTS = {"mlx-4bit": (4, 32), "mlx-8bit": (8, 64)}


def _header(path: Path) -> tuple[dict[str, Any], int]:
    with path.open("rb") as f:
        n = int.from_bytes(f.read(8), "little")
        return json.loads(f.read(n)), 8 + n


def _bf16_to_f32(raw: np.ndarray) -> np.ndarray:
    return (raw.astype(np.uint32) << 16).view(np.float32)


def _f32_to_bf16(x: np.ndarray) -> np.ndarray:
    u = x.astype(np.float32).view(np.uint32)
    return ((u + 0x7FFF + ((u >> 16) & 1)) >> 16).astype(np.uint16)


def _lora_pairs(adapter_dir: Path) -> tuple[dict[str, tuple[np.ndarray, np.ndarray]], float]:
    import mlx.core as mx

    cfg = json.loads((adapter_dir / "adapter_config.json").read_text())
    weights = mx.load(str(adapter_dir / "adapters.safetensors"))
    pairs: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    names = sorted(str(k) for k in weights)  # type: ignore[union-attr]
    for name in names:
        module, leaf = name.rsplit(".", 1)
        if leaf != "lora_a":
            continue
        a = np.array(weights[module + ".lora_a"].astype(mx.float32))  # type: ignore[index]
        b = np.array(weights[module + ".lora_b"].astype(mx.float32))  # type: ignore[index]
        pairs[_hf_name(module) + ".weight"] = (a, b)
    return pairs, float(cfg["lora_parameters"]["scale"])


def merge(run_id: str, out: Path | None = None) -> Path:
    spec = config.model("gemma-4-12b-qat")
    ref = Path(spec.reference_path() or "")
    src = ref / "model.safetensors"
    rd = RUNS_DIR / run_id
    target = out or rd / "export" / "merged-bf16"
    done = target / "merge.json"
    if done.exists():
        _log.info("merged checkpoint exists", path=str(target))
        return target
    target.mkdir(parents=True, exist_ok=True)
    for f in ref.iterdir():
        if f.is_file() and f.name != "model.safetensors":
            shutil.copy2(f, target / f.name)
    t0 = time.time()
    dst = target / "model.safetensors"
    shutil.copyfile(src, dst)
    header, data_start = _header(dst)
    pairs, scale = _lora_pairs(rd / "adapter")
    max_delta = 0.0
    with dst.open("r+b") as f, mmap.mmap(f.fileno(), 0) as mm:
        for key, (a, b) in pairs.items():
            info = header[key]
            if info["dtype"] != "BF16":
                raise ValueError(f"{key}: expected BF16, got {info['dtype']}")
            start, end = (data_start + o for o in info["data_offsets"])
            shape = tuple(info["shape"])
            delta = scale * (a @ b).T
            if delta.shape != shape:
                raise ValueError(f"{key}: delta {delta.shape} does not match weight {shape}")
            w = _bf16_to_f32(np.frombuffer(mm[start:end], dtype=np.uint16).reshape(shape))
            mm[start:end] = _f32_to_bf16(w + delta).tobytes()
            max_delta = max(max_delta, float(np.abs(delta).max()))
        mm.flush()
    adapter_sha = hashlib.sha256((rd / "adapter" / "adapters.safetensors").read_bytes()).hexdigest()
    done.write_text(
        json.dumps(
            {
                "run": run_id,
                "reference": str(src),
                "adapterSha256": adapter_sha,
                "scale": scale,
                "mergedTensors": len(pairs),
                "maxAbsDelta": round(max_delta, 6),
                "seconds": round(time.time() - t0, 1),
            },
            indent=2,
        )
        + "\n"
    )
    _log.info("merged", tensors=len(pairs), max_abs_delta=round(max_delta, 5), path=str(target))
    return target


def _run(cmd: list[str], cwd: Path | None = None) -> None:
    _log.info("exec", cmd=" ".join(cmd[:4]) + " …")
    subprocess.run(cmd, check=True, cwd=cwd)


def gguf(run_id: str, quants: list[str] | None = None) -> list[Path]:
    rd = RUNS_DIR / run_id
    merged = merge(run_id)
    out_dir = rd / "export" / "gguf"
    out_dir.mkdir(parents=True, exist_ok=True)
    bf16 = out_dir / "candela-pro-12b-v0.1-bf16.gguf"
    if not bf16.exists():
        _run(
            [
                sys.executable,
                str(LLAMA_CPP_DIR / "convert_hf_to_gguf.py"),
                str(merged),
                "--outtype",
                "bf16",
                "--outfile",
                str(bf16),
            ]
        )
    written = []
    for q in quants or GGUF_QUANTS:
        path = out_dir / f"candela-pro-12b-v0.1-{q}.gguf"
        if not path.exists():
            _run(["llama-quantize", str(bf16), str(path), q, "4"])
        written.append(path)
    return written


def mlx(run_id: str, variants: list[str] | None = None) -> list[Path]:
    from mlx_lm import convert

    rd = RUNS_DIR / run_id
    merged = merge(run_id)
    spec = config.model("gemma-4-12b-qat")
    guard = resources.ResourceGuard(budget_gb=spec.train_budget_gb, policy=resources.PRO_POLICY)
    written = []
    for name in variants or list(MLX_QUANTS):
        bits, group = MLX_QUANTS[name]
        path = rd / "export" / name
        if (path / "config.json").exists():
            written.append(path)
            continue
        with gpu_lease.Lease("lab-export", purpose=f"mlx convert {name}", state="waiting") as lease:
            guard.wait_for_headroom(what=f"mlx convert {name}")
            lease.activate()
            convert(str(merged), mlx_path=str(path), quantize=True, q_bits=bits, q_group_size=group)
            resources.release_mlx_memory()
        written.append(path)
    return written

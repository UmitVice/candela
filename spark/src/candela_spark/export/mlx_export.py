import hashlib
import json
import shutil
import time
from pathlib import Path
from typing import Any, cast

import mlx.core as mx
import numpy as np
from mlx.utils import tree_flatten

from candela_spark import log, paths
from candela_spark.data import config as data_config
from candela_spark.data.loader import validation_windows
from candela_spark.model.generate import load_from_checkpoint
from candela_spark.model.qat import QATLinear, quantize_export
from candela_spark.model.quantized import load_int4
from candela_spark.model.transformer import SparkLM
from candela_spark.ops.gpu import gpu_job
from candela_spark.tokenizer.train import frozen_hash
from candela_spark.train import checkpoint

_log = log.get("export")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _config_json(model: SparkLM, state: dict[str, Any], fmt: str) -> dict[str, Any]:
    cfg = model.cfg
    out: dict[str, Any] = {
        "model_type": "candela-spark",
        "architecture": "gemma3-compatible decoder (ADR 0600)",
        "format": fmt,
        "spark": cfg.to_dict(),
        "vocab_size": cfg.vocab_size,
        "hidden_size": cfg.hidden_size,
        "num_hidden_layers": cfg.num_layers,
        "num_attention_heads": cfg.num_heads,
        "num_key_value_heads": cfg.num_kv_heads,
        "head_dim": cfg.head_dim,
        "intermediate_size": cfg.intermediate_size,
        "max_position_embeddings": cfg.max_seq_len,
        "sliding_window": cfg.sliding_window,
        "sliding_window_pattern": cfg.global_every,
        "rope_theta": cfg.rope_global_base,
        "rope_local_base_freq": cfg.rope_local_base,
        "rms_norm_eps": cfg.norm_eps,
        "tie_word_embeddings": True,
        "bos_token_id": 1,
        "eos_token_id": 2,
        "pad_token_id": 0,
        "tokenizer_sha256": frozen_hash(),
        "training": {
            "step": state["step"],
            "tokens": state["tokens"],
            "run": state["runId"],
            "dataVersion": state["dataVersion"],
            "forkOrigin": state.get("forkOrigin"),
        },
    }
    if fmt == "mlx-int4":
        out["quantization"] = {
            "group_size": cfg.quant.group_size,
            "bits": cfg.quant.bits,
            "mode": "affine",
            "scale_dtype": cfg.quant.storage_dtype,
            "qat": True,
        }
    return out


def int4_weights(model: SparkLM) -> dict[str, mx.array]:
    q = model.cfg.quant
    out: dict[str, mx.array] = {}
    for name, mod in model.named_modules():
        if isinstance(mod, QATLinear):
            w, s, b = quantize_export(mod.weight, q)
            out[f"{name}.weight"], out[f"{name}.scales"], out[f"{name}.biases"] = w, s, b
    w, s, b = quantize_export(model.embed_tokens, q)
    out["embed_tokens.weight"], out["embed_tokens.scales"], out["embed_tokens.biases"] = w, s, b
    for k, v in tree_flatten(model.parameters()):
        if k.endswith("norm.weight"):
            out[k] = cast(mx.array, v).astype(mx.bfloat16)
    return out


def export(run: str, name: str, gguf: bool = True) -> dict[str, Any]:
    ckpt = checkpoint.latest_valid(paths.RUNS / run / "checkpoints")
    if ckpt is None:
        raise RuntimeError(f"no valid checkpoint for {run}")
    state = json.loads((ckpt / "state.json").read_text())
    root = paths.ARTIFACTS / name
    int4_dir, bf16_dir = root / "mlx-int4", root / "mlx-bf16"
    for d in (int4_dir, bf16_dir):
        d.mkdir(parents=True, exist_ok=True)
        shutil.copy(paths.TOKENIZER_FILE, d / "tokenizer.json")
    result: dict[str, Any] = {
        "name": name,
        "checkpoint": ckpt.name,
        "step": state["step"],
        "tokens": state["tokens"],
    }
    with gpu_job("spark-export", 60, f"spark export {name}"):
        model = load_from_checkpoint(ckpt)
        q_weights = int4_weights(model)
        mx.save_safetensors(str(int4_dir / "model.safetensors"), q_weights, metadata={"format": "mlx"})
        (int4_dir / "config.json").write_text(json.dumps(_config_json(model, state, "mlx-int4"), indent=2))
        bf = {k: cast(mx.array, v).astype(mx.bfloat16) for k, v in tree_flatten(model.parameters())}
        mx.save_safetensors(str(bf16_dir / "model.safetensors"), bf, metadata={"format": "mlx"})
        (bf16_dir / "config.json").write_text(json.dumps(_config_json(model, state, "mlx-bf16"), indent=2))
        result["check"] = check_export(model, int4_dir, state)
        if gguf:
            from candela_spark.export.gguf_export import write_gguf

            gpath = root / f"{name}-Q4_1.gguf"
            result["gguf"] = write_gguf(q_weights, model.cfg, gpath, name)
            result["gguf"]["sha256"] = _sha(gpath)
    for d in (int4_dir, bf16_dir):
        result[d.name] = {
            "bytes": (d / "model.safetensors").stat().st_size,
            "sha256": _sha(d / "model.safetensors"),
        }
    (root / "export.json").write_text(json.dumps(result, indent=2))
    _log.info("exported", **{k: v for k, v in result.items() if k in ("name", "step", "check")})
    return result


def check_export(model: SparkLM, int4_dir: Path, state: dict[str, Any]) -> dict[str, Any]:
    """The exported int4 model must reproduce the QAT forward pass (same grid, different kernels)."""
    t0 = time.time()
    qmodel = load_int4(int4_dir)
    model.set_qat(True)
    windows = validation_windows(data_config.load(state["dataVersion"]), 1024, 4)
    max_diff, rel_loss = 0.0, []
    for arr in list(windows.values()):
        x = mx.array(arr[:2, :-1])
        y = arr[:2, 1:]
        a = model(x).astype(mx.float32)
        b = qmodel(x).astype(mx.float32)
        max_diff = max(max_diff, float(mx.abs(a - b).max()))
        la = float(_ce(a, y))
        lb = float(_ce(b, y))
        rel_loss.append(abs(lb - la) / la)
    out = {
        "maxAbsLogitDiff": round(max_diff, 5),
        "maxRelLossDiff": round(max(rel_loss), 6),
        "ok": max(rel_loss) < 1e-3,
        "sec": round(time.time() - t0, 1),
    }
    if not out["ok"]:
        raise RuntimeError(f"int4 export does not reproduce the QAT forward pass: {out}")
    return out


def _ce(logits: mx.array, y: np.ndarray) -> mx.array:
    lse = mx.logsumexp(logits, axis=-1)
    picked = mx.take_along_axis(logits, mx.array(y)[..., None], axis=-1).squeeze(-1)
    return (lse - picked).mean()

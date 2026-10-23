import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

import mlx.core as mx
from mlx.utils import tree_flatten, tree_unflatten

from candela_spark import log

_log = log.get("checkpoint")
FORMAT = "candela.spark.checkpoint.v1"


def _fsync_file(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(8 << 20):
            h.update(block)
    return h.hexdigest()


def _flat(tree: Any) -> dict[str, mx.array]:
    out: dict[str, mx.array] = {}
    for k, v in tree_flatten(tree):
        if isinstance(v, mx.array):
            out[k] = v.reshape(1) if v.ndim == 0 else v
    return out


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, sort_keys=True))


def save(
    root: Path,
    step: int,
    params: Any,
    opt_state: Any,
    state: dict[str, Any],
    keep_last: int = 3,
    milestone: bool = False,
) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    name = f"step-{step:08d}"
    tmp = root / f".tmp-{name}-{os.getpid()}"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir()
    flat_opt = _flat(opt_state)
    scalars = sorted(k for k, v in tree_flatten(opt_state) if isinstance(v, mx.array) and v.ndim == 0)
    mx.save_safetensors(str(tmp / "model.safetensors"), _flat(params))
    mx.save_safetensors(str(tmp / "optimizer.safetensors"), flat_opt)
    _write_json(
        tmp / "state.json",
        {**state, "format": FORMAT, "step": step, "milestone": milestone, "optimizerScalars": scalars},
    )
    files = {}
    for f in ("model.safetensors", "optimizer.safetensors", "state.json"):
        _fsync_file(tmp / f)
        files[f] = {"sha256": _sha256(tmp / f), "bytes": (tmp / f).stat().st_size}
    _write_json(tmp / "manifest.json", {"format": FORMAT, "step": step, "files": files})
    _fsync_file(tmp / "manifest.json")
    _fsync_dir(tmp)
    final = root / name
    if final.exists():
        shutil.rmtree(final)
    os.replace(tmp, final)
    _fsync_dir(root)
    pointer = root / "latest.tmp"
    pointer.write_text(name + "\n")
    _fsync_file(pointer)
    os.replace(pointer, root / "latest")
    _fsync_dir(root)
    _prune(root, keep_last)
    return final


def _is_milestone(d: Path) -> bool:
    try:
        return bool(json.loads((d / "state.json").read_text()).get("milestone"))
    except OSError, ValueError:
        return False


def _strip_optimizer(d: Path) -> None:
    opt = d / "optimizer.safetensors"
    if not opt.exists():
        return
    manifest = json.loads((d / "manifest.json").read_text())
    manifest["files"].pop("optimizer.safetensors", None)
    manifest["optimizerStripped"] = True
    tmp = d / "manifest.json.tmp"
    _write_json(tmp, manifest)
    _fsync_file(tmp)
    os.replace(tmp, d / "manifest.json")
    opt.unlink()


def _prune(root: Path, keep_last: int, keep_milestone_optimizers: int = 2) -> None:
    ordered = sorted(root.glob("step-*"))
    regular = [d for d in ordered if not _is_milestone(d)]
    for d in regular[:-keep_last]:
        shutil.rmtree(d, ignore_errors=True)
    # Old milestones stay as fork points with fp32 weights only, so weeks of training do not fill the disk.
    milestones = [d for d in ordered if _is_milestone(d)]
    for d in milestones[:-keep_milestone_optimizers]:
        _strip_optimizer(d)
    for d in root.glob(".tmp-*"):
        if not d.name.endswith(f"-{os.getpid()}"):
            shutil.rmtree(d, ignore_errors=True)


def verify(d: Path) -> bool:
    try:
        manifest = json.loads((d / "manifest.json").read_text())
        return all(_sha256(d / f) == meta["sha256"] for f, meta in manifest["files"].items())
    except OSError, ValueError, KeyError:
        return False


def candidates(root: Path) -> list[Path]:
    if not root.exists():
        return []
    ordered = sorted(root.glob("step-*"), reverse=True)
    pointer = root / "latest"
    if pointer.exists():
        named = root / pointer.read_text().strip()
        if named in ordered:
            ordered.remove(named)
            ordered.insert(0, named)
    return ordered


def latest_valid(root: Path) -> Path | None:
    for d in candidates(root):
        if verify(d):
            return d
        _log.warning("checkpoint failed verification, falling back", checkpoint=d.name)
    return None


def load(d: Path) -> tuple[dict[str, mx.array], Any, dict[str, Any]]:
    params = mx.load(str(d / "model.safetensors"))
    assert isinstance(params, dict)
    state = json.loads((d / "state.json").read_text())
    if not (d / "optimizer.safetensors").exists():
        _log.warning("checkpoint has no optimizer state; optimizer restarts", checkpoint=d.name)
        return params, None, state
    raw_opt = mx.load(str(d / "optimizer.safetensors"))
    assert isinstance(raw_opt, dict)
    scalars = set(state.get("optimizerScalars", []))
    items = [(k, v.reshape(()) if k in scalars else v) for k, v in raw_opt.items()]
    return params, tree_unflatten(items), state

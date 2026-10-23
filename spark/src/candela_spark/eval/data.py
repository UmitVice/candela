import hashlib
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import yaml
from huggingface_hub import hf_hub_download

from candela_spark import paths


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch() -> dict[str, Any]:
    cfg = yaml.safe_load((paths.CONFIGS / "data" / "eval.yaml").read_text())
    manifest: dict[str, Any] = {}
    for s in cfg["suites"]:
        for f in s["files"]:
            if not f.endswith(".parquet"):
                raise ValueError(f"only parquet allowed: {f}")
            got = Path(
                hf_hub_download(
                    s["repo"],
                    f,
                    repo_type="dataset",
                    revision=s["revision"],
                    local_dir=paths.EVAL_DATA / s["id"],
                )
            )
            manifest[f"{s['id']}/{f}"] = {
                "repo": s["repo"],
                "revision": s["revision"],
                "license": s["license"],
                "bytes": got.stat().st_size,
                "sha256": _sha(got),
            }
    (paths.EVAL_DATA / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    return manifest


def rows(suite: str) -> list[dict[str, Any]]:
    cfg = yaml.safe_load((paths.CONFIGS / "data" / "eval.yaml").read_text())
    spec = next(s for s in cfg["suites"] if s["id"] == suite)
    out: list[dict[str, Any]] = []
    for f in spec["files"]:
        table = pq.read_table(paths.EVAL_DATA / suite / f)
        for r in table.to_pylist():
            r["_file"] = f
            out.append(r)
    return out

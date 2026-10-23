import hashlib
import json
import time
from pathlib import Path
from typing import Any

from huggingface_hub import HfApi, hf_hub_download

from candela_spark import log, paths
from candela_spark.data.config import DataConfig, Source

_log = log.get("data.fetch")


def sha256_file(path: Path, chunk: int = 8 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def _remote_meta(api: HfApi, src: Source) -> dict[str, tuple[int, str | None]]:
    meta: dict[str, tuple[int, str | None]] = {}
    infos = api.get_paths_info(src.repo, src.files, repo_type="dataset", revision=src.revision)
    for info in infos:
        size = getattr(info, "size", 0) or 0
        lfs = getattr(info, "lfs", None)
        meta[info.path] = (int(size), lfs.sha256 if lfs is not None else None)
    return meta


def manifest_path(cfg: DataConfig) -> Path:
    return paths.RAW / f"manifest-{cfg.version}.json"


def fetch(cfg: DataConfig, only: list[str] | None = None) -> dict[str, Any]:
    api = HfApi()
    mpath = manifest_path(cfg)
    manifest: dict[str, Any] = json.loads(mpath.read_text()) if mpath.exists() else {"files": {}}
    manifest["version"] = cfg.version
    for src in cfg.sources:
        if only and src.id not in only:
            continue
        info = api.dataset_info(src.repo, revision=src.revision)
        card_license = (info.card_data or {}).get("license") if info.card_data else None
        licenses = card_license if isinstance(card_license, list) else [card_license]
        if src.license not in licenses:
            raise RuntimeError(f"{src.id}: card license {card_license} != configured {src.license}")
        if info.gated or info.private:
            raise RuntimeError(f"{src.id}: gated or private datasets are not allowed")
        remote = _remote_meta(api, src)
        dest_root = paths.RAW / src.id
        for fname in src.files:
            key = f"{src.id}/{fname}"
            size, lfs_sha = remote[fname]
            local = dest_root / fname
            prior = manifest["files"].get(key)
            if local.exists() and prior and prior["sha256"] and local.stat().st_size == prior["bytes"]:
                _log.info("present", file=key)
                continue
            t0 = time.time()
            got = Path(
                hf_hub_download(
                    src.repo, fname, repo_type="dataset", revision=src.revision, local_dir=dest_root
                )
            )
            digest = sha256_file(got)
            if lfs_sha is not None and digest != lfs_sha:
                got.unlink()
                raise RuntimeError(f"{key}: sha256 mismatch against the hub LFS pointer")
            if got.stat().st_size != size:
                raise RuntimeError(f"{key}: size mismatch")
            manifest["files"][key] = {
                "repo": src.repo,
                "revision": src.revision,
                "path": fname,
                "license": src.license,
                "bytes": size,
                "sha256": digest,
                "verifiedAgainstHub": lfs_sha is not None,
            }
            mpath.parent.mkdir(parents=True, exist_ok=True)
            mpath.write_text(json.dumps(manifest, indent=2, sort_keys=True))
            _log.info("downloaded", file=key, bytes=size, sec=round(time.time() - t0, 1))
    return manifest


def verify(cfg: DataConfig) -> list[str]:
    manifest = json.loads(manifest_path(cfg).read_text())
    bad: list[str] = []
    for key, entry in manifest["files"].items():
        local = paths.RAW / key
        if not local.exists() or sha256_file(local) != entry["sha256"]:
            bad.append(key)
    return bad

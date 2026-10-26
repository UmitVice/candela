import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(os.environ.get("CANDELA_REPO_ROOT") or Path(__file__).resolve().parents[4])
PROTOCOL = "candela.worker.v1"
VERSION = "0.1.0"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    return float(raw) if raw else default


def resolve_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


@dataclass(frozen=True)
class Settings:
    gateway_url: str
    token: str
    model_ids: list[str]
    worker_id: str
    device: str | None
    http_host: str
    http_port: int
    idle_unload_sec: float
    admission_wait_sec: float
    reserve_gb: float
    max_prompt_tokens: int
    prefill_chunk: int
    kv_bits: int
    kv_start: int
    prompt_cache_entries: int
    prompt_cache_mb: int
    cache_limit_mb: int
    production: bool
    models_config: Path
    served_config: Path

    @classmethod
    def from_env(cls) -> Settings:
        ids = os.environ.get("CANDELA_WORKER_MODEL", "").strip()
        return cls(
            gateway_url=os.environ.get("CANDELA_WORKER_URL", "ws://127.0.0.1:8719/api/v1/worker/connect"),
            token=os.environ.get("CANDELA_WORKER_TOKEN", ""),
            model_ids=[m.strip() for m in ids.split(",") if m.strip()],
            worker_id=os.environ.get("CANDELA_WORKER_ID", "candela-worker"),
            device=os.environ.get("CANDELA_WORKER_DEVICE") or None,
            http_host="127.0.0.1",
            http_port=_env_int("CANDELA_WORKER_HTTP_PORT", 8711),
            idle_unload_sec=_env_float("CANDELA_WORKER_IDLE_UNLOAD_SEC", 900.0),
            admission_wait_sec=_env_float("CANDELA_WORKER_ADMISSION_WAIT_SEC", 30.0),
            reserve_gb=_env_float("CANDELA_WORKER_RESERVE_GB", 1.0),
            max_prompt_tokens=_env_int("CANDELA_WORKER_MAX_PROMPT_TOKENS", 16384),
            prefill_chunk=_env_int("CANDELA_WORKER_PREFILL_CHUNK", 256),
            kv_bits=_env_int("CANDELA_WORKER_KV_BITS", 0),
            kv_start=_env_int("CANDELA_WORKER_KV_START", 4096),
            prompt_cache_entries=_env_int("CANDELA_WORKER_PROMPT_CACHE_ENTRIES", 4),
            prompt_cache_mb=_env_int("CANDELA_WORKER_PROMPT_CACHE_MB", 1024),
            cache_limit_mb=_env_int("CANDELA_WORKER_MLX_CACHE_MB", 512),
            production=os.environ.get("CANDELA_ENV", "development") == "production",
            models_config=resolve_path(
                os.environ.get("CANDELA_WORKER_MODELS_CONFIG", "ml/configs/models.yaml")
            ),
            served_config=resolve_path(
                os.environ.get("CANDELA_WORKER_SERVED_CONFIG", "services/worker/served-models.yaml")
            ),
        )


@dataclass(frozen=True)
class ModelSpec:
    id: str
    display_name: str
    version: str
    family: str
    base_model: str
    path: Path | None
    hf_repo: str | None
    hf_revision: str | None
    adapter: Path | None
    quantization: str
    parameters: str
    budget_gb: float
    architecture: dict[str, Any] = field(default_factory=dict)
    stop: list[str] = field(default_factory=list)


def _override(entry: dict[str, Any]) -> Path:
    env = entry.get("env")
    return resolve_path(os.environ.get(env, "") or entry["path"]) if env else resolve_path(entry["path"])


def load_registry(settings: Settings) -> dict[str, ModelSpec]:
    served = yaml.safe_load(settings.served_config.read_text())
    bases: dict[str, Any] = {}
    if settings.models_config.exists():
        bases = yaml.safe_load(settings.models_config.read_text()).get("models", {})
    out: dict[str, ModelSpec] = {}
    for model_id, entry in served["models"].items():
        adapter = _override(entry["adapter"]) if entry.get("adapter") else None
        base_key = entry.get("base")
        if base_key:
            if base_key not in bases:
                continue
            base = bases[base_key]
            arch = base.get("architecture", {})
            out[model_id] = ModelSpec(
                id=model_id,
                display_name=entry["displayName"],
                version=entry["version"],
                family=base.get("family", "gemma4"),
                base_model=base.get("upstream", {}).get("qatUnquantized", base_key),
                path=_override(base["base"]),
                hf_repo=None,
                hf_revision=None,
                adapter=adapter,
                quantization=f"{base['base'].get('quantization', {}).get('bits', 4)}bit",
                parameters=entry.get("parameters", "12B"),
                budget_gb=float(base.get("memory", {}).get("inferenceBudgetGb", 8.0)),
                architecture=arch,
                stop=list(base.get("chatTemplate", {}).get("stop", [])),
            )
        else:
            hf = entry["hf"]
            out[model_id] = ModelSpec(
                id=model_id,
                display_name=entry["displayName"],
                version=entry["version"],
                family=entry.get("family", "qwen3"),
                base_model=entry.get("baseModel", hf["repo"]),
                path=None,
                hf_repo=hf["repo"],
                hf_revision=hf.get("revision"),
                adapter=adapter,
                quantization=entry.get("quantization", "4bit"),
                parameters=entry.get("parameters", ""),
                budget_gb=float(entry.get("memory", {}).get("inferenceBudgetGb", 2.0)),
                stop=list(entry.get("stop", [])),
            )
    return out


def default_model(settings: Settings) -> str:
    return str(yaml.safe_load(settings.served_config.read_text()).get("default", ""))


def _hf_architecture(path: Path) -> dict[str, Any]:
    try:
        import json

        cfg = json.loads((path / "config.json").read_text())
    except OSError, ValueError:
        return {}
    text = cfg.get("text_config", cfg)
    return {
        "layers": text.get("num_hidden_layers"),
        "hiddenSize": text.get("hidden_size"),
        "attentionHeads": text.get("num_attention_heads"),
        "kvHeads": text.get("num_key_value_heads"),
        "vocabSize": text.get("vocab_size"),
    }


def model_info(spec: ModelSpec, settings: Settings, local_path: Path | None = None) -> dict[str, Any]:
    """ModelInfo from contracts/api.md for `hello` and `GET /v1/models`."""
    arch = spec.architecture
    architecture: dict[str, Any] | None = None
    if arch:
        architecture = {
            "layers": arch["layers"],
            "hiddenSize": arch["hiddenSize"],
            "attentionHeads": arch["attentionHeads"],
            "kvHeads": arch["kvHeads"],
            "vocabSize": arch["vocabSize"],
        }
    elif local_path is not None:
        architecture = _hf_architecture(local_path) or None
    if architecture is not None:
        architecture["parameters"] = spec.parameters
    info: dict[str, Any] = {
        "id": spec.id,
        "displayName": spec.display_name,
        "tier": "pro",
        "version": spec.version,
        "baseModel": spec.base_model,
        "runtime": "mlx",
        "host": "local-gpu-worker",
        "quantization": spec.quantization,
        "contextLength": settings.max_prompt_tokens,
        "supportsReasoning": True,
        "supportsTools": True,
        "supportsTelemetry": True,
    }
    if architecture is not None:
        info["architecture"] = architecture
    return info

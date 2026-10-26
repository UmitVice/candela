import importlib.metadata as md
import platform
from typing import Any

from candela_worker import lease, sysinfo
from candela_worker.config import Settings, load_registry


def doctor(settings: Settings) -> dict[str, Any]:
    import mlx.core as mx

    registry = load_registry(settings)
    mem = sysinfo.memory()
    info = mx.device_info()
    models: dict[str, Any] = {}
    for mid, spec in registry.items():
        need = spec.budget_gb + settings.reserve_gb
        models[mid] = {
            "base": str(spec.path) if spec.path else f"hf:{spec.hf_repo}@{(spec.hf_revision or '')[:12]}",
            "baseExists": spec.path.exists() if spec.path else None,
            "adapter": str(spec.adapter) if spec.adapter else None,
            "adapterExists": (spec.adapter / "adapters.safetensors").exists() if spec.adapter else None,
            "budgetGb": spec.budget_gb,
            "admissible": mem.pressure != "critical" and mem.available_gb >= need,
        }
    return {
        "python": platform.python_version(),
        "packages": {
            p: md.version(p) for p in ("mlx", "mlx-lm", "transformers", "websockets", "fastapi", "uvicorn")
        },
        "device": sysinfo.device_label(),
        "metal": {
            "architecture": info.get("architecture"),
            "recommendedWorkingSetGb": round(
                float(info.get("max_recommended_working_set_size", 0)) / 1024**3, 1
            ),
        },
        "memory": mem.as_dict(),
        "leases": [
            {k: v for k, v in x.items() if k in ("holder", "priority", "state", "purpose")}
            for x in lease.live_leases()
        ],
        "gatewayUrl": settings.gateway_url,
        "tokenConfigured": bool(settings.token),
        "servedModels": settings.model_ids or "(all)",
        "idleUnloadSec": settings.idle_unload_sec,
        "kvBits": settings.kv_bits,
        "production": settings.production,
        "models": models,
    }

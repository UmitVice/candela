import hashlib
import json
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from candela_lab.paths import CONFIGS_DIR, CONTRACTS_DIR, REPO_ROOT


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open() as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping")
    return data


def config_hash(data: Any) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class ModelSpec:
    id: str
    raw: dict[str, Any]

    @property
    def tier(self) -> str:
        return self.raw["tier"]

    @property
    def family(self) -> str:
        return self.raw["family"]

    @property
    def source(self) -> str:
        return self.raw["source"]

    @property
    def display_name(self) -> str:
        return self.raw["displayName"]

    @property
    def lora(self) -> dict[str, Any]:
        return self.raw["lora"]

    @property
    def train_budget_gb(self) -> float:
        return float(self.raw["memory"]["trainBudgetGb"])

    @property
    def inference_budget_gb(self) -> float:
        return float(self.raw["memory"]["inferenceBudgetGb"])

    @property
    def chat_template(self) -> dict[str, Any]:
        return self.raw["chatTemplate"]

    def mlx_path(self) -> str:
        mlx = self.raw["mlx"]
        local = mlx.get("localPath")
        if local:
            path = REPO_ROOT / local
            if path.exists():
                return str(path)
            if mlx.get("repo") is None and mlx.get("fallbackRepo"):
                return mlx["fallbackRepo"]
        return mlx["repo"]


@cache
def models_config() -> dict[str, Any]:
    return load_yaml(CONFIGS_DIR / "models.yaml")


def model(model_id: str) -> ModelSpec:
    cfg = models_config()
    tiers = cfg["tiers"]
    if model_id in tiers:
        model_id = tiers[model_id]["selected"]
    if model_id not in cfg["models"]:
        raise KeyError(f"unknown model {model_id!r}; known: {', '.join(cfg['models'])}")
    return ModelSpec(model_id, cfg["models"][model_id])


def all_models() -> list[ModelSpec]:
    return [ModelSpec(k, v) for k, v in models_config()["models"].items()]


@cache
def tools_schema() -> list[dict[str, Any]]:
    return json.loads((CONTRACTS_DIR / "tools.json").read_text())


@cache
def system_prompt_template() -> str:
    return (CONTRACTS_DIR / "system-prompt.md").read_text().strip()


def system_prompt(today: str) -> str:
    return system_prompt_template().replace("{{today}}", today)

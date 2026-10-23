import hashlib
import json
import os
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from candela_lab.paths import CONFIGS_DIR, CONTRACTS_DIR


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open() as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a mapping")
    return data


def config_hash(data: Any) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _resolve(entry: dict[str, Any]) -> str:
    env = entry.get("env")
    if env and os.environ.get(env):
        return os.environ[env]
    raw = str(entry["path"])
    expanded = os.path.expanduser(raw)
    return expanded if (raw.startswith(("~", "/", ".")) or Path(expanded).exists()) else raw


@dataclass(frozen=True)
class ModelSpec:
    id: str
    raw: dict[str, Any]

    @property
    def family(self) -> str:
        return self.raw["family"]

    @property
    def display_name(self) -> str:
        return self.raw["displayName"]

    @property
    def lora(self) -> dict[str, Any]:
        return self.raw["lora"]

    @property
    def architecture(self) -> dict[str, Any]:
        return self.raw.get("architecture", {})

    @property
    def upstream(self) -> str:
        return self.raw.get("upstream", {}).get("qatUnquantized", self.id)

    @property
    def train_budget_gb(self) -> float:
        return float(self.raw["memory"]["trainBudgetGb"])

    @property
    def inference_budget_gb(self) -> float:
        return float(self.raw["memory"]["inferenceBudgetGb"])

    @property
    def chat_template(self) -> dict[str, Any]:
        return self.raw.get("chatTemplate", {})

    @property
    def context_length(self) -> int:
        return int(self.raw.get("contextLength", 0))

    def base_path(self) -> str:
        return _resolve(self.raw["base"])

    def reference_path(self) -> str | None:
        return _resolve(self.raw["reference"]) if "reference" in self.raw else None

    def gguf_path(self) -> str | None:
        return _resolve(self.raw["gguf"]) if "gguf" in self.raw else None


@cache
def models_config() -> dict[str, Any]:
    return load_yaml(CONFIGS_DIR / "models.yaml")


def model(model_id: str | None = None) -> ModelSpec:
    cfg = models_config()
    key = model_id or cfg["default"]
    if key in ("pro", "default"):
        key = cfg["default"]
    if key not in cfg["models"]:
        raise KeyError(f"unknown model {key!r}; known: {', '.join(cfg['models'])}")
    return ModelSpec(key, cfg["models"][key])


@cache
def tools_schema() -> list[dict[str, Any]]:
    return json.loads((CONTRACTS_DIR / "tools.json").read_text())


@cache
def system_prompt_template() -> str:
    return (CONTRACTS_DIR / "system-prompt.md").read_text().strip()


def system_prompt(today: str) -> str:
    return system_prompt_template().replace("{{today}}", today)

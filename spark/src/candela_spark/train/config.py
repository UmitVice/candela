from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

import yaml

from candela_spark import paths
from candela_spark.train.optim import OptimConfig


@dataclass(frozen=True)
class RunConfig:
    run_id: str
    preset: str = "spark-35m"
    data_version: str = "v0"
    seq_len: int = 1024
    micro_batch: int = 8
    accum: int = 4
    seed: int = 1234
    warmup_steps: int = 300
    decay_steps: int = 0
    fork_from: str | None = None
    fork_step: int | None = None
    max_steps: int | None = None
    log_every: int = 10
    eval_every: int = 250
    eval_windows_per_source: int = 16
    checkpoint_every_sec: float = 600.0
    keep_last: int = 3
    milestone_every_tokens: int = 250_000_000
    lease_holder: str = "spark-trainer"
    lease_priority: int = 20
    memory_budget_gb: float = 4.0
    cache_limit_gb: float = 0.5
    long_wait_sec: float = 600.0
    optim: OptimConfig = field(default_factory=OptimConfig)

    @property
    def tokens_per_step(self) -> int:
        return self.micro_batch * self.accum * self.seq_len

    @property
    def run_dir(self) -> Path:
        return paths.RUNS / self.run_id

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load(path: Path, overrides: dict[str, Any] | None = None) -> RunConfig:
    raw = yaml.safe_load(path.read_text()) or {}
    raw.update(overrides or {})
    optim_raw = raw.pop("optim", {}) or {}
    if "adam_betas" in optim_raw:
        optim_raw["adam_betas"] = tuple(optim_raw["adam_betas"])
    known = {f.name for f in fields(RunConfig)}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"unknown run config keys: {sorted(unknown)}")
    return RunConfig(optim=OptimConfig(**optim_raw), **raw)

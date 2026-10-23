from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

from candela_spark import paths


@dataclass(frozen=True)
class Source:
    id: str
    repo: str
    revision: str
    license: str
    format: Literal["parquet", "jsonl"]
    kind: Literal["general", "finance"]
    files: list[str]
    text_field: str = "text"
    text_fields: list[str] = field(default_factory=list)
    finance_split: bool = False


@dataclass(frozen=True)
class DataConfig:
    version: str
    seed: int
    validation_docs_per_source: int
    sources: list[Source]
    mixture: dict[str, float]

    def source(self, source_id: str) -> Source:
        for s in self.sources:
            if s.id == source_id:
                return s
        raise KeyError(source_id)


def load(version: str = "v0") -> DataConfig:
    path = paths.CONFIGS / "data" / f"{version}.yaml"
    raw = yaml.safe_load(Path(path).read_text())
    sources = [Source(**s) for s in raw["sources"]]
    for s in sources:
        if len(s.revision) != 40 or any(c not in "0123456789abcdef" for c in s.revision):
            raise ValueError(f"{s.id}: revision must be a full commit sha")
        for f in s.files:
            if not (f.endswith(".parquet") or f.endswith(".jsonl")):
                raise ValueError(f"{s.id}: only parquet and jsonl files are allowed: {f}")
    return DataConfig(
        version=raw["version"],
        seed=int(raw["seed"]),
        validation_docs_per_source=int(raw["validation_docs_per_source"]),
        sources=sources,
        mixture={k: float(v) for k, v in raw["mixture"].items()},
    )

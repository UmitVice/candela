import hashlib
import json
from dataclasses import asdict, dataclass, field


@dataclass(frozen=True)
class QuantConfig:
    bits: int = 4
    group_size: int = 32
    storage_dtype: str = "bfloat16"
    quantize_embedding: bool = True
    start_step: int = 0


@dataclass(frozen=True)
class ModelConfig:
    name: str
    hidden_size: int
    num_layers: int
    num_heads: int
    num_kv_heads: int
    head_dim: int
    intermediate_size: int
    vocab_size: int = 32768
    max_seq_len: int = 1024
    sliding_window: int = 256
    global_every: int = 6
    rope_local_base: float = 10_000.0
    rope_global_base: float = 1_000_000.0
    norm_eps: float = 1e-6
    base_width: int = 384
    init_std_scale: float = 1.0
    quant: QuantConfig = field(default_factory=QuantConfig)

    def is_global(self, layer: int) -> bool:
        # Same rule as llama.cpp's gemma3 set_swa_pattern(6): the last layer of every 6-block is global.
        return layer % self.global_every == self.global_every - 1

    @property
    def output_mult(self) -> float:
        return self.base_width / self.hidden_size

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict[str, object]) -> ModelConfig:
        data = dict(raw)
        quant = data.pop("quant", {})
        return cls(quant=QuantConfig(**quant), **data)  # type: ignore[arg-type]

    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.to_dict(), sort_keys=True).encode()).hexdigest()[:16]


def param_counts(cfg: ModelConfig) -> dict[str, int]:
    d, hd = cfg.hidden_size, cfg.head_dim
    attn = d * cfg.num_heads * hd * 2 + d * cfg.num_kv_heads * hd * 2
    ffn = 3 * d * cfg.intermediate_size
    norms = 4 * d + 2 * hd
    per_layer = attn + ffn + norms
    embedding = cfg.vocab_size * d
    blocks = per_layer * cfg.num_layers
    return {
        "embedding": embedding,
        "attention_per_layer": attn,
        "ffn_per_layer": ffn,
        "per_layer": per_layer,
        "blocks": blocks,
        "final_norm": d,
        "non_embedding": blocks + d,
        "total": embedding + blocks + d,
    }


PRESETS: dict[str, ModelConfig] = {
    "spark-35m": ModelConfig(
        name="spark-35m",
        hidden_size=384,
        num_layers=12,
        num_heads=6,
        num_kv_heads=2,
        head_dim=64,
        intermediate_size=1280,
    ),
    "spark-125m": ModelConfig(
        name="spark-125m",
        hidden_size=640,
        num_layers=24,
        num_heads=10,
        num_kv_heads=2,
        head_dim=64,
        intermediate_size=1728,
        max_seq_len=2048,
        sliding_window=512,
    ),
    "spark-350m": ModelConfig(
        name="spark-350m",
        hidden_size=1024,
        num_layers=24,
        num_heads=8,
        num_kv_heads=2,
        head_dim=128,
        intermediate_size=3456,
        max_seq_len=2048,
        sliding_window=512,
    ),
    "spark-1b": ModelConfig(
        name="spark-1b",
        hidden_size=1536,
        num_layers=30,
        num_heads=12,
        num_kv_heads=4,
        head_dim=128,
        intermediate_size=5504,
        max_seq_len=4096,
        sliding_window=1024,
    ),
    "spark-2b": ModelConfig(
        name="spark-2b",
        hidden_size=2048,
        num_layers=36,
        num_heads=16,
        num_kv_heads=4,
        head_dim=128,
        intermediate_size=7040,
        max_seq_len=4096,
        sliding_window=1024,
    ),
}

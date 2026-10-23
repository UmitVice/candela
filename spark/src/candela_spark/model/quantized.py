import json
import math
from pathlib import Path

import mlx.core as mx
import mlx.nn as nn

from candela_spark.model.config import ModelConfig
from candela_spark.model.transformer import SparkLM

LINEARS = (
    "self_attn.q_proj",
    "self_attn.k_proj",
    "self_attn.v_proj",
    "self_attn.o_proj",
    "mlp.gate_proj",
    "mlp.up_proj",
    "mlp.down_proj",
)


class Int4Linear(nn.Module):
    def __init__(
        self, weight: mx.array, scales: mx.array, biases: mx.array, group_size: int, bits: int
    ) -> None:
        super().__init__()
        self.weight, self.scales, self.biases = weight, scales, biases
        self.group_size, self.bits = group_size, bits
        self.qat = False

    def __call__(self, x: mx.array) -> mx.array:
        return mx.quantized_matmul(
            x,
            self.weight,
            self.scales,
            self.biases,
            transpose=True,
            group_size=self.group_size,
            bits=self.bits,
        )


class Int4SparkLM(SparkLM):
    """Runs the exported MLX int4 weights with quantized kernels, independent of the QAT code path."""

    def __init__(self, cfg: ModelConfig, weights: dict[str, mx.array]) -> None:
        super().__init__(cfg)
        q = cfg.quant
        for i, layer in enumerate(self.layers):
            for name in LINEARS:
                parent_name, attr = name.split(".")
                key = f"layers.{i}.{name}"
                setattr(
                    getattr(layer, parent_name),
                    attr,
                    Int4Linear(
                        weights[f"{key}.weight"],
                        weights[f"{key}.scales"],
                        weights[f"{key}.biases"],
                        q.group_size,
                        q.bits,
                    ),
                )
        self.emb_q = weights["embed_tokens.weight"]
        self.emb_s = weights["embed_tokens.scales"]
        self.emb_b = weights["embed_tokens.biases"]
        norms = [(k, v) for k, v in weights.items() if k.endswith("norm.weight")]
        self.load_weights(norms, strict=False)
        self.qat = False

    def set_qat(self, enabled: bool) -> None:
        self.qat = False

    def embed(self, tokens: mx.array) -> mx.array:
        q = self.cfg.quant
        rows = mx.dequantize(
            self.emb_q[tokens], self.emb_s[tokens], self.emb_b[tokens], group_size=q.group_size, bits=q.bits
        )
        return rows * mx.array(math.sqrt(self.cfg.hidden_size), dtype=rows.dtype)

    def head(self, h: mx.array) -> mx.array:
        q = self.cfg.quant
        return mx.quantized_matmul(
            h, self.emb_q, self.emb_s, self.emb_b, transpose=True, group_size=q.group_size, bits=q.bits
        )


def load_int4(export_dir: Path) -> Int4SparkLM:
    cfg_raw = json.loads((export_dir / "config.json").read_text())
    cfg = ModelConfig.from_dict(cfg_raw["spark"])
    weights = mx.load(str(export_dir / "model.safetensors"))
    assert isinstance(weights, dict)
    model = Int4SparkLM(cfg, weights)
    mx.eval(model.parameters())
    return model

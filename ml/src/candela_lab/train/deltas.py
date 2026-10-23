import re
from typing import Any

import mlx.core as mx
from mlx import nn

CONTRACT_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]
LAYER_RE = re.compile(r"layers\.(\d+)\.(?:self_attn|mlp)\.(\w+)$")


def lora_delta_norms(model: nn.Module, num_layers: int) -> list[list[float]]:
    """norms[layer][module] = ‖scale·(A·B)‖_F computed through the r×r Gram matrices (never forms the full delta)."""
    norms = [[0.0] * len(CONTRACT_MODULES) for _ in range(num_layers)]
    for name, module in model.named_modules():
        if not hasattr(module, "lora_a") or not hasattr(module, "lora_b"):
            continue
        m = LAYER_RE.search(name)
        if not m:
            continue
        layer, mod = int(m.group(1)), m.group(2)
        if mod not in CONTRACT_MODULES or layer >= num_layers:
            continue
        a = module.lora_a.astype(mx.float32)
        b = module.lora_b.astype(mx.float32)
        scale = float(getattr(module, "scale", 1.0))
        gram = (a.T @ a) * (b @ b.T)
        value = scale * float(mx.sqrt(mx.maximum(gram.sum(), 0.0)).item())  # type: ignore[arg-type]
        norms[layer][CONTRACT_MODULES.index(mod)] = round(value, 6)
    return norms


def trainable_parameters(model: nn.Module) -> int:
    from mlx.utils import tree_flatten

    return int(sum(v.size for _, v in tree_flatten(model.trainable_parameters()) if isinstance(v, mx.array)))


def adapted_layers(model: nn.Module) -> list[int]:
    out: set[int] = set()
    for name, module in model.named_modules():
        if hasattr(module, "lora_a"):
            m = LAYER_RE.search(name)
            if m:
                out.add(int(m.group(1)))
    return sorted(out)


def adapted_modules(model: nn.Module) -> list[str]:
    found: set[str] = set()
    for name, module in model.named_modules():
        if hasattr(module, "lora_a"):
            m = LAYER_RE.search(name)
            if m:
                found.add(m.group(2))
    return [m for m in CONTRACT_MODULES if m in found]


def summary(norms: list[list[float]]) -> dict[str, Any]:
    flat = [v for row in norms for v in row]
    return {"maxNorm": max(flat) if flat else 0.0}

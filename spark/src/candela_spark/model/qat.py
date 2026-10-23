import mlx.core as mx
import mlx.nn as nn

from candela_spark.model.config import QuantConfig

_DTYPES = {"bfloat16": mx.bfloat16, "float16": mx.float16, "float32": mx.float32}


def storage_dtype(q: QuantConfig) -> mx.Dtype:
    return _DTYPES[q.storage_dtype]


def quantize_export(w: mx.array, q: QuantConfig) -> tuple[mx.array, mx.array, mx.array]:
    packed, scales, biases = mx.quantize(w.astype(storage_dtype(q)), group_size=q.group_size, bits=q.bits)
    return packed, scales, biases


def int4_grid(w: mx.array, q: QuantConfig) -> mx.array:
    packed, scales, biases = quantize_export(w, q)
    return mx.dequantize(packed, scales, biases, group_size=q.group_size, bits=q.bits)


def fake_quant(w: mx.array, q: QuantConfig) -> mx.array:
    # Forward sees exactly the export grid (mx.quantize on the storage dtype); backward is the identity.
    w_lo = w.astype(storage_dtype(q))
    return w_lo + mx.stop_gradient(int4_grid(w, q) - w_lo)


class QATLinear(nn.Module):
    def __init__(self, in_dims: int, out_dims: int, std: float, quant: QuantConfig) -> None:
        super().__init__()
        self.weight = mx.random.normal((out_dims, in_dims), scale=std, dtype=mx.float32)
        self.quant = quant
        self.qat = True

    def effective_weight(self) -> mx.array:
        if self.qat:
            return fake_quant(self.weight, self.quant)
        return self.weight.astype(storage_dtype(self.quant))

    def __call__(self, x: mx.array) -> mx.array:
        return x @ self.effective_weight().T

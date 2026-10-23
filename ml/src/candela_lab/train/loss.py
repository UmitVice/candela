from collections.abc import Callable
from typing import Any

import mlx.core as mx
from mlx import nn


def to_float(a: mx.array) -> float:
    return float(a.item())  # type: ignore[arg-type]


def text_model(model: nn.Module) -> Any:
    return model.language_model if hasattr(model, "language_model") else model


def body_and_head(model: nn.Module) -> tuple[Callable[[mx.array], mx.array], Callable[[mx.array], mx.array]]:
    tm = text_model(model)
    inner = tm.model
    softcap = getattr(tm, "final_logit_softcapping", None)
    tied = not hasattr(tm, "lm_head")

    def body(inputs: mx.array) -> mx.array:
        return inner(inputs)

    def head(h: mx.array) -> mx.array:
        logits = inner.embed_tokens.as_linear(h) if tied else tm.lm_head(h)
        if softcap is not None:
            logits = mx.tanh(logits / softcap) * softcap
        return logits

    return body, head


def make_loss(model: nn.Module, chunk: int = 256) -> Callable[..., tuple[mx.array, mx.array]]:
    """Cross-entropy that runs the LM head only on supervised positions, in checkpointed chunks, so a 262k-vocabulary
    head never materialises [T, V] logits."""
    body, head = body_and_head(model)

    def chunk_ce(h: mx.array, targets: mx.array) -> mx.array:
        logits = head(h).astype(mx.float32)
        lse = mx.logsumexp(logits, axis=-1)
        picked = mx.take_along_axis(logits, targets[:, None], axis=-1)[:, 0]
        return (lse - picked).sum()

    checkpointed = mx.checkpoint(chunk_ce)

    def loss(model_: nn.Module, tokens: mx.array, positions: mx.array) -> tuple[mx.array, mx.array]:
        del model_
        inputs = tokens[:, :-1]
        targets = tokens[0, 1:]
        h = body(inputs)[0]
        sel_h = h[positions]
        sel_t = targets[positions]
        n = positions.shape[0]
        total = mx.array(0.0, dtype=mx.float32)
        for start in range(0, n, chunk):
            total = total + checkpointed(sel_h[start : start + chunk], sel_t[start : start + chunk])
        ntoks = mx.array(n, dtype=mx.float32)
        return total / ntoks, ntoks

    return loss


def checkpoint_layers(model: nn.Module) -> None:
    """Gradient checkpointing for decoder layers. Gemma 4 layers return (h, shared_kv, offset); without KV sharing
    (num_kv_shared_layers == 0 in the 12B model) only h is used downstream, so only h crosses the checkpoint."""
    layers: Any = text_model(model).layers
    cls = type(layers[0])
    if getattr(cls, "_candela_checkpointed", False):
        return
    fn = cls.__call__

    def wrapped(self: nn.Module, x: mx.array, *args: Any, **kwargs: Any) -> Any:
        tuple_out: list[bool] = []

        def inner(params: Any, x_: mx.array) -> mx.array:
            self.update(params)
            out = fn(self, x_, *args, **kwargs)
            if isinstance(out, tuple):
                tuple_out.append(True)
                return out[0]
            return out

        h = mx.checkpoint(inner)(self.trainable_parameters(), x)
        return (h, None, 0) if tuple_out else h

    cls.__call__ = wrapped
    cls._candela_checkpointed = True

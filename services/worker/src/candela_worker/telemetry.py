from typing import Any, cast

import mlx.core as mx
from mlx import nn

LENS_EVERY = 4
TOP_K = 5
LENS_TOP = 3


def _list(a: mx.array) -> list[Any]:
    return cast(list[Any], a.tolist())


class _Recorder:
    def __init__(self) -> None:
        self.active = False
        self.states: dict[int, mx.array] = {}


class TappedLayer(nn.Module):
    """Wraps one decoder layer and records the residual stream at the last position when the recorder is active."""

    def __init__(self, inner: nn.Module, index: int, recorder: _Recorder) -> None:
        super().__init__()
        self.inner = inner
        object.__setattr__(self, "_index", index)
        object.__setattr__(self, "_recorder", recorder)

    def __getattr__(self, name: str) -> Any:
        try:
            return super().__getattr__(name)
        except AttributeError:
            if "inner" not in self:
                raise
            return getattr(self["inner"], name)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        out = self.inner(*args, **kwargs)
        rec: _Recorder = object.__getattribute__(self, "_recorder")
        if rec.active:
            h = out[0] if isinstance(out, tuple) else out
            rec.states[object.__getattribute__(self, "_index")] = h[0, -1, :]
        return out


class Telemetry:
    """Per-token interpretability probes: residual-stream norms for every layer, entropy and top-k of the final
    distribution, and a logit lens (final norm + LM head) on every 4th layer, all computed inside the MLX graph."""

    def __init__(self, model: nn.Module) -> None:
        self.recorder = _Recorder()
        layers = cast(list[nn.Module], model.layers)
        self.n_layers = len(layers)
        for i, layer in enumerate(layers):
            if not isinstance(layer, TappedLayer):
                layers[i] = TappedLayer(layer, i, self.recorder)
        lm = model.get("language_model", model)
        inner = lm["model"]
        self._norm = inner["norm"]
        self._head = lm["lm_head"] if "lm_head" in lm else inner["embed_tokens"].as_linear
        self._softcap: float | None = getattr(lm, "final_logit_softcapping", None)
        self.lens_layers = [i for i in range(self.n_layers) if (i + 1) % LENS_EVERY == 0]
        if self.n_layers - 1 not in self.lens_layers:
            self.lens_layers.append(self.n_layers - 1)

    def arm(self) -> None:
        self.recorder.states = {}
        self.recorder.active = True

    def disarm(self) -> dict[int, mx.array]:
        self.recorder.active = False
        states, self.recorder.states = self.recorder.states, {}
        return states

    def graph(self, states: dict[int, mx.array], logprobs: mx.array) -> dict[str, mx.array]:
        """Lazy arrays for one generated position; evaluated together with the sampled token."""
        idx = sorted(states)
        hs = mx.stack([states[i] for i in idx]).astype(mx.float32)
        norms = mx.sqrt((hs * hs).sum(axis=-1))
        lp = logprobs.reshape(-1).astype(mx.float32)
        entropy = -(mx.exp(lp) * lp).sum()
        top_ids = mx.argpartition(-lp, TOP_K)[:TOP_K]
        top_p = mx.exp(lp[top_ids])
        lens_h = mx.stack([states[i] for i in self.lens_layers if i in states])
        logits = self._head(self._norm(lens_h)).astype(mx.float32)
        if self._softcap:
            logits = mx.tanh(logits / self._softcap) * self._softcap
        lens_lp = logits - mx.logsumexp(logits, axis=-1, keepdims=True)
        lens_ids = mx.argpartition(-lens_lp, LENS_TOP, axis=-1)[:, :LENS_TOP]
        lens_p = mx.exp(mx.take_along_axis(lens_lp, lens_ids, axis=-1))
        return {
            "layers": mx.array(idx),
            "norms": norms,
            "entropy": entropy,
            "top_ids": top_ids,
            "top_p": top_p,
            "lens_ids": lens_ids,
            "lens_p": lens_p,
        }

    def frame(self, g: dict[str, mx.array], step: int, token: str, phase: str, decode: Any) -> dict[str, Any]:
        layers = _list(g["layers"])
        norms = _list(g["norms"])
        top = sorted(zip(_list(g["top_p"]), _list(g["top_ids"]), strict=True), reverse=True)
        lens_ids, lens_p = _list(g["lens_ids"]), _list(g["lens_p"])
        lens = []
        for layer, ids, ps in zip(
            [i for i in self.lens_layers if i in layers], lens_ids, lens_p, strict=True
        ):
            ranked = sorted(zip(ps, ids, strict=True), reverse=True)
            lens.append({"layer": layer, "top": [{"token": decode(t), "p": round(p, 4)} for p, t in ranked]})
        return {
            "step": step,
            "token": token,
            "phase": phase,
            "entropy": round(float(cast(float, g["entropy"].item())), 4),
            "topK": [{"token": decode(t), "p": round(p, 4)} for p, t in top],
            "layers": [{"layer": layer, "norm": round(n, 2)} for layer, n in zip(layers, norms, strict=True)],
            "logitLens": lens,
        }

from dataclasses import dataclass

import mlx.core as mx
import mlx.optimizers as optim

_NS_COEFFS = (3.4445, -4.7750, 2.0315)


def newton_schulz(g: mx.array, steps: int) -> mx.array:
    x = g.astype(mx.bfloat16)
    transposed = x.shape[0] > x.shape[1]
    if transposed:
        x = x.T
    x = x / (mx.linalg.norm(x.astype(mx.float32)).astype(mx.bfloat16) + 1e-7)
    a, b, c = _NS_COEFFS
    for _ in range(steps):
        s = x @ x.T
        poly = b * s + c * (s @ s)
        x = a * x + poly @ x
    return x.T if transposed else x


class Muon(optim.Optimizer):
    """Muon with Nesterov momentum, decoupled weight decay and spectral (sqrt(fan_out/fan_in)) update scaling.

    mlx.optimizers.Muon adds weight decay to the gradient before orthogonalisation, which normalises it
    away; long continuous runs need the decoupled form.
    """

    def __init__(
        self, learning_rate: float, momentum: float = 0.95, weight_decay: float = 0.0, ns_steps: int = 5
    ) -> None:
        super().__init__()
        self._maybe_schedule("learning_rate", learning_rate)
        self.momentum = momentum
        self.weight_decay = weight_decay
        self.ns_steps = ns_steps

    def init_single(self, parameter: mx.array, state: dict) -> None:
        state["m"] = mx.zeros_like(parameter)

    def apply_single(self, gradient: mx.array, parameter: mx.array, state: dict) -> mx.array:
        mu = self.momentum
        m = mu * state["m"] + (1 - mu) * gradient
        state["m"] = m
        update = (1 - mu) * gradient + mu * m
        ortho = newton_schulz(update, self.ns_steps).astype(parameter.dtype)
        fan_out, fan_in = parameter.shape
        lr = self.learning_rate.astype(parameter.dtype)
        scale = max(1.0, fan_out / fan_in) ** 0.5
        return parameter * (1 - lr * self.weight_decay) - (lr * scale) * ortho


@dataclass(frozen=True)
class OptimConfig:
    muon_lr: float = 0.02
    muon_momentum: float = 0.95
    muon_weight_decay: float = 0.01
    adam_lr: float = 0.002
    adam_betas: tuple[float, float] = (0.9, 0.95)
    adam_eps: float = 1e-10
    embed_weight_decay: float = 0.0
    grad_clip: float = 1.0


def is_muon_param(path: str, value: mx.array) -> bool:
    return path.startswith("layers.") and value.ndim == 2


class SparkOptimizer:
    def __init__(self, cfg: OptimConfig) -> None:
        self.cfg = cfg
        self.muon = Muon(cfg.muon_lr, cfg.muon_momentum, cfg.muon_weight_decay)
        self.adam = optim.AdamW(
            cfg.adam_lr, betas=list(cfg.adam_betas), eps=cfg.adam_eps, weight_decay=cfg.embed_weight_decay
        )
        self.inner = optim.MultiOptimizer([self.muon, self.adam], [is_muon_param])

    def set_lr_mult(self, mult: float) -> None:
        self.muon.learning_rate = mx.array(self.cfg.muon_lr * mult, dtype=mx.float32)
        self.adam.learning_rate = mx.array(self.cfg.adam_lr * mult, dtype=mx.float32)

    @property
    def state(self) -> dict:
        return self.inner.state

    @state.setter
    def state(self, value: dict) -> None:
        self.inner.state = value

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class WSD:
    """Warmup-stable-decay. The continuous run never sets decay_start; release branches fork a stable
    checkpoint and set it, decaying with the 1-sqrt shape over decay_steps."""

    warmup_steps: int
    decay_start: int | None = None
    decay_steps: int = 0
    final_mult: float = 0.0

    def mult(self, step: int) -> float:
        if step < self.warmup_steps:
            return (step + 1) / self.warmup_steps
        if self.decay_start is None or step < self.decay_start:
            return 1.0
        p = min(1.0, (step - self.decay_start) / max(1, self.decay_steps))
        return self.final_mult + (1.0 - self.final_mult) * (1.0 - math.sqrt(p))

    def phase(self, step: int) -> str:
        if step < self.warmup_steps:
            return "warmup"
        if self.decay_start is None or step < self.decay_start:
            return "stable"
        return "decay"

    def done(self, step: int) -> bool:
        return self.decay_start is not None and step >= self.decay_start + self.decay_steps

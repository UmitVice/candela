import os
import re
import subprocess
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Literal

import psutil

from candela_spark import log

GB = 1024**3
Pressure = Literal["normal", "warn", "critical", "unknown"]
_log = log.get("resources")

# kern.memorystatus_vm_pressure_level uses the kernel's dispatch levels: 1 normal, 2 warn, 4 critical.
_PRESSURE_LEVELS: dict[int, Pressure] = {1: "normal", 2: "warn", 4: "critical"}


def _run(cmd: list[str]) -> str | None:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=True).stdout
    except subprocess.SubprocessError, OSError:
        return None


@dataclass(frozen=True)
class MemorySnapshot:
    at: float
    total_gb: float
    available_gb: float
    wired_gb: float
    swap_used_gb: float
    pressure: Pressure

    def as_dict(self) -> dict[str, float | str]:
        return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in asdict(self).items() if k != "at"}


def pressure_level() -> Pressure:
    raw = (_run(["sysctl", "-n", "kern.memorystatus_vm_pressure_level"]) or "").strip()
    return _PRESSURE_LEVELS.get(int(raw), "unknown") if raw.isdigit() else "unknown"


def _wired_gb() -> float:
    out = _run(["vm_stat"]) or ""
    page = int(m.group(1)) if (m := re.search(r"page size of (\d+) bytes", out)) else 16384
    if m := re.search(r"Pages wired down:\s+(\d+)", out):
        return int(m.group(1)) * page / GB
    return 0.0


def _swap_used_gb() -> float:
    raw = _run(["sysctl", "-n", "vm.swapusage"]) or ""
    if m := re.search(r"used = ([\d.]+)M", raw):
        return float(m.group(1)) / 1024
    return psutil.swap_memory().used / GB


def snapshot() -> MemorySnapshot:
    vm = psutil.virtual_memory()
    return MemorySnapshot(
        at=time.time(),
        total_gb=vm.total / GB,
        available_gb=vm.available / GB,
        wired_gb=_wired_gb(),
        swap_used_gb=_swap_used_gb(),
        pressure=pressure_level(),
    )


@dataclass(frozen=True)
class GuardPolicy:
    start_headroom_gb: float = 1.5
    pause_below_gb: float = 1.0
    swap_growth_gb: float = 1.0
    swap_window_sec: float = 300.0
    recover_hold_sec: float = 120.0
    sample_every_sec: float = 5.0


@dataclass
class Decision:
    ok: bool
    reason: str
    snapshot: MemorySnapshot


@dataclass
class ResourceGuard:
    """Admission and step-boundary memory checks. `budget_gb` is this process's own MLX limit, so the guard
    measures headroom for it on top of what everything else (the owner's work first) already uses."""

    budget_gb: float
    policy: GuardPolicy = field(default_factory=GuardPolicy)
    _swap: deque[tuple[float, float]] = field(default_factory=lambda: deque(maxlen=512))
    _last: MemorySnapshot | None = None
    _own_gb: float = 0.0

    def set_own_usage(self, gb: float) -> None:
        self._own_gb = gb

    def sample(self, force: bool = False) -> MemorySnapshot:
        if not force and self._last and time.time() - self._last.at < self.policy.sample_every_sec:
            return self._last
        snap = snapshot()
        self._swap.append((snap.at, snap.swap_used_gb))
        self._last = snap
        return snap

    def swap_growth_gb(self) -> float:
        if not self._swap:
            return 0.0
        now, current = self._swap[-1]
        window = [s for t, s in self._swap if now - t <= self.policy.swap_window_sec]
        return max(0.0, current - min(window)) if window else 0.0

    def start(self) -> Decision:
        snap = self.sample(force=True)
        need = self.budget_gb + self.policy.start_headroom_gb - self._own_gb
        if snap.pressure in ("warn", "critical"):
            return Decision(False, f"memory pressure {snap.pressure}", snap)
        if snap.available_gb < need:
            return Decision(False, f"available {snap.available_gb:.1f} GB < {need:.1f} GB needed", snap)
        if self.swap_growth_gb() > self.policy.swap_growth_gb:
            return Decision(False, f"swap grew {self.swap_growth_gb():.1f} GB recently", snap)
        return Decision(True, "ok", snap)

    def step(self) -> Decision:
        snap = self.sample()
        if snap.pressure == "critical":
            return Decision(False, "memory pressure critical", snap)
        if snap.available_gb < self.policy.pause_below_gb:
            return Decision(
                False, f"available {snap.available_gb:.2f} GB < {self.policy.pause_below_gb} GB", snap
            )
        if self.swap_growth_gb() > self.policy.swap_growth_gb:
            return Decision(False, f"swap grew {self.swap_growth_gb():.1f} GB in 5 min", snap)
        return Decision(True, "ok", snap)

    def recovered(self, healthy_since: float | None) -> tuple[bool, float | None]:
        ok = self.start().ok
        now = time.time()
        if not ok:
            return False, None
        since = healthy_since or now
        return now - since >= self.policy.recover_hold_sec, since


def apply_mlx_limits(budget_gb: float, cache_gb: float) -> None:
    import mlx.core as mx

    mx.set_memory_limit(int(budget_gb * GB))
    mx.set_cache_limit(int(cache_gb * GB))


def renice(target: int = 10) -> None:
    current = os.nice(0)
    if current < target:
        os.nice(target - current)


def on_battery(override: bool | None = None) -> bool:
    if override is not None:
        return override
    out = _run(["pmset", "-g", "batt"]) or ""
    return "Battery Power" in out


def thermal_serious() -> bool:
    out = _run(["pmset", "-g", "therm"]) or ""
    if m := re.search(r"CPU_Speed_Limit\s*=\s*(\d+)", out):
        return int(m.group(1)) < 70
    if "No thermal warning" in out:
        return False
    m = re.search(r"thermal warning level\D*(\d+)", out, re.IGNORECASE)
    return bool(m and int(m.group(1)) >= 2)


_FOREIGN_TRAINING = re.compile(r"train_mlx|mlx_lm[._ ]lora|mlx_lm_lora|-m mlx_lm\b|mlx_lm\.(lora|fuse)")
_CANDELA_MARKERS = ("candela_spark", "candela_lab", "/candela/")


def foreign_training() -> list[str]:
    """Training processes outside Candela (owner rule: never train two models at once on this Mac)."""
    found: list[str] = []
    me = os.getpid()
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(proc.info["cmdline"] or [])
        except psutil.Error:
            continue
        if proc.info["pid"] == me or not cmd or not _FOREIGN_TRAINING.search(cmd):
            continue
        if any(marker in cmd for marker in _CANDELA_MARKERS) or cmd.startswith(
            ("grep", "pgrep", "/bin/zsh", "zsh")
        ):
            continue
        found.append(f"pid {proc.info['pid']}: {_FOREIGN_TRAINING.search(cmd).group(0)}")  # type: ignore[union-attr]
    return found

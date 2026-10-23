import contextlib
import os
import re
import signal
import subprocess
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import psutil

from candela_lab import log

GB = 1024**3
Pressure = Literal["normal", "warn", "critical", "unknown"]

_log = log.get("resources")

# kern.memorystatus_vm_pressure_level reports the kernel's dispatch levels: 1 normal, 2 warn, 4 critical.
_PRESSURE_LEVELS: dict[int, Pressure] = {1: "normal", 2: "warn", 4: "critical"}


@dataclass(frozen=True)
class MemorySnapshot:
    at: float
    total_gb: float
    available_gb: float
    free_gb: float
    inactive_gb: float
    wired_gb: float
    compressed_gb: float
    swap_used_gb: float
    swap_total_gb: float
    pressure: Pressure

    def as_dict(self) -> dict[str, float | str]:
        return {k: (round(v, 2) if isinstance(v, float) else v) for k, v in asdict(self).items() if k != "at"}


def _sysctl(name: str) -> str | None:
    try:
        out = subprocess.run(["sysctl", "-n", name], capture_output=True, text=True, timeout=5, check=True)
    except subprocess.SubprocessError, OSError:
        return None
    return out.stdout.strip()


def _vm_stat() -> dict[str, int]:
    try:
        out = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5, check=True).stdout
    except subprocess.SubprocessError, OSError:
        return {}
    page = 16384
    if m := re.search(r"page size of (\d+) bytes", out):
        page = int(m.group(1))
    stats: dict[str, int] = {}
    for line in out.splitlines()[1:]:
        key, _, value = line.partition(":")
        value = value.strip().rstrip(".")
        if value.isdigit():
            stats[key.strip().strip('"')] = int(value) * page
    return stats


def _swap() -> tuple[float, float]:
    raw = _sysctl("vm.swapusage") or ""
    used = re.search(r"used = ([\d.]+)M", raw)
    total = re.search(r"total = ([\d.]+)M", raw)
    if used and total:
        return float(used.group(1)) / 1024, float(total.group(1)) / 1024
    sw = psutil.swap_memory()
    return sw.used / GB, sw.total / GB


def pressure_level() -> Pressure:
    raw = _sysctl("kern.memorystatus_vm_pressure_level")
    if raw is None or not raw.isdigit():
        return "unknown"
    return _PRESSURE_LEVELS.get(int(raw), "unknown")


def snapshot() -> MemorySnapshot:
    vm = psutil.virtual_memory()
    stats = _vm_stat()
    swap_used, swap_total = _swap()
    return MemorySnapshot(
        at=time.time(),
        total_gb=vm.total / GB,
        available_gb=vm.available / GB,
        free_gb=stats.get("Pages free", int(vm.free)) / GB,
        inactive_gb=stats.get("Pages inactive", 0) / GB,
        wired_gb=stats.get("Pages wired down", 0) / GB,
        compressed_gb=stats.get("Pages occupied by compressor", 0) / GB,
        swap_used_gb=swap_used,
        swap_total_gb=swap_total,
        pressure=pressure_level(),
    )


# Owner rule: one training at a time on this machine, including trainings outside Candela.
FOREIGN_TRAINING_RE = re.compile(
    r"train_mlx|mlx_lm[ .](lora|tuner|train)|\bmlx_lm\.lora\b|\btrain(er)?\.py\b|torchrun|accelerate launch"
    r"|-m\s+\S*train\S*|\bspark train\b(?!.*candela/spark)"
)


def foreign_training() -> list[tuple[int, str]]:
    """Training processes that are not this process (and not Candela Spark, which yields through the GPU lease)."""
    extra = os.environ.get("CANDELA_FOREIGN_TRAINING_RE")
    pattern = re.compile(extra) if extra else FOREIGN_TRAINING_RE
    me = os.getpid()
    found = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            if proc.info["pid"] in (me, os.getppid()):
                continue
            cmd = " ".join(proc.info["cmdline"] or [])
        except psutil.Error:
            continue
        if "candela/spark" in cmd or "candela_lab" in cmd or "lab train" in cmd:
            continue
        if pattern.search(cmd):
            found.append((int(proc.info["pid"]), cmd[:120]))
    return found


@dataclass(frozen=True)
class GuardPolicy:
    start_headroom_gb: float = 3.0
    pause_below_gb: float = 1.5
    swap_growth_gb: float = 1.0
    swap_window_sec: float = 300.0
    recover_sec: float = 600.0
    poll_sec: float = 15.0
    max_backoff_sec: float = 300.0
    sample_every_sec: float = 5.0


@dataclass
class GuardDecision:
    ok: bool
    reason: str
    snapshot: MemorySnapshot


@dataclass
class PauseEvent:
    step: int
    reason: str
    at: str
    resumed_at: str | None = None
    waited_sec: float | None = None


@dataclass
class ResourceGuard:
    budget_gb: float
    policy: GuardPolicy = field(default_factory=GuardPolicy)
    pause_file: Path | None = None
    _swap_history: deque[tuple[float, float]] = field(default_factory=lambda: deque(maxlen=512))
    _last_sample: MemorySnapshot | None = None
    _signal_pause: bool = False
    _simulated: set[int] = field(default_factory=set)
    _last_foreign_check: float = 0.0

    def _foreign_check_due(self) -> bool:
        now = time.time()
        if now - self._last_foreign_check >= 30:
            self._last_foreign_check = now
            return True
        return False

    def install_signal_handler(self) -> None:
        def handler(_signum: int, _frame: object) -> None:
            self._signal_pause = True

        signal.signal(signal.SIGUSR1, handler)

    def simulate_pause_at(self, steps: list[int]) -> None:
        self._simulated.update(steps)

    def sample(self, force: bool = False) -> MemorySnapshot:
        now = time.time()
        if not force and self._last_sample and now - self._last_sample.at < self.policy.sample_every_sec:
            return self._last_sample
        snap = snapshot()
        self._swap_history.append((snap.at, snap.swap_used_gb))
        self._last_sample = snap
        return snap

    def swap_growth_gb(self) -> float:
        if not self._swap_history:
            return 0.0
        now, current = self._swap_history[-1]
        window = [s for t, s in self._swap_history if now - t <= self.policy.swap_window_sec]
        return current - min(window) if window else 0.0

    def required_start_gb(self) -> float:
        return self.budget_gb + self.policy.start_headroom_gb

    def start_decision(self) -> GuardDecision:
        snap = self.sample(force=True)
        need = self.required_start_gb()
        foreign = foreign_training()
        if foreign:
            return GuardDecision(False, f"foreign training running (pid {foreign[0][0]})", snap)
        if snap.pressure == "critical":
            return GuardDecision(False, "memory pressure critical", snap)
        if snap.available_gb < need:
            return GuardDecision(
                False, f"available {snap.available_gb:.1f} GB < required {need:.1f} GB", snap
            )
        if self.swap_growth_gb() > self.policy.swap_growth_gb:
            return GuardDecision(False, f"swap grew {self.swap_growth_gb():.2f} GB in window", snap)
        return GuardDecision(True, f"available {snap.available_gb:.1f} GB >= required {need:.1f} GB", snap)

    def wait_for_headroom(self, timeout_sec: float | None = None, what: str = "job") -> GuardDecision:
        delay = self.policy.poll_sec
        started = time.time()
        while True:
            decision = self.start_decision()
            if decision.ok:
                _log.info("headroom ok", what=what, budget_gb=self.budget_gb, **decision.snapshot.as_dict())
                return decision
            waited = time.time() - started
            if timeout_sec is not None and waited >= timeout_sec:
                _log.warning("headroom timeout", what=what, waited_sec=round(waited), reason=decision.reason)
                return decision
            _log.info(
                "waiting for headroom",
                what=what,
                reason=decision.reason,
                retry_in_sec=round(delay),
                waited_sec=round(waited),
            )
            time.sleep(delay)
            delay = min(delay * 1.5, self.policy.max_backoff_sec)

    def check_step(self, step: int) -> GuardDecision:
        if step in self._simulated:
            self._simulated.discard(step)
            return GuardDecision(False, "simulated pause", self.sample(force=True))
        if self._signal_pause:
            self._signal_pause = False
            return GuardDecision(False, "pause signal (SIGUSR1)", self.sample(force=True))
        if self.pause_file is not None and self.pause_file.exists():
            with contextlib.suppress(OSError):
                self.pause_file.unlink()
            return GuardDecision(False, f"pause file {self.pause_file.name}", self.sample(force=True))
        snap = self.sample()
        if self._foreign_check_due():
            foreign = foreign_training()
            if foreign:
                return GuardDecision(False, f"foreign training running (pid {foreign[0][0]})", snap)
        if snap.available_gb < self.policy.pause_below_gb:
            return GuardDecision(
                False, f"available {snap.available_gb:.2f} GB < {self.policy.pause_below_gb} GB", snap
            )
        growth = self.swap_growth_gb()
        if growth > self.policy.swap_growth_gb:
            window_min = self.policy.swap_window_sec / 60
            return GuardDecision(False, f"swap grew {growth:.2f} GB in {window_min:.0f} min", snap)
        return GuardDecision(True, "ok", snap)

    def wait_for_recovery(self, recover_sec: float | None = None) -> float:
        need = self.required_start_gb()
        hold = self.policy.recover_sec if recover_sec is None else recover_sec
        started = time.time()
        healthy_since: float | None = None
        while True:
            snap = self.sample(force=True)
            healthy = (
                not foreign_training()
                and snap.available_gb >= need
                and snap.pressure != "critical"
                and self.swap_growth_gb() <= self.policy.swap_growth_gb
            )
            now = time.time()
            if healthy:
                healthy_since = healthy_since or now
                if now - healthy_since >= hold:
                    waited = now - started
                    _log.info("recovered", waited_sec=round(waited), **snap.as_dict())
                    return waited
            else:
                healthy_since = None
            _log.info(
                "paused, waiting for recovery",
                available_gb=round(snap.available_gb, 2),
                need_gb=need,
                healthy_for_sec=round(now - healthy_since) if healthy_since else 0,
                hold_sec=hold,
            )
            time.sleep(min(self.policy.poll_sec, max(hold / 4, 1.0)))


def apply_process_limits(
    budget_gb: float, cache_gb: float = 1.0, wired_gb: float = 0.0, nice: int = 10
) -> None:
    import mlx.core as mx

    mx.set_memory_limit(int(budget_gb * GB))
    mx.set_cache_limit(int(cache_gb * GB))
    if wired_gb > 0:
        mx.set_wired_limit(int(wired_gb * GB))
    current = os.nice(0)
    if current < nice:
        os.nice(nice - current)
    _log.info(
        "process limits", memory_limit_gb=budget_gb, cache_limit_gb=cache_gb, wired_gb=wired_gb, nice=nice
    )


def release_mlx_memory() -> None:
    import gc

    import mlx.core as mx

    gc.collect()
    mx.clear_cache()


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")

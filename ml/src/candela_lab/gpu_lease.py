import contextlib
import json
import os
import signal
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import FrameType
from typing import Any

from candela_lab import log

PROTOCOL = "candela.gpu-lease.v1"
LEASE_DIR = Path(os.environ.get("CANDELA_LEASE_DIR", "~/.candela/leases")).expanduser()
LIVE_SEC = 30.0
HEARTBEAT_SEC = 10.0
PRIORITIES = {
    "worker": 100,
    "lab-train": 80,
    "spark-milestone": 70,
    "lab-eval": 60,
    "lab-export": 60,
    "spark-trainer": 20,
}

_log = log.get("gpu_lease")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse(ts: str) -> float:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass(frozen=True)
class LeaseInfo:
    holder: str
    pid: int
    priority: int
    purpose: str
    heartbeat_at: float
    path: Path


def read_leases() -> list[LeaseInfo]:
    if not LEASE_DIR.exists():
        return []
    out = []
    for path in LEASE_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            out.append(
                LeaseInfo(
                    holder=str(data["holder"]),
                    pid=int(data["pid"]),
                    priority=int(data["priority"]),
                    purpose=str(data.get("purpose", "")),
                    heartbeat_at=_parse(str(data["heartbeatAt"])),
                    path=path,
                )
            )
        except OSError, ValueError, KeyError, TypeError:
            continue
    return out


def live_leases() -> list[LeaseInfo]:
    now = time.time()
    live = []
    for lease in read_leases():
        if now - lease.heartbeat_at < LIVE_SEC and _pid_alive(lease.pid):
            live.append(lease)
        else:
            with contextlib.suppress(OSError):
                lease.path.unlink()
    return live


class Lease:
    """Holds `~/.candela/leases/<holder>.json` with a 10 s heartbeat and yields to higher priorities at boundaries."""

    def __init__(self, holder: str, purpose: str, priority: int | None = None) -> None:
        self.holder = holder
        self.priority = PRIORITIES[holder] if priority is None else priority
        self.purpose = purpose
        self.path = LEASE_DIR / f"{holder}.json"
        self.started_at = _now()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._prev_handlers: dict[int, Any] = {}

    def _write(self) -> None:
        LEASE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(LEASE_DIR, 0o700)
        payload = {
            "protocol": PROTOCOL,
            "holder": self.holder,
            "pid": os.getpid(),
            "priority": self.priority,
            "purpose": self.purpose,
            "startedAt": self.started_at,
            "heartbeatAt": _now(),
        }
        tmp = self.path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(payload))
        tmp.replace(self.path)

    def _beat(self) -> None:
        while not self._stop.wait(HEARTBEAT_SEC):
            with contextlib.suppress(OSError):
                self._write()

    def _on_signal(self, signum: int, frame: FrameType | None) -> None:
        self.release()
        prev = self._prev_handlers.get(signum)
        if callable(prev):
            prev(signum, frame)
        else:
            raise SystemExit(128 + signum)

    def acquire(self) -> Lease:
        self._write()
        self._thread = threading.Thread(target=self._beat, name=f"lease-{self.holder}", daemon=True)
        self._thread.start()
        if threading.current_thread() is threading.main_thread():
            for sig in (signal.SIGTERM, signal.SIGINT):
                self._prev_handlers[sig] = signal.getsignal(sig)
                signal.signal(sig, self._on_signal)
        _log.info("lease acquired", holder=self.holder, priority=self.priority, path=str(self.path))
        return self

    def release(self) -> None:
        self._stop.set()
        with contextlib.suppress(OSError):
            if self.path.exists() and json.loads(self.path.read_text()).get("pid") == os.getpid():
                self.path.unlink()
        if threading.current_thread() is threading.main_thread():
            for sig, handler in self._prev_handlers.items():
                signal.signal(sig, handler)
            self._prev_handlers.clear()

    def __enter__(self) -> Lease:
        return self.acquire()

    def __exit__(self, *exc: object) -> None:
        self.release()

    def higher(self) -> list[LeaseInfo]:
        return [x for x in live_leases() if x.priority > self.priority and x.pid != os.getpid()]

    def yield_if_needed(self, on_long_wait: Any = None, long_wait_sec: float = 600.0) -> float:
        """Blocks while a higher-priority lease is live; returns the seconds waited."""
        blockers = self.higher()
        if not blockers:
            return 0.0
        started = time.time()
        released = False
        _log.info("yielding GPU", to=",".join(b.holder for b in blockers), priority=self.priority)
        while blockers:
            time.sleep(3.0)
            if not released and on_long_wait is not None and time.time() - started > long_wait_sec:
                on_long_wait()
                released = True
            blockers = self.higher()
        waited = time.time() - started
        _log.info("GPU lease regained", waited_sec=round(waited, 1))
        return waited

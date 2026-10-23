import contextlib
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from candela_spark import log, paths

PROTOCOL = "candela.gpu-lease.v1"
LIVE_SEC = 30.0
HEARTBEAT_SEC = 10.0
_log = log.get("lease")


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(ts: str) -> float:
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC).timestamp()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@dataclass(frozen=True)
class Lease:
    holder: str
    pid: int
    priority: int
    purpose: str
    state: str = "active"


def live_leases(directory: Path = paths.LEASES) -> list[Lease]:
    out: list[Lease] = []
    if not directory.exists():
        return out
    now = time.time()
    for f in directory.glob("*.json"):
        try:
            raw = json.loads(f.read_text())
            if raw.get("protocol") != PROTOCOL:
                continue
            fresh = now - _parse(raw["heartbeatAt"]) < LIVE_SEC
            pid = int(raw["pid"])
            if fresh and _pid_alive(pid):
                out.append(
                    Lease(
                        raw["holder"],
                        pid,
                        int(raw["priority"]),
                        str(raw.get("purpose", "")),
                        str(raw.get("state", "active")),
                    )
                )
        except OSError, ValueError, KeyError:
            continue
    return out


class GpuLease:
    def __init__(self, holder: str, priority: int, purpose: str, directory: Path = paths.LEASES) -> None:
        self.holder = holder
        self.priority = priority
        self.purpose = purpose
        self.dir = directory
        self.path = directory / f"{holder}.json"
        self._started = _now()
        self.state = "active"
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _write(self) -> None:
        payload = {
            "protocol": PROTOCOL,
            "holder": self.holder,
            "pid": os.getpid(),
            "priority": self.priority,
            "purpose": self.purpose,
            "state": self.state,
            "startedAt": self._started,
            "heartbeatAt": _now(),
        }
        with self._lock:
            self.dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            tmp = self.path.with_suffix(f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(payload))
            os.replace(tmp, self.path)

    def set_priority(self, priority: int, purpose: str | None = None) -> None:
        self.priority = priority
        if purpose:
            self.purpose = purpose
        self._write()

    def set_state(self, state: str) -> None:
        self.state = state
        self._write()

    def acquire(self, state: str = "active") -> None:
        self.state = state
        self._write()
        self._stop.clear()
        self._thread = threading.Thread(target=self._beat, name="lease-heartbeat", daemon=True)
        self._thread.start()
        _log.info("lease acquired", holder=self.holder, priority=self.priority, state=self.state)

    def _beat(self) -> None:
        while not self._stop.wait(HEARTBEAT_SEC):
            with contextlib.suppress(OSError):
                self._write()

    def release(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        with self._lock, contextlib.suppress(FileNotFoundError):
            self.path.unlink()
        _log.info("lease released", holder=self.holder)

    def higher(self) -> list[Lease]:
        return [
            lease
            for lease in live_leases(self.dir)
            if lease.priority > self.priority and lease.holder != self.holder and lease.pid != os.getpid()
        ]

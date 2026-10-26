import contextlib
import json
import os
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from candela_worker import log

PROTOCOL = "candela.gpu-lease.v1"
HOLDER = "worker"
PRIORITY = 100
HEARTBEAT_SEC = 10.0
LIVE_SEC = 30.0

_log = log.get("lease")


def lease_dir() -> Path:
    return Path(os.environ.get("CANDELA_LEASE_DIR", "~/.candela/leases")).expanduser()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def live_leases() -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    directory = lease_dir()
    if not directory.exists():
        return out
    now = time.time()
    for path in directory.glob("*.json"):
        try:
            data = json.loads(path.read_text())
            beat = datetime.fromisoformat(str(data["heartbeatAt"]).replace("Z", "+00:00")).timestamp()
            if now - beat < LIVE_SEC and _pid_alive(int(data["pid"])):
                out.append(data)
        except OSError, ValueError, KeyError, TypeError:
            continue
    return out


class GpuLease:
    """`~/.candela/leases/worker.json` (priority 100), written only while a job runs (contracts/gpu-lease.md).

    The lease is written as `waiting` before the memory check so lower-priority trainers release the GPU
    (reservation rules 7–9) and switched to `active` once admission passes.
    """

    def __init__(self, purpose: str) -> None:
        self.purpose = purpose
        self.state: Literal["waiting", "active"] = "waiting"
        self.path = lease_dir() / f"{HOLDER}.json"
        self.started_at = _now()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _write(self) -> None:
        directory = lease_dir()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        payload = {
            "protocol": PROTOCOL,
            "holder": HOLDER,
            "pid": os.getpid(),
            "priority": PRIORITY,
            "purpose": self.purpose,
            "state": self.state,
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

    def acquire(self) -> GpuLease:
        self._write()
        self._thread = threading.Thread(target=self._beat, name="gpu-lease", daemon=True)
        self._thread.start()
        _log.debug("lease written", state=self.state)
        return self

    def activate(self) -> None:
        if self.state != "active":
            self.state = "active"
            with contextlib.suppress(OSError):
                self._write()

    def release(self) -> None:
        self._stop.set()
        with contextlib.suppress(OSError, ValueError):
            if self.path.exists() and json.loads(self.path.read_text()).get("pid") == os.getpid():
                self.path.unlink()
        _log.debug("lease released")


def release_stale_own() -> None:
    """Removes a lease file left by a previous run of this worker (crash or SIGKILL)."""
    path = lease_dir() / f"{HOLDER}.json"
    with contextlib.suppress(OSError, ValueError, KeyError):
        data = json.loads(path.read_text())
        if not _pid_alive(int(data["pid"])) or int(data["pid"]) == os.getpid():
            path.unlink()

import json
import os
import time
from typing import Any

from candela_spark import paths

SCHEMA = "candela.spark.status.v1"
_last_write = 0.0
_last_state = ""


def write(payload: dict[str, Any], min_interval: float = 5.0) -> None:
    """Sanitised status for the Observatory and the gateway: no paths, hostnames or process details."""
    global _last_write, _last_state
    state = str(payload.get("state", ""))
    now = time.time()
    if state == _last_state and now - _last_write < min_interval:
        return
    _last_write, _last_state = now, state
    paths.SPARK_STATE.mkdir(parents=True, exist_ok=True, mode=0o700)
    doc = {"schema": SCHEMA, "updatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)), **payload}
    target = paths.SPARK_STATE / "status.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, separators=(",", ":")))
    os.replace(tmp, target)


def read() -> dict[str, Any] | None:
    try:
        return json.loads((paths.SPARK_STATE / "status.json").read_text())
    except OSError, ValueError:
        return None

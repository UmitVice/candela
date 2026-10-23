import json
import logging
import sys
import time
from typing import Any


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z",
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        extra = getattr(record, "fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


_configured = False


def setup(level: int = logging.INFO) -> None:
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger("spark")
    root.addHandler(handler)
    root.setLevel(level)
    root.propagate = False
    _configured = True


class Logger:
    def __init__(self, name: str) -> None:
        self._log = logging.getLogger(f"spark.{name}")

    def _emit(self, level: int, msg: str, fields: dict[str, Any]) -> None:
        setup()
        self._log.log(level, msg, extra={"fields": fields})

    def info(self, msg: str, **fields: Any) -> None:
        self._emit(logging.INFO, msg, fields)

    def warning(self, msg: str, **fields: Any) -> None:
        self._emit(logging.WARNING, msg, fields)

    def error(self, msg: str, **fields: Any) -> None:
        self._emit(logging.ERROR, msg, fields)


def get(name: str) -> Logger:
    return Logger(name)

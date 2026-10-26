import json
import logging
import os
import sys
from datetime import UTC, datetime
from typing import Any

_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "time": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED:
                out[key] = value
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


class Logger:
    def __init__(self, name: str) -> None:
        self._log = logging.getLogger(f"candela_worker.{name}")

    def _emit(self, level: int, msg: str, fields: dict[str, Any], exc: bool = False) -> None:
        self._log.log(level, msg, extra=fields, exc_info=exc)

    def debug(self, msg: str, **fields: Any) -> None:
        self._emit(logging.DEBUG, msg, fields)

    def info(self, msg: str, **fields: Any) -> None:
        self._emit(logging.INFO, msg, fields)

    def warning(self, msg: str, **fields: Any) -> None:
        self._emit(logging.WARNING, msg, fields)

    def error(self, msg: str, exc: bool = False, **fields: Any) -> None:
        self._emit(logging.ERROR, msg, fields, exc)


def setup(level: str | None = None) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger("candela_worker")
    root.handlers[:] = [handler]
    root.setLevel((level or os.environ.get("CANDELA_LOG_LEVEL", "info")).upper())
    root.propagate = False
    for noisy in ("uvicorn", "uvicorn.error", "uvicorn.access", "websockets"):
        logging.getLogger(noisy).handlers[:] = [handler]
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get(name: str) -> Logger:
    return Logger(name)

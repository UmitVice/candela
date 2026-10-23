import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_CONFIGURED = False


class _KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        ts = datetime.fromtimestamp(record.created, UTC).strftime("%H:%M:%S")
        fields: dict[str, Any] = getattr(record, "fields", {})
        extras = " ".join(f"{k}={_fmt(v)}" for k, v in fields.items())
        return f"{ts} {record.levelname.lower():5s} {record.name}: {record.getMessage()}" + (
            f" {extras}" if extras else ""
        )


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="seconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
            **getattr(record, "fields", {}),
        }
        return json.dumps(payload, default=str)


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.3f}"
    s = str(v)
    return f'"{s}"' if " " in s else s


class Logger:
    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def _log(self, level: int, msg: str, fields: dict[str, Any], exc_info: bool = False) -> None:
        if self._logger.isEnabledFor(level):
            self._logger.log(level, msg, extra={"fields": fields}, exc_info=exc_info, stacklevel=3)

    def debug(self, msg: str, **fields: Any) -> None:
        self._log(logging.DEBUG, msg, fields)

    def info(self, msg: str, **fields: Any) -> None:
        self._log(logging.INFO, msg, fields)

    def warning(self, msg: str, **fields: Any) -> None:
        self._log(logging.WARNING, msg, fields)

    def error(self, msg: str, exc_info: bool = False, **fields: Any) -> None:
        self._log(logging.ERROR, msg, fields, exc_info=exc_info)


def setup(level: int = logging.INFO) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(_KeyValueFormatter())
    root = logging.getLogger("candela")
    root.setLevel(level)
    root.addHandler(handler)
    root.propagate = False
    _CONFIGURED = True


def add_json_file(path: Path) -> logging.Handler:
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path)
    handler.setFormatter(_JsonFormatter())
    logging.getLogger("candela").addHandler(handler)
    return handler


def remove_handler(handler: logging.Handler) -> None:
    logging.getLogger("candela").removeHandler(handler)
    handler.close()


def get(name: str) -> Logger:
    setup()
    return Logger(logging.getLogger(f"candela.{name}"))

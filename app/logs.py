"""Structured (one JSON object per line) logging: access log, auth / limit events and unhandled errors, all with
the request id, never with bodies, query strings, tokens or API keys. Stdout only: the platform ships it."""
from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

logger = logging.getLogger("diy")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + "Z",
                                   "level": record.levelname.lower(), "event": record.getMessage()}
        payload.update(getattr(record, "fields", {}))
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(level: str = "INFO") -> None:
    if any(getattr(h, "_diy", False) for h in logger.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler._diy = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    logger.setLevel(level.upper())
    logger.propagate = False


def log_event(event: str, level: int = logging.INFO, exc_info: Any = None, **fields: Any) -> None:
    logger.log(level, event, exc_info=exc_info, extra={"fields": fields})

"""Logging setup: human-readable console output plus rotating JSON-lines files for traceability.

Every record carries the current ``request_id``. Structured fields are attached with
``logger.info("...", extra={"event": {...}})`` and appear as top-level JSON keys, e.g.::

    {"ts": "...", "level": "INFO", "logger": "parkfinder.access", "request_id": "3f2a...",
     "message": "GET /api/v1/parks/by-city -> 200 (412.3 ms)", "event": "http_request",
     "method": "GET", "path": "/api/v1/parks/by-city", "status": 200, "duration_ms": 412.3}

Trace one call end to end:  ``grep 3f2a... backend/logs/api.log``
"""

import json
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Any, Mapping

from app.config import Settings
from app.request_context import request_id_var

_OWNED = "_parkfinder_handler"
_SENSITIVE_KEYS = ("key", "token", "secret", "password", "auth", "signature")


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        event = getattr(record, "event", None)
        if isinstance(event, Mapping):
            payload.update({k: v for k, v in event.items() if k not in payload})
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, ensure_ascii=False)


def redact(params: Mapping[str, Any] | None) -> dict[str, Any] | None:
    """Mask values of credential-like parameters so secrets never reach the logs."""
    if params is None:
        return None
    return {
        k: "***" if any(s in k.lower() for s in _SENSITIVE_KEYS) else v
        for k, v in params.items()
    }


def configure_logging(settings: Settings) -> None:
    """Install our handlers on the root logger. Safe to call repeatedly (replaces previous ones)."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, _OWNED, False):
            root.removeHandler(handler)
            handler.close()

    root.setLevel(settings.log_level.upper())

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s"))
    handlers: list[logging.Handler] = [console]

    if settings.log_to_file:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            settings.log_dir / settings.log_file_name,
            maxBytes=settings.log_max_bytes,
            backupCount=settings.log_backup_count,
            encoding="utf-8",
            delay=True,
        )
        file_handler.setFormatter(JsonFormatter())
        handlers.append(file_handler)

    for handler in handlers:
        handler.addFilter(RequestIdFilter())
        setattr(handler, _OWNED, True)
        root.addHandler(handler)

    # Our access log and upstream-call log replace these (avoids duplicate, id-less lines).
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

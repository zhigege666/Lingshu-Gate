"""Structured logging helpers for Lingshu Gate."""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from typing import Any

from lingshu_gate.redaction import redact_value


GATE_EVENT_NAME_PATTERN = re.compile(
    r"^gate\.[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$"
)


def validate_gate_event_name(event: str) -> str:
    """Return a valid first-party event name or fail at the write boundary."""

    if not isinstance(event, str) or not GATE_EVENT_NAME_PATTERN.fullmatch(event):
        raise ValueError(
            "event name must use the lowercase Gate namespace "
            "(for example, gate.runtime.started)"
        )
    return event


class JsonFormatter(logging.Formatter):
    """Emit logs as one JSON object per line.

    The runtime intentionally keeps MCP logs verbose. This makes container logs
    useful when diagnosing config loading, process startup, protocol messages,
    stderr output, tool discovery, and tool invocation failures.
    """

    def format(self, record: logging.LogRecord) -> str:  # noqa: D401 - inherited contract
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key.startswith("gate_"):
                payload[key.removeprefix("gate_")] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(redact_value(payload), ensure_ascii=False, default=str)


def configure_logging(level: str) -> None:
    """Configure process-wide JSON logging."""

    root = logging.getLogger()
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level.upper())


def log_event(logger: logging.Logger, level: int, event: str, message: str, **fields: Any) -> None:
    """Log a structured event with a stable event name."""

    event = validate_gate_event_name(event)
    exc_info = bool(fields.pop("exc_info", False))
    extra = {"gate_event": event}
    for key, value in fields.items():
        extra[f"gate_{key}"] = value
    logger.log(level, message, extra=extra, exc_info=exc_info)

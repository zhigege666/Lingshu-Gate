"""Read-only system diagnostics exposed through Gate MCP."""

from __future__ import annotations

import re
from typing import Any

from lingshu_gate.config import Settings
from lingshu_gate.diagnostics import run_diagnostics
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.mcp_server_detail import build_mcp_server_detail
from lingshu_gate.models import ToolDefinition
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.protocol.tool_namespace import (
    SYSTEM_DEBUG_TOOL_ID,
    SYSTEM_DEBUG_TOOL_NAME,
)
from lingshu_gate.redaction import redact_text
from lingshu_gate.registry import ToolRegistry

DEFAULT_LIMIT = 50
MAX_LIMIT = 200
MAX_KEYWORD_LENGTH = 200
MAX_STRING_LENGTH = 16_000
SENSITIVE_KEY_PATTERN = re.compile(
    r"(?:password|passwd|secret|token|api[_-]?key|authorization|cookie|credential|private[_-]?key)",
    re.IGNORECASE,
)
BEARER_PATTERN = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
INLINE_SECRET_PATTERN = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization|cookie|credential)\b"
    r"(\s*[:=]\s*)([^\s,;]+)"
)


def system_debug_tool_definition() -> ToolDefinition:
    """Return the public definition shared by REST and MCP discovery."""

    return ToolDefinition(
        id=SYSTEM_DEBUG_TOOL_ID,
        name="Gate System Debug",
        description=(
            "Read Lingshu Gate runtime status, managed MCP server stdout/stderr, persisted logs, events, "
            "and read-only diagnostics. This tool never executes shell or Docker commands."
        ),
        permission="read:system_debug",
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["overview", "server_detail", "logs", "events", "diagnostics"],
                    "default": "overview",
                    "description": "Diagnostic view to return.",
                },
                "server_id": {"type": "string", "description": "MCP server ID; required by server_detail."},
                "level": {"type": "string", "description": "Optional log level filter."},
                "source": {"type": "string", "description": "Optional log/event source filter."},
                "event_type": {"type": "string", "description": "Optional log/event type filter."},
                "keyword": {"type": "string", "maxLength": MAX_KEYWORD_LENGTH},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT, "default": DEFAULT_LIMIT},
            },
            "additionalProperties": False,
        },
        source="builtin",
        metadata={
            "mcp_name": SYSTEM_DEBUG_TOOL_NAME,
            "annotations": {
                "readOnlyHint": True,
                "destructiveHint": False,
                "idempotentHint": True,
                "openWorldHint": False,
            },
        },
    )


class SystemDebugService:
    """Aggregate bounded, redacted diagnostics from existing runtime stores."""

    def __init__(
        self,
        settings: Settings,
        registry: ToolRegistry,
        runtime: McpRuntimeManager,
        observability_store: ObservabilityStore,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.runtime = runtime
        self.observability_store = observability_store

    def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action = str(arguments.get("action") or "overview").strip()
        limit = _parse_limit(arguments.get("limit"))
        keyword = _optional_text(arguments.get("keyword"), "keyword", MAX_KEYWORD_LENGTH)

        if action == "overview":
            result = self._overview(limit)
        elif action == "server_detail":
            server_id = _required_text(arguments.get("server_id"), "server_id")
            result = self._server_detail(server_id, limit)
        elif action == "logs":
            result = self._logs(arguments, keyword, limit)
        elif action == "events":
            result = self._events(arguments, keyword, limit)
        elif action == "diagnostics":
            result = run_diagnostics(self.settings, self.registry, self.runtime).model_dump(mode="json")
        else:
            raise ValueError(f"Unsupported action: {action}")

        return _sanitize(result)

    def _overview(self, limit: int) -> dict[str, Any]:
        servers = self.runtime.list_servers().model_dump(mode="json")
        recent_errors = self.observability_store.list_logs(level="error", limit=limit)
        return {
            "service": {
                "name": self.settings.service_name,
                "version": self.settings.version,
                "debug_mcp_enabled": self.settings.system_debug_mcp_enabled,
                "endpoint": "/mcp",
            },
            "servers": servers,
            "recent_error_logs": recent_errors,
            "notes": [
                "Managed MCP process/container stdout and stderr are read from Gate persisted runtime logs.",
                "The tool does not execute docker logs and does not require the Docker socket.",
            ],
        }

    def _server_detail(self, server_id: str, limit: int) -> dict[str, Any]:
        detail = build_mcp_server_detail(self.settings, self.runtime, self.observability_store, server_id)
        for key in ("logs", "events", "timeline", "restart_history"):
            value = detail.get(key)
            if isinstance(value, list):
                detail[key] = value[:limit]
        for key in ("recent_stdout", "recent_stderr"):
            value = detail.get(key)
            if isinstance(value, list):
                detail[key] = value[: min(limit, 50)]
        return detail

    def _logs(self, arguments: dict[str, Any], keyword: str | None, limit: int) -> dict[str, Any]:
        items = self.observability_store.list_logs(
            level=_optional_text(arguments.get("level"), "level"),
            server_id=_optional_text(arguments.get("server_id"), "server_id"),
            source=_optional_text(arguments.get("source"), "source"),
            event_type=_optional_text(arguments.get("event_type"), "event_type"),
            keyword=keyword,
            limit=min(limit + 1, MAX_LIMIT + 1),
        )
        return _page("logs", items, limit)

    def _events(self, arguments: dict[str, Any], keyword: str | None, limit: int) -> dict[str, Any]:
        subject_id = _optional_text(arguments.get("server_id"), "server_id")
        items = self.observability_store.list_events(
            event_type=_optional_text(arguments.get("event_type"), "event_type"),
            subject_id=subject_id,
            source=_optional_text(arguments.get("source"), "source"),
            keyword=keyword,
            limit=min(limit + 1, MAX_LIMIT + 1),
        )
        return _page("events", items, limit)


def register_system_debug_tool(registry: ToolRegistry, service: SystemDebugService) -> None:
    """Register the debug tool in the existing REST tool registry."""

    registry.register(system_debug_tool_definition(), service.invoke)


def _parse_limit(value: Any) -> int:
    if value is None:
        return DEFAULT_LIMIT
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("limit must be an integer")
    if not 1 <= value <= MAX_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_LIMIT}")
    return value


def _required_text(value: Any, name: str) -> str:
    parsed = _optional_text(value, name)
    if not parsed:
        raise ValueError(f"{name} is required")
    return parsed


def _optional_text(value: Any, name: str, max_length: int = MAX_KEYWORD_LENGTH) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    parsed = value.strip()
    if not parsed:
        return None
    if len(parsed) > max_length:
        raise ValueError(f"{name} must not exceed {max_length} characters")
    return parsed


def _page(key: str, items: list[dict[str, Any]], limit: int) -> dict[str, Any]:
    return {
        key: items[:limit],
        "count": min(len(items), limit),
        "limit": limit,
        "has_more": len(items) > limit,
    }


def _sanitize(value: Any, *, key: str | None = None) -> Any:
    """Redact common credentials and bound strings before returning diagnostics."""

    if key and SENSITIVE_KEY_PATTERN.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(item_key): _sanitize(item_value, key=str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, list):
        return [_sanitize(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize(item) for item in value]
    if isinstance(value, str):
        return redact_text(value, limit=MAX_STRING_LENGTH)
    return value

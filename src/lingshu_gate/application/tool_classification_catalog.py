"""Project persisted review history onto the currently registered tool catalog."""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from lingshu_gate.access_control import ClassificationConfirmationConflictError
from lingshu_gate.models import ToolDefinition


def current_tool_keys(definitions: Iterable[ToolDefinition]) -> set[tuple[str, str]]:
    keys = set()
    for definition in definitions:
        server_id = definition.metadata.get("server_id")
        server_id = (server_id.strip() if isinstance(server_id, str) and server_id.strip()
                     else definition.source or "builtin")
        keys.add((server_id, definition.id))
    return keys


def current_classifications(rows: Iterable[dict[str, Any]], definitions: Iterable[ToolDefinition]) -> list[dict[str, Any]]:
    """Keep history in storage, but never advertise missing tools as current."""
    keys = current_tool_keys(definitions)
    return [row for row in rows if (row["server_id"], row["tool_id"]) in keys]


def require_current_tools(definitions: Iterable[ToolDefinition], targets: Iterable[tuple[str, str]]) -> None:
    missing = set(targets) - current_tool_keys(definitions)
    if missing:
        server_id, tool_id = sorted(missing)[0]
        raise ClassificationConfirmationConflictError(
            f"tool is no longer registered: {server_id}/{tool_id}; refresh the current tool catalog"
        )

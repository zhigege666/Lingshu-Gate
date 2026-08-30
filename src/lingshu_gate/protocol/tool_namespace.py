"""Stable MCP wire-name projection with fail-closed collision handling."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from lingshu_gate.models import ToolDefinition

MAX_TOOL_NAME_LENGTH = 128
INVALID_TOOL_NAME = re.compile(r"[^A-Za-z0-9_-]")
SYSTEM_DEBUG_TOOL_ID = "gate_system_debug"
SYSTEM_DEBUG_TOOL_NAME = "gate_system_debug"


class ToolNamespaceCollisionError(ValueError):
    """Two registry ids project to the same public MCP tool name."""

    def __init__(self, wire_name: str, tool_ids: tuple[str, str]) -> None:
        self.wire_name = wire_name
        self.tool_ids = tuple(sorted(tool_ids))
        super().__init__(
            f"MCP tool namespace collision for {wire_name!r}: "
            f"{self.tool_ids[0]!r}, {self.tool_ids[1]!r}"
        )


@dataclass(frozen=True)
class ToolNamespaceEntry:
    wire_name: str
    definition: ToolDefinition


class ToolNamespace:
    """Immutable mapping from public names to one Registry snapshot.

    Previous code appended an implementation-specific hash when two ids
    collided.  That made names change as registrations changed.  The gateway
    now refuses to publish an ambiguous snapshot so calls can never be routed
    to an unexpected tool.
    """

    def __init__(self, definitions: list[ToolDefinition]) -> None:
        entries: list[ToolNamespaceEntry] = []
        by_name: dict[str, ToolDefinition] = {}
        ordered = sorted(
            definitions,
            key=lambda definition: (
                definition.id != SYSTEM_DEBUG_TOOL_ID,
                definition.id,
            ),
        )
        for definition in ordered:
            wire_name = public_tool_name(definition)
            existing = by_name.get(wire_name)
            if existing is not None and existing.id != definition.id:
                raise ToolNamespaceCollisionError(
                    wire_name, (existing.id, definition.id)
                )
            by_name[wire_name] = definition
            entries.append(ToolNamespaceEntry(wire_name, definition))
        self._entries = tuple(entries)
        self._by_name = by_name

    @property
    def entries(self) -> tuple[ToolNamespaceEntry, ...]:
        return self._entries

    def resolve(self, wire_name: str) -> ToolDefinition | None:
        return self._by_name.get(wire_name)


def public_tool_name(definition: ToolDefinition) -> str:
    if definition.id == SYSTEM_DEBUG_TOOL_ID:
        return SYSTEM_DEBUG_TOOL_NAME
    candidate = definition.id.replace(".", "__")
    candidate = INVALID_TOOL_NAME.sub("_", candidate).strip("_") or "gate_tool"
    if len(candidate) <= MAX_TOOL_NAME_LENGTH:
        return candidate
    digest = hashlib.sha256(definition.id.encode("utf-8")).hexdigest()[:12]
    prefix_length = MAX_TOOL_NAME_LENGTH - len(digest) - 2
    return f"{candidate[:prefix_length]}__{digest}"

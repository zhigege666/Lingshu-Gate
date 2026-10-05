"""Bounded, immutable published structure; handlers and connections stay outside."""
from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from lingshu_gate.models import ToolDefinition

MAX_SCHEMA_BYTES = 128 * 1024
MAX_SCHEMA_NODES = 10_000
MAX_SCHEMA_DEPTH = 64
MAX_METADATA_BYTES = 256 * 1024
MAX_TOOL_STRUCTURE_BYTES = 512 * 1024


def checked_json_size(value: Any, *, max_bytes: int = MAX_SCHEMA_BYTES,
                      max_nodes: int = MAX_SCHEMA_NODES, max_depth: int = MAX_SCHEMA_DEPTH) -> int:
    """Bound every traversal before copying or complete JSON serialization."""
    return _walk_json(value, max_bytes=max_bytes, max_nodes=max_nodes, max_depth=max_depth, freeze=False)[0]


def _walk_json(value: Any, *, max_bytes: int, max_nodes: int, max_depth: int, freeze: bool) -> tuple[int, Any]:
    nodes = size = 0

    def visit(item: Any, depth: int) -> Any:
        nonlocal nodes, size
        nodes += 1
        if nodes > max_nodes or depth > max_depth:
            raise ValueError("tool_structure_complexity_limit")
        if isinstance(item, dict):
            size += 2 + len(item) + max(0, len(item) - 1)
        elif isinstance(item, list):
            size += 2 + max(0, len(item) - 1)
        elif isinstance(item, str):
            if len(item) > max_bytes:
                raise ValueError("tool_structure_size_limit")
            size += 2
            for character in item:
                code = ord(character)
                if character in {'"', "\\", "\b", "\t", "\n", "\f", "\r"}:
                    size += 2
                elif code < 32:
                    size += 6
                elif 0xD800 <= code <= 0xDFFF:
                    raise ValueError("tool_structure_non_json")
                else:
                    size += 1 if code < 128 else 2 if code < 2048 else 3 if code < 65536 else 4
                if size > max_bytes:
                    raise ValueError("tool_structure_size_limit")
        elif item is None or isinstance(item, bool):
            size += 4 if item is None or item else 5
        elif isinstance(item, int):
            if item.bit_length() > max_bytes * 4:
                raise ValueError("tool_structure_size_limit")
            size += len(str(item))
        elif isinstance(item, float) and math.isfinite(item):
            size += len(repr(item))
        else:
            raise ValueError("tool_structure_non_json")
        if size > max_bytes:
            raise ValueError("tool_structure_size_limit")
        if isinstance(item, dict):
            children: dict[str, Any] | None = {} if freeze else None
            for key, child in item.items():
                if not isinstance(key, str):
                    raise ValueError("tool_structure_non_json")
                visit(key, depth + 1)
                result = visit(child, depth + 1)
                if children is not None:
                    children[key] = result
            return MappingProxyType(children) if children is not None else None
        elif isinstance(item, list):
            items: list[Any] | None = [] if freeze else None
            for child in item:
                result = visit(child, depth + 1)
                if items is not None:
                    items.append(result)
            return tuple(items) if items is not None else None
        return item if freeze else None

    result = visit(value, 0)
    return size, result


def check_tool_structure(data: dict[str, Any]) -> int:
    if not isinstance(data["input_schema"], dict) or not isinstance(data["metadata"], dict):
        raise ValueError("tool_structure_non_object")
    checked_json_size(data["input_schema"])
    metadata = data["metadata"]
    if "outputSchema" in metadata:
        if not isinstance(metadata["outputSchema"], dict):
            raise ValueError("tool_output_schema_non_object")
        checked_json_size(metadata["outputSchema"])
    checked_json_size(metadata, max_bytes=MAX_METADATA_BYTES, max_nodes=MAX_SCHEMA_NODES * 2,
                      max_depth=MAX_SCHEMA_DEPTH + 1)
    return checked_json_size(data, max_bytes=MAX_TOOL_STRUCTURE_BYTES, max_nodes=MAX_SCHEMA_NODES * 3,
                             max_depth=MAX_SCHEMA_DEPTH + 2)


def _freeze_json(value: Any, *, max_bytes: int, max_nodes: int, max_depth: int) -> tuple[int, Any]:
    # Keep the copy traversal bounded too if the caller mutates between checks.
    return _walk_json(value, max_bytes=max_bytes, max_nodes=max_nodes, max_depth=max_depth, freeze=True)


def _copy_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _copy_json(child) for key, child in value.items()}
    if isinstance(value, tuple):
        return [_copy_json(child) for child in value]
    return value


@dataclass(frozen=True, eq=False, slots=True)
class FrozenToolDefinition:
    id: str
    name: str
    description: str
    permission: str
    source: str
    input_schema: Mapping[str, Any]
    metadata: Mapping[str, Any]
    byte_count: int

    def copy_definition(self) -> ToolDefinition:
        return ToolDefinition(id=self.id, name=self.name, description=self.description, permission=self.permission,
                              source=self.source, input_schema=_copy_json(self.input_schema), metadata=_copy_json(self.metadata))


def freeze_tool_definition(definition: ToolDefinition) -> FrozenToolDefinition:
    # Build only a shallow field envelope until every nested value passes budget.
    data: dict[str, Any] = {"id": definition.id, "name": definition.name, "description": definition.description,
            "permission": definition.permission, "source": definition.source,
            "input_schema": definition.input_schema, "metadata": definition.metadata}
    check_tool_structure(data)
    input_bytes, input_schema = _freeze_json(data["input_schema"], max_bytes=MAX_SCHEMA_BYTES,
        max_nodes=MAX_SCHEMA_NODES, max_depth=MAX_SCHEMA_DEPTH)
    metadata_bytes, metadata = _freeze_json(data["metadata"], max_bytes=MAX_METADATA_BYTES,
        max_nodes=MAX_SCHEMA_NODES * 2, max_depth=MAX_SCHEMA_DEPTH + 1)
    headers = {**data, "input_schema": None, "metadata": None}
    byte_count = checked_json_size(headers, max_bytes=MAX_TOOL_STRUCTURE_BYTES) + input_bytes + metadata_bytes - 8
    if byte_count > MAX_TOOL_STRUCTURE_BYTES:
        raise ValueError("tool_structure_size_limit")
    return FrozenToolDefinition(data["id"], data["name"], data["description"], data["permission"],
                                data["source"], input_schema, metadata, byte_count)

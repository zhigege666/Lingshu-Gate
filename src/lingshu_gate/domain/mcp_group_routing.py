"""Logical routing envelopes are independent of downstream tool arguments."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictStr
from lingshu_gate.mcp_manifest import MCP_SERVER_ID_PATTERN

TOOL_REF_PATTERN = r"^mcp-group:[a-f0-9]{32}:[a-f0-9]{64}$"
INSTANCE_ID_PATTERN = MCP_SERVER_ID_PATTERN


class GroupToolSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool_ref: StrictStr = Field(pattern=TOOL_REF_PATTERN)
    instance_id: StrictStr = Field(pattern=INSTANCE_ID_PATTERN)


class GroupToolCall(GroupToolSelection):
    session_id: StrictStr = Field(pattern=r"^[a-f0-9]{32}$")
    arguments: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CatalogTarget:
    service_id: str
    group_id: str
    group_revision: int
    tool_ref: str
    instance_id: str
    server_id: str
    tool_id: str
    schema_revision: str
    definition_fingerprint: str


def logical_service_id(group_id: str) -> str:
    return f"mcp-group:{group_id}"


def logical_tool_ref(group_id: str, variant_id: str) -> str:
    return f"{logical_service_id(group_id)}:{variant_id}"

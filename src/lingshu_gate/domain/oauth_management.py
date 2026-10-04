"""Closed OAuth resource/tool policies; discovery never supplies authority."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

BUSINESS_SCOPES = frozenset({"tools.read", "tools.invoke"})
MANAGEMENT_SCOPES = frozenset({"operations.manage", "tools.invoke"})
MANAGEMENT_TOOL_IDS = frozenset({"gate_mcp_config_plan", "gate_mcp_config_apply",
                                "gate_mcp_config_status", "gate_mcp_config_cancel"})
MANAGEMENT_READ_TOOLS = frozenset({"gate_mcp_config_plan", "gate_mcp_config_status"})
MANAGEMENT_PATH = "/mcp/manage"
MANAGEMENT_METADATA_PATH = "/.well-known/oauth-protected-resource/mcp/manage"
TARGET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
MAX_MANAGEMENT_TARGETS = 1000


def management_resource(business_resource: str) -> str:
    if not business_resource:
        return ""
    parsed = urlsplit(business_resource)
    return urlunsplit((parsed.scheme, parsed.netloc, MANAGEMENT_PATH, "", ""))


def management_tool_snapshot(tool: Any) -> str:
    payload = tool.model_dump(mode="json")
    payload["metadata"].pop("gate_access", None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def normalize_management_targets(value: Any, *, allow_empty: bool = False) -> dict[str, list[str]]:
    if not isinstance(value, dict) or not (0 if allow_empty else 1) <= len(value) <= MAX_MANAGEMENT_TARGETS:
        raise ValueError("invalid_management_targets")
    result = {}
    for target, actions in value.items():
        if (not isinstance(target, str) or not TARGET_ID.fullmatch(target) or not isinstance(actions, list)
                or not actions or any(not isinstance(action, str) or action not in {"create", "update"} for action in actions)
                or len(actions) != len(set(actions))):
            raise ValueError("invalid_management_targets")
        result[target] = sorted(actions)
    return dict(sorted(result.items()))

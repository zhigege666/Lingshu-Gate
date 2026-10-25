"""Closed OAuth resource/tool policies; discovery never supplies authority."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

BUSINESS_SCOPES = frozenset({"tools.read", "tools.invoke"})
MANAGEMENT_SCOPES = frozenset({"operations.manage", "tools.invoke", "credentials.manage.system"})
# Keep the original four definitions and their consent fingerprints unchanged.
# A new entry in this allowlist is only eligible for a new, explicit consent;
# existing grants/families still carry their original scopes and snapshots.
LEGACY_MANAGEMENT_TOOL_IDS = frozenset({"gate_mcp_config_plan", "gate_mcp_config_apply",
                                       "gate_mcp_config_status", "gate_mcp_config_cancel"})
HTTP_MANAGEMENT_TOOL_IDS = frozenset({"gate_http_mcp_test", "gate_http_mcp_plan", "gate_http_mcp_apply",
                                     "gate_http_mcp_status", "gate_http_mcp_cancel"})
CREDENTIAL_MANAGEMENT_TOOL_IDS = frozenset({"gate_credential_list", "gate_credential_get",
    "gate_credential_create", "gate_credential_update", "gate_credential_delete"})
CONFIGURATION_MANAGEMENT_TOOL_IDS = LEGACY_MANAGEMENT_TOOL_IDS | HTTP_MANAGEMENT_TOOL_IDS
MANAGEMENT_TOOL_IDS = CONFIGURATION_MANAGEMENT_TOOL_IDS | CREDENTIAL_MANAGEMENT_TOOL_IDS
MANAGEMENT_READ_TOOLS = frozenset({"gate_mcp_config_plan", "gate_mcp_config_status",
    "gate_http_mcp_plan", "gate_http_mcp_status", "gate_credential_list", "gate_credential_get"})
HTTP_MANAGEMENT_ACTIONS = frozenset({"create", "update", "delete", "revoke_trust", "restore_trust"})
CREDENTIAL_MANAGEMENT_ACTIONS = frozenset({"credential.read", "credential.create", "credential.update", "credential.delete"})
MANAGEMENT_ACTIONS = HTTP_MANAGEMENT_ACTIONS | CREDENTIAL_MANAGEMENT_ACTIONS | {"test"}
MANAGEMENT_PATH = "/mcp/manage"
MANAGEMENT_METADATA_PATH = "/.well-known/oauth-protected-resource/mcp/manage"
TARGET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
MAX_MANAGEMENT_TARGETS = 1000


def management_tool_server(tool_id: str) -> str:
    return "gate_credentials" if tool_id in CREDENTIAL_MANAGEMENT_TOOL_IDS else "gate_mcp_configuration"


def management_tool_permissions(tool_id: str) -> frozenset[str]:
    return frozenset({"operations.manage", "credentials.manage.system"}) if tool_id in CREDENTIAL_MANAGEMENT_TOOL_IDS else frozenset({"operations.manage"})


def management_tool_actions(tool_id: str) -> frozenset[str]:
    if tool_id == "gate_http_mcp_test":
        return frozenset({"test"})
    if tool_id in CREDENTIAL_MANAGEMENT_TOOL_IDS:
        return CREDENTIAL_MANAGEMENT_ACTIONS
    if tool_id in HTTP_MANAGEMENT_TOOL_IDS:
        return HTTP_MANAGEMENT_ACTIONS
    return frozenset({"create", "update"})


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
                or not actions or any(not isinstance(action, str) or action not in MANAGEMENT_ACTIONS for action in actions)
                or len(actions) != len(set(actions))):
            raise ValueError("invalid_management_targets")
        result[target] = sorted(actions)
    return dict(sorted(result.items()))

"""Trusted local access policy, independent of upstream hints and review status."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any


def policy_snapshot(server_id: str, tool_id: str, access: str, binding: str = "", revision: int = 1) -> str:
    """An exact grant binds an identity and access level, not display metadata.

    Service lifecycle and local policy revisions prevent retired grants from
    reviving; the service binding is also independently checked at every use.
    The schema revision is still checked by describe/invoke and final dispatch.
    """
    value = json.dumps([server_id, tool_id, access, binding, revision], separators=(",", ":"))
    return "access-v1:" + hashlib.sha256(value.encode()).hexdigest()


def legacy_snapshot(row: Mapping[str, Any]) -> str:
    value = [row["fingerprint"], row["effective_access"], row["reviewed_at"]]
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def effective_policy(definition: Any, classification: Mapping[str, Any] | None) -> tuple[str, str]:
    """Only Gate-owned contracts or saved local policy can lower write access.

    Upstream permission strings, tool names and annotations are deliberately
    absent. ``permissions.default`` in a Manifest remains a declaration.
    """
    row = classification or {}
    source = row.get("access_policy_source")
    access = row.get("required_access")
    if source == "unavailable":
        return "none", "unavailable"
    if source == "local_override":
        if access in {"none", "read", "write"}:
            return str(access), "local_override"
        return "none", "local_override"
    if definition.source == "builtin":
        return ("read" if definition.permission.startswith("read") else "write"), "builtin_contract"
    return "write", "default_write"


def policy_status(source: str, access: str) -> str:
    if access == "none":
        return "disabled"
    return {"local_override": "configured", "builtin_contract": "builtin",
            "control_permission": "control_plane"}.get(source, "automatic")

"""Bounded, short-lived pure-text result previews for one authenticated credential."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from mcp.types import Implementation
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lingshu_gate.access_control import AccessControlStore, AccessDeniedError
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.authorization_discovery import discovery_setting, principal_authorization
from lingshu_gate.domain.mcp_group_routing import CatalogTarget, GroupToolCall
from lingshu_gate.domain.mcp_groups import McpGroupError
from lingshu_gate.protocol.sdk_adapter import SERVER_INFO_META_KEY
from lingshu_gate.registry import ToolExecutionError, ToolNotFoundError, ToolRegistry, tool_definition_revision
from lingshu_gate.tool_catalog import ToolCatalog, _same_invocation_principal

RESULT_TOOL = "gate_result_read"
META_KEY = "lingshu_gate/result_budget"


def _plain_text_envelope(result: dict[str, Any]) -> bool:
    if (set(result) - {"content", "isError", "resultType", "_meta"}
            or result.get("isError") is not False or result.get("resultType", "complete") != "complete"):
        return False
    if "_meta" not in result:
        return True
    metadata = result["_meta"]
    if (not isinstance(metadata, dict) or set(metadata) != {SERVER_INFO_META_KEY}
            or not isinstance(metadata[SERVER_INFO_META_KEY], dict)):
        return False
    try:
        Implementation.model_validate(metadata[SERVER_INFO_META_KEY], strict=True, extra="forbid", by_alias=True, by_name=False)
    except ValidationError:
        return False
    return True


class ResultRead(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    result_ref: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=8192, ge=1, le=65536)


def result_read_tool() -> dict[str, Any]:
    output = {"type": "object", "properties": {
        "schema_version": {"type": "integer", "const": 1}, "text": {"type": "string"},
        "offset": {"type": "integer"}, "next_offset": {"type": "integer"}, "has_more": {"type": "boolean"},
        "original_characters": {"type": "integer"}, "expires_at": {"type": "string"}},
        "required": ["schema_version", "text", "offset", "next_offset", "has_more", "original_characters", "expires_at"],
        "additionalProperties": False}
    return {"name": RESULT_TOOL, "title": "Read a saved result page",
            "description": "Read an exact text slice from this credential's five-minute result cache. Never executes the original tool.",
            "inputSchema": ResultRead.model_json_schema(), "outputSchema": output,
            "annotations": {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}}


@dataclass(frozen=True)
class ResultTarget:
    tool_id: str
    revision: str
    has_output_schema: bool
    group: CatalogTarget | None = None
    session_id: str | None = None


@dataclass(frozen=True)
class CachedResult:
    identity: str
    text: str
    byte_count: int
    deadline: float
    expires_at: str
    target: ResultTarget
    settings_revision: int


class ResultCache:
    def __init__(self, registry: ToolRegistry, access: AccessControlStore, catalog: ToolCatalog | None, *,
                 total_bytes: int = 64 * 1024 * 1024, identity_bytes: int = 8 * 1024 * 1024,
                 entry_bytes: int = 4 * 1024 * 1024, identity_entries: int = 16, ttl: int = 300) -> None:
        self.registry, self.access, self.catalog = registry, access, catalog
        self.total_bytes, self.identity_bytes, self.entry_bytes = total_bytes, identity_bytes, entry_bytes
        self.identity_entries, self.ttl = identity_entries, ttl
        self._key = secrets.token_bytes(32)
        self._lock = threading.RLock()
        self._entries: dict[str, CachedResult] = {}
        self._total = 0

    def identity(self, principal: AuthPrincipal, bearer_proof: str) -> str:
        authorization = principal_authorization(principal)
        if not authorization:
            raise self.unavailable()
        proof = ""
        if principal.auth_type == "oauth" and not principal.oauth_builtin:
            if not bearer_proof:
                raise self.unavailable()
            proof = hmac.new(self._key, bearer_proof.encode(), hashlib.sha256).hexdigest()
        value = [principal.id, principal.auth_type, authorization, principal.token_id,
                 principal.oauth_family_id, principal.oauth_issuer, principal.oauth_client_id,
                 principal.oauth_subject, proof]
        return hmac.new(self._key, json.dumps(value, separators=(",", ":")).encode(), hashlib.sha256).hexdigest()

    @staticmethod
    def unavailable() -> ToolExecutionError:
        return ToolExecutionError("result_unavailable", "The saved result is unavailable.", next_action="Inspect current authorization and use an existing result; no tool was replayed.")

    def setting(self, principal: AuthPrincipal) -> dict[str, Any]:
        authorization = principal_authorization(principal)
        if not authorization:
            raise self.unavailable()
        with self.access.database.session() as connection:
            return discovery_setting(connection, *authorization)

    def capture(self, principal: AuthPrincipal, tool_ref: str, *, instance_id: str | None = None,
                session_id: str | None = None, revision: str | None = None) -> ResultTarget | None:
        try:
            group = None
            tool_id = tool_ref
            if tool_ref.startswith("mcp-group:"):
                if not (self.catalog and self.catalog.group_router and instance_id and session_id):
                    return None
                group = self.catalog.group_router.resolve(principal, tool_ref=tool_ref, instance_id=instance_id)
                tool_id = group.tool_id
            definition = self.registry.get_definition(tool_id)
            actual = tool_definition_revision(definition)
            if revision is not None and revision != (group.schema_revision if group else actual):
                return None
            return ResultTarget(tool_id, actual, "outputSchema" in definition.metadata or "output_schema" in definition.metadata, group, session_id)
        except (ToolNotFoundError, ToolExecutionError, McpGroupError, AccessDeniedError):
            return None

    def validate_target(self, principal: AuthPrincipal, target: ResultTarget) -> bool:
        try:
            definition = self.registry.get_definition(target.tool_id)
            if tool_definition_revision(definition) != target.revision:
                return False
            with self.access.database.session() as connection:
                if not self.access.visible_tool_contracts(principal, [definition], connection=connection):
                    return False
            if target.group:
                if not (self.catalog and self.catalog.group_router and target.session_id):
                    return False
                call = GroupToolCall(tool_ref=target.group.tool_ref, instance_id=target.group.instance_id,
                                     session_id=target.session_id, arguments={})
                with self.catalog.group_router.dispatch_guard(principal, call) as (_, current):
                    return current == target.group
            return True
        except (ToolNotFoundError, ToolExecutionError, McpGroupError, AccessDeniedError):
            return False

    def _prune(self) -> None:
        now = time.monotonic()
        for reference in [key for key, value in self._entries.items() if value.deadline <= now]:
            self._total -= self._entries.pop(reference).byte_count

    def apply(self, result: dict[str, Any], principal: AuthPrincipal, proof: str,
              target: ResultTarget | None, *, refresh_principal: Callable[[], AuthPrincipal] | None = None) -> dict[str, Any]:
        if target is None or target.has_output_schema or not _plain_text_envelope(result):
            return result
        content = result.get("content")
        if (not isinstance(content, list) or len(content) != 1 or not isinstance(content[0], dict)
                or set(content[0]) != {"type", "text"} or content[0]["type"] != "text" or not isinstance(content[0]["text"], str)):
            return result
        setting = self.setting(principal)
        budget = setting["result_budget"]
        text = content[0]["text"]
        if not budget["enabled"] or len(text) <= budget["max_characters"] or not self.validate_target(principal, target):
            return result
        # Target checks can wait on configuration/runtime locks. Re-read after
        # that wait so a disabled or changed budget never creates a stale ref.
        current = refresh_principal() if refresh_principal else principal
        latest = self.setting(current)
        if (not _same_invocation_principal(current, principal) or latest["discovery_revision"] != setting["discovery_revision"]
                or not latest["result_budget"]["enabled"]):
            return result
        identity = self.identity(principal, proof)
        byte_count = len(text.encode("utf-8"))
        with self._lock:
            self._prune()
            owned = [entry for entry in self._entries.values() if entry.identity == identity]
            if (byte_count > self.entry_bytes or self._total + byte_count > self.total_bytes
                    or sum(entry.byte_count for entry in owned) + byte_count > self.identity_bytes or len(owned) >= self.identity_entries):
                return {**result, "_meta": {**result.get("_meta", {}),
                    META_KEY: {"schema_version": 1, "applied": False, "reason": "capacity"}}}
            reference = secrets.token_urlsafe(32)
            expires = (datetime.now(timezone.utc) + timedelta(seconds=self.ttl)).isoformat()
            self._entries[reference] = CachedResult(identity, text, byte_count, time.monotonic() + self.ttl, expires,
                                                     target, setting["discovery_revision"])
            self._total += byte_count
        note = f"\n[Gate text preview. Retrieve the original with gate_result_read, result_ref={reference}. Expires in five minutes.]"
        preview = text[:max(1, budget["max_characters"] - len(note))]
        return {**result, "content": [{"type": "text", "text": preview + note}],
                "_meta": {**result.get("_meta", {}), META_KEY: {"schema_version": 1, "applied": True, "truncated": True,
                    "original_characters": len(text), "preview_characters": len(preview), "result_ref": reference, "expires_at": expires}}}

    def read(self, principal: AuthPrincipal, proof: str, query: ResultRead, *,
             refresh_principal: Callable[[], AuthPrincipal] | None = None) -> dict[str, Any]:
        identity = self.identity(principal, proof)
        setting = self.setting(principal)
        with self._lock:
            self._prune()
            entry = self._entries.get(query.result_ref)
        if (entry is None or entry.identity != identity or not setting["result_budget"]["enabled"]
                or entry.settings_revision != setting["discovery_revision"] or not self.validate_target(principal, entry.target)):
            raise self.unavailable()
        current = refresh_principal() if refresh_principal else principal
        latest = self.setting(current)
        if (not _same_invocation_principal(current, principal) or not latest["result_budget"]["enabled"]
                or entry.settings_revision != latest["discovery_revision"]):
            raise self.unavailable()
        with self._lock:
            self._prune()
            if self._entries.get(query.result_ref) is not entry or entry.deadline <= time.monotonic():
                raise self.unavailable()
        if query.offset > len(entry.text):
            raise ToolExecutionError("result_parameters_invalid", "The requested offset is outside the saved text.")
        end = min(len(entry.text), query.offset + query.limit)
        value = {"schema_version": 1, "text": entry.text[query.offset:end], "offset": query.offset,
                 "next_offset": end, "has_more": end < len(entry.text), "original_characters": len(entry.text), "expires_at": entry.expires_at}
        return {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False, separators=(",", ":"))}],
                "structuredContent": value, "isError": False}

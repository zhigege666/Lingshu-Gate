"""Bounded, permission-first tool discovery over an incremental SQLite index."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, replace
from contextlib import contextmanager
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lingshu_gate.access_control import AccessControlStore, AccessDeniedError
from lingshu_gate.application.mcp_group_routing import McpGroupRoutingService
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.application.schema_validation import validate_arguments as _validate_arguments
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.domain.mcp_group_routing import GroupToolCall, GroupToolSelection
from lingshu_gate.domain.mcp_groups import McpGroupError
from lingshu_gate.models import ToolDefinition, ToolInvokeResponse
from lingshu_gate.protocol.tool_namespace import public_tool_name
from lingshu_gate.ports.catalog_target import CatalogTarget, CatalogTargetResolver
from lingshu_gate.registry import ToolExecutionError, ToolNotFoundError, ToolRegistry

CATALOG_TOOL_NAMES = ("gate_catalog_search", "gate_tool_describe", "gate_tool_invoke", "gate_instance_list",
                      "gate_instance_session_open", "gate_instance_session_close")
MAX_PAGE_OFFSET = 10_000
CURSOR_TTL_SECONDS = 300
MAX_INVOKE_ARGUMENT_BYTES = 1_048_576


def _same_invocation_principal(left: AuthPrincipal, right: AuthPrincipal) -> bool:
    """Compare proof/ceilings exactly, treating authority collections as sets."""
    def normalized(actor: AuthPrincipal) -> AuthPrincipal | None:
        roles = tuple(sorted(set(actor.roles or (actor.role,))))
        if actor.role not in roles:
            return None  # A primary role must not introduce authority absent from roles.
        return replace(actor, role="admin" if "admin" in roles else roles[0], roles=roles,
            permissions=tuple(sorted(set(actor.permissions))), scopes=tuple(sorted(set(actor.scopes))),
            delegated_scopes=None if actor.delegated_scopes is None else tuple(sorted(set(actor.delegated_scopes))),
            external_server_ids=tuple(sorted(set(actor.external_server_ids))),
            external_tool_ids=tuple(sorted(set(actor.external_tool_ids))),
            external_access=tuple(sorted(set(actor.external_access))),
            oauth_audiences=tuple(sorted(set(actor.oauth_audiences))),
            oauth_tool_snapshots=tuple(sorted(set(actor.oauth_tool_snapshots))))
    original = normalized(left)
    return original is not None and original == normalized(right)


class CatalogSearch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(default="", max_length=256)
    instance_id: str | None = Field(default=None, min_length=1, max_length=256)
    group_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    tool_ref: str | None = Field(default=None, min_length=1, max_length=512)
    limit: int = Field(default=20, ge=1, le=100)
    max_bytes: int = Field(default=16_384, ge=2_048, le=65_536)
    cursor: str | None = Field(default=None, max_length=1_024)


class CatalogDescribe(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tool_ref: str = Field(min_length=1, max_length=512)
    instance_id: str | None = Field(default=None, min_length=1, max_length=256)
    max_bytes: int = Field(default=65_536, ge=2_048, le=131_072)


class CatalogInvoke(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    tool_ref: str = Field(min_length=1, max_length=512)
    instance_id: str | None = Field(default=None, min_length=1, max_length=256)
    schema_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    session_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    arguments: dict[str, Any]


class CatalogSessionOpen(GroupToolSelection):
    schema_revision: str = Field(pattern=r"^[0-9a-f]{64}$")


class CatalogSessionClose(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    session_id: str = Field(pattern=r"^[a-f0-9]{32}$")


def schema_revision(definition: ToolDefinition) -> str:
    """Bind both schema and routing/policy metadata, not just the tool name."""
    return hashlib.sha256(_json(definition.model_dump()).encode()).hexdigest()


def instance_for(definition: ToolDefinition) -> str:
    """Current instance adapter; logical grouping can be added independently."""
    return str(definition.metadata.get("server_id") or definition.source or "builtin")


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _reject(code: str, message: str) -> ToolExecutionError:
    return ToolExecutionError(code, message, next_action="Search again and describe the selected tool before retrying.")


class ToolCatalog:
    def __init__(self, registry: ToolRegistry, access: AccessControlStore, *,
                 target_resolver: CatalogTargetResolver | None = None,
                 group_router: McpGroupRoutingService | None = None) -> None:
        self.registry = registry
        self.access = access
        self.database = access.database
        self.target_resolver = target_resolver or RegistryCatalogTargetResolver(registry)
        self.group_router = group_router
        self._queue_lock = threading.Lock()
        self._sync_lock = threading.Lock()
        self._pending: dict[str, ToolDefinition | None] = {}
        self._retired: set[str] = set()
        self._reserved: set[str] = set()
        self._generation = 0
        self._secret = secrets.token_bytes(32)
        self._initial = True
        registry.subscribe_catalog(self._enqueue)

    def _enqueue(self, changes: dict[str, ToolDefinition | None]) -> None:
        with self._queue_lock:
            self._pending.update(changes)
            self._retired.update(key for key, definition in changes.items() if definition is None)
            for key, definition in changes.items():
                self._reserved.discard(key)
                if definition is not None and public_tool_name(definition) in CATALOG_TOOL_NAMES:
                    self._reserved.add(key)
            self._generation += 1

    def synchronize(self) -> int:
        """Drain coalesced deltas once, including initial/restart reconciliation."""
        with self._sync_lock:
            with self._queue_lock:
                changes, self._pending = self._pending, {}
                retired, self._retired = self._retired, set()
                generation = self._generation
            if not changes and not self._initial:
                return generation
            try:
                with self.database.session() as connection:
                    if self._initial:
                        connection.execute("DELETE FROM gate_tool_catalog")
                    for tool_ref in retired:
                        connection.execute("""UPDATE mcp_tool_classifications
                            SET status='stale',effective_access='unknown' WHERE tool_id=?""", (tool_ref,))
                    definitions = [item for item in changes.values() if item is not None]
                    self.access._synchronize_tools(connection, definitions)
                    for tool_ref, definition in changes.items():
                        if definition is None:
                            connection.execute("DELETE FROM gate_tool_catalog WHERE tool_ref=?", (tool_ref,))
                            continue
                        policy = {key: definition.metadata[key] for key in
                                  ("required_control_permission", "classification_control_plane", "group_management_control_plane")
                                  if key in definition.metadata}
                        connection.execute("""
                            INSERT INTO gate_tool_catalog
                                (tool_ref,instance_id,name,description,source,permission,policy_json,schema_revision)
                            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(tool_ref) DO UPDATE SET
                                instance_id=excluded.instance_id,name=excluded.name,description=excluded.description,
                                source=excluded.source,permission=excluded.permission,policy_json=excluded.policy_json,
                                schema_revision=excluded.schema_revision
                            WHERE gate_tool_catalog.schema_revision!=excluded.schema_revision
                        """, (tool_ref, instance_for(definition), definition.name[:128], definition.description[:320],
                              definition.source, definition.permission, _json(policy), schema_revision(definition)))
                self._initial = False
            except BaseException:
                with self._queue_lock:
                    self._pending = {**changes, **self._pending}
                    self._retired.update(retired)
                raise
            return generation

    def _epoch(self) -> int:
        row = self.database.query_one("SELECT policy FROM gate_catalog_epochs WHERE id=1")
        assert row is not None
        return int(row[0])

    def revision_marker(self, connection: sqlite3.Connection) -> tuple[int, int]:
        """Read shared index/policy revisions in the caller's SQL snapshot."""
        with self._queue_lock:
            generation = self._generation
        row = connection.execute("SELECT policy FROM gate_catalog_epochs WHERE id=1").fetchone()
        assert row is not None
        return generation, int(row[0])

    def _binding(self, principal: AuthPrincipal, request: CatalogSearch, kind: str, generation: int, epoch: int) -> str:
        payload = [asdict(principal), request.model_dump(exclude={"cursor"}), kind, generation, epoch]
        return hmac.new(self._secret, _json(payload).encode(), hashlib.sha256).hexdigest()

    def _cursor(self, offset: int, binding: str) -> str:
        if offset > MAX_PAGE_OFFSET:
            raise _reject("catalog_page_limit", "Refine the search to continue within the page limit.")
        raw = _json({"offset": offset, "binding": binding, "expires": int(time.time()) + CURSOR_TTL_SECONDS}).encode()
        signed = hmac.new(self._secret, raw, hashlib.sha256).digest() + raw
        return base64.urlsafe_b64encode(signed).decode().rstrip("=")

    def _offset(self, cursor: str | None, binding: str) -> int:
        if cursor is None:
            return 0
        try:
            signed = base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True)
            signature, raw = signed[:32], signed[32:]
            payload = json.loads(raw)
            if not hmac.compare_digest(signature, hmac.new(self._secret, raw, hashlib.sha256).digest()):
                raise ValueError
            offset = payload["offset"]
            if (payload["binding"] != binding or payload["expires"] <= time.time()
                    or type(offset) is not int or not 0 <= offset <= MAX_PAGE_OFFSET):
                raise ValueError
            return offset
        except (ValueError, KeyError, TypeError):
            raise _reject("catalog_cursor_invalid", "The cursor expired or its catalog, identity, permissions or query changed.") from None

    def search(self, principal: AuthPrincipal, request: CatalogSearch, *, instances: bool = False) -> dict[str, Any]:
        generation = self.synchronize()
        epoch = self._epoch()
        kind = "instances" if instances else "tools"
        terms = re.findall(r"[^\W_]+", request.query.casefold(), re.UNICODE)
        if len(terms) > 8 or len(request.query.encode()) > 1_024:
            raise _reject("catalog_query_limit", "Use at most eight keywords and 256 characters.")
        if request.query.strip() and not terms:
            raise _reject("catalog_query_invalid", "Use at least one keyword.")
        if request.group_id is not None:
            router = self._groups()
            marker = router.directory_revision(request.group_id)
            binding = self._binding(principal, request, kind + _json(marker), generation, epoch)
            offset = self._offset(request.cursor, binding)
            items = router.directory_page(principal, group_id=request.group_id, keywords=terms,
                tool_ref=request.tool_ref, instance_id=request.instance_id, offset=offset,
                limit=request.limit + 1, instances=instances)
            output = self._page(items, request, kind, offset, binding)
            if marker != router.directory_revision(request.group_id):
                raise _reject("catalog_changed", "Service or instance configuration changed during search.")
            if generation != self._generation or epoch != self._epoch():
                raise _reject("catalog_changed", "Catalog or permissions changed during search.")
            return output
        if request.tool_ref is not None:
            raise _reject("catalog_parameters_invalid", "tool_ref filtering requires an explicit group_id.")
        binding = self._binding(principal, request, kind, generation, epoch)
        offset = self._offset(request.cursor, binding)
        where: list[str] = []
        parameters: list[Any] = []
        if terms:
            where.append("c.rowid IN (SELECT rowid FROM gate_tool_catalog_fts WHERE gate_tool_catalog_fts MATCH ?)")
            parameters.append(" AND ".join('"' + term + '"*' for term in terms))
        if request.instance_id:
            where.append("c.instance_id=?")
            parameters.append(request.instance_id)
        where.append("gate_catalog_allowed(c.tool_ref,c.instance_id,c.source,c.permission,c.policy_json,p.effective_access,p.status)=1")
        # MATERIALIZED makes authorization happen before ordering and pagination.
        # Ranking uses local lexical fields; hidden FTS document frequencies never
        # influence a visible tool's score, count or recommendations.
        query = """WITH allowed AS MATERIALIZED (
            SELECT c.* FROM gate_tool_catalog c LEFT JOIN mcp_tool_classifications p
            ON p.server_id=c.instance_id AND p.tool_id=c.tool_ref WHERE """ + " AND ".join(where) + ") "
        if instances:
            query += "SELECT DISTINCT instance_id FROM allowed ORDER BY instance_id LIMIT ? OFFSET ?"
        else:
            query += """SELECT tool_ref,instance_id,name,description,schema_revision FROM allowed
                ORDER BY CASE WHEN lower(name)=? OR lower(tool_ref)=? THEN 0
                    WHEN instr(lower(name),?)=1 THEN 1 ELSE 2 END,tool_ref LIMIT ? OFFSET ?"""
            parameters.extend([request.query.casefold()] * 3)
        parameters.extend([request.limit + 1, offset])
        with self.database.session() as connection:
            connection.execute("BEGIN")
            connection.create_function("gate_catalog_allowed", 7, self.access.catalog_authorizer(connection, principal))
            rows = connection.execute(query, tuple(parameters)).fetchall()
        items = ([{"instance_id": row["instance_id"], "group_id": None} for row in rows]
                 if instances else [dict(row) for row in rows])
        output = self._page(items, request, kind, offset, binding)
        if generation != self._generation or epoch != self._epoch():
            raise _reject("catalog_changed", "Catalog or permissions changed during search.")
        return output

    def _page(self, items: list[dict[str, Any]], request: CatalogSearch, kind: str,
              offset: int, binding: str) -> dict[str, Any]:
        # Fetch at most limit+1 authorized summaries; never serialize a directory.
        selected = items[:request.limit]
        while True:
            has_more = len(items) > len(selected)
            cursor = self._cursor(offset + len(selected), binding) if has_more else None
            output = {kind: selected, "next_cursor": cursor, "has_more": has_more}
            if len(_json(output).encode()) <= request.max_bytes - 512:
                break
            selected = selected[:-1]
            if not selected:
                raise _reject("catalog_output_limit", "Increase max_bytes to fit a single summary.")
        return output

    def _groups(self) -> McpGroupRoutingService:
        if self.group_router is None:
            raise _reject("catalog_tool_unavailable", "The selected tool is unavailable.")
        return self.group_router

    def selected(self, principal: AuthPrincipal, tool_ref: str, instance_id: str | None = None) -> ToolDefinition:
        self.synchronize()
        try:
            target = self.target_resolver.resolve(tool_ref, instance_id)
            definition = self.registry.get_definition(target.tool_id)
            if target.server_id != instance_for(definition) or target.instance_id != target.server_id:
                raise _reject("catalog_instance_mismatch", "The resolved target does not identify the selected instance.")
        except ToolNotFoundError:
            raise _reject("catalog_tool_unavailable", "The selected tool is unavailable.") from None
        if (principal.oauth_resource and principal.oauth_resource.endswith("/mcp/manage")
                or not self.access.evaluate(principal, definition)["allowed"]):
            raise _reject("catalog_tool_unavailable", "The selected tool is unavailable.")
        return definition

    def describe(self, principal: AuthPrincipal, request: CatalogDescribe) -> dict[str, Any]:
        generation, epoch = self.synchronize(), self._epoch()
        if request.tool_ref.startswith("mcp-group:"):
            if request.instance_id is None:
                raise _reject("catalog_instance_required", "Select an explicit instance for this logical tool.")
            described = self._groups().describe(principal, tool_ref=request.tool_ref, instance_id=request.instance_id)
            definition = ToolDefinition.model_validate(described["definition"])
            revision = described["schema_revision"]
        else:
            definition = self.selected(principal, request.tool_ref, request.instance_id)
            revision = schema_revision(definition)
        output = {"tool_ref": request.tool_ref, "instance_id": instance_for(definition),
                  "schema_revision": revision, "name": definition.name,
                  "description": definition.description,
                  "input_schema": definition.input_schema if definition.input_schema is not None else {"type": "object"}}
        output_schema = definition.metadata.get("outputSchema", definition.metadata.get("output_schema"))
        if isinstance(output_schema, dict):
            output["output_schema"] = output_schema
        if len(_json(output).encode()) > request.max_bytes - 512:
            raise _reject("catalog_schema_limit", "The full schema exceeds max_bytes; it was not truncated.")
        if generation != self._generation or epoch != self._epoch():
            raise _reject("catalog_changed", "Catalog or permissions changed during describe.")
        return output

    def _audit_rejection(self, principal: AuthPrincipal, request: CatalogInvoke, correlation_id: str,
                         definition: ToolDefinition | None, reason: str) -> None:
        if definition is not None:
            self.access._record_invocation_audit(principal, definition, correlation_id=correlation_id,
                decision={**self.access.evaluate(principal, definition), "allowed": False, "reason": reason},
                outcome="not_invoked", duration_ms=None, payload={"values_recorded": False})
        else:
            ObservabilityStore(self.database).emit_event("gate.catalog.invocation_rejected", source="catalog",
                subject_type="user", subject_id=principal.id, payload={"correlation_id": correlation_id,
                    "reference_sha256": hashlib.sha256(request.tool_ref.encode()).hexdigest(), "reason": reason})

    @staticmethod
    def _checked_response(response: ToolInvokeResponse) -> ToolInvokeResponse:
        error = response.output.get("error") if isinstance(response.output, dict) else None
        if (not response.ok and isinstance(error, dict) and str(error.get("code", "")).startswith("catalog_")
                and error.get("code") != "catalog_identity_changed"):
            raise _reject(error["code"], error["message"])
        return response

    def check_namespace(self) -> None:
        with self._queue_lock:
            if self._reserved:
                raise _reject("catalog_namespace_conflict", "A reserved catalog entry name conflicts with a registered tool.")

    def invoke(self, principal: AuthPrincipal, request: CatalogInvoke, *,
               refresh_principal: Callable[[], AuthPrincipal] | None = None,
               correlation_id: str | None = None) -> ToolInvokeResponse:
        if request.tool_ref.startswith("mcp-group:"):
            return self._invoke_group(principal, request, refresh_principal=refresh_principal,
                                      correlation_id=correlation_id)
        correlation_id = correlation_id or secrets.token_hex(16)
        self.synchronize()
        try:
            definition = self.registry.get_definition(request.tool_ref)
        except ToolNotFoundError:
            self._audit_rejection(principal, request, correlation_id, None, "unavailable")
            raise _reject("catalog_tool_unavailable", "The selected tool is unavailable.") from None

        def validate() -> None:
            if (request.session_id is not None or request.instance_id is not None and request.instance_id != instance_for(definition)
                    or principal.oauth_resource and principal.oauth_resource.endswith("/mcp/manage")):
                raise _reject("catalog_tool_unavailable", "The selected tool is unavailable.")
            if schema_revision(definition) != request.schema_revision:
                raise _reject("catalog_schema_revision_conflict", "The selected tool definition changed; describe it again.")
            _validate_arguments(definition.input_schema if definition.input_schema is not None else {"type": "object"}, request.arguments)

        def guard() -> None:
            current = refresh_principal() if refresh_principal is not None else principal
            if not _same_invocation_principal(current, principal):
                raise _reject("catalog_identity_changed", "The invocation identity changed before dispatch.")
            # A runtime refresh may publish an equivalent new object; compare its
            # exact definition revision rather than relying on object identity.
            try:
                latest = self.registry.get_definition(definition.id)
            except ToolNotFoundError:
                raise _reject("catalog_tool_unavailable", "The selected tool is unavailable.") from None
            if schema_revision(latest) != request.schema_revision:
                raise _reject("catalog_schema_revision_conflict", "The selected tool definition changed before dispatch.")
            if not self.access.evaluate(current, latest)["allowed"]:
                raise _reject("catalog_tool_unavailable", "The selected tool is unavailable.")

        try:
            response = self.access.invoke_tool(self.registry, principal, definition.id, request.arguments,
                correlation_id=correlation_id, dispatch_guard=guard, arguments_validator=validate)
        except AccessDeniedError:
            raise _reject("catalog_tool_unavailable", "The selected tool is unavailable.") from None
        except ToolNotFoundError:
            self._audit_rejection(principal, request, correlation_id, definition, "unavailable")
            raise _reject("catalog_tool_unavailable", "The selected tool is unavailable.") from None
        return self._checked_response(response)

    def _invoke_group(self, principal: AuthPrincipal, request: CatalogInvoke, *,
                      refresh_principal: Callable[[], AuthPrincipal] | None,
                      correlation_id: str | None) -> ToolInvokeResponse:
        correlation_id = correlation_id or secrets.token_hex(16)
        try:
            if request.instance_id is None or request.session_id is None:
                raise _reject("catalog_tool_unavailable", "The selected tool is unavailable.")
            router = self._groups()
            target = router.resolve(principal, tool_ref=request.tool_ref, instance_id=request.instance_id)
            definition = self.registry.get_definition(target.tool_id)
        except (McpGroupError, ToolExecutionError, ToolNotFoundError):
            self._audit_rejection(principal, request, correlation_id, None, "unavailable")
            raise _reject("catalog_tool_unavailable", "The selected tool is unavailable.") from None
        call = GroupToolCall(tool_ref=request.tool_ref, instance_id=request.instance_id,
                             session_id=request.session_id, arguments=request.arguments)

        def validate() -> None:
            if request.schema_revision != target.schema_revision or schema_revision(definition) != target.definition_fingerprint:
                raise _reject("catalog_schema_revision_conflict", "The selected logical contract changed; describe it again.")
            _validate_arguments(definition.input_schema if definition.input_schema is not None else {"type": "object"}, request.arguments)

        @contextmanager
        def dispatch():
            try:
                with router.dispatch_guard(principal, call) as (current, latest):
                    if not _same_invocation_principal(current, principal) or latest != target:
                        raise _reject("catalog_tool_unavailable", "The selected tool is unavailable.")
                    yield
            except McpGroupError:
                raise _reject("catalog_tool_unavailable", "The selected tool is unavailable.") from None

        def guard() -> None:
            if refresh_principal is not None and not _same_invocation_principal(refresh_principal(), principal):
                raise _reject("catalog_tool_unavailable", "The selected tool is unavailable.")
            # Reuse the bounded selected-instance binding check at the actual
            # call boundary. A private client can initialize after the outer
            # context's check while close/expiry remains independent of its locks.
            try:
                with router.dispatch_guard(principal, call) as (current, latest):
                    if not _same_invocation_principal(current, principal):
                        raise _reject("catalog_tool_unavailable", "The selected tool is unavailable.")
                    if latest != target:
                        raise _reject("catalog_schema_revision_conflict", "The selected target changed before dispatch.")
            except McpGroupError:
                raise _reject("catalog_tool_unavailable", "The selected tool is unavailable.") from None

        try:
            response = self.access.invoke_tool(self.registry, principal, target.tool_id, request.arguments,
                correlation_id=correlation_id, dispatch_guard=guard, arguments_validator=validate,
                dispatch_context=dispatch(), expected_definition_revision=target.definition_fingerprint,
                allow_read_retry=False)
        except AccessDeniedError:
            raise _reject("catalog_tool_unavailable", "The selected tool is unavailable.") from None
        except ToolNotFoundError:
            self._audit_rejection(principal, request, correlation_id, definition, "unavailable")
            raise _reject("catalog_tool_unavailable", "The selected tool is unavailable.") from None
        except ToolExecutionError as error:
            # This structural precondition runs before AccessControl's audit
            # boundary. Failures inside that boundary return an audited response.
            if error.code != "group_tool_contract_changed":
                raise
            self._audit_rejection(principal, request, correlation_id, definition, "contract_changed")
            raise _reject("catalog_schema_revision_conflict", "The selected tool contract changed; describe it again.") from None
        return self._checked_response(response)

    def call(self, name: str, arguments: dict[str, Any], principal: AuthPrincipal, *,
             refresh_principal: Callable[[], AuthPrincipal] | None = None,
             correlation_id: str | None = None) -> ToolInvokeResponse:
        try:
            return self._call(name, arguments, principal, refresh_principal=refresh_principal,
                              correlation_id=correlation_id)
        except McpGroupError as exc:
            code = "catalog_tool_unavailable" if exc.code == "group_tool_unavailable" else exc.code
            raise _reject(code, str(exc)) from None

    def _call(self, name: str, arguments: dict[str, Any], principal: AuthPrincipal, *,
              refresh_principal: Callable[[], AuthPrincipal] | None,
              correlation_id: str | None) -> ToolInvokeResponse:
        self.check_namespace()
        if name == "gate_tool_invoke":
            return self.invoke(principal, CatalogInvoke.model_validate(arguments),
                refresh_principal=refresh_principal, correlation_id=correlation_id)
        if name == "gate_tool_describe":
            output = self.describe(principal, CatalogDescribe.model_validate(arguments))
        elif name in {"gate_catalog_search", "gate_instance_list"}:
            output = self.search(principal, CatalogSearch.model_validate(arguments), instances=name == "gate_instance_list")
        elif name == "gate_instance_session_open":
            selection = CatalogSessionOpen.model_validate(arguments)
            router = self._groups()
            target = router.resolve(principal, tool_ref=selection.tool_ref, instance_id=selection.instance_id)
            if selection.schema_revision != target.schema_revision:
                raise _reject("catalog_schema_revision_conflict", "The logical contract changed; describe it again.")
            output = router.open_session(principal, GroupToolSelection(tool_ref=selection.tool_ref, instance_id=selection.instance_id))
        elif name == "gate_instance_session_close":
            closing = CatalogSessionClose.model_validate(arguments)
            output = self._groups().close_session(principal, closing.session_id)
        else:
            raise _reject("catalog_entry_unavailable", "Select one of the catalog entries.")
        if refresh_principal is not None and refresh_principal() != principal:
            raise _reject("catalog_identity_changed", "The discovery identity changed before returning results.")
        return ToolInvokeResponse(ok=True, tool_id=name, output=output)


def catalog_tools() -> list[dict[str, Any]]:
    descriptions = (
        "Search authorized tools by keywords. Returns bounded summaries and stable tool_ref/schema_revision; no full schemas.",
        "Describe one authorized tool_ref. Returns its full input schema within max_bytes; never truncates a schema.",
        "Invoke one described tool with its schema_revision and original arguments. Current permissions are checked independently.",
        "List authorized instances; optional group_id and logical tool_ref select a service contract. Never selects a default.",
        "Explicitly open an instance routing session for a described logical tool. This does not create authorization or retry calls.",
        "Close this connection's instance routing session; future invocations require an explicitly opened session.",
    )
    models: tuple[type[BaseModel], ...] = (CatalogSearch, CatalogDescribe, CatalogInvoke, CatalogSearch,
                                         CatalogSessionOpen, CatalogSessionClose)
    return [{"name": name, "description": description, "inputSchema": model.model_json_schema(),
             "annotations": {"readOnlyHint": name in CATALOG_TOOL_NAMES[:2] or name == "gate_instance_list",
                             "openWorldHint": name == "gate_tool_invoke"}}
            for name, description, model in zip(CATALOG_TOOL_NAMES, descriptions, models)]


class RegistryCatalogTargetResolver:
    """Single-instance default. Logical groups do not replace real ACL keys."""
    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def resolve(self, tool_ref: str, instance_id: str | None = None) -> CatalogTarget:
        definition = self.registry.get_definition(tool_ref)
        server_id = instance_for(definition)
        if instance_id is not None and instance_id != server_id:
            raise _reject("catalog_instance_mismatch", "The selected tool does not belong to the requested instance.")
        return CatalogTarget(tool_id=definition.id, server_id=server_id, instance_id=server_id)

"""Bounded, permission-first tool discovery over an incremental SQLite index."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from jsonschema import FormatChecker
from jsonschema.exceptions import SchemaError, ValidationError as SchemaValidationError
from jsonschema.validators import validator_for
from referencing import Registry
from referencing.exceptions import NoSuchResource, Unresolvable

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.models import ToolDefinition, ToolInvokeResponse
from lingshu_gate.protocol.tool_namespace import public_tool_name
from lingshu_gate.ports.catalog_target import CatalogTarget, CatalogTargetResolver
from lingshu_gate.registry import ToolExecutionError, ToolNotFoundError, ToolRegistry

CATALOG_TOOL_NAMES = ("gate_catalog_search", "gate_tool_describe", "gate_tool_invoke", "gate_instance_list")
MAX_PAGE_OFFSET = 10_000
CURSOR_TTL_SECONDS = 300
MAX_INVOKE_ARGUMENT_BYTES = 1_048_576


class CatalogSearch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(default="", max_length=256)
    instance_id: str | None = Field(default=None, min_length=1, max_length=256)
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
    arguments: dict[str, Any]


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
                 target_resolver: CatalogTargetResolver | None = None) -> None:
        self.registry = registry
        self.access = access
        self.database = access.database
        self.target_resolver = target_resolver or RegistryCatalogTargetResolver(registry)
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
                                  ("required_control_permission", "classification_control_plane")
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
        binding = self._binding(principal, request, kind, generation, epoch)
        offset = self._offset(request.cursor, binding)
        terms = re.findall(r"[^\W_]+", request.query.casefold(), re.UNICODE)
        if len(terms) > 8 or len(request.query.encode()) > 1_024:
            raise _reject("catalog_query_limit", "Use at most eight keywords and 256 characters.")
        if request.query.strip() and not terms:
            raise _reject("catalog_query_invalid", "Use at least one keyword.")
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
        if generation != self._generation or epoch != self._epoch():
            raise _reject("catalog_changed", "Catalog or permissions changed during search.")
        return output

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
        definition = self.selected(principal, request.tool_ref, request.instance_id)
        output = {"tool_ref": definition.id, "instance_id": instance_for(definition),
                  "schema_revision": schema_revision(definition), "name": definition.name,
                  "description": definition.description, "input_schema": definition.input_schema or {"type": "object"}}
        output_schema = definition.metadata.get("outputSchema") or definition.metadata.get("output_schema")
        if isinstance(output_schema, dict):
            output["output_schema"] = output_schema
        if len(_json(output).encode()) > request.max_bytes - 512:
            raise _reject("catalog_schema_limit", "The full schema exceeds max_bytes; it was not truncated.")
        return output

    def check_namespace(self) -> None:
        with self._queue_lock:
            if self._reserved:
                raise _reject("catalog_namespace_conflict", "A reserved catalog entry name conflicts with a registered tool.")

    def invoke(self, principal: AuthPrincipal, request: CatalogInvoke, *,
               refresh_principal: Callable[[], AuthPrincipal] | None = None,
               correlation_id: str | None = None) -> ToolInvokeResponse:
        definition = self.selected(principal, request.tool_ref, request.instance_id)
        try:
            if request.instance_id is not None and request.instance_id != instance_for(definition):
                raise _reject("catalog_instance_mismatch", "The selected tool does not belong to the requested instance.")
            if schema_revision(definition) != request.schema_revision:
                raise _reject("catalog_schema_revision_conflict", "The selected tool definition changed; describe it again.")
            _validate_arguments(definition.input_schema or {"type": "object"}, request.arguments)
        except ToolExecutionError as exc:
            # Attribute rejected parameters/versions to the selected target, using
            # the same redacted audit boundary as ordinary invocation.
            self.access._record_invocation_audit(principal, definition,
                correlation_id=correlation_id or secrets.token_hex(16),
                decision={**self.access.evaluate(principal, definition), "allowed": False, "reason": exc.code},
                outcome="not_invoked", duration_ms=None, payload={"values_recorded": False})
            raise

        def guard() -> None:
            current = refresh_principal() if refresh_principal is not None else principal
            if current != principal:
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

        return self.access.invoke_tool(self.registry, principal, definition.id, request.arguments,
            correlation_id=correlation_id, dispatch_guard=guard)

    def call(self, name: str, arguments: dict[str, Any], principal: AuthPrincipal, *,
             refresh_principal: Callable[[], AuthPrincipal] | None = None,
             correlation_id: str | None = None) -> ToolInvokeResponse:
        self.check_namespace()
        if name == "gate_tool_invoke":
            return self.invoke(principal, CatalogInvoke.model_validate(arguments),
                refresh_principal=refresh_principal, correlation_id=correlation_id)
        if name == "gate_tool_describe":
            output = self.describe(principal, CatalogDescribe.model_validate(arguments))
        elif name in {"gate_catalog_search", "gate_instance_list"}:
            output = self.search(principal, CatalogSearch.model_validate(arguments), instances=name == "gate_instance_list")
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
        "List authorized service instances, adapted from server_id. Select an instance_id to search; grouping is not implemented.",
    )
    models: tuple[type[BaseModel], ...] = (CatalogSearch, CatalogDescribe, CatalogInvoke, CatalogSearch)
    return [{"name": name, "description": description, "inputSchema": model.model_json_schema(),
             "annotations": {"readOnlyHint": name != "gate_tool_invoke", "openWorldHint": name == "gate_tool_invoke"}}
            for name, description, model in zip(CATALOG_TOOL_NAMES, descriptions, models)]


def _validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    """Validate bounded JSON Schema locally; reference resolution never uses I/O."""
    try:
        if len(_json(arguments).encode()) > MAX_INVOKE_ARGUMENT_BYTES:
            raise _reject("catalog_argument_limit", "Arguments exceed 1048576 bytes.")
        if len(_json(schema).encode()) > 131_072:
            raise _reject("catalog_schema_limit", "The schema exceeds the validation byte limit.")
        for value, is_schema in ((schema, True), (arguments, False)):
            pending = [(value, 0)]
            nodes = 0
            while pending:
                node, depth = pending.pop()
                nodes += 1
                if nodes > 8_192 or depth > 32:
                    raise _reject("catalog_validation_limit", "JSON exceeds the validation depth or node limit.")
                if isinstance(node, dict):
                    if is_schema and any(key in node for key in ("$dynamicRef", "$recursiveRef")):
                        raise _reject("catalog_schema_unsupported", "Dynamic schema references are unsupported.")
                    if is_schema and "$ref" in node:
                        ref = node["$ref"]
                        if not isinstance(ref, str) or not ref.startswith("#/"):
                            raise _reject("catalog_schema_unsupported", "Only local JSON Pointer schema references are supported.")
                    pending.extend((child, depth + 1) for child in node.values())
                elif isinstance(node, list):
                    pending.extend((child, depth + 1) for child in node)
        validator_class = validator_for(schema, default=None) if "$schema" in schema else validator_for(schema)
        if validator_class is None:
            raise _reject("catalog_schema_unsupported", "The schema dialect is unsupported.")
        validator_class.check_schema(schema)
        def no_remote(uri: str) -> Any:
            raise NoSuchResource(ref=uri)  # type: ignore[call-arg]
        registry = Registry(retrieve=no_remote)  # type: ignore[call-arg]
        validator_class(schema, format_checker=FormatChecker(), registry=registry).validate(arguments)
    except (SchemaValidationError, SchemaError, Unresolvable, ValueError, TypeError, RecursionError):
        raise _reject("catalog_arguments_invalid", "Arguments or the selected schema failed validation.") from None


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

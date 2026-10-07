"""Current-policy logical directory, explicit instance resolution and sticky sessions."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

from lingshu_gate.access_control import ACCESS_RANK, AccessControlStore
from lingshu_gate.application.mcp_groups import McpGroupService
from lingshu_gate.application.mcp_group_structures import ToolStructureCache
from lingshu_gate.application.tool_authority import current_tool_principal
from lingshu_gate.auth import AuthPrincipal, AuthStore
from lingshu_gate.domain.mcp_group_catalog import (
    MAX_CATALOG_CONTRACT_BYTES, MAX_CATALOG_TOOLS, CatalogVariant, VisibleCatalogTool, build_catalog,
)
from lingshu_gate.domain.mcp_group_routing import (
    CatalogTarget, GroupToolCall, GroupToolSelection, logical_service_id, logical_tool_ref,
)
from lingshu_gate.domain.mcp_groups import McpGroupError
from lingshu_gate.registry import RegistrySnapshotCapacityError, ToolRegistry, tool_definition_revision

SESSION_TTL = timedelta(hours=1)
SESSION_CONNECTION_LIMIT = 128
SESSION_GLOBAL_LIMIT = 10_000


def _binding(actor: AuthPrincipal) -> str:
    proof = [actor.id, actor.auth_type, actor.session_id, actor.token_id,
             actor.external_grant_id, actor.oauth_client_id, actor.oauth_family_id]
    return hashlib.sha256(json.dumps(proof, separators=(",", ":")).encode()).hexdigest()


class McpGroupRoutingService:
    """Internal adapter for on-demand directories; original IDs remain callable."""

    def __init__(self, groups: McpGroupService, registry: ToolRegistry,
                 access: AccessControlStore, auth: AuthStore) -> None:
        self.groups, self.registry, self.access, self.auth = groups, registry, access, auth
        self.structures = ToolStructureCache()

    @staticmethod
    def _unavailable() -> McpGroupError:
        return McpGroupError("group_tool_unavailable", "The selected service, instance or contract is unavailable.", 404)

    def _group(self, connection: sqlite3.Connection, group_id: str, instance_id: str | None) -> dict[str, Any]:
        if instance_id is None:
            return self.groups.store.detail(connection, group_id)
        # A selected target needs one membership row, not every group member or
        # the contracts belonging to other instances. This stores no authority.
        row = connection.execute("SELECT id,status,revision FROM mcp_groups WHERE id=?", (group_id,)).fetchone()
        member = connection.execute("SELECT server_id AS instance_id,status FROM mcp_group_members "
            "WHERE group_id=? AND server_id=? AND status='active'", (group_id, instance_id)).fetchone()
        if row is None or member is None:
            raise self._unavailable()
        return {**dict(row), "members": [dict(member)]}

    def _snapshot(self, group_id: str, actor: AuthPrincipal, *,
                  instance_id: str | None = None) -> tuple[dict[str, Any], list[VisibleCatalogTool], list[CatalogVariant]]:
        actor = current_tool_principal(self.auth, actor)
        for _ in range(3):
            with self.groups.store.database.session() as connection:
                try:
                    group = self._group(connection, group_id, instance_id)
                except McpGroupError:
                    raise self._unavailable() from None
            if group["status"] != "active":
                raise self._unavailable()
            active = {member["instance_id"] for member in group["members"] if member["status"] == "active"}
            revision, names = self.groups.configs.selected_instance_metadata(active)
            try:
                snapshot = self.registry.mcp_snapshot(names, max_tools=MAX_CATALOG_TOOLS)
            except RegistrySnapshotCapacityError:
                raise McpGroupError("group_catalog_capacity", "The service exceeds bounded catalog capacity.", 503) from None
            candidates = [entry for entry in snapshot.tools if entry.structure.source == "mcp"
                and isinstance(entry.structure.metadata.get("original_tool_name"), str)
                and entry.structure.metadata["original_tool_name"]
                and entry.structure.id == f'mcp.{entry.structure.metadata["server_id"]}.{entry.structure.metadata["original_tool_name"]}']
            if sum(item.structure.byte_count for item in candidates) > MAX_CATALOG_CONTRACT_BYTES:
                raise McpGroupError("group_catalog_capacity", "The service exceeds bounded catalog capacity.", 503)
            # Cheap, conservative physical admission before schema preparation.
            # Exact tool overrides (including none) use the original grant map.
            # Fresh contract/publication/control checks still happen below; no
            # visibility or grant result survives this request.
            keys = [(entry.structure.metadata["server_id"], entry.structure.id) for entry in candidates]
            with self.groups.store.database.session() as connection:
                grants = self.access._effective_access_map(connection, actor, keys)
            oauth_tools, oauth_instances = set(actor.external_tool_ids), set(actor.external_server_ids)
            candidates = [entry for entry, key in zip(candidates, keys, strict=True)
                if (grants[key] != "none" or entry.structure.metadata.get("classification_control_plane") is True)
                and (actor.auth_type != "oauth" or key[0] in oauth_instances and key[1] in oauth_tools)]
            prepared = self.structures.get_many(candidates)
            by_id = {item.definition.id: item for item in prepared}
            actor = current_tool_principal(self.auth, actor)
            with self.groups.store.database.session() as connection:
                connection.execute("BEGIN")
                if self._group(connection, group_id, instance_id)["revision"] != group["revision"]:
                    continue
                visible = [VisibleCatalogTool(definition, definition.metadata["server_id"],
                    names[definition.metadata["server_id"]], classification, by_id[definition.id].contract)
                    for definition, classification in self.access.visible_tool_contracts(actor,
                        [item.definition for item in prepared], connection=connection,
                        fingerprints={item.definition.id: item.fingerprint for item in prepared})]
                # Compute contract references before service grants, then intersect
                # each reference's logical service/tool grant with physical policy.
                variants = build_catalog(group_id, visible)
                refs = [(logical_service_id(group_id), logical_tool_ref(group_id, variant.summary.variant_id))
                        for variant in variants]
                grants = self.access._effective_access_map(connection, actor, refs)
                allowed = []
                for variant, key in zip(variants, refs, strict=True):
                    required = variant.summary.safety.required_access if variant.summary.safety else "write"
                    if ACCESS_RANK[grants[key]] >= ACCESS_RANK[required]:
                        allowed.append(variant)
            with self.groups.configs.mutation_lock.read_lock(), self.groups.store.database.session() as connection:
                try:
                    current_group = self._group(connection, group_id, instance_id)
                except McpGroupError:
                    raise self._unavailable() from None
                if (current_group["revision"] == group["revision"] and current_group["status"] == "active"
                        and self.groups.configs.metadata_snapshot_current(revision)
                        and self.registry.mcp_snapshot_current(snapshot.revisions)):
                    counts = Counter(item.summary.original_tool_name for item in allowed)
                    for item in allowed:
                        item.summary = item.summary.model_copy(update={"visible_variant_count": counts[item.summary.original_tool_name]})
                    return group, visible, allowed
        raise McpGroupError("group_catalog_changed", "The service changed repeatedly; retry the read.")

    def search(self, actor: AuthPrincipal, *, group_id: str, q: str = "", offset: int = 0,
               limit: int = 20) -> dict[str, Any]:
        if not 0 <= offset <= 100_000 or not 1 <= limit <= 100 or len(q) > 200:
            raise McpGroupError("invalid_group_query", "Use bounded search and pagination.", 422)
        group, _, variants = self._snapshot(group_id, actor)
        selected = [variant for variant in variants if q.strip().casefold() in variant.search_text]
        return {"service_id": logical_service_id(group_id), "group_revision": group["revision"] if selected else None,
            "tools": [{**variant.summary.model_dump(), "tool_ref": logical_tool_ref(group_id, variant.summary.variant_id),
                       "instances": [member.model_dump() for member in variant.members]}
                      for variant in selected[offset:offset + limit]],
            "total": len(selected), "offset": offset, "limit": limit}

    def directory_revision(self, group_id: str) -> tuple[int | None, int]:
        """Internal cursor marker; never a public discovery count or descriptor."""
        # Warm metadata alone before capturing the marker. Preparing a complete
        # authorized group just to warm this cache doubled paginated searches.
        self.groups.configs.selected_instance_metadata(set())
        row = self.groups.store.database.query_one("SELECT revision FROM mcp_groups WHERE id=?", (group_id,))
        return (int(row[0]) if row is not None else None, self.groups.configs.metadata_revision())

    def directory_page(self, actor: AuthPrincipal, *, group_id: str, keywords: list[str],
                       tool_ref: str | None, instance_id: str | None, offset: int,
                       limit: int, instances: bool) -> list[dict[str, Any]]:
        """Reuse group partitions and current authority; materialize only a page.

        This adapter deliberately omits member counts, full member arrays and
        contracts. Physical-instance and logical grants were intersected in the
        existing snapshot before keyword ordering or pagination.
        """
        _, visible, variants = self._snapshot(group_id, actor)
        selected = [variant for variant in variants
            if all(word in variant.search_text for word in keywords)
            and (tool_ref is None or logical_tool_ref(group_id, variant.summary.variant_id) == tool_ref)
            and (instance_id is None or any(member.instance_id == instance_id for member in variant.members))]
        if instances:
            identifiers = sorted({member.instance_id for variant in selected for member in variant.members
                if instance_id is None or member.instance_id == instance_id})
            return [{"instance_id": identifier, "group_id": group_id}
                    for identifier in identifiers[offset:offset + limit]]
        selected.sort(key=lambda variant: (variant.summary.original_tool_name, variant.summary.variant_id))
        definitions = {item.definition.id: item.definition for item in visible}
        summaries = []
        for variant in selected[offset:offset + limit]:
            definition = definitions[variant.members[0].tool_id]
            summaries.append({"tool_ref": logical_tool_ref(group_id, variant.summary.variant_id),
                "instance_id": instance_id, "group_id": group_id,
                "name": definition.name[:128], "description": definition.description[:320],
                "schema_revision": variant.summary.variant_id})
        return summaries

    def resolve(self, actor: AuthPrincipal, *, tool_ref: str, instance_id: str) -> CatalogTarget:
        selection = GroupToolSelection(tool_ref=tool_ref, instance_id=instance_id)
        _, group_id, variant_id = selection.tool_ref.split(":")
        group, tools, variants = self._snapshot(group_id, actor, instance_id=selection.instance_id)
        for variant in variants:
            if variant.summary.variant_id != variant_id:
                continue
            if variant.summary.safety is None or variant.summary.compatibility in {"review_required", "uncomparable"}:
                raise McpGroupError("group_tool_review_required", "Review and publish this contract before grouped invocation.")
            for member in variant.members:
                if member.instance_id == selection.instance_id:
                    definition = next(item.definition for item in tools if item.definition.id == member.tool_id)
                    mutable = definition.copy_definition() if hasattr(definition, "copy_definition") else definition
                    return CatalogTarget(logical_service_id(group_id), group_id, group["revision"], tool_ref,
                        instance_id, instance_id, member.tool_id, variant_id, tool_definition_revision(mutable))
        raise self._unavailable()

    def describe(self, actor: AuthPrincipal, *, tool_ref: str, instance_id: str) -> dict[str, Any]:
        resolved = self.resolve(actor, tool_ref=tool_ref, instance_id=instance_id)
        definition = self.registry.get_definition(resolved.tool_id)
        if tool_definition_revision(definition) != resolved.definition_fingerprint:
            raise McpGroupError("group_tool_contract_changed", "The contract changed; search again.")
        return {"service_id": resolved.service_id, "tool_ref": resolved.tool_ref, "instance_id": resolved.instance_id,
            "server_id": resolved.server_id, "tool_id": resolved.tool_id, "schema_revision": resolved.schema_revision,
            "definition": definition.model_dump()}

    def open_session(self, actor: AuthPrincipal, selection: GroupToolSelection) -> dict[str, Any]:
        with self.groups.configs.mutation_lock:
            resolved = self.resolve(actor, **selection.model_dump())
            with self.groups.runtime.route_instance_guard(resolved.instance_id) as generation:
                actor = current_tool_principal(self.auth, actor)
                config = self.groups.configs.get_config(resolved.instance_id)
                now = datetime.now(timezone.utc)
                session_id = uuid4().hex
                expires = (now + SESSION_TTL).isoformat()
                with self.groups.store.database.session() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    connection.execute("DELETE FROM mcp_group_route_sessions WHERE expires_at<=? OR closed_at IS NOT NULL", (now.isoformat(),))
                    count = connection.execute("SELECT COUNT(*) FROM mcp_group_route_sessions WHERE actor_id=? AND connection_binding=?",
                                               (actor.id, _binding(actor))).fetchone()[0]
                    total = connection.execute("SELECT COUNT(*) FROM mcp_group_route_sessions").fetchone()[0]
                    if count >= SESSION_CONNECTION_LIMIT or total >= SESSION_GLOBAL_LIMIT:
                        raise McpGroupError("group_session_capacity", "Close an unused routing session before opening another.", 429)
                    connection.execute("INSERT INTO mcp_group_route_sessions VALUES(?,?,?,?,?,?,?,?,?,?,NULL)",
                        (session_id, actor.id, _binding(actor), resolved.group_id, resolved.group_revision,
                         resolved.instance_id, config.digest, generation, now.isoformat(), expires))
                return {"session_id": session_id, "service_id": resolved.service_id,
                        "instance_id": resolved.instance_id, "expires_at": expires}

    def close_session(self, actor: AuthPrincipal, session_id: str) -> dict[str, Any]:
        actor = current_tool_principal(self.auth, actor)
        with self.groups.store.database.session() as connection:
            row = connection.execute("SELECT id FROM mcp_group_route_sessions WHERE id=? AND actor_id=? AND connection_binding=?",
                                     (session_id, actor.id, _binding(actor))).fetchone()
            if row is None:
                raise McpGroupError("group_session_unavailable", "The routing session is unavailable.", 404)
            connection.execute("UPDATE mcp_group_route_sessions SET closed_at=? WHERE id=?",
                               (datetime.now(timezone.utc).isoformat(), session_id))
        return {"session_id": session_id, "closed": True}

    @contextmanager
    def dispatch_guard(self, actor: AuthPrincipal, call: GroupToolCall) -> Iterator[tuple[AuthPrincipal, CatalogTarget]]:
        """Read-only resolution/binding port; the existing invocation adapter dispatches."""
        with self.groups.configs.mutation_lock.read_lock():
            resolved = self.resolve(actor, tool_ref=call.tool_ref, instance_id=call.instance_id)
            with self.groups.runtime.route_instance_guard(resolved.instance_id) as generation:
                # Runtime/config waits cannot preserve old authority.
                actor = current_tool_principal(self.auth, actor)
                resolved = self.resolve(actor, tool_ref=call.tool_ref, instance_id=call.instance_id)
                config = self.groups.configs.get_config(resolved.instance_id)
                with self.groups.store.database.session() as connection:
                    row = connection.execute("SELECT * FROM mcp_group_route_sessions WHERE id=? AND actor_id=? AND connection_binding=?",
                                             (call.session_id, actor.id, _binding(actor))).fetchone()
                if row is None or row["closed_at"] is not None or row["expires_at"] <= datetime.now(timezone.utc).isoformat():
                    raise McpGroupError("group_session_unavailable", "Open an explicit routing session for the selected instance.", 404)
                if row["group_id"] != resolved.group_id or row["instance_id"] != resolved.instance_id:
                    raise McpGroupError("group_session_instance_mismatch", "A routing session cannot switch instances.")
                if (row["group_revision"] != resolved.group_revision or row["config_digest"] != config.digest
                        or row["runtime_generation"] != generation):
                    raise McpGroupError("group_session_changed", "The bound instance or service changed; reconcile before opening a new session.")
                # The caller uses access.invoke_tool with this actual tool_id,
                # expected_definition_revision and allow_read_retry=False. Route fields
                # never become downstream arguments. No alternative is selected.
                yield actor, resolved

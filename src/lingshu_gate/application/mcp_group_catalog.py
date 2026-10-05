"""Administrator-only, authorization-filtered compatibility candidates."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.application.mcp_groups import McpGroupService
from lingshu_gate.application.mcp_group_structures import ToolStructureCache
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.domain.mcp_group_catalog import (
    MAX_CATALOG_CONTRACT_BYTES, MAX_CATALOG_TOOLS,
    CatalogVariant, GroupToolCatalogPage, GroupToolVariantPage, VisibleCatalogTool, build_catalog,
)
from lingshu_gate.domain.mcp_groups import McpGroupError
from lingshu_gate.mcp_config_store import McpConfigConflict
from lingshu_gate.registry import RegistrySnapshotCapacityError, ToolRegistry

MAX_SNAPSHOT_ATTEMPTS = 3


class McpGroupCatalogService:
    def __init__(self, groups: McpGroupService, registry: ToolRegistry, access: AccessControlStore) -> None:
        self.groups, self.registry, self.access = groups, registry, access
        self.structures = ToolStructureCache()

    def _current_actor(self, connection: sqlite3.Connection, actor: AuthPrincipal) -> AuthPrincipal:
        self.groups.authorize(connection, actor)
        permissions = {row[0] for row in connection.execute("SELECT p.code FROM user_roles ur "
            "JOIN roles r ON r.id=ur.role_id AND r.enabled=1 JOIN role_permissions rp ON rp.role_id=r.id "
            "JOIN control_permissions p ON p.id=rp.permission_id WHERE ur.user_id=?", (actor.id,))}
        scopes = set(actor.scopes)
        if actor.auth_type == "token":
            row = connection.execute("SELECT scopes_json FROM api_tokens WHERE id=?", (actor.token_id,)).fetchone()
            current = set(json.loads(row[0]))
            scopes = current if "*" in scopes else scopes if "*" in current else scopes & current
        # Request authentication may precede waiting for the configuration lock.
        # Recheck the narrower current permission/token ceilings in this snapshot.
        return replace(actor, permissions=tuple(sorted(set(actor.permissions) & permissions)), scopes=tuple(sorted(scopes)))

    def _snapshot(self, group_id: str, actor: AuthPrincipal) -> tuple[int, list[VisibleCatalogTool], list[CatalogVariant]]:
        self.groups.check(actor)
        for _ in range(MAX_SNAPSHOT_ATTEMPTS):
            # Capture only group metadata under the write lock. File loading,
            # fingerprints, policy projection and comparison happen outside it.
            with self.groups.configs.mutation_lock, self.groups.store.database.session() as connection:
                self.groups.authorize(connection, actor)
                group = self.groups.store.detail(connection, group_id)
            active = {item["instance_id"] for item in group["members"] if item["status"] == "active"}
            try:
                metadata_revision, names = self.groups.configs.selected_instance_metadata(active)
                snapshot = self.registry.mcp_snapshot(names, max_tools=MAX_CATALOG_TOOLS)
            except McpConfigConflict:
                raise self._changed() from None
            except RegistrySnapshotCapacityError:
                raise McpGroupError("group_catalog_capacity", "The group exceeds bounded structural input capacity.", 503) from None
            candidates = []
            input_bytes = 0
            for entry in snapshot.tools:
                definition = entry.structure
                instance = definition.metadata.get("server_id")
                original = definition.metadata.get("original_tool_name")
                if (definition.source == "mcp" and isinstance(instance, str) and instance in names
                        and isinstance(original, str) and original and original == original.strip()
                        and definition.id == f"mcp.{instance}.{original}"):
                    input_bytes += definition.byte_count
                    if input_bytes > MAX_CATALOG_CONTRACT_BYTES:
                        raise McpGroupError("group_catalog_capacity", "The group exceeds bounded structural input capacity.", 503)
                    candidates.append(entry)
            # No configuration, Registry or database lock across preparation.
            prepared = [self.structures.get(entry) for entry in candidates]
            by_id = {item.definition.id: item for item in prepared}
            with self.groups.store.database.session() as connection:
                connection.execute("BEGIN")
                current = self._current_actor(connection, actor)
                if self.groups.store.detail(connection, group_id)["revision"] != group["revision"]:
                    continue
                visible = [VisibleCatalogTool(definition, definition.metadata["server_id"],
                    names[definition.metadata["server_id"]], classification, by_id[definition.id].contract)
                    for definition, classification in self.access.visible_tool_contracts(current,
                        [item.definition for item in prepared], connection=connection,
                        fingerprints={item.definition.id: item.fingerprint for item in prepared})]
            variants = build_catalog(group_id, visible)
            # Validate the selected version vector, not unrelated global writes.
            with self.groups.configs.mutation_lock:
                if (not self.groups.configs.metadata_snapshot_current(metadata_revision)
                        or not self.registry.mcp_snapshot_current(snapshot.revisions)):
                    continue
                with self.groups.store.database.session() as connection:
                    row = connection.execute("SELECT revision FROM mcp_groups WHERE id=?", (group_id,)).fetchone()
                    if row is None:
                        raise McpGroupError("group_not_found", "The group no longer exists; refresh the list.", 404)
                    if row[0] != group["revision"]:
                        continue
            return group["revision"], visible, variants
        raise self._changed()

    @staticmethod
    def _changed() -> McpGroupError:
        return McpGroupError("group_catalog_changed", "The directory changed repeatedly; retry this read.", 409)

    def catalog(self, group_id: str, actor: AuthPrincipal, *, q: str = "", offset: int = 0,
                limit: int = 20) -> GroupToolCatalogPage:
        revision, tools, variants = self._snapshot(group_id, actor)
        needle = q.strip().casefold()
        selected = [variant for variant in variants if needle in variant.search_text]
        return GroupToolCatalogPage(group_id=group_id, group_revision=revision,
            variants=[item.summary for item in selected[offset:offset + limit]], total=len(selected),
            visible_tool_count=len(tools), visible_member_count=len({item.instance_id for item in tools}),
            offset=offset, limit=limit)

    def variant(self, group_id: str, variant_id: str, actor: AuthPrincipal, *, offset: int = 0,
                limit: int = 20) -> GroupToolVariantPage:
        revision, _, variants = self._snapshot(group_id, actor)
        for variant in variants:
            if variant.summary.variant_id == variant_id:
                return GroupToolVariantPage(group_id=group_id, group_revision=revision, variant=variant.summary,
                    members=variant.members[offset:offset + limit], total=len(variant.members), offset=offset, limit=limit)
        # Do not distinguish a removed, changed or now-hidden candidate.
        raise McpGroupError("group_catalog_variant_not_found", "This visible variant is unavailable; refresh the catalog.", 404)

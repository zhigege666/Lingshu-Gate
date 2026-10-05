"""Administrator-only, authorization-filtered compatibility candidates."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.application.mcp_groups import McpGroupService
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.domain.mcp_group_catalog import (
    CatalogVariant, GroupToolCatalogPage, GroupToolVariantPage, VisibleCatalogTool, build_catalog,
)
from lingshu_gate.domain.mcp_groups import McpGroupError
from lingshu_gate.registry import ToolRegistry


class McpGroupCatalogService:
    def __init__(self, groups: McpGroupService, registry: ToolRegistry, access: AccessControlStore) -> None:
        self.groups, self.registry, self.access = groups, registry, access

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
        with self.groups.configs.mutation_lock:
            definitions = self.registry.list_definitions()
            names = {item.instance_id: item.name for item in self.groups.configs.instance_metadata()}
            with self.groups.store.database.session() as connection:
                connection.execute("BEGIN")
                current = self._current_actor(connection, actor)
                group = self.groups.store.detail(connection, group_id)
                active = {item["instance_id"] for item in group["members"]
                          if item["status"] == "active" and item["instance_id"] in names}
                candidates = []
                for definition in definitions:
                    instance = definition.metadata.get("server_id")
                    original = definition.metadata.get("original_tool_name")
                    if (definition.source == "mcp" and isinstance(instance, str) and instance in active
                            and isinstance(original, str) and original and original == original.strip()
                            and definition.id == f"mcp.{instance}.{original}"):
                        candidates.append(definition)
                visible = [VisibleCatalogTool(definition, definition.metadata["server_id"],
                    names[definition.metadata["server_id"]], classification)
                    for definition, classification in self.access.visible_tool_contracts(current, candidates, connection=connection)]
                return group["revision"], visible, build_catalog(group_id, visible)

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

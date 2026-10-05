"""Transactional group metadata and audit. No grants, endpoints or credentials here."""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.domain.mcp_groups import McpGroupDraft, McpGroupError
from lingshu_gate.observability_store import ObservabilityStore, iso_now

Authorize = Callable[[sqlite3.Connection], None]


class McpGroupStore:
    def __init__(self, database: SQLiteDatabase, observability: ObservabilityStore) -> None:
        self.database, self.observability = database, observability

    @staticmethod
    def detail(connection: sqlite3.Connection, group_id: str) -> dict[str, Any]:
        row = connection.execute("SELECT * FROM mcp_groups WHERE id=?", (group_id,)).fetchone()
        if row is None:
            raise McpGroupError("group_not_found", "The group no longer exists; refresh the list.", 404)
        result = dict(row)
        result.pop("search_text")
        result["members"] = [dict(item) for item in connection.execute(
            "SELECT server_id AS instance_id,status FROM mcp_group_members WHERE group_id=? ORDER BY server_id", (group_id,))]
        return result

    def list_groups(self, *, q: str, status: str, offset: int, limit: int, authorize: Authorize) -> dict[str, Any]:
        with self.database.session() as connection:
            authorize(connection)
            where = "instr(g.search_text,?)>0 AND (?='all' OR g.status=?)"
            params = (q.casefold().strip(), status, status)
            total = connection.execute(f"SELECT COUNT(*) FROM mcp_groups g WHERE {where}", params).fetchone()[0]
            rows = connection.execute(f"SELECT g.id,g.name,g.description,g.status,g.revision,g.created_at,g.updated_at,"
                "COUNT(m.server_id) AS member_count,SUM(m.status='missing') AS missing_count "
                f"FROM mcp_groups g LEFT JOIN mcp_group_members m ON m.group_id=g.id WHERE {where} "
                "GROUP BY g.id ORDER BY g.name COLLATE NOCASE,g.id LIMIT ? OFFSET ?", (*params, limit, offset))
            return {"groups": [{**dict(row), "missing_count": row["missing_count"] or 0} for row in rows],
                    "total": total, "offset": offset, "limit": limit}

    def save(self, draft: McpGroupDraft, *, group_id: str | None, expected_revision: int | None,
             actor_id: str, authorize: Authorize, available_instances: set[str],
             request_key: str | None = None, request_digest: str | None = None) -> dict[str, Any]:
        with self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            authorize(connection)
            if group_id is None:
                if request_key is None or request_digest is None:
                    raise McpGroupError("group_request_key_required", "A new group needs a bound request key.", 422)
                receipt = connection.execute("SELECT request_digest,group_id FROM mcp_group_requests WHERE actor_id=? AND request_key=?",
                    (actor_id, request_key)).fetchone()
                if receipt:
                    if receipt["request_digest"] != request_digest:
                        raise McpGroupError("group_request_conflict", "This create request was used with a different body; reconcile its saved result before editing.")
                    return self._receipt_result(connection, receipt["group_id"])
            previous = self.detail(connection, group_id) if group_id else None
            if previous and previous["revision"] != expected_revision:
                raise McpGroupError("group_revision_conflict", "The group changed; reload it before saving. Your draft has not been applied.")
            old_members = {item["instance_id"]: item["status"] for item in previous["members"]} if previous else {}
            required = (set(draft.members) - old_members.keys()) | set(draft.reconfirm_members)
            if not set(draft.reconfirm_members).issubset(draft.members) or not required.issubset(available_instances):
                raise McpGroupError("group_instance_unavailable", "A newly selected or reconfirmed instance is missing; reload the catalog. Existing missing members can be retained or removed.")
            if not previous and connection.execute("SELECT COUNT(*) FROM mcp_groups").fetchone()[0] >= 1000:
                raise McpGroupError("group_capacity", "The group limit has been reached.", 429)
            group_id = group_id or uuid4().hex
            now = iso_now()
            revision = previous["revision"] + 1 if previous else 1
            search = f"{group_id} {draft.name} {draft.description}".casefold()
            if previous:
                connection.execute("UPDATE mcp_groups SET name=?,description=?,status=?,revision=?,search_text=?,updated_at=? WHERE id=?",
                    (draft.name, draft.description, draft.status, revision, search, now, group_id))
                connection.execute("DELETE FROM mcp_group_members WHERE group_id=?", (group_id,))
            else:
                connection.execute("INSERT INTO mcp_groups VALUES(?,?,?,?,?,?,?,?)",
                    (group_id, draft.name, draft.description, draft.status, revision, search, now, now))
            connection.executemany("INSERT INTO mcp_group_members VALUES(?,?,?)", (
                (group_id, item, "active" if item in available_instances and
                 (old_members.get(item, "active") == "active" or item in draft.reconfirm_members) else "missing")
                for item in draft.members))
            result = self.detail(connection, group_id)
            if not previous:
                connection.execute("INSERT INTO mcp_group_requests VALUES(?,?,?,?,?)", (actor_id, request_key, request_digest, group_id, now))
            self.observability.emit_event("gate.mcp.group_updated" if previous else "gate.mcp.group_created",
                subject_type="mcp_group", subject_id=group_id,
                payload={"actor_id": actor_id, "previous": previous, "current": result, "metadata_only": True}, connection=connection)
            return result

    @classmethod
    def _receipt_result(cls, connection: sqlite3.Connection, group_id: str) -> dict[str, Any]:
        try:
            return cls.detail(connection, group_id)
        except McpGroupError:
            raise McpGroupError("group_request_deleted", "This request created a group that was deleted; it cannot recreate that group.") from None

    def create_result(self, request_key: str, *, actor_id: str, authorize: Authorize) -> dict[str, Any]:
        with self.database.session() as connection:
            authorize(connection)
            receipt = connection.execute("SELECT group_id FROM mcp_group_requests WHERE actor_id=? AND request_key=?", (actor_id, request_key)).fetchone()
            if receipt is None:
                raise McpGroupError("group_request_not_found", "No saved result has been found yet; this does not prove the earlier request failed.", 404)
            return self._receipt_result(connection, receipt["group_id"])

    def delete(self, group_id: str, expected_revision: int, *, actor_id: str, authorize: Authorize) -> dict[str, Any]:
        with self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            authorize(connection)
            previous = self.detail(connection, group_id)
            if previous["revision"] != expected_revision:
                raise McpGroupError("group_revision_conflict", "The group changed; reload it before deleting.")
            connection.execute("DELETE FROM mcp_groups WHERE id=?", (group_id,))
            self.observability.emit_event("gate.mcp.group_deleted", subject_type="mcp_group", subject_id=group_id,
                payload={"actor_id": actor_id, "previous": previous, "metadata_only": True}, connection=connection)
            return {"id": group_id, "deleted": True, "metadata_only": True}

    def invalidate_instances(self, ids: set[str], *, reason: str) -> None:
        if not ids:
            return
        with self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            affected: set[str] = set()
            for instance_id in sorted(ids):
                rows = connection.execute("SELECT group_id FROM mcp_group_members WHERE server_id=? AND status='active'", (instance_id,)).fetchall()
                if not rows:
                    continue
                connection.execute("UPDATE mcp_group_members SET status='missing' WHERE server_id=?", (instance_id,))
                affected.update(row["group_id"] for row in rows)
                self.observability.emit_event("gate.mcp.group_instance_missing", subject_type="server", subject_id=instance_id,
                    payload={"group_ids": sorted(row["group_id"] for row in rows), "reason": reason, "metadata_only": True}, connection=connection)
            for group_id in affected:
                connection.execute("UPDATE mcp_groups SET revision=revision+1,updated_at=? WHERE id=?", (iso_now(), group_id))

    def reconcile_instances(self, present: set[str]) -> None:
        related = {str(row[0]) for row in self.database.query_all("SELECT DISTINCT server_id FROM mcp_group_members WHERE status='active'")}
        self.invalidate_instances(related - present, reason="instance_missing_on_reload")

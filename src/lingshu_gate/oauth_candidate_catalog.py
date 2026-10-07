"""Permission-first OAuth candidate queries over the shared schema-free index."""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.auth import AuthPrincipal, hash_secret
from lingshu_gate.oauth_server import MAX_TOOLS, OAuthError
from lingshu_gate.ports.oauth_candidate_catalog import SharedCatalogIndex

JOIN = "FROM gate_tool_catalog c LEFT JOIN mcp_tool_classifications p ON p.server_id=c.instance_id AND p.tool_id=c.tool_ref"
FIELDS = "c.tool_ref,c.instance_id,c.name,p.effective_access,p.fingerprint,p.reviewed_at"


def summary(row: sqlite3.Row) -> dict[str, Any]:
    access = row["effective_access"]
    return {"id": row["tool_ref"], "server_id": row["instance_id"], "server_name": None,
            "name": row["name"], "access": access,
            "snapshot": hash_secret(json.dumps([row["fingerprint"], access, row["reviewed_at"]], sort_keys=True))}


class OAuthCandidateCatalog:
    def __init__(self, index: SharedCatalogIndex, access: AccessControlStore) -> None:
        self.index, self.access = index, access

    def synchronize(self) -> int:
        return self.index.synchronize()

    def revision_marker(self, connection: sqlite3.Connection, owner: AuthPrincipal) -> tuple[int, int, int]:
        generation, policy = self.index.revision_marker(connection)
        # Time-based grant withdrawal has no SQL write to advance the policy epoch.
        expired = connection.execute("""SELECT COUNT(*) FROM mcp_resource_grants g
            WHERE g.expires_at IS NOT NULL AND datetime(g.expires_at)<=datetime('now') AND
            ((g.subject_type='user' AND g.subject_id=?) OR (g.subject_type='role' AND g.subject_id IN
                (SELECT role_id FROM user_roles WHERE user_id=?)))""", (owner.id, owner.id)).fetchone()[0]
        return generation, policy, int(expired)

    def _where(self, connection: sqlite3.Connection, owner: AuthPrincipal, scopes: set[str], *,
               query: str = "", server_id: str = "", access: str = "", published: bool = True) -> tuple[list[str], list[Any]]:
        if owner.auth_type != "session":
            raise OAuthError("session_required", 403)
        connection.create_function("gate_oauth_candidate_allowed", 7, self.access.catalog_authorizer(connection, owner))
        clauses = ["c.source='mcp'", "c.instance_id!=''",
            "gate_oauth_candidate_allowed(c.tool_ref,c.instance_id,c.source,c.permission,c.policy_json,p.effective_access,p.status)=1"]
        params: list[Any] = []
        if published:
            allowed = [level for scope, level in (("tools.read", "read"), ("tools.invoke", "write")) if scope in scopes]
            clauses.extend(["p.status='published'", "p.effective_access IN (" + ",".join("?" for _ in allowed) + ")"])
            params.extend(allowed)
        terms = re.findall(r"[^\W_]+", query.casefold(), re.UNICODE)
        if len(terms) > 8 or len(query.encode()) > 1024:
            raise OAuthError("scope_catalog_query_invalid")
        if query.strip() and not terms:
            raise OAuthError("scope_catalog_query_invalid")
        if terms:
            clauses.append("c.rowid IN (SELECT rowid FROM gate_tool_catalog_fts WHERE gate_tool_catalog_fts MATCH ?)")
            params.append(" AND ".join('"' + term + '"*' for term in terms))
        if server_id:
            clauses.append("c.instance_id=?")
            params.append(server_id)
        if access:
            clauses.append("p.effective_access=?")
            params.append(access)
        return clauses, params

    @staticmethod
    def _counts(connection: sqlite3.Connection, clauses: list[str], params: list[Any]) -> dict[str, int]:
        row = connection.execute("SELECT COUNT(*),COALESCE(SUM(p.effective_access='read'),0),"
            "COALESCE(SUM(p.effective_access='write'),0),COUNT(DISTINCT c.instance_id) " + JOIN +
            " WHERE " + " AND ".join(clauses), params).fetchone()
        return dict(zip(("tools", "read", "write", "mcps"), map(int, row), strict=True))

    def page(self, connection: sqlite3.Connection, owner: AuthPrincipal, scopes: set[str], *,
             query: str, server_id: str, access: str, view: str, after: str, limit: int, grant_scopes: set[str]) -> dict[str, Any]:
        base, base_params = self._where(connection, owner, scopes)
        whole = self._counts(connection, base, base_params)
        unavailable, unavailable_params = self._unavailable_where(connection, owner, scopes)
        unavailable_counts = self._counts(connection, unavailable, unavailable_params)
        if view == "unavailable":
            clauses, params = self._unavailable_where(connection, owner, scopes, query=query, server_id=server_id, access=access)
            matching = self._counts(connection, clauses, params) if (query or server_id or access) else unavailable_counts
            rows = connection.execute("SELECT DISTINCT c.instance_id " + JOIN + " WHERE " + " AND ".join(clauses) +
                " AND c.instance_id>? ORDER BY c.instance_id LIMIT ?", [*params, after, limit + 1]).fetchall()
            ids = [row[0] for row in rows[:limit]]
            groups = {key: {"server_id": key, "server_name": None, "reasons": []} for key in ids}
            if ids:
                reason = """CASE WHEN p.status IS NULL OR p.status!='published' THEN 'classification_not_published'
                    WHEN p.effective_access NOT IN ('read','write') THEN 'classification_unavailable'
                    WHEN (p.effective_access='read' AND ?=0) OR (p.effective_access='write' AND ?=0)
                        THEN 'grant_scope_ceiling' ELSE 'client_scope_ceiling' END"""
                details = connection.execute("SELECT c.instance_id," + reason + " AS reason,COUNT(*) AS count " + JOIN +
                    " WHERE " + " AND ".join(clauses) + " AND c.instance_id IN (" + ",".join("?" for _ in ids) +
                    ") GROUP BY c.instance_id,reason ORDER BY c.instance_id,reason",
                    [int("tools.read" in grant_scopes), int("tools.invoke" in grant_scopes), *params, *ids])
                for row in details:
                    groups[row[0]]["reasons"].append({"code": row[1], "count": row[2]})
            return {"items": list(groups.values()), "has_more": len(rows) > limit, "item_key": "server_id",
                    "catalog_counts": whole, "matching_counts": matching, "unavailable_counts": unavailable_counts}
        clauses, params = self._where(connection, owner, scopes, query=query, server_id=server_id, access=access)
        matching = self._counts(connection, clauses, params) if (query or server_id or access) else whole
        if view == "groups":
            # A filter finds groups, but group counts and selection cover their
            # whole eligible membership, including tools outside the filter.
            query_sql = "SELECT c.instance_id AS server_id,NULL AS server_name,COUNT(*) AS tool_count,"
            query_sql += "SUM(p.effective_access='read') AS read_count,SUM(p.effective_access='write') AS write_count " + JOIN
            query_sql += " WHERE " + " AND ".join(base) + " AND c.instance_id>? AND c.instance_id IN (SELECT c.instance_id "
            query_sql += JOIN + " WHERE " + " AND ".join(clauses) + ") GROUP BY c.instance_id ORDER BY c.instance_id LIMIT ?"
            rows = connection.execute(query_sql, [*base_params, after, *params, limit + 1]).fetchall()
            items = [dict(row) for row in rows]
            key = "server_id"
        else:
            rows = connection.execute("SELECT " + FIELDS + " " + JOIN + " WHERE " + " AND ".join(clauses) +
                " AND c.tool_ref>? ORDER BY c.tool_ref LIMIT ?", [*params, after, limit + 1]).fetchall()
            items = [summary(row) for row in rows]
            key = "id"
        return {"items": items[:limit], "has_more": len(items) > limit, "item_key": key,
                "catalog_counts": whole, "matching_counts": matching, "unavailable_counts": unavailable_counts}

    def _unavailable_where(self, connection: sqlite3.Connection, owner: AuthPrincipal, scopes: set[str], *,
                           query: str = "", server_id: str = "", access: str = "") -> tuple[list[str], list[Any]]:
        clauses, params = self._where(connection, owner, scopes, query=query, server_id=server_id, access=access, published=False)
        clauses.append("(p.status IS NULL OR p.status!='published' OR p.effective_access NOT IN ('read','write') OR "
            "(p.effective_access='read' AND ?=0) OR (p.effective_access='write' AND ?=0))")
        params.extend([int("tools.read" in scopes), int("tools.invoke" in scopes)])
        return clauses, params

    def selected(self, connection: sqlite3.Connection, owner: AuthPrincipal, scopes: set[str],
                 ids: list[str]) -> dict[str, dict[str, Any]]:
        if not ids:
            return {}
        clauses, params = self._where(connection, owner, scopes)
        placeholders = ",".join("?" for _ in ids)
        rows = connection.execute("SELECT " + FIELDS + " " + JOIN + " WHERE " + " AND ".join(clauses) +
            f" AND c.tool_ref IN ({placeholders}) ORDER BY c.tool_ref", [*params, *ids]).fetchall()
        return {row["tool_ref"]: summary(row) for row in rows}

    def resolve(self, connection: sqlite3.Connection, owner: AuthPrincipal, scopes: set[str], *,
                mode: str, server_ids: list[str]) -> list[str]:
        clauses, params = self._where(connection, owner, scopes, access="read" if mode == "read" else "")
        if mode == "groups":
            if not server_ids:
                raise OAuthError("invalid_request")
            clauses.append("c.instance_id IN (" + ",".join("?" for _ in server_ids) + ")")
            params.extend(server_ids)
        counts = self._counts(connection, clauses, params)
        if counts["tools"] > MAX_TOOLS:
            raise OAuthError("scope_selection_tool_limit", 409)
        if counts["mcps"] > 100:
            raise OAuthError("server_scope_limit", 409)
        return [row[0] for row in connection.execute("SELECT c.tool_ref " + JOIN + " WHERE " +
            " AND ".join(clauses) + " ORDER BY c.tool_ref", params)]

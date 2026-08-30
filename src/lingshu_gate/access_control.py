"""MCP 访问治理、工具分类与调用审计。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Iterable
from uuid import uuid4

from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.models import ToolDefinition, ToolInvokeResponse
from lingshu_gate.registry import ToolInvocationContext, ToolRegistry
from lingshu_gate.user_credential_store import UserCredentialBindingError

ACCESS_RANK = {"none": 0, "read": 1, "write": 2, "unknown": -1}
VALID_ACCESS = {"none", "read", "write"}

READ_PATTERNS = {
    "get",
    "list",
    "query",
    "search",
    "read",
    "describe",
    "inspect",
    "status",
    "fetch",
    "find",
    "show",
    "check",
    "preview",
}
WRITE_PATTERNS = {
    "create",
    "update",
    "delete",
    "remove",
    "set",
    "save",
    "upload",
    "publish",
    "execute",
    "send",
    "add",
    "edit",
    "write",
    "start",
    "stop",
    "restart",
    "clear",
    "apply",
    "deploy",
}
DESTRUCTIVE_PATTERNS = {"delete", "remove", "drop", "destroy", "clear", "revoke", "disable", "stop"}
SENSITIVE_KEY_PATTERN = re.compile(r"(password|secret|token|credential|authorization|cookie|api[_-]?key)", re.I)

CONTROL_PERMISSIONS = (
    ("console.view", "查看控制台", "登录并查看基础控制台"),
    ("users.manage", "管理用户", "审核、启用、停用和维护用户"),
    ("roles.manage", "管理角色", "维护角色与控制面权限"),
    ("grants.manage", "管理资源授权", "维护用户和角色的 MCP 授权"),
    ("classifications.manage", "管理工具分类", "分析、确认并发布 Tool 读写分类"),
    ("credentials.manage.self", "管理个人凭据", "维护自己的 Gate API Token 与下游 MCP 凭据"),
    ("credentials.manage.all", "管理全部凭据", "查看并吊销全部用户 API Token，不读取用户下游秘密"),
    ("audit.read", "查看调用审计", "查询 MCP 调用授权和结果审计"),
    ("tools.read", "读取工具", "发现并调用获准的只读 MCP Tool"),
    ("tools.invoke", "调用写工具", "调用获准的写入 MCP Tool"),
    ("operations.manage", "管理运行态", "管理 MCP 配置、服务和运行态"),
)

SYSTEM_ROLES = (
    ("admin", "管理员", "拥有全部控制面权限"),
    ("operator", "运维人员", "管理 MCP 运行态并调用获准工具"),
    ("viewer", "只读观察者", "查看控制台和获准只读工具"),
)

ROLE_PERMISSION_MAP = {
    "admin": {item[0] for item in CONTROL_PERMISSIONS},
    "operator": {
        "console.view",
        "credentials.manage.self",
        "audit.read",
        "tools.read",
        "tools.invoke",
        "operations.manage",
    },
    "viewer": {"console.view", "credentials.manage.self", "tools.read"},
}

SYSTEM_PERMISSION_TYPES = (
    ("none", "无权限", "none", "完全禁止访问"),
    ("read", "只读", "read", "允许调用已发布的只读工具"),
    ("write", "读写", "write", "允许调用已发布的只读和写入工具"),
)


class AccessDeniedError(PermissionError):
    """工具调用未通过访问策略。"""

    def __init__(self, reason: str, *, required_access: str, granted_access: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.required_access = required_access
        self.granted_access = granted_access


class ClassificationConfirmationConflictError(RuntimeError):
    """批量确认目标已不存在或工具元数据已变化。"""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AccessControlStore:
    """SQLite-backed access-control plane shared by REST and MCP gateways."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database
        self.mcp_runtime: McpRuntimeManager | None = None
        self._seed_system_data()

    def attach_mcp_runtime(self, mcp_runtime: McpRuntimeManager) -> None:
        """在应用装配完成后接入带用户上下文的 MCP 调用器。"""

        self.mcp_runtime = mcp_runtime

    # ------------------------------------------------------------------
    # 系统角色、控制面权限与 MCP 权限类型
    # ------------------------------------------------------------------
    def _seed_system_data(self) -> None:
        now = iso_now()
        for code, name, description in CONTROL_PERMISSIONS:
            self.database.execute(
                """
                INSERT OR IGNORE INTO control_permissions
                    (id, code, name, description, is_system, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (f"permission-{code}", code, name, description, now, now),
            )
        for code, name, description in SYSTEM_ROLES:
            role_id = f"role-{code}"
            self.database.execute(
                """
                INSERT OR IGNORE INTO roles
                    (id, code, name, description, is_system, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, 1, ?, ?)
                """,
                (role_id, code, name, description, now, now),
            )
            for permission_code in ROLE_PERMISSION_MAP[code]:
                self.database.execute(
                    """
                    INSERT OR IGNORE INTO role_permissions (role_id, permission_id)
                    SELECT ?, id FROM control_permissions WHERE code = ?
                    """,
                    (role_id, permission_code),
                )
        for code, name, base_level, description in SYSTEM_PERMISSION_TYPES:
            self.database.execute(
                """
                INSERT OR IGNORE INTO permission_types
                    (id, code, name, base_level, description, is_system, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?)
                """,
                (f"permission-type-{code}", code, name, base_level, description, now, now),
            )

    def roles_for_user(self, user_id: str) -> list[str]:
        rows = self.database.query_all(
            """
            SELECT roles.code
            FROM user_roles
            JOIN roles ON roles.id = user_roles.role_id
            WHERE user_roles.user_id = ? AND roles.enabled = 1
            ORDER BY roles.is_system DESC, roles.code
            """,
            (user_id,),
        )
        return [str(row["code"]) for row in rows]

    def permissions_for_user(self, user_id: str) -> list[str]:
        rows = self.database.query_all(
            """
            SELECT DISTINCT control_permissions.code
            FROM user_roles
            JOIN roles ON roles.id = user_roles.role_id AND roles.enabled = 1
            JOIN role_permissions ON role_permissions.role_id = roles.id
            JOIN control_permissions ON control_permissions.id = role_permissions.permission_id
            WHERE user_roles.user_id = ?
            ORDER BY control_permissions.code
            """,
            (user_id,),
        )
        return [str(row["code"]) for row in rows]

    def set_user_roles(self, user_id: str, role_codes: Iterable[str]) -> None:
        codes = sorted({str(code).strip() for code in role_codes if str(code).strip()})
        if not codes:
            raise ValueError("at least one role is required")
        placeholders = ",".join("?" for _ in codes)
        rows = self.database.query_all(
            f"SELECT id, code FROM roles WHERE code IN ({placeholders}) AND enabled = 1",
            tuple(codes),
        )
        if len(rows) != len(codes):
            found = {str(row["code"]) for row in rows}
            raise ValueError(f"unknown or disabled role(s): {', '.join(sorted(set(codes) - found))}")
        self.database.execute("DELETE FROM user_roles WHERE user_id = ?", (user_id,))
        for row in rows:
            self.database.execute(
                "INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)",
                (user_id, row["id"]),
            )

    def has_control_permission(self, principal: AuthPrincipal, permission_code: str) -> bool:
        roles = set(getattr(principal, "roles", ()) or (principal.role,))
        role_allows = principal.role == "admin" or "admin" in roles
        role_allows = role_allows or permission_code in set(getattr(principal, "permissions", ()))
        if not role_allows:
            return False
        if principal.auth_type != "token":
            return True
        scopes = set(getattr(principal, "scopes", ()))
        return "*" in scopes or permission_code in scopes

    def require_control_permission(self, principal: AuthPrincipal, permission_code: str) -> None:
        if not self.has_control_permission(principal, permission_code):
            raise AccessDeniedError(
                f"missing control permission: {permission_code}",
                required_access=permission_code,
                granted_access="none",
            )

    def list_roles(self) -> list[dict[str, Any]]:
        rows = self.database.query_all(
            """
            SELECT roles.*,
                   COUNT(DISTINCT user_roles.user_id) AS member_count
            FROM roles
            LEFT JOIN user_roles ON user_roles.role_id = roles.id
            GROUP BY roles.id
            ORDER BY roles.is_system DESC, roles.name
            """
        )
        result: list[dict[str, Any]] = []
        for row in rows:
            permissions = self.database.query_all(
                """
                SELECT control_permissions.code
                FROM role_permissions
                JOIN control_permissions ON control_permissions.id = role_permissions.permission_id
                WHERE role_permissions.role_id = ?
                ORDER BY control_permissions.code
                """,
                (row["id"],),
            )
            result.append(
                {
                    "id": row["id"],
                    "code": row["code"],
                    "name": row["name"],
                    "description": row["description"],
                    "is_system": bool(row["is_system"]),
                    "enabled": bool(row["enabled"]),
                    "member_count": int(row["member_count"]),
                    "permissions": [item["code"] for item in permissions],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return result

    def save_role(
        self,
        *,
        code: str,
        name: str,
        description: str,
        permissions: Iterable[str],
        role_id: str | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        code = _normalize_code(code)
        name = name.strip()
        if not name:
            raise ValueError("role name is required")
        target_id = role_id or f"role-{uuid4()}"
        existing = self.database.query_one("SELECT * FROM roles WHERE id = ?", (target_id,))
        if existing and existing["is_system"] and code != existing["code"]:
            raise ValueError("system role code cannot be changed")
        if existing and existing["is_system"] and not enabled:
            raise ValueError("system role cannot be disabled")
        duplicate = self.database.query_one("SELECT id FROM roles WHERE code = ? AND id <> ?", (code, target_id))
        if duplicate:
            raise ValueError(f"role code already exists: {code}")
        permission_codes = sorted({str(item).strip() for item in permissions if str(item).strip()})
        permission_rows: dict[str, str] = {}
        for permission_code in permission_codes:
            row = self.database.query_one("SELECT id FROM control_permissions WHERE code = ?", (permission_code,))
            if not row:
                raise ValueError(f"unknown control permission: {permission_code}")
            permission_rows[permission_code] = str(row["id"])
        now = iso_now()
        if existing:
            self.database.execute(
                "UPDATE roles SET code = ?, name = ?, description = ?, enabled = ?, updated_at = ? WHERE id = ?",
                (code, name, description.strip(), int(enabled), now, target_id),
            )
        else:
            self.database.execute(
                """
                INSERT INTO roles (id, code, name, description, is_system, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (target_id, code, name, description.strip(), int(enabled), now, now),
            )
        self.database.execute("DELETE FROM role_permissions WHERE role_id = ?", (target_id,))
        for permission_code in permission_codes:
            self.database.execute(
                "INSERT INTO role_permissions (role_id, permission_id) VALUES (?, ?)",
                (target_id, permission_rows[permission_code]),
            )
        return next(item for item in self.list_roles() if item["id"] == target_id)

    def delete_role(self, role_id: str) -> None:
        row = self.database.query_one("SELECT is_system FROM roles WHERE id = ?", (role_id,))
        if not row:
            raise KeyError(f"role not found: {role_id}")
        if row["is_system"]:
            raise ValueError("system role cannot be deleted")
        assigned = self.database.query_one("SELECT COUNT(*) AS total FROM user_roles WHERE role_id = ?", (role_id,))
        if assigned and assigned["total"]:
            raise ValueError("role is assigned to users")
        self.database.execute("DELETE FROM roles WHERE id = ?", (role_id,))

    def list_control_permissions(self) -> list[dict[str, Any]]:
        rows = self.database.query_all("SELECT * FROM control_permissions ORDER BY code")
        return [
            {
                "id": row["id"],
                "code": row["code"],
                "name": row["name"],
                "description": row["description"],
                "is_system": bool(row["is_system"]),
            }
            for row in rows
        ]

    def list_permission_types(self) -> list[dict[str, Any]]:
        rows = self.database.query_all(
            """
            SELECT permission_types.*,
                   COUNT(mcp_resource_grants.id) AS reference_count
            FROM permission_types
            LEFT JOIN mcp_resource_grants
                ON mcp_resource_grants.permission_type_id = permission_types.id
            GROUP BY permission_types.id
            ORDER BY permission_types.is_system DESC,
                     CASE permission_types.base_level WHEN 'none' THEN 0 WHEN 'read' THEN 1 ELSE 2 END,
                     permission_types.name
            """
        )
        return [
            {
                "id": row["id"],
                "code": row["code"],
                "name": row["name"],
                "base_level": row["base_level"],
                "description": row["description"],
                "is_system": bool(row["is_system"]),
                "enabled": bool(row["enabled"]),
                "reference_count": int(row["reference_count"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def save_permission_type(
        self,
        *,
        code: str,
        name: str,
        base_level: str,
        description: str,
        permission_type_id: str | None = None,
        enabled: bool = True,
    ) -> dict[str, Any]:
        code = _normalize_code(code)
        name = name.strip()
        if base_level not in VALID_ACCESS:
            raise ValueError("base_level must be none, read, or write")
        if not name:
            raise ValueError("permission type name is required")
        target_id = permission_type_id or f"permission-type-{uuid4()}"
        existing = self.database.query_one("SELECT * FROM permission_types WHERE id = ?", (target_id,))
        if existing and existing["is_system"]:
            if code != existing["code"] or base_level != existing["base_level"]:
                raise ValueError("system permission type semantics cannot be changed")
            if not enabled:
                raise ValueError("system permission type cannot be disabled")
        duplicate = self.database.query_one(
            "SELECT id FROM permission_types WHERE code = ? AND id <> ?",
            (code, target_id),
        )
        if duplicate:
            raise ValueError(f"permission type code already exists: {code}")
        now = iso_now()
        if existing:
            self.database.execute(
                """
                UPDATE permission_types
                SET code = ?, name = ?, base_level = ?, description = ?, enabled = ?, updated_at = ?
                WHERE id = ?
                """,
                (code, name, base_level, description.strip(), int(enabled), now, target_id),
            )
        else:
            self.database.execute(
                """
                INSERT INTO permission_types
                    (id, code, name, base_level, description, is_system, enabled, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
                """,
                (target_id, code, name, base_level, description.strip(), int(enabled), now, now),
            )
        return next(item for item in self.list_permission_types() if item["id"] == target_id)

    def delete_permission_type(self, permission_type_id: str) -> None:
        row = self.database.query_one(
            "SELECT is_system FROM permission_types WHERE id = ?",
            (permission_type_id,),
        )
        if not row:
            raise KeyError(f"permission type not found: {permission_type_id}")
        if row["is_system"]:
            raise ValueError("system permission type cannot be deleted")
        referenced = self.database.query_one(
            "SELECT COUNT(*) AS total FROM mcp_resource_grants WHERE permission_type_id = ?",
            (permission_type_id,),
        )
        if referenced and referenced["total"]:
            raise ValueError("permission type is referenced by grants")
        self.database.execute("DELETE FROM permission_types WHERE id = ?", (permission_type_id,))

    # ------------------------------------------------------------------
    # MCP 资源授权
    # ------------------------------------------------------------------
    def list_grants(
        self,
        *,
        server_id: str | None = None,
        subject_type: str | None = None,
        subject_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if server_id:
            clauses.append("mcp_resource_grants.server_id = ?")
            params.append(server_id)
        if subject_type:
            clauses.append("mcp_resource_grants.subject_type = ?")
            params.append(subject_type)
        if subject_id:
            clauses.append("mcp_resource_grants.subject_id = ?")
            params.append(subject_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.database.query_all(
            f"""
            SELECT mcp_resource_grants.*, permission_types.code AS permission_type_code,
                   permission_types.name AS permission_type_name,
                   permission_types.base_level
            FROM mcp_resource_grants
            JOIN permission_types ON permission_types.id = mcp_resource_grants.permission_type_id
            {where}
            ORDER BY mcp_resource_grants.server_id, mcp_resource_grants.subject_type,
                     mcp_resource_grants.subject_id, mcp_resource_grants.tool_id
            """,
            tuple(params),
        )
        return [
            {
                "id": row["id"],
                "subject_type": row["subject_type"],
                "subject_id": row["subject_id"],
                "server_id": row["server_id"],
                "tool_id": row["tool_id"] or None,
                "permission_type_id": row["permission_type_id"],
                "permission_type_code": row["permission_type_code"],
                "permission_type_name": row["permission_type_name"],
                "base_level": row["base_level"],
                "expires_at": row["expires_at"],
                "created_by": row["created_by"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def save_grant(
        self,
        *,
        subject_type: str,
        subject_id: str,
        server_id: str,
        permission_type_code: str,
        created_by: str,
        tool_id: str | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        if subject_type not in {"user", "role"}:
            raise ValueError("subject_type must be user or role")
        if not subject_id.strip() or not server_id.strip():
            raise ValueError("subject_id and server_id are required")
        subject_table = "users" if subject_type == "user" else "roles"
        subject = self.database.query_one(f"SELECT id FROM {subject_table} WHERE id = ?", (subject_id,))
        if not subject:
            raise ValueError(f"{subject_type} not found: {subject_id}")
        permission_type = self.database.query_one(
            "SELECT id FROM permission_types WHERE code = ? AND enabled = 1",
            (permission_type_code,),
        )
        if not permission_type:
            raise ValueError(f"permission type not found or disabled: {permission_type_code}")
        normalized_tool_id = (tool_id or "").strip()
        existing = self.database.query_one(
            """
            SELECT id, created_at FROM mcp_resource_grants
            WHERE subject_type = ? AND subject_id = ? AND server_id = ? AND tool_id = ?
            """,
            (subject_type, subject_id, server_id.strip(), normalized_tool_id),
        )
        now = iso_now()
        if existing:
            grant_id = existing["id"]
            self.database.execute(
                """
                UPDATE mcp_resource_grants
                SET permission_type_id = ?, expires_at = ?, created_by = ?, updated_at = ?
                WHERE id = ?
                """,
                (permission_type["id"], expires_at, created_by, now, grant_id),
            )
        else:
            grant_id = str(uuid4())
            self.database.execute(
                """
                INSERT INTO mcp_resource_grants
                    (id, subject_type, subject_id, server_id, tool_id, permission_type_id,
                     expires_at, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    grant_id,
                    subject_type,
                    subject_id,
                    server_id.strip(),
                    normalized_tool_id,
                    permission_type["id"],
                    expires_at,
                    created_by,
                    now,
                    now,
                ),
            )
        return next(item for item in self.list_grants() if item["id"] == grant_id)

    def delete_grant(self, grant_id: str) -> None:
        row = self.database.query_one("SELECT id FROM mcp_resource_grants WHERE id = ?", (grant_id,))
        if not row:
            raise KeyError(f"grant not found: {grant_id}")
        self.database.execute("DELETE FROM mcp_resource_grants WHERE id = ?", (grant_id,))

    # ------------------------------------------------------------------
    # Tool 读写分类
    # ------------------------------------------------------------------
    def synchronize_tools(
        self,
        definitions: Iterable[ToolDefinition],
    ) -> list[dict[str, Any]]:
        now = iso_now()
        for definition in definitions:
            server_id = _server_id(definition)
            fingerprint = _tool_fingerprint(definition)
            suggestion = _suggest_tool(definition)
            existing = self.database.query_one(
                "SELECT * FROM mcp_tool_classifications WHERE server_id = ? AND tool_id = ?",
                (server_id, definition.id),
            )
            evidence_json = json.dumps(suggestion["evidence"], ensure_ascii=False)
            if not existing:
                # Console 首次加载可能并发触发同步；由数据库原子忽略重复插入，
                # 避免两个请求同时完成查询后争抢同一个工具唯一键。
                self.database.execute(
                    """
                    INSERT INTO mcp_tool_classifications
                        (id, server_id, tool_id, tool_name, fingerprint, suggested_access,
                         effective_access, status, confidence, source, destructive, idempotent,
                         open_world, evidence_json, reviewed_by, reviewed_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(server_id, tool_id) DO NOTHING
                    """,
                    (
                        str(uuid4()),
                        server_id,
                        definition.id,
                        definition.name,
                        fingerprint,
                        suggestion["access"],
                        "unknown",
                        "pending",
                        suggestion["confidence"],
                        suggestion["source"],
                        int(suggestion["destructive"]),
                        int(suggestion["idempotent"]),
                        int(suggestion["open_world"]),
                        evidence_json,
                        None,
                        None,
                        now,
                        now,
                    ),
                )
                continue
            if existing["fingerprint"] != fingerprint:
                self.database.execute(
                    """
                    UPDATE mcp_tool_classifications
                    SET tool_name = ?, fingerprint = ?, suggested_access = ?,
                        effective_access = 'unknown', status = 'stale', confidence = ?,
                        source = ?, destructive = ?, idempotent = ?, open_world = ?,
                        evidence_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        definition.name,
                        fingerprint,
                        suggestion["access"],
                        suggestion["confidence"],
                        suggestion["source"],
                        int(suggestion["destructive"]),
                        int(suggestion["idempotent"]),
                        int(suggestion["open_world"]),
                        evidence_json,
                        now,
                        existing["id"],
                    ),
                )
            elif (
                existing["status"] != "published"
                and existing["source"] != "manual"
            ):
                self.database.execute(
                    """
                    UPDATE mcp_tool_classifications
                    SET tool_name = ?, suggested_access = ?, confidence = ?, source = ?,
                        destructive = ?, idempotent = ?, open_world = ?, evidence_json = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        definition.name,
                        suggestion["access"],
                        suggestion["confidence"],
                        suggestion["source"],
                        int(suggestion["destructive"]),
                        int(suggestion["idempotent"]),
                        int(suggestion["open_world"]),
                        evidence_json,
                        now,
                        existing["id"],
                    ),
                )
        return self.list_classifications()

    def analyze_tools(
        self,
        definitions: Iterable[ToolDefinition],
    ) -> list[dict[str, Any]]:
        definitions_list = list(definitions)
        self.synchronize_tools(definitions_list)
        return self.list_classifications()

    def reconcile_server_tools(
        self,
        server_id: str,
        definitions: Iterable[ToolDefinition],
        reviewer_id: str,
    ) -> dict[str, Any]:
        """按目标 Server 对账工具事实；只收紧分类，不确认、发布或授予权限。"""

        definitions_list = list(definitions)
        mismatched = sorted(
            definition.id
            for definition in definitions_list
            if _server_id(definition) != server_id
        )
        if mismatched:
            raise ValueError(
                "tool definition server_id mismatch: " + ", ".join(mismatched)
            )

        before = {
            item["tool_id"]: item
            for item in self.list_classifications(server_id=server_id)
        }
        self.synchronize_tools(definitions_list)
        current_ids = {definition.id for definition in definitions_list}
        now = iso_now()

        retired_ids: list[str] = []
        for tool_id in sorted(set(before) - current_ids):
            lifecycle = dict(before[tool_id].get("evidence") or {}).get("lifecycle")
            if not isinstance(lifecycle, dict) or lifecycle.get("status") != "retired":
                retired_ids.append(tool_id)
        for tool_id in retired_ids:
            previous = before[tool_id]
            evidence = dict(previous.get("evidence") or {})
            evidence["lifecycle"] = {
                "status": "retired",
                "reason": "missing_from_latest_tools_list",
                "actor_id": reviewer_id,
                "at": now,
            }
            self.database.execute(
                """
                UPDATE mcp_tool_classifications
                SET suggested_access = 'unknown', effective_access = 'unknown',
                    status = 'stale', evidence_json = ?, reviewed_at = NULL,
                    updated_at = ?
                WHERE server_id = ? AND tool_id = ?
                """,
                (json.dumps(evidence, ensure_ascii=False), now, server_id, tool_id),
            )

        reappeared_ids: list[str] = []
        for definition in definitions_list:
            previous_record = before.get(definition.id)
            lifecycle = dict((previous_record or {}).get("evidence") or {}).get("lifecycle")
            if not isinstance(lifecycle, dict) or lifecycle.get("status") != "retired":
                continue
            reappeared_ids.append(definition.id)
            row = self.database.query_one(
                """
                SELECT evidence_json FROM mcp_tool_classifications
                WHERE server_id = ? AND tool_id = ?
                """,
                (server_id, definition.id),
            )
            evidence = _loads(row["evidence_json"]) if row else {}
            evidence["lifecycle"] = {
                "status": "active",
                "reason": "reappeared_in_tools_list",
                "actor_id": reviewer_id,
                "at": now,
            }
            self.database.execute(
                """
                UPDATE mcp_tool_classifications
                SET effective_access = 'unknown', status = 'stale',
                    evidence_json = ?, reviewed_at = NULL, updated_at = ?
                WHERE server_id = ? AND tool_id = ?
                """,
                (json.dumps(evidence, ensure_ascii=False), now, server_id, definition.id),
            )

        after = {
            item["tool_id"]: item
            for item in self.list_classifications(server_id=server_id)
        }
        new_ids = sorted(current_ids - set(before))
        changed_ids = sorted(
            tool_id
            for tool_id in current_ids & set(before)
            if before[tool_id]["fingerprint"] != after[tool_id]["fingerprint"]
            and tool_id not in reappeared_ids
        )
        unchanged_ids = sorted(
            current_ids
            - set(new_ids)
            - set(changed_ids)
            - set(reappeared_ids)
        )
        permissions_expanded = any(
            ACCESS_RANK.get(str(after[tool_id]["effective_access"]), -1)
            > ACCESS_RANK.get(str(before.get(tool_id, {}).get("effective_access", "unknown")), -1)
            for tool_id in current_ids
        )
        if permissions_expanded:
            raise RuntimeError("tool reconciliation unexpectedly expanded effective permissions")

        needs_review_ids = sorted(
            tool_id
            for tool_id in current_ids
            if after[tool_id]["status"] != "published"
        )
        return {
            "server_id": server_id,
            "counts": {
                "discovered": len(current_ids),
                "unchanged": len(unchanged_ids),
                "new": len(new_ids),
                "changed": len(changed_ids),
                "reappeared": len(reappeared_ids),
                "retired": len(retired_ids),
                "needs_review": len(needs_review_ids),
            },
            "new_tool_ids": new_ids,
            "changed_tool_ids": changed_ids,
            "reappeared_tool_ids": sorted(reappeared_ids),
            "retired_tool_ids": retired_ids,
            "needs_review_tool_ids": needs_review_ids,
            "effective_permissions_expanded": False,
        }

    def list_classifications(
        self,
        *,
        server_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if server_id:
            clauses.append("server_id = ?")
            params.append(server_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.database.query_all(
            f"SELECT * FROM mcp_tool_classifications {where} ORDER BY server_id, tool_name",
            tuple(params),
        )
        return [_classification_row(row) for row in rows]

    def set_classification(
        self,
        *,
        server_id: str,
        tool_id: str,
        access: str,
        destructive: bool,
        idempotent: bool,
        reviewer_id: str,
        note: str = "",
    ) -> dict[str, Any]:
        if access not in {"read", "write", "unknown"}:
            raise ValueError("access must be read, write, or unknown")
        row = self.database.query_one(
            "SELECT * FROM mcp_tool_classifications WHERE server_id = ? AND tool_id = ?",
            (server_id, tool_id),
        )
        if not row:
            raise KeyError(f"tool classification not found: {server_id}/{tool_id}")
        evidence = _loads(row["evidence_json"])
        evidence["manual"] = {"note": note.strip(), "reviewer_id": reviewer_id}
        now = iso_now()
        self.database.execute(
            """
            UPDATE mcp_tool_classifications
            SET effective_access = ?, status = 'pending', source = 'manual',
                destructive = ?, idempotent = ?, evidence_json = ?,
                reviewed_by = ?, reviewed_at = NULL, updated_at = ?
            WHERE id = ?
            """,
            (
                access,
                int(destructive),
                int(idempotent),
                json.dumps(evidence, ensure_ascii=False),
                reviewer_id,
                now,
                row["id"],
            ),
        )
        return next(
            item
            for item in self.list_classifications(server_id=server_id)
            if item["tool_id"] == tool_id
        )

    def confirm_classifications(
        self,
        *,
        reviewer_id: str,
        items: Iterable[dict[str, Any]],
        note: str = "",
    ) -> dict[str, Any]:
        """按每条工具的人工结论或机器建议原子完成批量确认。

        确认只生成待发布的人工结论，不直接改变运行时授权。先在同一写事务中
        校验全部目标及 fingerprint，避免部分成功或基于旧元数据误确认。
        """

        raw_items = list(items)
        if not raw_items:
            raise ValueError("at least one tool classification is required")
        if len(raw_items) > 500:
            raise ValueError("at most 500 tool classifications can be confirmed at once")

        targets: dict[tuple[str, str], str] = {}
        for item in raw_items:
            if not isinstance(item, dict):
                raise ValueError("tool classification item must be an object")
            server_id = str(item.get("server_id") or "").strip()
            tool_id = str(item.get("tool_id") or "").strip()
            expected_fingerprint = str(item.get("expected_fingerprint") or "").strip()
            if not server_id or not tool_id or not expected_fingerprint:
                raise ValueError("server_id, tool_id, and expected_fingerprint are required")
            key = (server_id, tool_id)
            previous_fingerprint = targets.get(key)
            if previous_fingerprint and previous_fingerprint != expected_fingerprint:
                raise ClassificationConfirmationConflictError(
                    f"conflicting fingerprints for tool classification: {server_id}/{tool_id}"
                )
            targets[key] = expected_fingerprint

        note_text = str(note or "").strip()
        now = iso_now()
        confirmed: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []

        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows: dict[tuple[str, str], Any] = {}
            # 必须先完成整批校验再写入，任一目标缺失或版本冲突都由事务整体回滚。
            for (server_id, tool_id), expected_fingerprint in targets.items():
                row = connection.execute(
                    """
                    SELECT *
                    FROM mcp_tool_classifications
                    WHERE server_id = ? AND tool_id = ?
                    """,
                    (server_id, tool_id),
                ).fetchone()
                if not row:
                    raise ClassificationConfirmationConflictError(
                        f"tool classification not found: {server_id}/{tool_id}"
                    )
                if str(row["fingerprint"]) != expected_fingerprint:
                    raise ClassificationConfirmationConflictError(
                        f"tool classification fingerprint changed: {server_id}/{tool_id}"
                    )
                rows[(server_id, tool_id)] = row

            for (server_id, tool_id), row in rows.items():
                if row["status"] == "published":
                    skipped.append(
                        {
                            "server_id": server_id,
                            "tool_id": tool_id,
                            "reason": "published",
                        }
                    )
                    continue

                effective_access = str(row["effective_access"])
                confirmed_from = "effective"
                if effective_access not in {"read", "write"}:
                    effective_access = str(row["suggested_access"])
                    confirmed_from = "suggested"
                if effective_access not in {"read", "write"}:
                    skipped.append(
                        {
                            "server_id": server_id,
                            "tool_id": tool_id,
                            "reason": "unknown",
                        }
                    )
                    continue

                evidence = _loads(row["evidence_json"])
                evidence["confirmation"] = {
                    "note": note_text,
                    "reviewer_id": reviewer_id,
                    "confirmed_from": confirmed_from,
                }
                connection.execute(
                    """
                    UPDATE mcp_tool_classifications
                    SET effective_access = ?, status = 'pending', source = 'manual',
                        evidence_json = ?, reviewed_by = ?, reviewed_at = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        effective_access,
                        json.dumps(evidence, ensure_ascii=False),
                        reviewer_id,
                        now,
                        row["id"],
                    ),
                )
                updated = connection.execute(
                    "SELECT * FROM mcp_tool_classifications WHERE id = ?",
                    (row["id"],),
                ).fetchone()
                if updated:
                    confirmed.append(_classification_row(updated))

        return {
            "confirmed": confirmed,
            "skipped": skipped,
            "confirmed_count": len(confirmed),
            "skipped_count": len(skipped),
            "total_count": len(targets),
        }

    def publish_classifications(
        self,
        *,
        reviewer_id: str,
        server_id: str | None = None,
        tool_ids: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        clauses = ["effective_access IN ('read', 'write')"]
        params: list[Any] = []
        if server_id:
            clauses.append("server_id = ?")
            params.append(server_id)
        ids = sorted({str(item) for item in (tool_ids or []) if str(item)})
        if ids:
            placeholders = ",".join("?" for _ in ids)
            clauses.append(f"tool_id IN ({placeholders})")
            params.extend(ids)
        now = iso_now()
        rows = self.database.query_all(
            f"SELECT id FROM mcp_tool_classifications WHERE {' AND '.join(clauses)}",
            tuple(params),
        )
        for row in rows:
            self.database.execute(
                """
                UPDATE mcp_tool_classifications
                SET status = 'published', reviewed_by = ?, reviewed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (reviewer_id, now, now, row["id"]),
            )
        return self.list_classifications(server_id=server_id)

    # ------------------------------------------------------------------
    # 运行时授权与调用审计
    # ------------------------------------------------------------------
    def visible_tools(
        self,
        principal: AuthPrincipal,
        definitions: Iterable[ToolDefinition],
    ) -> list[ToolDefinition]:
        definitions_list = list(definitions)
        self.synchronize_tools(definitions_list)
        return [
            definition
            for definition in definitions_list
            if self.evaluate(principal, definition)["allowed"]
        ]

    def evaluate(self, principal: AuthPrincipal, definition: ToolDefinition) -> dict[str, Any]:
        server_id = _server_id(definition)
        required_control_permission = definition.metadata.get("required_control_permission")
        if not isinstance(required_control_permission, str) or not required_control_permission.strip():
            required_control_permission = None
        else:
            required_control_permission = required_control_permission.strip()
        classification = self.database.query_one(
            "SELECT * FROM mcp_tool_classifications WHERE server_id = ? AND tool_id = ?",
            (server_id, definition.id),
        )
        roles = set(getattr(principal, "roles", ()) or (principal.role,))
        if (
            definition.metadata.get("classification_control_plane") is True
            and required_control_permission == "classifications.manage"
        ):
            # 分类治理工具必须在下游工具尚未发布时仍可被审核员发现；
            # 这里跳过的是 Tool 分类状态，不是控制面权限校验。
            allowed = self.has_control_permission(principal, required_control_permission)
            return {
                "allowed": allowed,
                "reason": (
                    "classification control-plane permission matched"
                    if allowed
                    else f"missing control permission: {required_control_permission}"
                ),
                "server_id": server_id,
                "required_access": "read" if definition.permission.startswith("read") else "write",
                "granted_access": "write" if allowed else "none",
                "classification_status": "control_plane",
            }
        if principal.role == "admin" or "admin" in roles:
            required = (
                classification["effective_access"]
                if classification and classification["effective_access"] in {"read", "write"}
                else "write"
            )
            required_permission = "tools.read" if required == "read" else "tools.invoke"
            control_allowed = _principal_control_allows(principal, required_permission)
            token_allowed = _token_scope_allows(principal, required)
            extra_control_allowed = (
                required_control_permission is None
                or self.has_control_permission(principal, required_control_permission)
            )
            allowed = control_allowed and token_allowed and extra_control_allowed
            if not control_allowed:
                reason = f"missing control permission: {required_permission}"
            elif not token_allowed:
                reason = "API token scope does not allow this operation"
            elif not extra_control_allowed:
                reason = f"missing control permission: {required_control_permission}"
            else:
                reason = "admin bypass"
            return {
                "allowed": allowed,
                "reason": reason,
                "server_id": server_id,
                "required_access": required,
                "granted_access": "write",
                "classification_status": classification["status"] if classification else "missing",
            }
        if (
            not classification
            or classification["status"] != "published"
            or classification["effective_access"] not in {"read", "write"}
        ):
            return {
                "allowed": False,
                "reason": "tool classification is not published",
                "server_id": server_id,
                "required_access": "unknown",
                "granted_access": self.effective_access(principal, server_id, definition.id),
                "classification_status": classification["status"] if classification else "missing",
            }
        required = str(classification["effective_access"])
        required_permission = "tools.read" if required == "read" else "tools.invoke"
        granted = self.effective_access(principal, server_id, definition.id)
        if not _principal_control_allows(principal, required_permission):
            return {
                "allowed": False,
                "reason": f"missing control permission: {required_permission}",
                "server_id": server_id,
                "required_access": required,
                "granted_access": granted,
                "classification_status": classification["status"],
            }
        if not _token_scope_allows(principal, required):
            return {
                "allowed": False,
                "reason": "API token scope does not allow this operation",
                "server_id": server_id,
                "required_access": required,
                "granted_access": granted,
                "classification_status": classification["status"],
            }
        if required_control_permission and not self.has_control_permission(principal, required_control_permission):
            return {
                "allowed": False,
                "reason": f"missing control permission: {required_control_permission}",
                "server_id": server_id,
                "required_access": required,
                "granted_access": granted,
                "classification_status": classification["status"],
            }
        allowed = ACCESS_RANK.get(granted, 0) >= ACCESS_RANK[required]
        return {
            "allowed": allowed,
            "reason": "grant matched" if allowed else f"{required} access is required",
            "server_id": server_id,
            "required_access": required,
            "granted_access": granted,
            "classification_status": classification["status"],
        }

    def effective_access(self, principal: AuthPrincipal, server_id: str, tool_id: str) -> str:
        roles = set(getattr(principal, "roles", ()) or (principal.role,))
        if principal.role == "admin" or "admin" in roles:
            return "write"
        direct_tool = self._grant_level("user", principal.id, server_id, tool_id)
        if direct_tool is not None:
            return direct_tool
        direct_server = self._grant_level("user", principal.id, server_id, "")
        if direct_server is not None:
            return direct_server
        role_ids = self.database.query_all(
            """
            SELECT roles.id
            FROM user_roles
            JOIN roles ON roles.id = user_roles.role_id
            WHERE user_roles.user_id = ? AND roles.enabled = 1
            """,
            (principal.id,),
        )
        levels: list[str] = []
        for role in role_ids:
            level = self._grant_level("role", role["id"], server_id, tool_id)
            if level is None:
                level = self._grant_level("role", role["id"], server_id, "")
            if level is not None:
                levels.append(level)
        return max(levels, key=lambda item: ACCESS_RANK[item]) if levels else "none"

    def delivery_target_access(
        self,
        context: ToolInvocationContext,
        server_id: str,
        required_access: str,
    ) -> bool:
        """复用现有服务级 grant，校验自动交付所指向的目标 MCP Server。"""

        if required_access not in {"read", "write"}:
            raise ValueError(f"invalid target access: {required_access}")
        roles = tuple(context.roles)
        if "admin" in roles or "*" in context.permissions:
            return True
        role = roles[0] if roles else "viewer"
        principal = AuthPrincipal(
            id=context.actor_id,
            username=context.username,
            role=role,
            auth_type=context.auth_type,
            roles=roles,
            permissions=tuple(context.permissions),
            token_id=context.token_id,
            scopes=tuple(context.scopes),
        )
        if not self.has_control_permission(principal, "operations.manage"):
            return False
        granted = self.effective_access(principal, server_id, "")
        return ACCESS_RANK.get(granted, 0) >= ACCESS_RANK[required_access]

    def _grant_level(
        self,
        subject_type: str,
        subject_id: str,
        server_id: str,
        tool_id: str,
    ) -> str | None:
        row = self.database.query_one(
            """
            SELECT permission_types.base_level, mcp_resource_grants.expires_at
            FROM mcp_resource_grants
            JOIN permission_types ON permission_types.id = mcp_resource_grants.permission_type_id
            WHERE mcp_resource_grants.subject_type = ?
              AND mcp_resource_grants.subject_id = ?
              AND mcp_resource_grants.server_id = ?
              AND mcp_resource_grants.tool_id = ?
              AND permission_types.enabled = 1
            """,
            (subject_type, subject_id, server_id, tool_id),
        )
        if not row or _is_expired(row["expires_at"]):
            return None
        return str(row["base_level"])

    def invoke_tool(
        self,
        registry: ToolRegistry,
        principal: AuthPrincipal,
        tool_id: str,
        arguments: dict[str, Any],
        *,
        correlation_id: str | None = None,
    ) -> ToolInvokeResponse:
        definition = registry.get_definition(tool_id)
        self.synchronize_tools([definition])
        decision = self.evaluate(principal, definition)
        correlation_id = correlation_id or str(uuid4())
        summary = _payload_summary(arguments)
        if not decision["allowed"]:
            self._record_invocation_audit(
                principal,
                definition,
                correlation_id=correlation_id,
                decision=decision,
                outcome="not_invoked",
                duration_ms=None,
                payload=summary,
            )
            raise AccessDeniedError(
                decision["reason"],
                required_access=decision["required_access"],
                granted_access=decision["granted_access"],
            )
        started = perf_counter()
        try:
            if definition.source == "mcp" and self.mcp_runtime:
                server_id = str(definition.metadata.get("server_id") or "")
                tool_name = str(definition.metadata.get("original_tool_name") or "")
                if not server_id or not tool_name:
                    raise RuntimeError(f"MCP tool metadata is incomplete: {tool_id}")
                output = self.mcp_runtime.invoke_mcp_tool_for_user(
                    server_id,
                    tool_name,
                    arguments,
                    user_id=principal.id,
                )
                response = ToolInvokeResponse(ok=True, tool_id=tool_id, output=output)
            else:
                response = registry.invoke(
                    tool_id,
                    arguments,
                    context=ToolInvocationContext(
                        actor_id=principal.id,
                        username=principal.username,
                        auth_type=principal.auth_type,
                        token_id=getattr(principal, "token_id", None),
                        correlation_id=correlation_id,
                        roles=tuple(getattr(principal, "roles", ()) or (principal.role,)),
                        permissions=tuple(getattr(principal, "permissions", ())),
                        scopes=tuple(getattr(principal, "scopes", ())),
                    ),
                )
        except UserCredentialBindingError as exc:
            credential_decision = {
                **decision,
                "allowed": False,
                "reason": str(exc),
            }
            duration_ms = max(0, round((perf_counter() - started) * 1000))
            self._record_invocation_audit(
                principal,
                definition,
                correlation_id=correlation_id,
                decision=credential_decision,
                outcome="not_invoked",
                duration_ms=duration_ms,
                payload=summary,
            )
            raise AccessDeniedError(
                str(exc),
                required_access=decision["required_access"],
                granted_access=decision["granted_access"],
            ) from exc
        except Exception as exc:  # noqa: BLE001 - 工具边界统一返回失败响应
            response = ToolInvokeResponse(ok=False, tool_id=tool_id, error=str(exc))
        duration_ms = max(0, round((perf_counter() - started) * 1000))
        self._record_invocation_audit(
            principal,
            definition,
            correlation_id=correlation_id,
            decision=decision,
            outcome="success" if response.ok else "error",
            duration_ms=duration_ms,
            payload=summary,
        )
        return response

    def _record_invocation_audit(
        self,
        principal: AuthPrincipal,
        definition: ToolDefinition,
        *,
        correlation_id: str,
        decision: dict[str, Any],
        outcome: str,
        duration_ms: int | None,
        payload: dict[str, Any],
    ) -> None:
        self.database.execute(
            """
            INSERT INTO invocation_audits
                (id, correlation_id, user_id, username, auth_type, api_token_id,
                 server_id, tool_id, tool_access, required_access, granted_access,
                 decision, reason, outcome, duration_ms, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                correlation_id,
                principal.id,
                principal.username,
                principal.auth_type,
                getattr(principal, "token_id", None),
                decision["server_id"],
                definition.id,
                decision["required_access"],
                decision["required_access"],
                decision["granted_access"],
                "allow" if decision["allowed"] else "deny",
                decision["reason"],
                outcome,
                duration_ms,
                json.dumps(payload, ensure_ascii=False),
                iso_now(),
            ),
        )

    def list_invocation_audits(
        self,
        *,
        user_id: str | None = None,
        server_id: str | None = None,
        tool_id: str | None = None,
        decision: str | None = None,
        outcome: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (
            ("user_id", user_id),
            ("server_id", server_id),
            ("tool_id", tool_id),
            ("decision", decision),
            ("outcome", outcome),
        ):
            if value:
                clauses.append(f"{column} = ?")
                params.append(value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.database.query_all(
            f"SELECT * FROM invocation_audits {where} ORDER BY created_at DESC LIMIT ?",
            tuple(params + [max(1, min(limit, 500))]),
        )
        return [
            {
                "id": row["id"],
                "correlation_id": row["correlation_id"],
                "user_id": row["user_id"],
                "username": row["username"],
                "auth_type": row["auth_type"],
                "api_token_id": row["api_token_id"],
                "server_id": row["server_id"],
                "tool_id": row["tool_id"],
                "tool_access": row["tool_access"],
                "required_access": row["required_access"],
                "granted_access": row["granted_access"],
                "decision": row["decision"],
                "reason": row["reason"],
                "outcome": row["outcome"],
                "duration_ms": row["duration_ms"],
                "payload": _loads(row["payload_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def list_invocation_audit_filter_options(self) -> dict[str, Any]:
        """从历史审计快照生成筛选候选，保留已删除用户和已下线资源。"""

        user_rows = self.database.query_all(
            """
            SELECT audit.user_id, audit.username
            FROM invocation_audits AS audit
            WHERE audit.id = (
                SELECT latest.id
                FROM invocation_audits AS latest
                WHERE latest.user_id = audit.user_id
                ORDER BY latest.created_at DESC, latest.id DESC
                LIMIT 1
            )
            ORDER BY audit.username COLLATE NOCASE, audit.user_id
            """
        )
        resource_rows = self.database.query_all(
            """
            SELECT DISTINCT server_id, tool_id
            FROM invocation_audits
            ORDER BY server_id COLLATE NOCASE, tool_id COLLATE NOCASE
            """
        )
        return {
            "users": [
                {"id": row["user_id"], "username": row["username"]}
                for row in user_rows
            ],
            "servers": sorted(
                {str(row["server_id"]) for row in resource_rows},
                key=str.casefold,
            ),
            "tools": [
                {"server_id": row["server_id"], "tool_id": row["tool_id"]}
                for row in resource_rows
            ],
        }


def _server_id(definition: ToolDefinition) -> str:
    value = definition.metadata.get("server_id")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return definition.source or "builtin"


def _tool_fingerprint(definition: ToolDefinition) -> str:
    payload = {
        "id": definition.id,
        "name": definition.name,
        "description": definition.description,
        "permission": definition.permission,
        "source": definition.source,
        "input_schema": definition.input_schema,
        "annotations": _safe_annotations(definition),
        "required_control_permission": definition.metadata.get("required_control_permission"),
        "output_schema": definition.metadata.get("outputSchema"),
        "sensitive_input_fields": definition.metadata.get("sensitive_input_fields"),
        "sensitive_output_fields": definition.metadata.get("sensitive_output_fields"),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _suggest_tool(definition: ToolDefinition) -> dict[str, Any]:
    annotations = _safe_annotations(definition)
    tokens = set(
        token
        for token in re.split(r"[^a-z0-9]+", f"{definition.id} {definition.name}".lower())
        if token
    )
    read_hits = sorted(tokens & READ_PATTERNS)
    write_hits = sorted(tokens & WRITE_PATTERNS)
    annotation_read = annotations.get("readOnlyHint")
    destructive = bool(annotations.get("destructiveHint")) or bool(tokens & DESTRUCTIVE_PATTERNS)
    idempotent = bool(annotations.get("idempotentHint"))
    open_world = bool(annotations.get("openWorldHint", definition.source == "mcp"))
    access = "unknown"
    confidence = 0.35
    source = "rule"
    if annotation_read is True and not write_hits:
        access, confidence, source = "read", 0.88, "annotation"
    elif annotation_read is False and write_hits and not read_hits:
        access, confidence, source = "write", 0.86, "annotation"
    elif write_hits and not read_hits:
        access, confidence = "write", 0.78
    elif read_hits and not write_hits:
        access, confidence = "read", 0.78
    elif annotation_read is False and not read_hits:
        access, confidence, source = "write", 0.62, "annotation"
    return {
        "access": access,
        "confidence": confidence,
        "source": source,
        "destructive": destructive,
        "idempotent": idempotent,
        "open_world": open_world,
        "evidence": {
            "annotations": annotations,
            "rule": {
                "read_hits": read_hits,
                "write_hits": write_hits,
                "note": "机器结果仅为建议，人工发布后才进入运行时授权。",
            },
        },
    }


def _classification_row(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "server_id": row["server_id"],
        "tool_id": row["tool_id"],
        "tool_name": row["tool_name"],
        "fingerprint": row["fingerprint"],
        "suggested_access": row["suggested_access"],
        "effective_access": row["effective_access"],
        "status": row["status"],
        "confidence": float(row["confidence"]),
        "source": row["source"],
        "destructive": bool(row["destructive"]),
        "idempotent": bool(row["idempotent"]),
        "open_world": bool(row["open_world"]),
        "evidence": _loads(row["evidence_json"]),
        "reviewed_by": row["reviewed_by"],
        "reviewed_at": row["reviewed_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _safe_annotations(definition: ToolDefinition) -> dict[str, Any]:
    value = definition.metadata.get("annotations")
    if not isinstance(value, dict):
        return {}
    allowed = {"readOnlyHint", "destructiveHint", "idempotentHint", "openWorldHint"}
    return {key: value[key] for key in allowed if isinstance(value.get(key), bool)}


def _payload_summary(arguments: dict[str, Any]) -> dict[str, Any]:
    try:
        payload_bytes = len(json.dumps(arguments, ensure_ascii=False).encode("utf-8"))
    except (TypeError, ValueError):
        payload_bytes = None
    return {
        "argument_keys": [
            "[REDACTED]" if SENSITIVE_KEY_PATTERN.search(str(key)) else str(key)
            for key in sorted(arguments)
        ],
        "payload_bytes": payload_bytes,
        "values_recorded": False,
    }


def _token_scope_allows(principal: AuthPrincipal, required_access: str) -> bool:
    if principal.auth_type != "token":
        return True
    scopes = set(getattr(principal, "scopes", ()))
    if "*" in scopes:
        return True
    if required_access == "read":
        return bool(scopes & {"tools.read", "mcp.read", "mcp.write"})
    return bool(scopes & {"tools.invoke", "mcp.write"})


def _principal_control_allows(principal: AuthPrincipal, permission_code: str) -> bool:
    roles = set(getattr(principal, "roles", ()) or (principal.role,))
    permissions = set(getattr(principal, "permissions", ()))
    return principal.role == "admin" or "admin" in roles or "*" in permissions or permission_code in permissions


def _normalize_code(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9_.-]+", "-", value.strip().lower()).strip("-.")
    if not normalized:
        raise ValueError("code is required")
    return normalized


def _loads(value: str | None) -> dict[str, Any]:
    try:
        data = json.loads(value or "{}")
        return data if isinstance(data, dict) else {"value": data}
    except json.JSONDecodeError:
        return {"raw": value}


def _is_expired(value: str | None) -> bool:
    if not value:
        return False
    try:
        expires_at = datetime.fromisoformat(value)
    except ValueError:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc)

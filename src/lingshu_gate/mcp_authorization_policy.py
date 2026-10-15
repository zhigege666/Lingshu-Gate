"""持续 MCP 授权的服务身份与策略格式；不承担用户权限和协议校验。"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from pathlib import Path
from typing import Any
from uuid import uuid4

MAX_AUTHORIZATION_SERVERS = 100


def _file_marker(path: str | Path) -> str:
    stat = Path(path).stat()
    # 内部覆盖保存会同时更新标记；未经 Gate 保存的文件替换使旧授权失败关闭。
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    return f"{stat.st_ino}:{stat.st_ctime_ns}:{stat.st_mtime_ns}:{stat.st_size}:{digest}"


def ensure_server_identity(connection: sqlite3.Connection, server_id: str) -> str:
    """工具发现仅补建身份，不重用已删除服务的历史 binding。"""
    connection.execute("INSERT INTO gate_mcp_authorization_identities(server_id,binding) VALUES (?,?) "
                       "ON CONFLICT(server_id) DO NOTHING", (server_id, uuid4().hex))
    return str(connection.execute("SELECT binding FROM gate_mcp_authorization_identities WHERE server_id=?",
                                  (server_id,)).fetchone()[0])


def server_binding(connection: sqlite3.Connection, server_id: str) -> str:
    row = connection.execute("SELECT * FROM gate_mcp_authorization_identities WHERE server_id=?", (server_id,)).fetchone()
    if row is None:
        raise ValueError("server_scope_unavailable")
    if row["file_path"]:
        try:
            current = _file_marker(row["file_path"])
        except OSError:
            raise ValueError("server_scope_unavailable") from None
        if current != row["file_marker"]:
            raise ValueError("server_scope_changed")
    return str(row["binding"])


def bind_server_policies(connection: sqlite3.Connection, policies: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """绑定服务端身份；接收已绑定策略时仍校验当前生命周期。"""
    if not isinstance(policies, list) or len(policies) > MAX_AUTHORIZATION_SERVERS:
        raise ValueError("server_scope_limit")
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for policy in policies:
        if (not isinstance(policy, dict) or set(policy) - {"server_id", "mode", "access", "server_binding"}
                or policy.get("mode") != "continuous" or policy.get("access") not in {"read", "write"}):
            raise ValueError("invalid_server_policy")
        server_id = policy.get("server_id")
        if (not isinstance(server_id, str) or len(server_id) > 512
                or re.fullmatch(r"[A-Za-z0-9_.-]+", server_id) is None or server_id in seen):
            raise ValueError("invalid_server_policy")
        binding = server_binding(connection, server_id)
        if "server_binding" in policy and policy["server_binding"] != binding:
            raise ValueError("server_scope_changed")
        seen.add(server_id)
        result.append({"server_id": server_id, "mode": "continuous", "access": policy["access"],
                       "server_binding": binding})
    return sorted(result, key=lambda item: item["server_id"])


def tool_snapshot(definition: Any, classification: dict[str, Any] | sqlite3.Row) -> str:
    """与现有 OAuth 工具快照使用同一分类指纹、级别和审核版本。"""
    return hashlib.sha256(json.dumps([classification["fingerprint"], classification["effective_access"],
                                     classification["reviewed_at"]], sort_keys=True).encode()).hexdigest()


def record_config_identity(connection: sqlite3.Connection, server_id: str, path: Path,
                           target: dict[str, Any], *, replace: bool = False) -> str:
    """Gate 内普通版本覆盖保留身份，目标替换或显式重建轮换身份。"""
    digest = hashlib.sha256(json.dumps(target, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    marker = _file_marker(path)
    row = connection.execute("SELECT * FROM gate_mcp_authorization_identities WHERE server_id=?", (server_id,)).fetchone()
    changed_target = bool(row and row["target_digest"] and row["target_digest"] != digest)
    binding = uuid4().hex if row is None or replace or changed_target else str(row["binding"])
    connection.execute("INSERT INTO gate_mcp_authorization_identities(server_id,binding,target_digest,file_path,file_marker) "
                       "VALUES (?,?,?,?,?) ON CONFLICT(server_id) DO UPDATE SET binding=excluded.binding,"
                       "target_digest=excluded.target_digest,file_path=excluded.file_path,file_marker=excluded.file_marker",
                       (server_id, binding, digest, str(path.resolve()), marker))
    return binding

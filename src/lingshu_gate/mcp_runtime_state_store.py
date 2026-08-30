"""MCP 服务期望运行状态的持久化存储。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from lingshu_gate.database import SQLiteDatabase

DesiredState = Literal["running", "stopped"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class McpRuntimeIntent:
    server_id: str
    desired_state: DesiredState
    source: str
    updated_at: str | None
    revision: int = 0


class McpRuntimeStateStore:
    """仅保存用户期望，不保存瞬时运行状态。"""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def get(self, server_id: str) -> McpRuntimeIntent | None:
        row = self.database.query_one(
            "SELECT server_id, desired_state, source, updated_at, revision FROM mcp_runtime_intents WHERE server_id = ?",
            (server_id,),
        )
        if not row:
            return None
        return McpRuntimeIntent(
            server_id=str(row["server_id"]),
            desired_state=str(row["desired_state"]),  # type: ignore[arg-type]
            source=str(row["source"]),
            updated_at=str(row["updated_at"]),
            revision=int(row["revision"]),
        )

    def resolve(self, server_id: str, *, auto_start: bool) -> McpRuntimeIntent:
        stored = self.get(server_id)
        if stored:
            return stored
        return McpRuntimeIntent(
            server_id=server_id,
            desired_state="running" if auto_start else "stopped",
            source="manifest_default",
            updated_at=None,
        )

    def set(self, server_id: str, desired_state: DesiredState, *, source: str, reason: str | None = None) -> McpRuntimeIntent:
        if desired_state not in {"running", "stopped"}:
            raise ValueError("desired_state must be running or stopped")
        now = _now()
        self.database.execute(
            """
            INSERT INTO mcp_runtime_intents (server_id, desired_state, revision, source, reason, created_at, updated_at)
            VALUES (?, ?, 1, ?, ?, ?, ?)
            ON CONFLICT(server_id) DO UPDATE SET
                desired_state = excluded.desired_state,
                revision = mcp_runtime_intents.revision + 1,
                source = excluded.source,
                reason = excluded.reason,
                updated_at = excluded.updated_at
            """,
            (server_id, desired_state, source, reason, now, now),
        )
        resolved = self.get(server_id)
        if not resolved:
            raise RuntimeError(f"Failed to persist MCP runtime intent: {server_id}")
        return resolved

    def delete(self, server_id: str) -> None:
        self.database.execute("DELETE FROM mcp_runtime_intents WHERE server_id = ?", (server_id,))

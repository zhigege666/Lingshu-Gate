"""Logs and events support."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, cast
from uuid import uuid4

from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.logging import validate_gate_event_name
from lingshu_gate.redaction import redact_text, redact_value


EVENT_SERVER_ID_SQL = """CASE
    WHEN subject_type IN ('server', 'mcp_server', 'config') THEN subject_id
    WHEN json_type(payload_json, '$.server_id') = 'text' THEN json_extract(payload_json, '$.server_id')
    ELSE NULL END"""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ObservabilityStore:
    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    def emit_event(
        self,
        event_type: str,
        *,
        source: str = "gate",
        subject_type: str | None = None,
        subject_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event_type = validate_gate_event_name(event_type)
        safe_payload = cast(dict[str, Any], redact_value(payload or {}))
        event = {
            "id": str(uuid4()),
            "type": event_type,
            "source": source,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "payload": safe_payload,
            "created_at": iso_now(),
        }
        self.database.execute(
            """
            INSERT INTO events (id, type, source, subject_type, subject_id, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["id"],
                event["type"],
                event["source"],
                event["subject_type"],
                event["subject_id"],
                json.dumps(event["payload"], ensure_ascii=False),
                event["created_at"],
            ),
        )
        return event

    def add_log(
        self,
        level: str,
        message: str,
        *,
        source: str = "gate",
        server_id: str | None = None,
        tool_id: str | None = None,
        event_type: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if event_type is not None:
            event_type = validate_gate_event_name(event_type)
        safe_payload = cast(dict[str, Any], redact_value(payload or {}))
        log = {
            "id": str(uuid4()),
            "level": level.lower(),
            "source": source,
            "server_id": server_id,
            "tool_id": tool_id,
            "event_type": event_type,
            "message": redact_text(message),
            "payload": safe_payload,
            "created_at": iso_now(),
        }
        self.database.execute(
            """
            INSERT INTO logs (id, level, source, server_id, tool_id, event_type, message, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                log["id"],
                log["level"],
                log["source"],
                log["server_id"],
                log["tool_id"],
                log["event_type"],
                log["message"],
                json.dumps(log["payload"], ensure_ascii=False),
                log["created_at"],
            ),
        )
        return log

    def historical_tool_ids(self, server_id: str) -> list[str]:
        """Exact service scope is authorized by the caller before this lookup."""
        rows = self.database.query_all(
            "SELECT DISTINCT tool_id FROM logs WHERE server_id = ? AND tool_id IS NOT NULL AND tool_id != ''",
            (server_id,),
        )
        return [str(row["tool_id"]) for row in rows]

    def historical_server_ids(self) -> list[str]:
        rows = self.database.query_all(
            f"SELECT server_id FROM logs WHERE server_id IS NOT NULL AND server_id != '' "
            f"UNION SELECT {EVENT_SERVER_ID_SQL} AS server_id FROM events "
            f"WHERE ({EVENT_SERVER_ID_SQL}) IS NOT NULL AND ({EVENT_SERVER_ID_SQL}) != ''"
        )
        return [str(row["server_id"]) for row in rows]

    def list_events(
        self,
        *,
        event_type: str | None = None,
        subject_id: str | None = None,
        server_id: str | None = None,
        allowed_server_ids: list[str] | None = None,
        source: str | None = None,
        keyword: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if allowed_server_ids is not None:
            if not allowed_server_ids:
                return []
            clauses.append(f"({EVENT_SERVER_ID_SQL}) IN ({','.join('?' for _ in allowed_server_ids)})")
            params.extend(allowed_server_ids)
        if server_id:
            clauses.append(f"({EVENT_SERVER_ID_SQL}) = ?")
            params.append(server_id)
        if event_type:
            clauses.append("type = ?")
            params.append(event_type)
        if subject_id:
            clauses.append("subject_id = ?")
            params.append(subject_id)
        if source:
            clauses.append("source = ?")
            params.append(source)
        if keyword:
            clauses.append("(type LIKE ? OR source LIKE ? OR subject_id LIKE ? OR payload_json LIKE ?)")
            like = f"%{keyword}%"
            params.extend([like, like, like, like])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.database.query_all(
            f"SELECT * FROM events {where} ORDER BY created_at DESC LIMIT ?",
            tuple(params + [max(1, min(limit, 500))]),
        )
        return [_event_row_to_dict(row) for row in rows]

    def list_logs(
        self,
        *,
        level: str | None = None,
        server_id: str | None = None,
        allowed_server_ids: list[str] | None = None,
        tool_id: str | None = None,
        event_type: str | None = None,
        source: str | None = None,
        keyword: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if allowed_server_ids is not None:
            if not allowed_server_ids:
                return []
            clauses.append(f"server_id IN ({','.join('?' for _ in allowed_server_ids)})")
            params.extend(allowed_server_ids)
        if level:
            clauses.append("level = ?")
            params.append(level.lower())
        if server_id:
            clauses.append("server_id = ?")
            params.append(server_id)
        if tool_id:
            clauses.append("tool_id = ?")
            params.append(tool_id)
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if source:
            clauses.append("source = ?")
            params.append(source)
        if keyword:
            clauses.append("(message LIKE ? OR event_type LIKE ? OR server_id LIKE ? OR tool_id LIKE ? OR payload_json LIKE ?)")
            like = f"%{keyword}%"
            params.extend([like, like, like, like, like])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.database.query_all(
            f"SELECT * FROM logs {where} ORDER BY created_at DESC LIMIT ?",
            tuple(params + [max(1, min(limit, 500))]),
        )
        return [_log_row_to_dict(row) for row in rows]

def _event_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "type": row["type"],
        "source": row["source"],
        "subject_type": row["subject_type"],
        "subject_id": row["subject_id"],
        "payload": _loads(row["payload_json"]),
        "created_at": row["created_at"],
    }


def _log_row_to_dict(row: Any) -> dict[str, Any]:
    return {
        "id": row["id"],
        "level": row["level"],
        "source": row["source"],
        "server_id": row["server_id"],
        "tool_id": row["tool_id"],
        "event_type": row["event_type"],
        "message": row["message"],
        "payload": _loads(row["payload_json"]),
        "created_at": row["created_at"],
    }


def _loads(value: str) -> dict[str, Any]:
    try:
        data = json.loads(value or "{}")
        return data if isinstance(data, dict) else {"value": data}
    except json.JSONDecodeError:
        return {"raw": value}

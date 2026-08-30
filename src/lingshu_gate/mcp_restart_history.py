"""Persistent restart / recovery history for MCP servers."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from lingshu_gate.logging import validate_gate_event_name

HistoryEntry = dict[str, Any]
HistoryDocument = dict[str, list[HistoryEntry]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class McpRestartHistoryStore:
    """Append-only JSON history for MCP auto recovery events.

    The history is intentionally lightweight and local to the Gate data dir so it
    survives container restarts without requiring a database migration.
    """

    def __init__(self, data_dir: Path, *, per_server_limit: int = 200) -> None:
        self.data_dir = data_dir
        self.path = data_dir / "restart-history.json"
        self.per_server_limit = per_server_limit
        self._lock = threading.RLock()

    def append(self, server_id: str, event_type: str, message: str, payload: dict[str, Any] | None = None, *, level: str = "info") -> HistoryEntry:
        event_type = validate_gate_event_name(event_type)
        entry = {
            "id": uuid4().hex,
            "server_id": server_id,
            "event_type": event_type,
            "level": level,
            "message": message,
            "payload": payload or {},
            "created_at": _now(),
        }
        with self._lock:
            data = self._read_all()
            history = data.setdefault(server_id, [])
            history.append(entry)
            data[server_id] = history[-self.per_server_limit :]
            self._write_all(data)
        return entry

    def list(self, server_id: str, *, limit: int = 80) -> list[HistoryEntry]:
        with self._lock:
            data = self._read_all()
            history = data.get(server_id, [])
            if not isinstance(history, list):
                return []
            return list(reversed(history[-limit:]))

    def _read_all(self) -> HistoryDocument:
        if not self.path.exists():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8") or "{}")
        if not isinstance(raw, dict):
            return {}
        normalized: HistoryDocument = {}
        for key, value in raw.items():
            if isinstance(value, list):
                normalized[str(key)] = [item for item in value if isinstance(item, dict)]
        return normalized

    def _write_all(self, data: HistoryDocument) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        tmp.replace(self.path)

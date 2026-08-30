"""用户下游 MCP 凭据的独立加密存储。"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken

from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.mcp_manifest import UserCredentialSlot


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class UserCredentialBindingError(RuntimeError):
    """用户凭据槽位缺失、损坏或不匹配。"""


class UserCredentialStore:
    """按 user + MCP server + slot 隔离保存秘密，不提供明文读取 API。"""

    def __init__(self, database: SQLiteDatabase, data_dir: Path) -> None:
        self.database = database
        self.key_path = data_dir / "user-credential.key"
        self._lock = threading.RLock()

    def list_bindings(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.database.query_all(
            """
            SELECT id, user_id, server_id, slot_id, created_at, updated_at, last_used_at
            FROM user_downstream_credentials
            WHERE user_id = ?
            ORDER BY server_id, slot_id
            """,
            (user_id,),
        )
        return [self._safe_record(dict(row)) for row in rows]

    def get_binding(self, user_id: str, server_id: str, slot_id: str) -> dict[str, Any] | None:
        row = self.database.query_one(
            """
            SELECT id, user_id, server_id, slot_id, created_at, updated_at, last_used_at
            FROM user_downstream_credentials
            WHERE user_id = ? AND server_id = ? AND slot_id = ?
            """,
            (user_id, server_id, slot_id),
        )
        return self._safe_record(dict(row)) if row else None

    def save_binding(self, *, user_id: str, server_id: str, slot_id: str, value: str) -> dict[str, Any]:
        secret = self.validate_value(value)

        with self._lock:
            existing = self.database.query_one(
                """
                SELECT id, created_at FROM user_downstream_credentials
                WHERE user_id = ? AND server_id = ? AND slot_id = ?
                """,
                (user_id, server_id, slot_id),
            )
            now = _now()
            binding_id = str(existing["id"]) if existing else str(uuid4())
            created_at = str(existing["created_at"]) if existing else now
            encrypted = self._fernet().encrypt(secret.encode("utf-8")).decode("utf-8")
            self.database.execute(
                """
                INSERT INTO user_downstream_credentials
                    (id, user_id, server_id, slot_id, encrypted_value, created_at, updated_at, last_used_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(user_id, server_id, slot_id) DO UPDATE SET
                    encrypted_value = excluded.encrypted_value,
                    updated_at = excluded.updated_at,
                    last_used_at = NULL
                """,
                (binding_id, user_id, server_id, slot_id, encrypted, created_at, now),
            )
            binding = self.get_binding(user_id, server_id, slot_id)
            if not binding:
                raise RuntimeError("credential binding was not saved")
            return binding

    @staticmethod
    def validate_value(value: str) -> str:
        secret = value
        if not secret or not secret.strip() or secret == "***":
            raise ValueError("credential value is required")
        if len(secret) < 4:
            raise ValueError("credential value must contain at least 4 characters")
        if "\r" in secret or "\n" in secret:
            raise ValueError("credential value cannot contain line breaks")
        return secret

    def delete_binding(self, *, user_id: str, server_id: str, slot_id: str) -> dict[str, Any]:
        with self._lock:
            binding = self.get_binding(user_id, server_id, slot_id)
            if not binding:
                raise KeyError(f"user credential binding not found: {server_id}/{slot_id}")
            self.database.execute(
                """
                DELETE FROM user_downstream_credentials
                WHERE user_id = ? AND server_id = ? AND slot_id = ?
                """,
                (user_id, server_id, slot_id),
            )
            return binding

    def delete_server_bindings(self, server_id: str) -> int:
        """删除已移除 MCP Server 的全部用户秘密，避免同名配置重建后意外复用。"""

        with self._lock:
            row = self.database.query_one(
                """
                SELECT COUNT(*) AS total
                FROM user_downstream_credentials
                WHERE server_id = ?
                """,
                (server_id,),
            )
            total = int(row["total"]) if row else 0
            self.database.execute(
                "DELETE FROM user_downstream_credentials WHERE server_id = ?",
                (server_id,),
            )
            return total

    def resolve_slots(
        self,
        *,
        user_id: str,
        server_id: str,
        slots: Iterable[UserCredentialSlot],
    ) -> tuple[dict[str, str], list[str]]:
        """只在当前调用内解密槽位，并返回缺失的必填槽位。"""

        values: dict[str, str] = {}
        missing: list[str] = []
        with self._lock:
            fernet = self._fernet()
            for slot in slots:
                row = self.database.query_one(
                    """
                    SELECT encrypted_value FROM user_downstream_credentials
                    WHERE user_id = ? AND server_id = ? AND slot_id = ?
                    """,
                    (user_id, server_id, slot.id),
                )
                if not row:
                    if slot.required:
                        missing.append(slot.id)
                    continue
                try:
                    values[slot.id] = fernet.decrypt(str(row["encrypted_value"]).encode("utf-8")).decode("utf-8")
                except InvalidToken as exc:
                    raise UserCredentialBindingError(
                        f"user credential cannot be decrypted: {server_id}/{slot.id}"
                    ) from exc
        return values, missing

    def mark_used(self, *, user_id: str, server_id: str, slot_ids: Iterable[str]) -> None:
        now = _now()
        for slot_id in set(slot_ids):
            self.database.execute(
                """
                UPDATE user_downstream_credentials
                SET last_used_at = ?
                WHERE user_id = ? AND server_id = ? AND slot_id = ?
                """,
                (now, user_id, server_id, slot_id),
            )

    def _fernet(self) -> Fernet:
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.key_path.exists():
            self.key_path.write_bytes(Fernet.generate_key())
            try:
                self.key_path.chmod(0o600)
            except OSError:
                pass
        return Fernet(self.key_path.read_bytes())

    @staticmethod
    def _safe_record(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": record["id"],
            "user_id": record["user_id"],
            "server_id": record["server_id"],
            "slot_id": record["slot_id"],
            "configured": True,
            "created_at": record["created_at"],
            "updated_at": record["updated_at"],
            "last_used_at": record.get("last_used_at"),
        }

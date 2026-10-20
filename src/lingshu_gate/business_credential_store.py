"""Encrypted business accounts and durable, versioned adapter bindings.

Only resolve_secret returns plaintext, for the final controlled dispatch. The
encryption key lifecycle is shared with CredentialStore, in a separate domain;
ciphertext and metadata commit in the same SQLite transaction.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from cryptography.fernet import InvalidToken

from lingshu_gate.credential_store import CredentialStore
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.domain.business_credentials import (
    BusinessCredentialBindingCreate,
    BusinessCredentialBindingUpdate,
    BusinessCredentialCreate,
    BusinessCredentialError,
    BusinessCredentialUpdate,
    SYNC_ERROR_CODES,
    SYNC_STATUSES,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class BusinessCredentialStore:
    """Single-Core store; the application holds lock across controlled I/O.

    Authorization belongs to the application service. Holding this reentrant
    lock serializes final dispatch with credential edits and revocation. SQL
    revision checks also reject stale writes from another store instance.
    """

    def __init__(self, database: SQLiteDatabase, data_dir: Path) -> None:
        self.database = database
        self.lock = threading.RLock()
        encryption_dir = data_dir / "business-credentials"
        encryption_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            encryption_dir.chmod(0o700)
        except OSError:
            pass  # Windows/filesystem ACLs may not expose Unix modes.
        self._encryption = CredentialStore(encryption_dir)

    @staticmethod
    def _credential_row(connection: sqlite3.Connection, credential_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM business_credentials WHERE id=?", (credential_id,)).fetchone()
        if row is None:
            raise BusinessCredentialError("credential_not_found", "The business credential is unavailable.", 404)
        return row

    @staticmethod
    def _binding_row(connection: sqlite3.Connection, binding_id: str) -> sqlite3.Row:
        row = connection.execute("SELECT * FROM business_credential_bindings WHERE id=?", (binding_id,)).fetchone()
        if row is None:
            raise BusinessCredentialError("binding_not_found", "The credential binding is unavailable.", 404)
        return row

    @staticmethod
    def _version(actual: int, expected: int) -> None:
        if actual != expected:
            raise BusinessCredentialError("credential_revision_conflict", "The credential or binding changed; reload it.", 409)

    @staticmethod
    def _credential_safe(row: sqlite3.Row) -> dict[str, Any]:
        return {**json.loads(row["metadata_json"]), "id": row["id"], "credential_ref": f'gate:{row["id"]}',
            "owner_id": row["owner_id"], "scope": row["scope"], "enabled": bool(row["enabled"]),
            "username_masked": "***", "configured": True, "password_configured": True, "version": row["version"],
            "created_at": row["created_at"], "updated_at": row["updated_at"]}

    @staticmethod
    def _binding_safe(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["tool_revisions"] = json.loads(result.pop("tool_revisions_json"))
        result["enabled"] = bool(result["enabled"])
        result["remote_copy_possible"] = bool(result["remote_copy_possible"])
        return result

    @staticmethod
    def _metadata(request: BusinessCredentialCreate | BusinessCredentialUpdate) -> str:
        return _json(request.model_dump(mode="json", exclude={"username", "password", "scope", "expected_version"}))

    def _encrypt(self, values: dict[str, str]) -> str:
        try:
            if (not self._encryption.key_path.is_file()
                    and self.database.query_one("SELECT 1 FROM business_credentials LIMIT 1") is not None):
                raise ValueError("credential encryption key is unavailable")
            return self._encryption._fernet().encrypt(_json(values).encode()).decode()
        except (ValueError, OSError):
            raise BusinessCredentialError("credential_unavailable", "The business credential cannot be encrypted.", 409) from None

    def _decrypt(self, ciphertext: str) -> dict[str, str]:
        try:
            # Existing ciphertext must not silently replace a lost key.
            if not self._encryption.key_path.is_file():
                raise ValueError("credential encryption key is unavailable")
            values = json.loads(self._encryption._fernet().decrypt(ciphertext.encode()).decode())
            if (not isinstance(values, dict) or set(values) != {"username", "password"}
                    or any(not isinstance(value, str) or not value for value in values.values())):
                raise ValueError("invalid secret envelope")
            return values
        except (InvalidToken, ValueError, UnicodeError, OSError):
            raise BusinessCredentialError("credential_unavailable", "The business credential cannot be decrypted.", 409) from None

    def create_credential(self, owner_id: str, request: BusinessCredentialCreate) -> dict[str, Any]:
        with self.lock, self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if connection.execute("SELECT 1 FROM users WHERE id=?", (owner_id,)).fetchone() is None:
                raise BusinessCredentialError("credential_owner_unavailable", "A current Gate account is required.", 403)
            credential_id, now = uuid4().hex, _now()
            encrypted = self._encrypt({"username": request.username.get_secret_value(),
                "password": request.password.get_secret_value()})
            connection.execute("INSERT INTO business_credentials "
                "(id,owner_id,scope,metadata_json,encrypted_secret,enabled,version,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,1,?,?)", (credential_id, owner_id, request.scope, self._metadata(request),
                    encrypted, int(request.enabled), now, now))
            return self._credential_safe(self._credential_row(connection, credential_id))

    def update_credential(self, credential_id: str, request: BusinessCredentialUpdate) -> dict[str, Any]:
        with self.lock, self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._credential_row(connection, credential_id)
            self._version(row["version"], request.expected_version)
            if row["scope"] == "personal" and (request.allowed_user_ids or request.allowed_role_ids):
                raise BusinessCredentialError("personal_credential_grant_denied", "Personal credentials cannot be shared.", 422)
            encrypted = row["encrypted_secret"]
            if request.username is not None or request.password is not None:
                values = self._decrypt(encrypted)
                if request.username is not None:
                    values["username"] = request.username.get_secret_value()
                if request.password is not None:
                    values["password"] = request.password.get_secret_value()
                encrypted = self._encrypt(values)
            now = _now()
            connection.execute("UPDATE business_credentials SET metadata_json=?,encrypted_secret=?,enabled=?,"
                "version=version+1,updated_at=? WHERE id=? AND version=?", (self._metadata(request), encrypted,
                    int(request.enabled), now, credential_id, request.expected_version))
            # Old receipts must never mark a newly edited account as synchronized.
            connection.execute("UPDATE business_credential_bindings SET sync_status='pending',revision=revision+1,"
                "last_error_code=NULL,updated_at=? WHERE credential_id=?", (now, credential_id))
            return self._credential_safe(self._credential_row(connection, credential_id))

    def get_credential(self, credential_id: str) -> dict[str, Any]:
        with self.lock, self.database.session() as connection:
            return self._credential_safe(self._credential_row(connection, credential_id))

    def list_credentials(self) -> list[dict[str, Any]]:
        with self.lock, self.database.session() as connection:
            return [self._credential_safe(row) for row in connection.execute(
                "SELECT * FROM business_credentials ORDER BY created_at,id")]

    def resolve_secret(self, credential_id: str, *, expected_version: int) -> dict[str, str]:
        with self.lock, self.database.session() as connection:
            row = self._credential_row(connection, credential_id)
            self._version(row["version"], expected_version)
            if not row["enabled"]:
                raise BusinessCredentialError("credential_disabled", "The business credential is disabled.", 403)
            return self._decrypt(row["encrypted_secret"])

    def delete_credential(self, credential_id: str, *, expected_version: int) -> dict[str, Any]:
        with self.lock, self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._credential_row(connection, credential_id)
            self._version(row["version"], expected_version)
            if connection.execute("SELECT 1 FROM business_credential_bindings WHERE credential_id=? "
                    "AND remote_copy_possible=1 LIMIT 1", (credential_id,)).fetchone():
                raise BusinessCredentialError("remote_copy_cleanup_required",
                    "Remove remote vault copies first, or keep this credential disabled for cleanup.", 409)
            if connection.execute("SELECT 1 FROM business_credential_sessions WHERE credential_id=? "
                    "AND status!='closed' LIMIT 1", (credential_id,)).fetchone():
                raise BusinessCredentialError("browser_session_cleanup_required",
                    "Close managed browser sessions first, or keep this credential disabled for cleanup.", 409)
            result = self._credential_safe(row)
            connection.execute("DELETE FROM business_credential_bindings WHERE credential_id=?", (credential_id,))
            connection.execute("DELETE FROM business_credentials WHERE id=?", (credential_id,))
            return result

    @staticmethod
    def _validate_contract(manifest_digest: str, tool_revisions: dict[str, str]) -> None:
        if (not re.fullmatch(r"[a-f0-9]{64}", manifest_digest)
                or not {"save", "login", "delete", "open"}.issubset(tool_revisions)
                or len(tool_revisions) > 128
                or any(not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}", key) for key in tool_revisions)
                or any(not re.fullmatch(r"[a-f0-9]{64}", revision) for revision in tool_revisions.values())):
            raise BusinessCredentialError("invalid_binding_contract", "An exact manifest and adapter tool contract is required.", 422)

    def create_binding(self, credential_id: str, request: BusinessCredentialBindingCreate, *,
                       manifest_digest: str, tool_revisions: dict[str, str]) -> dict[str, Any]:
        self._validate_contract(manifest_digest, tool_revisions)
        with self.lock, self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            self._credential_row(connection, credential_id)
            target = connection.execute("SELECT * FROM business_credential_targets WHERE server_id=?",
                (request.server_id,)).fetchone()
            if target is not None and (target["adapter"] != request.adapter or target["tool_prefix"] != request.tool_prefix):
                raise BusinessCredentialError("adapter_target_conflict", "This target already uses a different adapter contract.", 409)
            if connection.execute("SELECT 1 FROM business_credential_bindings WHERE credential_id=? AND server_id=?",
                    (credential_id, request.server_id)).fetchone():
                raise BusinessCredentialError("binding_exists", "This credential is already bound to the selected instance.", 409)
            binding_id, now = uuid4().hex, _now()
            connection.execute("INSERT OR IGNORE INTO business_credential_targets "
                "(server_id,adapter,tool_prefix,created_at) VALUES (?,?,?,?)",
                (request.server_id, request.adapter, request.tool_prefix, now))
            connection.execute("INSERT INTO business_credential_bindings "
                "(id,credential_id,server_id,adapter,tool_prefix,profile_name,manifest_digest,tool_revisions_json,"
                "enabled,revision,synced_version,sync_status,remote_copy_possible,last_sync_at,last_error_code,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,1,NULL,'pending',0,NULL,NULL,?,?)", (binding_id, credential_id,
                    request.server_id, request.adapter, request.tool_prefix, f"gate_{binding_id}", manifest_digest,
                    _json(tool_revisions), int(request.enabled), now, now))
            return self._binding_safe(self._binding_row(connection, binding_id))

    def update_binding(self, binding_id: str, request: BusinessCredentialBindingUpdate, *,
                       manifest_digest: str, tool_revisions: dict[str, str]) -> dict[str, Any]:
        self._validate_contract(manifest_digest, tool_revisions)
        with self.lock, self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._binding_row(connection, binding_id)
            self._version(row["revision"], request.expected_revision)
            credential = self._credential_row(connection, row["credential_id"])
            self._version(credential["version"], request.expected_version)
            changed = (manifest_digest != row["manifest_digest"] or _json(tool_revisions) != row["tool_revisions_json"])
            if changed and row["remote_copy_possible"]:
                raise BusinessCredentialError("remote_copy_cleanup_required",
                    "Remove the old remote vault copy before accepting a changed target contract.", 409)
            connection.execute("UPDATE business_credential_bindings SET enabled=?,manifest_digest=?,tool_revisions_json=?,"
                "revision=revision+1,sync_status=?,updated_at=? WHERE id=?", (int(request.enabled), manifest_digest,
                    _json(tool_revisions), "pending" if changed else row["sync_status"], _now(), binding_id))
            return self._binding_safe(self._binding_row(connection, binding_id))

    def get_binding(self, binding_id: str) -> dict[str, Any]:
        with self.lock, self.database.session() as connection:
            return self._binding_safe(self._binding_row(connection, binding_id))

    def find_binding(self, credential_id: str, server_id: str) -> dict[str, Any] | None:
        with self.lock, self.database.session() as connection:
            row = connection.execute("SELECT * FROM business_credential_bindings WHERE credential_id=? AND server_id=?",
                (credential_id, server_id)).fetchone()
            return self._binding_safe(row) if row is not None else None

    def list_bindings(self, *, credential_id: str | None = None, server_id: str | None = None) -> list[dict[str, Any]]:
        clauses, params = [], []
        for column, value in (("credential_id", credential_id), ("server_id", server_id)):
            if value is not None:
                clauses.append(f"{column}=?")
                params.append(value)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.lock, self.database.session() as connection:
            return [self._binding_safe(row) for row in connection.execute(
                "SELECT * FROM business_credential_bindings" + where + " ORDER BY created_at,id", params)]

    def mark_sync(self, binding_id: str, *, expected_revision: int, expected_version: int,
                  status: str, error_code: str | None = None) -> dict[str, Any]:
        """Write an intent as unknown before I/O; only exact receipts can finish it.

        A timeout or failure after dispatch preserves remote_copy_possible. A
        successful delete is the sole state transition that clears that flag.
        """
        if status not in SYNC_STATUSES or error_code is not None and error_code not in SYNC_ERROR_CODES:
            raise BusinessCredentialError("invalid_sync_result", "Unsupported synchronization result.", 422)
        with self.lock, self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._binding_row(connection, binding_id)
            self._version(row["revision"], expected_revision)
            credential = self._credential_row(connection, row["credential_id"])
            self._version(credential["version"], expected_version)
            if status == "synced" and (not row["enabled"] or not credential["enabled"]):
                raise BusinessCredentialError("credential_disabled", "Disabled credentials cannot be synchronized.", 403)
            synced_version = expected_version if status == "synced" else None if status == "deleted" else row["synced_version"]
            remote_possible = 0 if status == "deleted" else 1 if status in {"unknown", "synced"} else row["remote_copy_possible"]
            now = _now()
            connection.execute("UPDATE business_credential_bindings SET sync_status=?,synced_version=?,remote_copy_possible=?,"
                "last_sync_at=?,last_error_code=?,revision=revision+1,updated_at=? WHERE id=?",
                (status, synced_version, remote_possible, now, error_code, now, binding_id))
            return self._binding_safe(self._binding_row(connection, binding_id))

    def delete_binding(self, binding_id: str, *, expected_revision: int) -> dict[str, Any]:
        with self.lock, self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = self._binding_row(connection, binding_id)
            self._version(row["revision"], expected_revision)
            if row["remote_copy_possible"]:
                raise BusinessCredentialError("remote_copy_cleanup_required",
                    "Remove the remote vault copy first, or keep the binding disabled for cleanup.", 409)
            if connection.execute("SELECT 1 FROM business_credential_sessions WHERE binding_id=? "
                    "AND status!='closed' LIMIT 1", (binding_id,)).fetchone():
                raise BusinessCredentialError("browser_session_cleanup_required",
                    "Close managed browser sessions first, or keep this binding disabled for cleanup.", 409)
            result = self._binding_safe(row)
            connection.execute("DELETE FROM business_credential_bindings WHERE id=?", (binding_id,))
            # The permanent target marker prevents old raw vault APIs reopening.
            return result

    def is_managed_server(self, server_id: str) -> bool:
        return self.database.query_one("SELECT 1 FROM business_credential_targets WHERE server_id=?", (server_id,)) is not None

    def list_managed_servers(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self.database.query_all("SELECT * FROM business_credential_targets ORDER BY server_id")]

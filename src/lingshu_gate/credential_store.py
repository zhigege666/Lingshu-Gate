"""Encrypted local credential store for Lingshu Gate."""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from lingshu_gate.logging import log_event
from lingshu_gate.models import CredentialResponse

logger = logging.getLogger(__name__)
_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CredentialStore:
    """Store encrypted credential values under data_dir."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.store_path = data_dir / "credentials.json"
        self.key_path = data_dir / "credential.key"
        self._lock = threading.RLock()

    def list_credentials(self) -> list[CredentialResponse]:
        with self._lock:
            data = self._read_all()
            return [self._safe_response(item) for item in data.values()]

    def get_credential(self, credential_id: str) -> CredentialResponse:
        with self._lock:
            data = self._read_all()
            item = data.get(credential_id)
            if not item:
                raise KeyError(f"Credential not found: {credential_id}")
            return self._safe_response(item)

    def save_credential(self, *, name: str, value: str | None, description: str = "", credential_id: str | None = None) -> CredentialResponse:
        with self._lock:
            data = self._read_all()
            now = _now()
            target_id = credential_id or self._make_id(name)
            self._validate_id(target_id)
            existing = data.get(target_id, {})
            encrypted_value = existing.get("encrypted_value", "")
            if value is not None and value != "***":
                encrypted_value = self._fernet().encrypt(value.encode("utf-8")).decode("utf-8")
            if not encrypted_value:
                raise ValueError("Credential value is required")
            item = {
                "id": target_id,
                "name": name,
                "description": description,
                "encrypted_value": encrypted_value,
                "created_at": existing.get("created_at", now),
                "updated_at": now,
            }
            data[target_id] = item
            self._write_all(data)
            log_event(logger, logging.INFO, "gate.credential.saved", "Credential saved", credential_id=target_id, name=name)
            return self._safe_response(item)

    def delete_credential(self, credential_id: str) -> CredentialResponse:
        with self._lock:
            data = self._read_all()
            item = data.pop(credential_id, None)
            if not item:
                raise KeyError(f"Credential not found: {credential_id}")
            self._write_all(data)
            log_event(logger, logging.INFO, "gate.credential.deleted", "Credential deleted", credential_id=credential_id)
            return self._safe_response(item)

    def resolve_value(self, credential_id: str | None) -> str | None:
        if not credential_id:
            return None
        with self._lock:
            data = self._read_all()
            item = data.get(credential_id)
            if not item:
                raise KeyError(f"Credential not found: {credential_id}")
            token = item.get("encrypted_value", "")
            try:
                return self._fernet().decrypt(token.encode("utf-8")).decode("utf-8")
            except InvalidToken as exc:
                raise RuntimeError(f"Credential cannot be decrypted: {credential_id}") from exc

    def _safe_response(self, item: dict[str, Any]) -> CredentialResponse:
        return CredentialResponse(
            id=item["id"],
            name=item.get("name", item["id"]),
            description=item.get("description", ""),
            value_masked="***",
            created_at=item.get("created_at", ""),
            updated_at=item.get("updated_at", ""),
        )

    def _read_all(self) -> dict[str, dict[str, Any]]:
        if not self.store_path.exists():
            return {}
        data = json.loads(self.store_path.read_text(encoding="utf-8") or "{}")
        if not isinstance(data, dict):
            raise ValueError("credentials.json root must be an object")
        return data

    def _write_all(self, data: dict[str, dict[str, Any]]) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.store_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.store_path)

    def _fernet(self) -> Fernet:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.key_path.exists():
            self.key_path.write_bytes(Fernet.generate_key())
            try:
                self.key_path.chmod(0o600)
            except OSError:
                pass
            log_event(logger, logging.INFO, "gate.credential.key_created", "Credential encryption key created", path=str(self.key_path))
        return Fernet(self.key_path.read_bytes())

    def _make_id(self, name: str) -> str:
        normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "-", name.strip()).strip("-.")
        if not normalized:
            normalized = "credential"
        return normalized

    def _validate_id(self, credential_id: str) -> None:
        if not credential_id or not _ID_RE.match(credential_id):
            raise ValueError("credential_id must match ^[a-zA-Z0-9_.-]+$")

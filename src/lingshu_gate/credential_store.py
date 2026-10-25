"""Encrypted local credential store for Lingshu Gate."""

from __future__ import annotations

import json
import hashlib
import hmac
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken

from lingshu_gate.logging import log_event
from lingshu_gate.domain.dispatch_lock import DispatchLock
from lingshu_gate.endpoint_security import validate_streamable_http_endpoint
from lingshu_gate.models import CredentialResponse

logger = logging.getLogger(__name__)
_ID_RE = re.compile(r"^[a-zA-Z0-9_.-]+$")
_LOCKS_GUARD = threading.Lock()
_STORE_LOCKS: dict[Path, DispatchLock] = {}


class CredentialRevisionConflict(RuntimeError):
    """The approved binding no longer matches the encrypted value's revision."""


class CredentialAlreadyExists(ValueError):
    """Create never replaces an existing secret."""


class CredentialUsageDenied(ValueError):
    """The credential is not approved for this HTTP consumer and generation."""


class CredentialPersistenceInterrupted(RuntimeError):
    """A write or its completion logging failed; never claim it was rejected."""

    def __init__(self, *, committed: bool | None) -> None:
        self.committed = committed
        super().__init__("Credential persistence completion could not be confirmed.")


def canonical_http_origin(endpoint: str) -> str:
    """Normalize an already validated endpoint without granting network access."""
    validate_streamable_http_endpoint(endpoint, allow_rfc1918_declaration=True)
    parsed = urlsplit(endpoint)
    host = (parsed.hostname or "").encode("idna").decode("ascii").lower()
    if ":" in host:
        host = f"[{host}]"
    return f"{parsed.scheme.lower()}://{host}:{parsed.port or (443 if parsed.scheme.lower() == 'https' else 80)}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CredentialStore:
    """Store encrypted credential values under data_dir."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        self.store_path = data_dir / "credentials.json"
        self.key_path = data_dir / "credential.key"
        # Runtime clients construct their own stores. All instances for this
        # file must share the dispatch/mutation barrier, including rotations.
        with _LOCKS_GUARD:
            self._lock = _STORE_LOCKS.setdefault(self.store_path.resolve(), DispatchLock())

    def dispatch_guard(self) -> Any:
        """Hold until a request has been dispatched; writers wait for old sends."""
        return self._lock.read_lock()

    def mutation_guard(self) -> DispatchLock:
        return self._lock

    def list_credentials(self) -> list[CredentialResponse]:
        with self._lock.read_lock():
            data = self._read_all()
            return [self._safe_response(item) for item in data.values()]

    def get_credential(self, credential_id: str) -> CredentialResponse:
        with self._lock.read_lock():
            data = self._read_all()
            item = data.get(credential_id)
            if not item:
                raise KeyError(f"Credential not found: {credential_id}")
            return self._safe_response(item)

    def save_credential(self, *, name: str, value: str | None, description: str = "", credential_id: str | None = None,
                        http_scopes: list[dict[str, Any]] | None = None) -> CredentialResponse:
        """Internal compatibility upsert; public management uses create/update."""
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
                "http_scopes": http_scopes if http_scopes is not None else existing.get("http_scopes", []),
            }
            data[target_id] = item
            response = self._safe_response(item)
            self._persist(data, "gate.credential.saved", "Credential saved", credential_id=target_id, name=name)
            return response

    def create_credential(self, *, name: str, value: str, description: str = "", credential_id: str | None = None,
                          http_scopes: list[dict[str, Any]] | None = None) -> CredentialResponse:
        with self._lock:
            target_id = credential_id or self._make_id(name)
            self._validate_id(target_id)
            if target_id in self._read_all():
                raise CredentialAlreadyExists("Credential already exists.")
            if not value or value == "***":
                raise ValueError("A non-masked credential value is required.")
            return self.save_credential(name=name, value=value, description=description,
                                        credential_id=target_id, http_scopes=http_scopes or [])

    def update_credential(self, credential_id: str, *, expected_revision: str, name: str | None = None,
                          value: str | None = None, description: str | None = None,
                          http_scopes: list[dict[str, Any]] | None = None) -> CredentialResponse:
        with self._lock:
            current = self.get_credential(credential_id)
            if not expected_revision or current.updated_at != expected_revision:
                raise CredentialRevisionConflict("Credential revision changed; reload before updating.")
            if value is not None and (not value or value == "***"):
                raise ValueError("Use null to retain the value; masks are not credential values.")
            return self.save_credential(name=name if name is not None else current.name, value=value,
                description=description if description is not None else current.description,
                credential_id=credential_id, http_scopes=http_scopes)

    def delete_credential(self, credential_id: str, *, expected_revision: str | None = None) -> CredentialResponse:
        with self._lock:
            data = self._read_all()
            item = data.pop(credential_id, None)
            if not item:
                raise KeyError(f"Credential not found: {credential_id}")
            if expected_revision is not None and item.get("updated_at") != expected_revision:
                raise CredentialRevisionConflict("Credential revision changed; reload before deleting.")
            response = self._safe_response(item)
            self._persist(data, "gate.credential.deleted", "Credential deleted", credential_id=credential_id)
            return response

    def resolve_value(self, credential_id: str | None, *, expected_revision: str | None = None) -> str | None:
        if not credential_id:
            return None
        with self._lock.read_lock():
            data = self._read_all()
            item = data.get(credential_id)
            if not item:
                raise KeyError(f"Credential not found: {credential_id}")
            if expected_revision is not None and item.get("updated_at") != expected_revision:
                raise CredentialRevisionConflict("Managed credential binding changed after planning.")
            token = item.get("encrypted_value", "")
            try:
                return self._fernet().decrypt(token.encode("utf-8")).decode("utf-8")
            except InvalidToken as exc:
                raise RuntimeError(f"Credential cannot be decrypted: {credential_id}") from exc

    def request_fingerprint(self, request: dict[str, Any]) -> str:
        """Secret-bearing input is represented only by a private keyed digest."""
        with self._lock:
            self._fernet()
            encoded = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
            return hmac.new(self.key_path.read_bytes(), b"gate-shared-credential-operation-v1\0" + encoded,
                            hashlib.sha256).hexdigest()

    def assert_http_binding(self, credential_id: str, *, server_id: str, endpoint: str,
                            server_binding: str | None, expected_revision: str | None = None,
                            allow_pending: bool = False) -> None:
        origin = canonical_http_origin(endpoint)
        with self._lock.read_lock():
            item = self._read_all().get(credential_id)
            if item is None:
                raise KeyError("Credential reference is unavailable.")
            if expected_revision is not None and item.get("updated_at") != expected_revision:
                raise CredentialRevisionConflict("Managed credential binding changed after planning.")
            if any(scope.get("server_id") == server_id and scope.get("origin") == origin
                   and ((server_binding is not None and scope.get("server_binding") == server_binding)
                        or (allow_pending and scope.get("server_binding") is None))
                   for scope in item.get("http_scopes", [])):
                return
            raise CredentialUsageDenied("Credential is not approved for this HTTP service, origin and generation.")

    def bind_http_usage(self, credential_ids: Any, *, server_id: str, endpoint: str, server_binding: str) -> None:
        """Seal explicit pending scopes once, after configuration identity save.

        This consumes existing authority, so the approved value revision stays
        unchanged. No runtime/read path calls this method.
        """
        if not server_binding:
            raise CredentialUsageDenied("A saved service identity is required.")
        origin = canonical_http_origin(endpoint)
        with self._lock:
            refs = sorted(set(credential_ids))
            for ref in refs:
                self.assert_http_binding(ref, server_id=server_id, endpoint=endpoint,
                                         server_binding=server_binding, allow_pending=True)
            data, changed = self._read_all(), False
            for ref in refs:
                for scope in data[ref].get("http_scopes", []):
                    if scope.get("server_id") == server_id and scope.get("origin") == origin and scope.get("server_binding") is None:
                        scope["server_binding"], changed = server_binding, True
            if changed:
                self._write_all(data)

    def migrate_legacy_http_scopes(self, scopes: dict[str, list[dict[str, Any]]]) -> int:
        """Mark every legacy record once, even when it has no approved consumer."""
        with self._lock:
            data, changed = self._read_all(), 0
            for credential_id, item in data.items():
                if "http_scopes" not in item:
                    item["http_scopes"] = scopes.get(credential_id, [])
                    changed += 1
            if changed:
                self._write_all(data)
            return changed

    def _safe_response(self, item: dict[str, Any]) -> CredentialResponse:
        return CredentialResponse(
            id=item["id"],
            name=item.get("name", item["id"]),
            description=item.get("description", ""),
            value_masked="***",
            created_at=item.get("created_at", ""),
            updated_at=item.get("updated_at", ""),
            http_scopes=item.get("http_scopes", []),
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
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        tmp.replace(self.store_path)

    def _persist(self, data: dict[str, dict[str, Any]], event: str, message: str, **metadata: str) -> None:
        committed: bool | None = None
        try:
            self._write_all(data)
            committed = True
            log_event(logger, logging.INFO, event, message, **metadata)
        except Exception:
            raise CredentialPersistenceInterrupted(committed=committed) from None

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

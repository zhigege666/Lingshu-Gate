"""Private, encrypted delivery drafts; no configuration or runtime side effects."""
from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from lingshu_gate.credential_store import CredentialStore
from lingshu_gate.registry import ToolExecutionError

_SENSITIVE_NAME = re.compile(r"password|passwd|secret|token|authorization|cookie|api[_-]?key|private[_-]?key", re.I)
_REFERENCE = re.compile(r"^\$\{credential:[A-Za-z0-9_.-]+\}$")


class DeliveryDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)
    manifest_patch: dict[str, Any] = Field(default_factory=dict)
    server_id: str | None = None
    build_id: str | None = None
    deployment_id: str | None = None
    overwrite: StrictBool = False
    start: StrictBool = False
    project_root: str | None = None
    runtime_override: str | None = None


class DeliveryDraftStore:
    """Single-Core revision checks and atomic encrypted-file replacement.

    Name-based secret rejection is defense in depth, not a content classifier.
    Encrypt the whole draft so unrecognized sensitive values never enter a
    plaintext database or manifest. Only the owning operator can retrieve it.
    """
    def __init__(self, root: Path) -> None:
        self._encrypted = CredentialStore(root)
        self._lock = threading.RLock()

    @staticmethod
    def _key(upload_id: str, actor_id: str) -> str:
        return hashlib.sha256(json.dumps([upload_id, actor_id]).encode()).hexdigest()

    def get(self, upload_id: str, actor_id: str) -> dict[str, Any]:
        with self._lock:
            try:
                value = self._encrypted.resolve_value(self._key(upload_id, actor_id))
            except KeyError:
                return {"upload_id": upload_id, "revision": 0, **DeliveryDraftRequest(expected_revision=0).model_dump(exclude={"expected_revision"})}
            return json.loads(value or "{}")

    def save(self, upload_id: str, actor_id: str, request: DeliveryDraftRequest) -> dict[str, Any]:
        patch = request.manifest_patch
        if "user_credential_values" in patch:
            raise ValueError("Personal secret values cannot be stored in a delivery draft")
        launch = patch.get("launch") or {}
        transport = patch.get("transport") or {}
        if not isinstance(launch, dict) or not isinstance(transport, dict):
            raise ValueError("Draft launch and transport must be objects")
        for values in (launch.get("env", {}), launch.get("environment", {}), transport.get("headers", {})):
            if not isinstance(values, dict):
                raise ValueError("Draft environment and headers must be objects")
            for name, value in values.items():
                if value == "***":
                    raise ValueError("A redacted value cannot be saved as a draft; use credential references")
                if _SENSITIVE_NAME.search(name) and not _REFERENCE.fullmatch(str(value)):
                    raise ValueError("Sensitive draft fields require managed credential references")
        payload = request.model_dump(exclude={"expected_revision"})
        if len(json.dumps(payload).encode()) > 256 * 1024:
            raise ValueError("Delivery draft exceeds 256 KiB")
        with self._lock:
            existing = self.get(upload_id, actor_id)
            if existing["revision"] != request.expected_revision:
                raise ToolExecutionError("draft_revision_conflict", "Draft changed; reload it before saving")
            result = {"upload_id": upload_id, "revision": request.expected_revision + 1, **payload}
            self._encrypted.save_credential(name="Private delivery draft", credential_id=self._key(upload_id, actor_id), value=json.dumps(result))
            return result

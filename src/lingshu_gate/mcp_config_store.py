"""Writable MCP config store backed by the configured mcp.d directory."""

from __future__ import annotations

import json
import hashlib
import logging
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from lingshu_gate.application.manifest_edit import restore_masked_mounts
from lingshu_gate.logging import log_event
from lingshu_gate.endpoint_security import REDACTED_ENDPOINT
from lingshu_gate.mcp_manifest import McpServerManifest, validate_manifest_for_write
from lingshu_gate.mcp_http_trust import McpHttpTrustStore, require_mcp_http_endpoint
from lingshu_gate.models import McpConfigListResponse, McpConfigResponse
from lingshu_gate.redaction import redact_text, redact_validation_errors

logger = logging.getLogger(__name__)
SUPPORTED_SUFFIXES = {".yaml", ".yml", ".json"}
SECRET_MASK = "***"
METADATA_SNAPSHOT_TTL_SECONDS = 30.0


@dataclass(frozen=True)
class McpInstanceMetadata:
    instance_id: str
    name: str


class McpConfigConflict(ValueError):
    """The saved draft changed after the edit session was opened."""


class McpConfigStore:
    """Read and write MCP Server Manifest files in config_dir."""

    def __init__(self, config_dir: Path, *, http_trust_store: McpHttpTrustStore | None = None) -> None:
        self.config_dir = config_dir
        self.http_trust_store = http_trust_store
        self.mutation_lock = threading.RLock()
        self._instance_metadata: tuple[McpInstanceMetadata, ...] | None = None
        self._metadata_built_at = 0.0

    def invalidate_instance_metadata(self) -> None:
        with self.mutation_lock:
            self._instance_metadata = None

    def instance_metadata(self, *, refresh: bool = False) -> tuple[McpInstanceMetadata, ...]:
        """Cache only immutable IDs/names; never credentials, manifests or authority."""
        with self.mutation_lock:
            if (refresh or self._instance_metadata is None
                    or time.monotonic() - self._metadata_built_at >= METADATA_SNAPSHOT_TTL_SECONDS):
                records = []
                for path in self._iter_files():
                    try:
                        manifest = self._load_manifest(path)
                        records.append(McpInstanceMetadata(manifest.id, manifest.name or manifest.id))
                    except Exception:  # noqa: BLE001 - invalid files cannot become available members
                        log_event(logger, logging.ERROR, "gate.mcp.config_metadata_error", "Invalid MCP instance metadata", path=str(path))
                self._instance_metadata = tuple(records)
                self._metadata_built_at = time.monotonic()
            return self._instance_metadata

    def list_configs(self) -> McpConfigListResponse:
        configs: list[McpConfigResponse] = []
        errors: list[str] = []
        for path in self._iter_files():
            try:
                configs.append(self._to_response(path))
            except Exception as exc:  # noqa: BLE001 - list should continue after one bad file
                safe_error = redact_text(str(exc))
                error = f"{path.name}: {safe_error}"
                errors.append(error)
                log_event(logger, logging.ERROR, "gate.mcp.config_read_error", "Failed to read MCP config", path=str(path), error=safe_error, exc_info=True)
        return McpConfigListResponse(configs=configs, errors=errors)

    def get_config(self, server_id: str) -> McpConfigResponse:
        self._validate_server_id(server_id)
        path = self._find_path(server_id)
        if not path:
            raise KeyError(f"MCP config not found: {server_id}")
        return self._to_response(path)

    def load_manifest(self, server_id: str) -> McpServerManifest:
        """读取供内部运行时使用的未脱敏 Manifest；不得直接返回给 API 调用方。"""

        self._validate_server_id(server_id)
        path = self._find_path(server_id)
        if not path:
            raise KeyError(f"MCP config not found: {server_id}")
        return self._load_manifest(path)

    def save_config(self, manifest_data: dict[str, Any], *, expected_id: str | None = None, overwrite: bool = False, expected_digest: str | None = None) -> McpConfigResponse:
        with self.mutation_lock:
            try:
                return self._save_config(manifest_data, expected_id=expected_id, overwrite=overwrite, expected_digest=expected_digest)
            finally:
                self.invalidate_instance_metadata()

    def _save_config(self, manifest_data: dict[str, Any], *, expected_id: str | None = None, overwrite: bool = False, expected_digest: str | None = None) -> McpConfigResponse:
        manifest_id = str(manifest_data.get("id", ""))
        self._validate_server_id(manifest_id)
        if expected_id and manifest_id != expected_id:
            raise ValueError(f"Manifest id mismatch: expected {expected_id}, got {manifest_id}")

        existing_path = self._find_path(manifest_id)
        if existing_path is not None:
            existing_path = self._checked_path(existing_path)
        if expected_digest is not None and (existing_path is None or hashlib.sha256(existing_path.read_bytes()).hexdigest() != expected_digest):
            raise McpConfigConflict("MCP configuration changed; reopen the saved configuration before updating")
        if existing_path and not overwrite:
            raise FileExistsError(f"MCP config already exists: {manifest_id}")
        if existing_path:
            existing_raw = self._load_raw(existing_path)
            manifest_data = self._preserve_masked_env(manifest_data, existing_raw)

        manifest = _validate_manifest(manifest_data, for_write=True, http_trust_store=self.http_trust_store)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        path = self._checked_path(existing_path or self.config_dir / f"{manifest.id}.yaml")
        self._write_manifest(path, manifest.model_dump(mode="json", exclude={"manifest_path"}))
        saved = self._load_manifest(path)
        log_event(logger, logging.INFO, "gate.mcp.config_saved", "MCP config saved", server_id=saved.id, path=str(path), overwrite=bool(existing_path))
        return self._to_response(path)

    def check_http_trust(self, manifest: McpServerManifest) -> None:
        if manifest.transport.endpoint:
            require_mcp_http_endpoint(manifest.id, manifest.transport.endpoint, self.http_trust_store)

    def delete_config(self, server_id: str) -> McpConfigResponse:
        with self.mutation_lock:
            try:
                return self._delete_config(server_id)
            finally:
                self.invalidate_instance_metadata()

    def _delete_config(self, server_id: str) -> McpConfigResponse:
        self._validate_server_id(server_id)
        path = self._find_path(server_id)
        if not path:
            raise KeyError(f"MCP config not found: {server_id}")
        path = self._checked_path(path)
        response = self._to_response(path)
        path.unlink()
        log_event(logger, logging.INFO, "gate.mcp.config_deleted", "MCP config deleted", server_id=server_id, path=str(path))
        return response

    def _iter_files(self) -> list[Path]:
        if not self.config_dir.exists():
            return []
        return sorted(path for path in self.config_dir.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES)

    def _find_path(self, server_id: str) -> Path | None:
        for path in self._iter_files():
            try:
                raw = self._load_raw(path)
            except Exception:
                continue
            if str(raw.get("id", "")) == server_id:
                return path
        for suffix in (".yaml", ".yml", ".json"):
            candidate = self._checked_path(self.config_dir / f"{server_id}{suffix}")
            if candidate.exists():
                return candidate
        return None

    def _load_manifest(self, path: Path) -> McpServerManifest:
        raw = self._load_raw(path)
        manifest = _validate_manifest(raw)
        manifest.manifest_path = path
        return manifest

    def _checked_path(self, path: Path) -> Path:
        # Resolve before checking the directory boundary: lexical prefixes and
        # server-ID validation alone cannot contain a symlinked configuration.
        root = os.path.realpath(self.config_dir)
        normalized = os.path.realpath(path)
        if not normalized.startswith(os.path.join(root, "")) or os.path.dirname(normalized) != root:
            raise ValueError("MCP configuration must be a direct file in config_dir")
        return Path(normalized)

    def _load_raw(self, path: Path, *, content: bytes | None = None) -> dict[str, Any]:
        path = self._checked_path(path)
        text = (path.read_bytes() if content is None else content).decode("utf-8")
        if path.suffix.lower() == ".json":
            data = json.loads(text)
        else:
            data = yaml.safe_load(text) or {}
        if not isinstance(data, dict):
            raise ValueError("Manifest root must be an object")
        return data

    def _write_manifest(self, path: Path, data: dict[str, Any]) -> None:
        path = self._checked_path(path)
        if path.suffix.lower() == ".json":
            content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        else:
            content = yaml.safe_dump(data, allow_unicode=True, sort_keys=False)

        temporary_path: Path | None = None
        try:
            # Windows 上必须先关闭临时文件句柄，再通过 os.replace 原子替换目标文件。
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=f".{path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                temporary_file.write(content)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, path)
        except BaseException:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError as cleanup_error:
                    log_event(
                        logger,
                        logging.WARNING,
                        "gate.mcp.config_temp_cleanup_error",
                        "Failed to clean temporary MCP config",
                        path=str(temporary_path),
                        error=str(cleanup_error),
                    )
            raise

    def _to_response(self, path: Path) -> McpConfigResponse:
        # The manifest and CAS digest come from the same opened file snapshot,
        # even if a writer atomically replaces the path while it is read.
        path = self._checked_path(path)
        content = path.read_bytes()
        manifest = _validate_manifest(self._load_raw(path, content=content))
        manifest.manifest_path = path
        suffix = path.suffix.lower().lstrip(".") or "yaml"
        return McpConfigResponse(id=manifest.id, path=str(path), format=suffix, manifest=manifest.safe_dict(), digest=hashlib.sha256(content).hexdigest())

    def _preserve_masked_env(self, new_data: dict[str, Any], existing_data: dict[str, Any]) -> dict[str, Any]:
        new_copy = restore_masked_mounts(new_data, existing_data)
        new_launch = dict(new_copy.get("launch") or {})
        existing_launch = existing_data.get("launch") if isinstance(existing_data.get("launch"), dict) else {}
        for field_name in ("env", "environment"):
            new_env = new_launch.get(field_name)
            old_env = existing_launch.get(field_name) if isinstance(existing_launch, dict) else None
            if not isinstance(new_env, dict) or not isinstance(old_env, dict):
                continue
            merged = dict(new_env)
            for key, value in new_env.items():
                if value == SECRET_MASK and key in old_env:
                    merged[key] = old_env[key]
            new_launch[field_name] = merged
        new_copy["launch"] = new_launch

        # 安全响应同样会掩码 HTTP headers；回滚/编辑时必须保留磁盘中的真实值。
        new_transport = dict(new_copy.get("transport") or {})
        raw_existing_transport = existing_data.get("transport")
        existing_transport: dict[str, Any] = (
            dict(raw_existing_transport)
            if isinstance(raw_existing_transport, dict)
            else {}
        )
        new_headers = new_transport.get("headers")
        old_headers = existing_transport.get("headers")
        if isinstance(new_headers, dict) and isinstance(old_headers, dict):
            merged_headers = dict(new_headers)
            for key, value in new_headers.items():
                if value == SECRET_MASK and key in old_headers:
                    merged_headers[key] = old_headers[key]
            new_transport["headers"] = merged_headers
        if new_transport.get("endpoint") == REDACTED_ENDPOINT and isinstance(
            existing_transport.get("endpoint"),
            str,
        ):
            new_transport["endpoint"] = existing_transport["endpoint"]
        new_copy["transport"] = new_transport
        return new_copy

    def _validate_server_id(self, server_id: str) -> None:
        try:
            McpServerManifest.model_validate(
                {
                    "id": server_id,
                    "launch": {"type": "managed_process", "command": "placeholder"},
                    "transport": {"type": "stdio"},
                }
            )
        except ValidationError as exc:
            raise ValueError("server_id must match ^[a-zA-Z0-9_.-]+$") from exc


def _validate_manifest(data: dict[str, Any], *, for_write: bool = False, http_trust_store: McpHttpTrustStore | None = None) -> McpServerManifest:
    try:
        return validate_manifest_for_write(data, http_trust_store=http_trust_store) if for_write else McpServerManifest.model_validate(data)
    except ValidationError as exc:
        errors = redact_validation_errors(exc.errors())
        raise ValueError(redact_text(f"Manifest validation failed: {errors}")) from None

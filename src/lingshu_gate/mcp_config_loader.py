"""Load MCP server manifests from a mounted config directory."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import ValidationError

from lingshu_gate.logging import log_event
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.path_diagnostics import inspect_directory
from lingshu_gate.redaction import redact_text, redact_validation_errors

logger = logging.getLogger(__name__)

McpConfigScanStatus = Literal["not_scanned", "missing", "loaded", "failed"]


@dataclass
class McpConfigLoadResult:
    manifests: list[McpServerManifest] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    scan_status: McpConfigScanStatus = "not_scanned"


class McpConfigLoader:
    """Load JSON/YAML MCP manifests from a directory."""

    supported_suffixes = {".yaml", ".yml", ".json"}

    def __init__(self, config_dir: Path) -> None:
        self.config_dir = config_dir

    def load(self) -> McpConfigLoadResult:
        result = McpConfigLoadResult()
        log_event(logger, logging.INFO, "gate.mcp.config_scan_started", "Scanning MCP config directory", config_dir=str(self.config_dir))

        directory = inspect_directory(self.config_dir, allow_missing=True, require_writable=False)
        if not directory.ok:
            result.scan_status = "failed"
            error = f"MCP configuration scan failed ({directory.code}): {directory.detail}"
            result.errors.append(error)
            log_event(
                logger, logging.ERROR, "gate.mcp.config_dir_invalid", "Cannot scan MCP config directory",
                reason_code=directory.code, diagnostic=directory.metadata(),
            )
            return result
        if directory.code == "directory_creatable":
            result.scan_status = "missing"
            log_event(
                logger,
                logging.WARNING,
                "gate.mcp.config_dir_missing",
                "MCP config directory does not exist",
                config_dir=str(self.config_dir),
            )
            return result

        try:
            paths = sorted(path for path in self.config_dir.iterdir() if path.suffix.lower() in self.supported_suffixes)
        except OSError as exc:
            result.scan_status = "failed"
            result.errors.append(f"MCP configuration directory cannot be scanned ({type(exc).__name__})")
            log_event(
                logger, logging.ERROR, "gate.mcp.config_scan_failed", "Cannot enumerate MCP config directory",
                config_dir=str(self.config_dir), error_type=type(exc).__name__, errno=exc.errno,
            )
            return result
        log_event(
            logger,
            logging.INFO,
            "gate.mcp.config_files_found",
            "MCP config files found",
            config_dir=str(self.config_dir),
            count=len(paths),
            files=[path.name for path in paths],
        )

        seen_ids: set[str] = set()
        for path in paths:
            try:
                manifest = self._load_one(path)
                if manifest.id in seen_ids:
                    raise ValueError(f"Duplicate MCP server id: {manifest.id}")
                seen_ids.add(manifest.id)
                result.manifests.append(manifest)
                log_event(
                    logger,
                    logging.INFO,
                    "gate.mcp.manifest_loaded",
                    "MCP manifest loaded",
                    server_id=manifest.id,
                    path=str(path),
                    manifest=manifest.safe_dict(),
                )
            except Exception as exc:  # noqa: BLE001 - config boundary must continue loading other files
                safe_error = redact_text(str(exc))
                error = f"{path}: {safe_error}"
                result.errors.append(error)
                log_event(
                    logger,
                    logging.ERROR,
                    "gate.mcp.manifest_load_error",
                    "Failed to load MCP manifest",
                    path=str(path),
                    error=safe_error,
                )
        result.scan_status = "failed" if result.errors else "loaded"
        return result

    def _load_one(self, path: Path) -> McpServerManifest:
        payload = self._read_payload(path)
        try:
            manifest = McpServerManifest.model_validate(payload)
        except ValidationError as exc:
            raise ValueError(redact_validation_errors(exc.errors())) from None
        manifest.manifest_path = path
        return manifest

    def _read_payload(self, path: Path) -> dict[str, Any]:
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            payload = json.loads(text)
        else:
            payload = yaml.safe_load(text)
        if not isinstance(payload, dict):
            raise ValueError("Manifest root must be an object")
        return payload

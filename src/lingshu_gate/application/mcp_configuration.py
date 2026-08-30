"""Application workflows for MCP configuration changes.

This module owns the ordering and compensating actions required to keep the
configuration files, runtime state, and per-user credential bindings aligned.
HTTP concerns such as authentication and transport security stay in the
control API adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lingshu_gate.endpoint_security import REDACTED_ENDPOINT
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.models import McpConfigApplyResponse, McpConfigSaveRequest
from lingshu_gate.ports.control_plane import (
    McpConfigurationRepository,
    McpRuntimeControl,
    UserCredentialRepository,
)


@dataclass(frozen=True, slots=True)
class PreparedUserCredentials:
    """Validated one-request credential values kept outside the manifest."""

    manifest: McpServerManifest
    values: dict[str, str]


def _restore_redacted_endpoint(
    manifest_data: dict[str, Any],
    existing_manifest: McpServerManifest | None,
) -> dict[str, Any]:
    """Restore a masked endpoint only while editing its existing manifest."""

    restored = dict(manifest_data)
    transport = dict(restored.get("transport") or {})
    if transport.get("endpoint") == REDACTED_ENDPOINT and existing_manifest is not None:
        transport["endpoint"] = existing_manifest.transport.endpoint
    restored["transport"] = transport
    return restored


class McpConfigurationService:
    """Coordinate durable MCP configuration and runtime state transitions."""

    def __init__(
        self,
        config_store: McpConfigurationRepository,
        runtime: McpRuntimeControl,
        user_credential_store: UserCredentialRepository,
    ) -> None:
        self._config_store = config_store
        self._runtime = runtime
        self._user_credential_store = user_credential_store

    def prepare_user_credentials(
        self,
        request: McpConfigSaveRequest,
        *,
        existing_server_id: str | None = None,
    ) -> PreparedUserCredentials:
        """Validate one-time secrets without adding them to the manifest."""

        manifest_data = _restore_redacted_endpoint(
            request.manifest,
            self._config_store.load_manifest(existing_server_id)
            if existing_server_id
            else None,
        )
        manifest = McpServerManifest.model_validate(manifest_data)
        values = dict(request.user_credential_values)
        declared_slots = {slot.id for slot in manifest.user_credentials}
        unknown = sorted(set(values) - declared_slots)
        if unknown:
            raise ValueError(
                "user_credential_values contains undeclared slot(s): "
                + ", ".join(unknown)
            )
        for value in values.values():
            self._user_credential_store.validate_value(value)
        return PreparedUserCredentials(manifest=manifest, values=values)

    def create(
        self,
        request: McpConfigSaveRequest,
        *,
        user_id: str,
        prepared: PreparedUserCredentials,
    ) -> McpConfigApplyResponse:
        """Persist a new config and compensate if applying it fails."""

        config = self._config_store.save_config(request.manifest, overwrite=False)
        try:
            server = (
                self._runtime.apply_manifest(
                    self._config_store.load_manifest(config.id),
                    start=request.start,
                    source="config_create",
                )
                if request.apply
                else None
            )
        except Exception as apply_error:
            try:
                self._config_store.delete_config(config.id)
            except Exception as rollback_error:
                raise RuntimeError(
                    f"MCP config create failed and disk rollback failed: {rollback_error}"
                ) from apply_error
            raise

        self._save_user_credentials(user_id, prepared)
        return McpConfigApplyResponse(config=config, server=server, message="created")

    def update(
        self,
        server_id: str,
        request: McpConfigSaveRequest,
        *,
        user_id: str,
        prepared: PreparedUserCredentials,
    ) -> McpConfigApplyResponse:
        """Persist a replacement and restore the exact prior manifest on failure."""

        previous_manifest = self._config_store.load_manifest(server_id)
        config = self._config_store.save_config(
            request.manifest,
            expected_id=server_id,
            overwrite=True,
        )
        try:
            server = (
                self._runtime.apply_manifest(
                    self._config_store.load_manifest(config.id),
                    start=request.start,
                    source="config_update",
                )
                if request.apply
                else None
            )
        except Exception as apply_error:
            try:
                self._config_store.save_config(
                    previous_manifest.model_dump(
                        mode="json",
                        exclude={"manifest_path"},
                    ),
                    expected_id=server_id,
                    overwrite=True,
                )
            except Exception as rollback_error:
                raise RuntimeError(
                    f"MCP config update failed and disk rollback failed: {rollback_error}"
                ) from apply_error
            raise

        self._save_user_credentials(user_id, prepared)
        return McpConfigApplyResponse(config=config, server=server, message="updated")

    def delete(self, server_id: str) -> tuple[McpConfigApplyResponse, int]:
        """Remove runtime then disk state, restoring the target runtime if needed."""

        previous_manifest = self._config_store.load_manifest(server_id)
        previous_server = (
            self._runtime.get_server(server_id)
            if self._runtime.has_server(server_id)
            else None
        )
        restore_start = bool(
            previous_server
            and (
                previous_server.desired_state == "running"
                or previous_server.status == "running"
            )
        )
        self._runtime.remove_manifest(server_id)
        try:
            config = self._config_store.delete_config(server_id)
        except Exception as delete_error:
            if previous_server is not None:
                try:
                    self._runtime.apply_manifest(
                        previous_manifest,
                        start=restore_start,
                        source="config_delete_rollback",
                    )
                except Exception as rollback_error:
                    raise RuntimeError(
                        "MCP config delete failed and runtime rollback failed: "
                        f"{rollback_error}"
                    ) from delete_error
            raise

        removed_user_credentials = (
            self._user_credential_store.delete_server_bindings(server_id)
        )
        response = McpConfigApplyResponse(
            config=config,
            servers=self._runtime.list_servers(),
            message="deleted",
        )
        return response, removed_user_credentials

    def reload(self) -> McpConfigApplyResponse:
        self._runtime.reload_manifests()
        return McpConfigApplyResponse(
            servers=self._runtime.list_servers(),
            message="reloaded",
        )

    def apply(self, server_id: str) -> McpConfigApplyResponse:
        config = self._config_store.get_config(server_id)
        server = self._runtime.apply_manifest(
            self._config_store.load_manifest(server_id),
            start=False,
            source="config_apply",
        )
        return McpConfigApplyResponse(
            config=config,
            server=server,
            message="applied",
        )

    def _save_user_credentials(
        self,
        user_id: str,
        prepared: PreparedUserCredentials,
    ) -> None:
        for slot_id, value in prepared.values.items():
            self._user_credential_store.save_binding(
                user_id=user_id,
                server_id=prepared.manifest.id,
                slot_id=slot_id,
                value=value,
            )

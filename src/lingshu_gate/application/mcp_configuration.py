"""Application workflows for MCP configuration changes.

This module owns the ordering and compensating actions required to keep the
configuration files, runtime state, and per-user credential bindings aligned.
HTTP concerns such as authentication and transport security stay in the
control API adapter.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any

from lingshu_gate.application.manifest_edit import restore_masked_mounts
from lingshu_gate.credential_refs import extract_credential_refs
from lingshu_gate.credential_store import CredentialStore, canonical_http_origin
from lingshu_gate.endpoint_security import REDACTED_ENDPOINT
from lingshu_gate.domain.mcp_configuration_errors import McpConfigPartialError
from lingshu_gate.mcp_manifest import McpServerManifest, validate_manifest_for_write, with_new_manifest_defaults
from lingshu_gate.mcp_authorization_policy import server_binding
from lingshu_gate.models import McpConfigApplyResponse, McpConfigSaveRequest
from lingshu_gate.persistence.mcp_groups import McpGroupStore
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

    restored = (
        restore_masked_mounts(manifest_data, existing_manifest.model_dump(mode="json", exclude={"manifest_path"}))
        if existing_manifest is not None else dict(manifest_data)
    )
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
        group_store: McpGroupStore | None = None,
        *,
        on_deleted: Callable[[str], None] | None = None,
        credentials: CredentialStore | None = None,
    ) -> None:
        self._config_store = config_store
        self._runtime = runtime
        self._user_credential_store = user_credential_store
        self._group_store = group_store
        self._on_deleted = on_deleted
        self._credentials = credentials

    def http_credential_binding(self, manifest: McpServerManifest) -> str | None:
        """Return the identity only when the saved target is still this target."""
        trust = getattr(self._config_store, "http_trust_store", None)
        if trust is None:
            return None
        try:
            current = self._config_store.load_manifest(manifest.id)
            if (current.launch.type, current.transport.type, current.transport.endpoint) != (
                    manifest.launch.type, manifest.transport.type, manifest.transport.endpoint):
                return None
            with trust.database.session() as connection:
                return server_binding(connection, manifest.id)
        except (KeyError, ValueError):
            return None

    def validate_http_credentials(self, manifest: McpServerManifest, *, allow_pending: bool = True) -> None:
        if self._credentials is None or manifest.transport.type != "streamable_http":
            return
        binding = self.http_credential_binding(manifest)
        for value in manifest.transport.headers.values():
            for ref in extract_credential_refs(value):
                self._credentials.assert_http_binding(ref, server_id=manifest.id, endpoint=manifest.transport.endpoint or "",
                                                      server_binding=binding, allow_pending=allow_pending)

    def _bind_saved_http_credentials(self, manifest: McpServerManifest) -> None:
        if self._credentials is None or manifest.transport.type != "streamable_http":
            return
        refs = {ref for value in manifest.transport.headers.values() for ref in extract_credential_refs(value)}
        if refs:
            binding = self.http_credential_binding(manifest)
            if binding is None:
                raise ValueError("Saved HTTP service identity is unavailable")
            self._credentials.bind_http_usage(sorted(refs), server_id=manifest.id,
                                             endpoint=manifest.transport.endpoint or "", server_binding=binding)

    def _has_new_http_side_effects(self, manifest: McpServerManifest, trust_plan: dict[str, Any] | None) -> bool:
        """Keep legacy rollback when the save changes no new policy store."""
        if trust_plan is not None and (trust_plan["change"] in {"authorize", "retire"}
                                       or trust_plan["policy_state"] == "pending"):
            return True
        if self._credentials is not None and manifest.transport.type == "streamable_http":
            origin = canonical_http_origin(manifest.transport.endpoint or "")
            refs = {ref for value in manifest.transport.headers.values() for ref in extract_credential_refs(value)}
            return any(scope.server_id == manifest.id and scope.origin == origin and scope.server_binding is None
                       for ref in refs for scope in self._credentials.get_credential(ref).http_scopes)
        return False

    def plan_http_save(self, manifest_data: dict[str, Any], *, existing_server_id: str | None = None,
                       action: str = "auto", expected_revision: int | None = None) -> dict[str, Any] | None:
        """Prepare an exact permission change without writing or contacting a peer."""
        previous = self._config_store.load_manifest(existing_server_id) if existing_server_id else None
        data = _restore_redacted_endpoint(manifest_data, previous)
        manifest = validate_manifest_for_write(data, check_http_trust=False)
        trust = getattr(self._config_store, "http_trust_store", None)
        if trust is None or manifest.transport.type != "streamable_http":
            return None
        return trust.plan_configuration(manifest.id, manifest.transport.endpoint, action=action,
                                        previous_endpoint=previous.transport.endpoint if previous else None,
                                        creating=previous is None, expected_revision=expected_revision)

    def prepare_user_credentials(
        self,
        request: McpConfigSaveRequest,
        *,
        existing_server_id: str | None = None,
        http_trust_plan: dict[str, Any] | None = None,
    ) -> PreparedUserCredentials:
        """Validate one-time secrets without adding them to the manifest."""

        manifest_data = _restore_redacted_endpoint(
            request.manifest,
            self._config_store.load_manifest(existing_server_id)
            if existing_server_id
            else None,
        )
        if existing_server_id is None:
            manifest_data = with_new_manifest_defaults(manifest_data)
        manifest = validate_manifest_for_write(manifest_data, http_trust_store=getattr(self._config_store, "http_trust_store", None),
                                               check_http_trust=http_trust_plan is None)
        self.validate_http_credentials(manifest)
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
        http_trust_plan: dict[str, Any] | None = None,
    ) -> McpConfigApplyResponse:
        """Persist a new config and compensate if applying it fails."""

        with getattr(self._config_store, "mutation_lock", nullcontext()):
            self.validate_http_credentials(prepared.manifest)
            has_policy_writes = self._has_new_http_side_effects(prepared.manifest, http_trust_plan)
            if http_trust_plan is not None:
                if request.start and not http_trust_plan["connection_allowed"]:
                    raise ValueError("HTTP connection permission is revoked; explicitly restore it before connecting")
                config = self._config_store.save_config_with_http_trust(  # type: ignore[attr-defined]
                    request.manifest, overwrite=False, trust_plan=http_trust_plan, actor_id=user_id)
            else:
                config = self._config_store.save_config(request.manifest, overwrite=False)
            try:
                if self._credentials is not None:
                    self._bind_saved_http_credentials(self._config_store.load_manifest(config.id))
                server = (
                    self._runtime.apply_manifest(
                        self._config_store.load_manifest(config.id),
                        start=request.start,
                        source="config_create",
                    )
                    if request.apply and (http_trust_plan is None or http_trust_plan["connection_allowed"])
                    else None
                )
                self._save_user_credentials(user_id, prepared)
            except Exception as apply_error:
                if has_policy_writes:
                    # File, identity, trust and secret-scope stores have no
                    # shared transaction. Retain facts and require review;
                    # silently deleting a saved target cannot undo a sealed
                    # credential scope or a permission change.
                    raise McpConfigPartialError(config.id, config.digest) from apply_error
                try:
                    self._config_store.delete_config(config.id)
                except Exception as rollback_error:
                    raise RuntimeError(
                        f"MCP config create failed and disk rollback failed: {rollback_error}"
                    ) from apply_error
                raise

            return McpConfigApplyResponse(config=config, server=server, message="created")

    def update(
        self,
        server_id: str,
        request: McpConfigSaveRequest,
        *,
        user_id: str,
        prepared: PreparedUserCredentials,
        http_trust_plan: dict[str, Any] | None = None,
    ) -> McpConfigApplyResponse:
        """Persist a replacement and restore the exact prior manifest on failure."""

        with getattr(self._config_store, "mutation_lock", nullcontext()):
            previous_manifest = self._config_store.load_manifest(server_id)
            self.validate_http_credentials(prepared.manifest)
            has_policy_writes = self._has_new_http_side_effects(prepared.manifest, http_trust_plan)
            if http_trust_plan is not None:
                if request.start and not http_trust_plan["connection_allowed"]:
                    raise ValueError("HTTP connection permission is revoked; explicitly restore it before connecting")
                config = self._config_store.save_config_with_http_trust(  # type: ignore[attr-defined]
                    request.manifest, expected_id=server_id, overwrite=True, expected_digest=request.expected_config_digest,
                    trust_plan=http_trust_plan, actor_id=user_id)
            else:
                config = self._config_store.save_config(
                    request.manifest,
                    expected_id=server_id,
                    overwrite=True,
                    **({"expected_digest": request.expected_config_digest} if request.expected_config_digest is not None else {}),
                )
            try:
                if self._credentials is not None:
                    self._bind_saved_http_credentials(self._config_store.load_manifest(config.id))
                server = (
                    self._runtime.apply_manifest(
                        self._config_store.load_manifest(config.id),
                        start=request.start,
                        source="config_update",
                    )
                    if request.apply and (http_trust_plan is None or http_trust_plan["connection_allowed"])
                    else None
                )
                self._save_user_credentials(user_id, prepared)
            except Exception as apply_error:
                if has_policy_writes:
                    raise McpConfigPartialError(config.id, config.digest) from apply_error
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

            return McpConfigApplyResponse(config=config, server=server, message="updated")

    def delete(self, server_id: str, *, remove_runtime: Callable[[], Any] | None = None,
               remove_group_memberships: bool = False) -> tuple[McpConfigApplyResponse, int]:
        """Remove runtime then disk state, restoring the target runtime if needed."""

        with getattr(self._config_store, "mutation_lock", nullcontext()):
            previous_manifest = self._config_store.load_manifest(server_id)
            if self._group_store is not None:
                # Fail closed before destructive file/runtime steps. A compensated
                # failure still needs an explicit group re-confirmation.
                self._group_store.invalidate_instances({server_id}, reason="instance_delete_requested")
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
            if remove_runtime is not None:
                remove_runtime()
            else:
                self._runtime.remove_manifest(server_id)
            try:
                config = self._config_store.delete_config(server_id)
            except McpConfigPartialError:
                # The file is already gone. Reconnecting an old runtime would
                # recreate access while durable cleanup remains incomplete.
                raise
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

            # A stop or compensated disk failure is temporary unavailability.
            # Retire review state only after the configuration is really gone.
            try:
                removed_user_credentials = self.cleanup_deleted_metadata(server_id, remove_group_memberships=remove_group_memberships)
            except Exception as exc:
                raise McpConfigPartialError(server_id, None, deleted=True) from exc
            response = McpConfigApplyResponse(
                config=config,
                servers=self._runtime.list_servers(),
                message="deleted",
            )
            return response, removed_user_credentials

    def cleanup_deleted_metadata(self, server_id: str, *, remove_group_memberships: bool = True) -> int:
        """Retire derived state after the caller has verified durable removal."""
        with getattr(self._config_store, "mutation_lock", nullcontext()):
            if remove_group_memberships and self._group_store is not None:
                self._group_store.remove_instance_memberships(server_id)
            if self._on_deleted is not None:
                self._on_deleted(server_id)
            return self._user_credential_store.delete_server_bindings(server_id)

    def reload(self) -> McpConfigApplyResponse:
        with getattr(self._config_store, "mutation_lock", nullcontext()):
            self._config_store.invalidate_instance_metadata()
            if self._group_store is not None:
                present = {config.id for config in self._config_store.list_configs().configs}
                self._group_store.reconcile_instances(present)
            self._runtime.reload_manifests()
            return McpConfigApplyResponse(servers=self._runtime.list_servers(), message="reloaded")

    def apply(self, server_id: str) -> McpConfigApplyResponse:
        with getattr(self._config_store, "mutation_lock", nullcontext()):
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

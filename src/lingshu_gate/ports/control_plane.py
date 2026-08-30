"""Control-plane contracts that isolate application logic from concrete stores."""

from __future__ import annotations

from typing import Any, Mapping, Protocol

from lingshu_gate.domain.health import ComponentStatus
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.models import (
    McpConfigResponse,
    McpServerListResponse,
    McpServerStatusResponse,
)


class RuntimeDriver(Protocol):
    """Runtime status boundary; lifecycle commands can be added without leaking internals."""

    def readiness(self) -> ComponentStatus:
        """Return whether the local runtime catalog can safely serve requests."""


class StateStore(Protocol):
    """Durable control-plane state boundary."""

    def readiness(self) -> ComponentStatus:
        """Return whether durable state is reachable and initialized."""


class ConfigurationSource(Protocol):
    """Manifest/configuration source boundary."""

    def readiness(self) -> ComponentStatus:
        """Return whether the source is readable and can accept updates."""


class SecretStore(Protocol):
    """Secret resolution boundary used by runtime and deployment services."""

    def resolve(self, secret_id: str | None) -> str | None:
        """Resolve a secret without exposing the concrete storage format."""


class EventSink(Protocol):
    """Application event output boundary."""

    def emit(
        self,
        event_type: str,
        *,
        source: str,
        subject_type: str | None = None,
        subject_id: str | None = None,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        """Publish an event to the configured observability backend."""


class McpConfigurationRepository(Protocol):
    """Durable manifest operations needed by configuration workflows."""

    def get_config(self, server_id: str) -> McpConfigResponse: ...

    def load_manifest(self, server_id: str) -> McpServerManifest: ...

    def save_config(
        self,
        manifest_data: dict[str, Any],
        *,
        expected_id: str | None = None,
        overwrite: bool = False,
    ) -> McpConfigResponse: ...

    def delete_config(self, server_id: str) -> McpConfigResponse: ...


class McpRuntimeControl(Protocol):
    """Targeted runtime operations used by configuration workflows."""

    def apply_manifest(
        self,
        manifest: McpServerManifest,
        *,
        start: bool,
        source: str = "config_apply",
    ) -> McpServerStatusResponse: ...

    def reload_manifests(
        self,
        *,
        server_id_to_start: str | None = None,
        start: bool = False,
    ) -> McpServerStatusResponse | None: ...

    def remove_manifest(self, server_id: str) -> McpServerStatusResponse | None: ...

    def list_servers(self) -> McpServerListResponse: ...

    def get_server(self, server_id: str) -> McpServerStatusResponse: ...

    def has_server(self, server_id: str) -> bool: ...


class UserCredentialRepository(Protocol):
    """Per-user credential operations needed by configuration workflows."""

    def validate_value(self, value: str) -> str: ...

    def save_binding(
        self,
        *,
        user_id: str,
        server_id: str,
        slot_id: str,
        value: str,
    ) -> dict[str, Any]: ...

    def delete_server_bindings(self, server_id: str) -> int: ...

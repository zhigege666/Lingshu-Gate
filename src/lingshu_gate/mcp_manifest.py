"""MCP Server manifest models."""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from lingshu_gate.endpoint_security import redact_endpoint, validate_streamable_http_endpoint
from lingshu_gate.protocol.version import require_current_protocol_version
from lingshu_gate.subprocess_environment import validate_docker_child_environment_names

LaunchType = Literal["managed_process", "external", "managed_container"]
TransportType = Literal["stdio", "streamable_http"]
PackageManager = Literal["npm"]
HealthCheckMethod = Literal["tools_list"]
UserCredentialInjectionType = Literal["http_header"]
PROTECTED_HTTP_HEADERS = {"content-type", "accept", "mcp-session-id", "mcp-protocol-version"}
CONTAINER_IMAGE_DIGEST_PATTERN = re.compile(
    r"^[a-z0-9][a-z0-9._:/-]*@sha256:[a-f0-9]{64}$"
)
CONTAINER_MEMORY_PATTERN = re.compile(r"^([1-9][0-9]*)([kmg])$")
CONTAINER_MEMORY_MIN_BYTES = 16 * 1024 * 1024
CONTAINER_MEMORY_MAX_BYTES = 4 * 1024 * 1024 * 1024
_CONTAINER_MEMORY_MULTIPLIERS = {
    "k": 1024,
    "m": 1024 * 1024,
    "g": 1024 * 1024 * 1024,
}
_PROTECTED_CONTAINER_TARGETS = {
    PurePosixPath("/dev"),
    PurePosixPath("/proc"),
    PurePosixPath("/run"),
    PurePosixPath("/sys"),
    PurePosixPath("/tmp"),
}


class PackageConfig(BaseModel):
    """Optional dynamic package metadata for user-provided MCP servers."""

    model_config = ConfigDict(
        extra="forbid",
        hide_input_in_errors=True,
        validate_assignment=True,
    )

    manager: PackageManager = "npm"
    name: str
    version: str | None = None
    bin: str | None = None
    cache: bool = True


class RestartHealthCheck(BaseModel):
    """Active health check configuration for a running stdio MCP server."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    enabled: bool = False
    method: HealthCheckMethod = "tools_list"
    interval_seconds: float = Field(default=30, ge=1)
    timeout_seconds: float = Field(default=10, ge=1)
    failure_threshold: int = Field(default=3, ge=1)


class RestartPolicy(BaseModel):
    """How Gate should recover a managed MCP process after unexpected exit."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    enabled: bool = False
    max_attempts: int = Field(default=3, ge=0)
    delay_seconds: float = Field(default=5, ge=0)
    backoff_multiplier: float = Field(default=2.0, ge=1.0)
    max_delay_seconds: float = Field(default=60, ge=0)
    restart_on_exit: bool = True
    reset_after_seconds: float = Field(default=300, ge=0)
    exit_code_allowlist: list[int] = Field(default_factory=list)
    exit_code_blocklist: list[int] = Field(default_factory=list)
    health_check: RestartHealthCheck = Field(default_factory=RestartHealthCheck)


class ContainerResources(BaseModel):
    """Hard-bounded resource limits for managed_container launches."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    memory: str = "512m"
    cpus: float = Field(default=1.0, ge=0.1, le=4.0)
    pids_limit: int = Field(default=128, ge=16, le=512)

    @field_validator("memory")
    @classmethod
    def validate_memory(cls, value: str) -> str:
        normalized = value.strip().lower()
        match = CONTAINER_MEMORY_PATTERN.fullmatch(normalized)
        if match is None:
            raise ValueError("container memory must use an integer k, m, or g suffix")
        size_bytes = int(match.group(1)) * _CONTAINER_MEMORY_MULTIPLIERS[match.group(2)]
        if not CONTAINER_MEMORY_MIN_BYTES <= size_bytes <= CONTAINER_MEMORY_MAX_BYTES:
            raise ValueError("container memory must be between 16m and 4g")
        return normalized


class ContainerMount(BaseModel):
    """One immutable, read-only bind mount for a managed container."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    read_only: Literal[True] = True

    @field_validator("source")
    @classmethod
    def validate_source(cls, value: str) -> str:
        if "," in value or any(ord(character) < 32 for character in value):
            raise ValueError("container mount source contains an unsupported character")
        if not Path(value).is_absolute():
            raise ValueError("container mount source must be an absolute host path")
        return value

    @field_validator("target")
    @classmethod
    def validate_target(cls, value: str) -> str:
        if "," in value or any(ord(character) < 32 for character in value):
            raise ValueError("container mount target contains an unsupported character")
        target = PurePosixPath(value)
        if (
            not value.startswith("/")
            or value.startswith("//")
            or target == PurePosixPath("/")
            or ".." in target.parts
        ):
            raise ValueError("container mount target must be a non-root absolute container path")
        if any(target == protected or protected in target.parents for protected in _PROTECTED_CONTAINER_TARGETS):
            raise ValueError("container mount target overlaps a protected container path")
        return str(target)


class LaunchConfig(BaseModel):
    """How Gate obtains and starts an MCP server."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    type: LaunchType
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    package: PackageConfig | None = None
    image: str | None = None
    mounts: list[ContainerMount] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)
    resources: ContainerResources | None = None

    @model_validator(mode="after")
    def validate_launch(self) -> "LaunchConfig":
        if self.type == "managed_process" and not self.command:
            raise ValueError("launch.command is required when launch.type=managed_process")
        if self.type == "managed_container":
            process_only = {
                "command": self.command,
                "cwd": self.cwd,
                "env": self.env,
                "package": self.package,
            }
            unexpected = sorted(name for name, value in process_only.items() if value)
            if unexpected:
                raise ValueError(
                    "managed_container does not accept managed-process fields: "
                    + ", ".join(unexpected)
                )
            if not self.image:
                raise ValueError("launch.image is required when launch.type=managed_container")
            require_digest_pinned_container_image(self.image)
            validate_docker_child_environment_names(self.environment)
            targets = [mount.target for mount in self.mounts]
            if len(targets) != len(set(targets)):
                raise ValueError("managed_container mount targets must be unique")
        else:
            container_only = {
                "image": self.image,
                "mounts": self.mounts,
                "environment": self.environment,
                "resources": self.resources,
            }
            unexpected = sorted(name for name, value in container_only.items() if value)
            if unexpected:
                raise ValueError(
                    f"launch.type={self.type} does not accept managed-container fields: "
                    + ", ".join(unexpected)
                )
        return self


def require_digest_pinned_container_image(image: str) -> str:
    """Reject mutable or option-shaped image references."""

    if CONTAINER_IMAGE_DIGEST_PATTERN.fullmatch(image) is None:
        raise ValueError(
            "managed_container image must be an OCI reference pinned by a lowercase sha256 digest"
        )
    return image


class TransportConfig(BaseModel):
    """How Gate communicates with an MCP server."""

    model_config = ConfigDict(
        extra="forbid",
        hide_input_in_errors=True,
        validate_assignment=True,
    )

    type: TransportType
    endpoint: str | None = None
    protocol_version: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)

    @field_validator("endpoint")
    @classmethod
    def validate_endpoint(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return validate_streamable_http_endpoint(value)

    @model_validator(mode="after")
    def validate_transport(self) -> "TransportConfig":
        if self.protocol_version is not None:
            require_current_protocol_version(self.protocol_version)
        if self.type == "streamable_http" and not self.endpoint:
            raise ValueError("transport.endpoint is required when transport.type=streamable_http")
        return self


class UserCredentialInjection(BaseModel):
    """声明用户下游凭据在独立 HTTP 会话中的注入位置。"""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    type: UserCredentialInjectionType = "http_header"
    name: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9-]+$")
    template: str = Field(default="{value}", min_length=7, max_length=512)

    @model_validator(mode="after")
    def validate_injection(self) -> "UserCredentialInjection":
        if self.name.lower() in PROTECTED_HTTP_HEADERS:
            raise ValueError(f"user credential cannot override protected HTTP header: {self.name}")
        if self.template.count("{value}") != 1:
            raise ValueError("user credential injection.template must contain exactly one {value}")
        if "\r" in self.template or "\n" in self.template:
            raise ValueError("user credential injection.template cannot contain line breaks")
        return self


class UserCredentialSlot(BaseModel):
    """Manifest 中不含秘密的用户凭据槽位。"""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)

    id: str = Field(..., pattern=r"^[a-zA-Z0-9_.-]+$")
    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="", max_length=500)
    required: bool = True
    injection: UserCredentialInjection


class McpServerManifest(BaseModel):
    """MCP server manifest loaded from config directory."""

    model_config = ConfigDict(
        extra="forbid",
        hide_input_in_errors=True,
        validate_assignment=True,
    )

    id: str = Field(..., pattern=r"^[a-zA-Z0-9_.-]+$")
    name: str | None = None
    enabled: bool = True
    launch: LaunchConfig
    transport: TransportConfig
    timeout_seconds: int = 30
    permissions: dict[str, Any] = Field(default_factory=dict)
    analysis: dict[str, Any] = Field(default_factory=dict)
    user_credentials: list[UserCredentialSlot] = Field(default_factory=list)
    roots: list[str] = Field(default_factory=list)
    auto_start: bool = False
    restart_policy: RestartPolicy = Field(default_factory=RestartPolicy)
    manifest_path: Path | None = None

    @model_validator(mode="after")
    def validate_manifest(self) -> "McpServerManifest":
        if self.transport.type == "stdio" and self.launch.type not in {"managed_process", "managed_container"}:
            raise ValueError("transport.type=stdio requires launch.type=managed_process or managed_container")
        if self.launch.type == "external" and self.auto_start:
            self.auto_start = False
        restart_supported = (
            self.launch.type == "managed_process"
            and self.transport.type in {"stdio", "streamable_http"}
        ) or (
            self.launch.type == "managed_container"
            and self.transport.type == "stdio"
        )
        if not restart_supported:
            self.restart_policy.enabled = False
            self.restart_policy.health_check.enabled = False
        if self.user_credentials:
            if self.launch.type != "external" or self.transport.type != "streamable_http":
                raise ValueError("user_credentials currently requires launch.type=external and transport.type=streamable_http")
            slot_ids = [slot.id for slot in self.user_credentials]
            if len(slot_ids) != len(set(slot_ids)):
                raise ValueError("user_credentials ids must be unique within one manifest")
            header_names = [slot.injection.name.lower() for slot in self.user_credentials]
            if len(header_names) != len(set(header_names)):
                raise ValueError("user_credentials cannot inject the same HTTP header more than once")
        return self

    @property
    def display_name(self) -> str:
        return self.name or self.id

    def safe_dict(self) -> dict[str, Any]:
        """Return a log-safe representation without environment values."""

        data = self.model_dump(mode="json")
        launch = data.get("launch", {})
        if isinstance(launch, dict):
            if "env" in launch and launch["env"]:
                launch["env"] = {key: "***" for key in launch["env"]}
            if "environment" in launch and launch["environment"]:
                launch["environment"] = {key: "***" for key in launch["environment"]}
            if isinstance(launch.get("mounts"), list):
                for mount in launch["mounts"]:
                    if isinstance(mount, dict) and mount.get("source"):
                        mount["source"] = "***"
        transport = data.get("transport", {})
        if isinstance(transport, dict):
            if transport.get("endpoint"):
                transport["endpoint"] = redact_endpoint(str(transport["endpoint"]))
            if transport.get("headers"):
                transport["headers"] = {key: "***" for key in transport["headers"]}
        return data

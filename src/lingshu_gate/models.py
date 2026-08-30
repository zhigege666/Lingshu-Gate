"""API models for Lingshu Gate."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator


class ResourceDeleteConflict(Exception):
    """删除资源前置条件不满足时返回给 API 层的结构化冲突。"""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        resource_type: str,
        resource_id: str,
        dependencies: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.dependencies = dependencies or {}

    def detail(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "resource_type": self.resource_type,
            "resource_id": self.resource_id,
            "dependencies": self.dependencies,
        }


class ToolDefinition(BaseModel):
    """A tool capability exposed by the Gate gateway."""

    id: str = Field(..., description="Stable tool identifier, for example server.tool")
    name: str
    description: str
    permission: str = Field(default="read", description="Permission level required by this tool")
    input_schema: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="builtin", description="Tool source, for example builtin or mcp")
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolInvokeRequest(BaseModel):
    """Request body for invoking a tool."""

    arguments: dict[str, Any] = Field(default_factory=dict)


class GateInvokeRequest(BaseModel):
    """Generic invoke request that includes the target tool id."""

    tool_id: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolInvokeResponse(BaseModel):
    """Normalized response returned by every tool invocation."""

    ok: bool
    tool_id: str
    output: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class DiagnosticsCheck(BaseModel):
    """One runtime diagnostic check item."""

    name: str
    ok: bool
    severity: str = Field(default="info", description="Diagnostic severity: info, warning, or error")
    detail: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class DiagnosticsResponse(BaseModel):
    """Runtime diagnostics response."""

    ok: bool
    checks: list[DiagnosticsCheck] = Field(default_factory=list)
    summary: dict[str, Any] = Field(default_factory=dict)


class AuthLoginRequest(BaseModel):
    """Login request."""

    username: str
    password: str


class AuthUserResponse(BaseModel):
    """Safe auth user/session response."""

    id: str
    username: str
    display_name: str = ""
    role: str
    roles: list[str] = Field(default_factory=list)
    permissions: list[str] = Field(default_factory=list)
    status: str = "active"
    must_change_password: bool = False
    auth_type: str = "session"
    token_id: str | None = None
    scopes: list[str] = Field(default_factory=list)


class AuthSessionResponse(BaseModel):
    """Login response."""

    user: AuthUserResponse
    expires_at: str | None = None
    message: str = "ok"


class McpServerStatusResponse(BaseModel):
    """Runtime status for one MCP server."""

    id: str
    name: str | None = None
    enabled: bool
    launch_type: str
    transport_type: str
    endpoint: str | None = None
    status: str
    pid: int | None = None
    tool_count: int = 0
    last_error: str | None = None
    manifest_path: str | None = None
    restart_policy: dict[str, Any] = Field(default_factory=dict)
    restart_count: int = 0
    restart_attempts: int = 0
    last_exit_code: int | None = None
    last_started_at: str | None = None
    last_exited_at: str | None = None
    last_restart_at: str | None = None
    next_restart_at: str | None = None
    consecutive_health_failures: int = 0
    last_health_check_at: str | None = None
    last_health_ok_at: str | None = None
    health_status: str = "unknown"
    desired_state: str = "stopped"
    desired_state_source: str = "manifest_default"
    desired_state_updated_at: str | None = None
    desired_state_revision: int = 0
    effective_should_run: bool = False
    restore_blocked_reason: str | None = None
    allowed_actions: list[str] = Field(default_factory=list)


class McpServerListResponse(BaseModel):
    """List of configured MCP servers."""

    servers: list[McpServerStatusResponse] = Field(default_factory=list)
    load_errors: list[str] = Field(default_factory=list)


class McpConfigResponse(BaseModel):
    """One MCP config file and its safe manifest."""

    id: str
    path: str
    format: str = "yaml"
    manifest: dict[str, Any] = Field(default_factory=dict)


class McpConfigListResponse(BaseModel):
    """List of MCP config files."""

    configs: list[McpConfigResponse] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class McpConfigSaveRequest(BaseModel):
    """Create or update an MCP config file."""

    model_config = ConfigDict(extra="forbid")

    manifest: dict[str, Any]
    apply: StrictBool = Field(default=False, description="Apply the saved manifest to runtime")
    start: StrictBool = Field(default=False, description="Start this server after applying it")
    user_credential_values: dict[str, str] = Field(
        default_factory=dict,
        description="One-time current-user secrets extracted before the manifest is persisted",
        exclude=True,
    )

    @model_validator(mode="after")
    def require_apply_before_start(self) -> "McpConfigSaveRequest":
        if self.start and not self.apply:
            raise ValueError("start=true requires apply=true")
        return self


class DeployBuildRequest(BaseModel):
    """Explicit deployment side effects requested by an operator."""

    model_config = ConfigDict(extra="forbid")

    server_id: str | None = None
    start: StrictBool = False
    overwrite: StrictBool = False


class RollbackDeploymentRequest(BaseModel):
    """Explicit runtime side effect requested for a rollback."""

    model_config = ConfigDict(extra="forbid")

    start: StrictBool = False


class McpConfigApplyResponse(BaseModel):
    """Response returned after saving/reloading/applying an MCP config."""

    config: McpConfigResponse | None = None
    server: McpServerStatusResponse | None = None
    servers: McpServerListResponse | None = None
    message: str = "ok"


class CredentialResponse(BaseModel):
    """Safe credential record."""

    id: str
    name: str
    description: str = ""
    value_masked: str = "***"
    created_at: str
    updated_at: str


class CredentialSaveRequest(BaseModel):
    """Create or update a credential."""

    name: str
    value: str | None = None
    description: str = ""

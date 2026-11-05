"""Explicit HTTP management contracts, separate from legacy tool snapshots."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from lingshu_gate.models import CredentialHttpTarget, McpConfigSaveRequest


class HttpMcpPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    mode: Literal["create", "update", "delete", "revoke_trust", "restore_trust"]
    manifest: dict[str, Any] | None = None
    server_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    expected_config_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    connect: StrictBool = False
    refresh_tools: StrictBool = False
    timeout_seconds: int = Field(default=30, ge=1, le=120)

    @model_validator(mode="after")
    def target_and_actions(self) -> HttpMcpPlanInput:
        if self.mode in {"create", "update"}:
            if self.manifest is None or self.server_id is not None:
                raise ValueError("Create/update require manifest; other modes use server_id")
        elif self.server_id is None or self.manifest is not None:
            raise ValueError("Delete and trust changes require server_id without manifest")
        if self.mode != "create" and self.expected_config_digest is None:
            raise ValueError("This operation requires the saved configuration digest")
        if self.mode == "create" and self.expected_config_digest is not None:
            raise ValueError("Create must not include an existing configuration digest")
        if self.refresh_tools and not self.connect:
            raise ValueError("Tool refresh requires connect=true")
        if self.mode in {"delete", "revoke_trust"} and (self.connect or self.refresh_tools):
            raise ValueError("Delete/revoke cannot connect or refresh tools")
        return self


class McpConfigSaveWithHttpTrustRequest(McpConfigSaveRequest):
    """Console save folds a reviewed private origin into the existing action."""

    http_trust_action: Literal["auto", "preserve", "restore"] = "auto"
    expected_http_trust_revision: int | None = Field(default=None, ge=0)


class ConfigurationCredentialDraft(BaseModel):
    """One explicit HTTP credential use, staged until the configuration save."""

    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    credential_id: str = Field(min_length=1, max_length=512, pattern=r"^[A-Za-z0-9_.-]+$")
    target: CredentialHttpTarget


class NewConfigurationCredential(ConfigurationCredentialDraft):
    kind: Literal["create"]
    name: str = Field(min_length=1, max_length=256)
    value: str = Field(min_length=1, max_length=65536, repr=False)


class ExistingConfigurationCredential(ConfigurationCredentialDraft):
    kind: Literal["authorize"]
    expected_revision: str = Field(min_length=1, max_length=128)
    expected_http_scopes_revision: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")


class McpConfigCredentialSaveRequest(McpConfigSaveWithHttpTrustRequest):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    existing_server_id: str | None = Field(default=None, min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.-]+$")
    credential_write: NewConfigurationCredential | ExistingConfigurationCredential = Field(discriminator="kind")
    idempotency_key: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def require_saved_revision(self) -> McpConfigCredentialSaveRequest:
        if bool(self.existing_server_id) != bool(self.expected_config_digest):
            raise ValueError("Updates require the current configuration digest; creates have no saved digest")
        return self


class HttpMcpTestInput(BaseModel):
    """An explicit ephemeral network test; no persistent grant or config writes."""
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    manifest: dict[str, Any]
    existing_server_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    expected_config_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    timeout_seconds: int = Field(default=15, ge=1, le=30)
    confirmed: StrictBool

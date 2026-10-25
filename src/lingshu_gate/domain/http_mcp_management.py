"""Explicit HTTP management contracts, separate from legacy tool snapshots."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, model_validator

from lingshu_gate.models import McpConfigSaveRequest


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


class HttpMcpTestInput(BaseModel):
    """An explicit ephemeral network test; no persistent grant or config writes."""
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    manifest: dict[str, Any]
    existing_server_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    expected_config_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    timeout_seconds: int = Field(default=15, ge=1, le=30)
    confirmed: StrictBool

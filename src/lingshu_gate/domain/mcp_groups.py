"""Explicit metadata-only MCP collections; members retain their server identities."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator


class McpGroupError(Exception):
    def __init__(self, code: str, message: str, status: int = 409) -> None:
        self.code, self.message, self.status = code, message, status
        super().__init__(message)


class McpGroupDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: StrictStr = Field(min_length=1, max_length=128)
    description: StrictStr = Field(default="", max_length=500)
    status: Literal["active", "archived"] = "active"
    members: list[StrictStr] = Field(max_length=1000)
    reconfirm_members: list[StrictStr] = Field(default_factory=list, max_length=1000)
    default_instance_id: StrictStr | None = None
    confirmed: Literal[True]

    @model_validator(mode="after")
    def default_is_member(self) -> McpGroupDraft:
        if self.default_instance_id is not None and self.default_instance_id not in self.members:
            raise ValueError("The suggested default must be an explicitly selected member")
        return self

    @field_validator("name", "description")
    @classmethod
    def clean_text(cls, value: str) -> str:
        if any(ord(char) < 32 for char in value):
            raise ValueError("Control characters are not allowed")
        return value.strip()

    @field_validator("name")
    @classmethod
    def nonempty_name(cls, value: str) -> str:
        if not value:
            raise ValueError("A group name is required")
        return value

    @field_validator("members", "reconfirm_members")
    @classmethod
    def distinct_members(cls, value: list[str]) -> list[str]:
        if len(value) != len(set(value)) or any(not item for item in value):
            raise ValueError("Members must be distinct existing instance IDs")
        return sorted(value)


class McpGroupCreate(McpGroupDraft):
    request_key: StrictStr = Field(pattern=r"^[a-f0-9]{32}$")


class McpGroupUpdate(McpGroupDraft):
    expected_revision: StrictInt = Field(ge=1)


class McpGroupDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: StrictInt = Field(ge=1)
    confirmed: Literal[True]

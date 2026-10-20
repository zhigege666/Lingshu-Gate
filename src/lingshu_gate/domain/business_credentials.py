"""Strict, secret-safe requests for business accounts and adapter bindings."""
from __future__ import annotations

from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class BusinessCredentialError(RuntimeError):
    """Public errors contain a stable code and never the submitted secret."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True, strict=True)


class BusinessCredentialSelectors(_Input):
    username: str | None = Field(default=None, min_length=1, max_length=512)
    password: str | None = Field(default=None, min_length=1, max_length=512)
    submit: str | None = Field(default=None, min_length=1, max_length=512)

    @field_validator("username", "password", "submit")
    @classmethod
    def clean_selector(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or any(ord(char) < 32 for char in value)):
            raise ValueError("selector must be a nonempty single line")
        return value


class _CredentialFields(_Input):
    name: str = Field(min_length=1, max_length=120)
    environment: str = Field(default="", max_length=80)
    business_role: str = Field(default="", max_length=80)
    login_url: str = Field(min_length=1, max_length=2048)
    enabled: bool = True
    allow_http: bool = False
    allowed_user_ids: list[str] = Field(default_factory=list, max_length=100)
    allowed_role_ids: list[str] = Field(default_factory=list, max_length=100)
    selectors: BusinessCredentialSelectors = Field(default_factory=BusinessCredentialSelectors)

    @field_validator("name", "environment", "business_role")
    @classmethod
    def clean_label(cls, value: str) -> str:
        if any(ord(char) < 32 for char in value):
            raise ValueError("metadata must contain no control characters")
        if value and not value.strip():
            raise ValueError("metadata must not be blank")
        return value.strip()

    @field_validator("allowed_user_ids", "allowed_role_ids")
    @classmethod
    def clean_subjects(cls, value: list[str]) -> list[str]:
        import re

        if any(not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", item) for item in value):
            raise ValueError("invalid authorization subject ID")
        return sorted(set(value))

    @model_validator(mode="after")
    def safe_login_url(self) -> Self:
        try:
            parsed = urlsplit(self.login_url)
            safe_fragment = (not parsed.fragment or (parsed.fragment.startswith("/")
                and "?" not in parsed.fragment and "=" not in parsed.fragment))
            valid = (not any(ord(char) <= 32 for char in self.login_url)
                and parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None
                and not parsed.query and safe_fragment
                and (parsed.port is None or 1 <= parsed.port <= 65535))
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("login URL must be HTTP(S), without user info, query or a token fragment")
        if parsed.scheme == "http" and not self.allow_http:
            raise ValueError("HTTP login requires explicit allow_http acknowledgement")
        return self


def _secret(value: SecretStr | None, *, username: bool = False) -> SecretStr | None:
    if value is None:
        return value
    raw = value.get_secret_value()
    if not raw.strip() or raw in {"***", "**********"} or "\x00" in raw or "\r" in raw or "\n" in raw:
        raise ValueError("a real, nonempty single-line secret is required")
    if len(raw) > (1024 if username else 16384):
        raise ValueError("secret exceeds the supported length")
    return value


class BusinessCredentialCreate(_CredentialFields):
    scope: Literal["personal", "shared"] = "personal"
    username: SecretStr
    password: SecretStr

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: SecretStr) -> SecretStr:
        _secret(value, username=True)
        return value

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: SecretStr) -> SecretStr:
        _secret(value)
        return value

    @model_validator(mode="after")
    def personal_scope(self) -> Self:
        if self.scope == "personal" and (self.allowed_user_ids or self.allowed_role_ids):
            raise ValueError("personal credentials cannot grant access to other subjects")
        return self


class BusinessCredentialUpdate(_CredentialFields):
    expected_version: int = Field(ge=1)
    username: SecretStr | None = None
    password: SecretStr | None = None

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: SecretStr | None) -> SecretStr | None:
        return _secret(value, username=True)

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: SecretStr | None) -> SecretStr | None:
        return _secret(value)


class BusinessCredentialBindingCreate(_Input):
    server_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
    adapter: Literal["agent_browser"] = "agent_browser"
    tool_prefix: Literal["agent_browser_", ""] = "agent_browser_"
    enabled: bool = True
    confirm_managed_mode: bool = False


class BusinessCredentialBindingUpdate(_Input):
    expected_revision: int = Field(ge=1)
    expected_version: int = Field(ge=1)
    enabled: bool


class BusinessCredentialVersion(_Input):
    expected_version: int = Field(ge=1)


class BusinessCredentialBindingRevision(_Input):
    expected_revision: int = Field(ge=1)


SYNC_STATUSES = frozenset({"pending", "synced", "failed", "unknown", "deleted"})
SYNC_ERROR_CODES = frozenset({"downstream_failed", "downstream_unknown", "target_unavailable",
    "contract_changed", "permission_denied", "credential_unavailable"})

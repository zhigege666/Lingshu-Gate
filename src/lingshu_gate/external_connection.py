"""Default-disabled external MCP trust configuration and delegation policy."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit


def _https_resource(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    return bool(parsed.scheme == "https" and parsed.hostname and (port is None or 1 <= port <= 65535)
                and len(value) <= 2048 and not any(char.isspace() for char in value)
                and not parsed.username
                and not parsed.password and not parsed.query and not parsed.fragment)


@dataclass(frozen=True)
class ExternalConnectionConfig:
    enabled: bool = False
    mode: Literal["disabled", "direct", "secure_mcp_tunnel"] = "disabled"
    endpoint: str | None = None
    canonical_resource_url: str | None = None
    tunnel_reference: str | None = None
    runtime_secret_reference: str | None = None
    trusted_issuers: tuple[str, ...] = ()
    issuer_jwks: tuple[tuple[str, str], ...] = ()
    client_allowlist: tuple[str, ...] = ()
    # Exact (externally advertised resource, internal canonical resource) pairs.
    resource_mappings: tuple[tuple[str, str], ...] = ()

    def validation_errors(self) -> tuple[str, ...]:
        errors: list[str] = []
        if self.mode == "disabled":
            errors.append("transport_not_configured")
        elif self.mode == "direct" and (not self.endpoint or not _https_resource(self.endpoint)):
            errors.append("https_endpoint_required")
        elif self.mode == "secure_mcp_tunnel" and not self.tunnel_reference:
            errors.append("tunnel_reference_required")
        if self.mode == "secure_mcp_tunnel" and not self.runtime_secret_reference:
            errors.append("runtime_secret_reference_required")
        if not self.trusted_issuers or not all(_https_resource(i) for i in self.trusted_issuers):
            errors.append("trusted_issuer_required")
        if not self.resource_mappings or not all(
            _https_resource(external) and _https_resource(canonical)
            for external, canonical in self.resource_mappings
        ):
            errors.append("trusted_resource_mapping_required")
        if len(dict(self.resource_mappings)) != len(self.resource_mappings):
            errors.append("ambiguous_resource_mapping")
        canonical = self.canonical_resource_url or self.endpoint
        if (not canonical or not _https_resource(canonical)
                or any(target != canonical for _, target in self.resource_mappings)):
            errors.append("canonical_resource_required")
        mappings = dict(self.issuer_jwks)
        if (not mappings or len(mappings) != len(self.issuer_jwks)
                or set(mappings) != set(self.trusted_issuers)
                or not all(_https_resource(uri) for uri in mappings.values())):
            errors.append("trusted_jwks_mapping_required")
        if (not self.client_allowlist or len(self.client_allowlist) > 100
                or any(not isinstance(client, str) or not client or len(client) > 256 for client in self.client_allowlist)):
            errors.append("trusted_client_required")
        if len(self.trusted_issuers) > 20 or len(self.resource_mappings) > 20:
            errors.append("too_many_trust_entries")
        return tuple(errors)

    def canonical_resource(self, audience: str) -> str | None:
        if "ambiguous_resource_mapping" in self.validation_errors():
            return None
        return next((canonical for external, canonical in self.resource_mappings
                     if audience == external and _https_resource(external)
                     and _https_resource(canonical)), None)

    def status(self) -> dict[str, object]:
        errors = self.validation_errors()
        return {"enabled": self.enabled, "connected": False, "mode": self.mode,
                "state": "configured" if self.enabled and not errors else "disabled",
                "validation_errors": list(errors), "oauth_verifier_ready": not errors,
                "grant_store_ready": True, "provider_verified": False,
                "rate_concurrency_enforcement_ready": True}


@dataclass(frozen=True)
class OAuthSubjectLink:
    issuer: str
    subject: str
    user_id: str
    enabled: bool = False

    def matches(self, *, verified_issuer: str, verified_subject: str,
                trusted_issuers: tuple[str, ...]) -> bool:
        return bool(self.enabled and self.subject and self.user_id
                    and self.issuer in trusted_issuers
                    and self.issuer == verified_issuer and self.subject == verified_subject)


@dataclass(frozen=True)
class UserExternalGrant:
    user_id: str
    client_id: str
    grant_id: str
    enabled: bool = False
    server_allowlist: tuple[str, ...] = ()
    tool_allowlist: tuple[str, ...] = ()
    access: tuple[Literal["read", "write"], ...] = ()
    expires_at: datetime | None = None
    rate_per_minute: int = 1
    concurrency: int = 1
    policy_version: int = 1
    revoked_at: datetime | None = None

    def allows(self, *, user_id: str, client_id: str, server_id: str,
               qualified_tool_name: str, required_access: Literal["read", "write"],
               oauth_scopes: tuple[str, ...], now: datetime,
               policy_version: int) -> bool:
        """Policy intersection only; caller must additionally enforce Gate policy/limits.

        No wildcard or admin bypass exists. Tool IDs must be the qualified IDs
        returned by Gate, not an unqualified downstream tool name.
        """
        if (not self.enabled or self.revoked_at is not None
                or not self.grant_id or not self.user_id or not self.client_id
                or self.user_id != user_id or self.client_id != client_id
                or self.expires_at is None or self.expires_at.tzinfo is None
                or now.tzinfo is None or self.expires_at <= now
                or self.policy_version != policy_version
                or self.rate_per_minute <= 0 or self.concurrency <= 0):
            return False
        scope = "tools.read" if required_access == "read" else "tools.invoke"
        return (server_id in self.server_allowlist
                and qualified_tool_name in self.tool_allowlist
                and required_access in self.access and scope in oauth_scopes)

"""OAuth protected-resource discovery boundary for MCP HTTP.

This module intentionally does not validate tokens.  Publishing discovery
metadata before an OAuth issuer/audience validator is wired would falsely claim
OAuth compatibility.  Applications must explicitly provide this boundary only
after their bearer-token verifier accepts tokens for ``metadata.resource``.
Inbound bearer tokens are never exposed as downstream MCP credentials.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI, HTTPException, Request


class OAuthAccessTokenVerifier(Protocol):
    """Future OAuth verifier port; implementations must validate issuer and audience."""

    def verify(self, token: str, *, resource: str) -> object: ...


@dataclass(frozen=True)
class OAuthProtectedResourceMetadata:
    resource: str
    authorization_servers: tuple[str, ...]
    scopes_supported: tuple[str, ...] = ("tools.read", "tools.invoke")

    def __post_init__(self) -> None:
        _validate_oauth_url(self.resource, "OAuth protected resource")
        if not self.authorization_servers:
            raise ValueError("at least one OAuth authorization server is required")
        for issuer in self.authorization_servers:
            _validate_oauth_url(issuer, "OAuth authorization server")
        for scope in self.scopes_supported:
            if not scope or any(
                ord(character) < 0x21
                or ord(character) > 0x7E
                or character in {'"', "\\"}
                for character in scope
            ):
                raise ValueError(
                    "OAuth scopes must use RFC 6749 scope-token characters"
                )

    def document(self) -> dict[str, object]:
        return {
            "resource": self.resource,
            "authorization_servers": list(self.authorization_servers),
            "scopes_supported": list(self.scopes_supported),
            "bearer_methods_supported": ["header"],
        }


@dataclass(frozen=True)
class McpOAuthDiscoveryBoundary:
    metadata: OAuthProtectedResourceMetadata
    metadata_path: str = "/.well-known/oauth-protected-resource/mcp"

    def __post_init__(self) -> None:
        if (
            not self.metadata_path.startswith("/")
            or "?" in self.metadata_path
            or "#" in self.metadata_path
        ):
            raise ValueError("OAuth metadata path must be an absolute path")

    def challenge(self, request: Request) -> str:
        del request  # Metadata origin is trusted configuration, never the Host header.
        resource = urlsplit(self.metadata.resource)
        metadata_url = urlunsplit(
            (resource.scheme, resource.netloc, self.metadata_path, "", "")
        )
        return (
            'Bearer realm="lingshu-gate", '
            f'resource_metadata="{metadata_url}", '
            f'scope="{" ".join(self.metadata.scopes_supported)}"'
        )


def register_oauth_protected_resource_routes(
    app: FastAPI,
    boundary: McpOAuthDiscoveryBoundary,
) -> None:
    """Register RFC 9728 metadata at root and MCP path-specific locations."""

    async def metadata_document() -> dict[str, object]:
        return boundary.metadata.document()

    app.add_api_route(
        "/.well-known/oauth-protected-resource",
        metadata_document,
        methods=["GET"],
        tags=["mcp-authorization"],
        include_in_schema=False,
    )
    app.add_api_route(
        boundary.metadata_path,
        metadata_document,
        methods=["GET"],
        tags=["mcp-authorization"],
        include_in_schema=False,
    )


def with_mcp_auth_challenge(
    require_principal: Callable[[Request], object],
    boundary: McpOAuthDiscoveryBoundary | None,
) -> Callable[[Request], object]:
    """Wrap an existing auth dependency without changing 403 semantics."""

    def dependency(request: Request):
        try:
            return require_principal(request)
        except HTTPException as exc:
            if exc.status_code != 401:
                raise
            headers = dict(exc.headers or {})
            headers.setdefault(
                "WWW-Authenticate",
                boundary.challenge(request) if boundary is not None else "Bearer",
            )
            raise HTTPException(
                status_code=exc.status_code,
                detail=exc.detail,
                headers=headers,
            ) from exc

    return dependency


def _validate_oauth_url(value: str, field_name: str) -> None:
    if any(ord(character) < 0x21 or character in {'"', "\\"} for character in value):
        raise ValueError(f"{field_name} contains unsafe characters")
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise ValueError(f"{field_name} is not a valid URL") from exc
    if (
        not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise ValueError(f"{field_name} must have a host and no userinfo")
    loopback = parsed.hostname in {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        raise ValueError(f"{field_name} must use HTTPS outside loopback")
    if parsed.fragment:
        raise ValueError(f"{field_name} cannot include a fragment")
    if parsed.query:
        raise ValueError(f"{field_name} cannot include a query")

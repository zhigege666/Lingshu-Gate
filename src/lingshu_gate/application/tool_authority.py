"""Refresh current identity ceilings for logical directory and routing operations."""
from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone

from fastapi import HTTPException

from lingshu_gate.auth import AuthPrincipal, AuthStore
from lingshu_gate.domain.mcp_groups import McpGroupError
from lingshu_gate.oauth_server import OAuthError


def _intersection(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
    if "*" in left:
        return right
    if "*" in right:
        return left
    return tuple(sorted(set(left) & set(right)))


def current_tool_principal(auth: AuthStore, actor: AuthPrincipal) -> AuthPrincipal:
    """No cached descriptor, session or old principal can supply current authority."""
    try:
        if not auth.enabled:
            raise ValueError("authentication_required")
        user = auth.database.query_one("SELECT * FROM users WHERE id=?", (actor.id,))
        if user is None or user["status"] != "active" or user["must_change_password"]:
            raise ValueError("inactive_identity")
        current = auth._build_principal(user, auth_type=actor.auth_type)
        scopes = actor.scopes
        if actor.auth_type == "session":
            row = auth.database.query_one("SELECT user_id,purpose,expires_at FROM auth_sessions WHERE id=?", (actor.session_id,))
            if (row is None or row["user_id"] != actor.id or row["purpose"] != "console"
                    or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc)):
                raise ValueError("session_unavailable")
        elif actor.auth_type == "token":
            row = auth.database.query_one("SELECT * FROM api_tokens WHERE id=?", (actor.token_id,))
            if (row is None or row["user_id"] != actor.id or row["revoked_at"] is not None
                    or row["expires_at"] and datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc)):
                raise ValueError("token_unavailable")
            scopes = _intersection(scopes, tuple(json.loads(row["scopes_json"])))
        elif actor.auth_type == "oauth":
            if actor.oauth_builtin:
                if auth.builtin_oauth is None:
                    raise ValueError("oauth_unavailable")
                refreshed = auth.builtin_oauth.refresh_verified_principal(actor)
            else:
                store = auth.external_connections
                config = store.configuration() if store is not None else None
                if (store is None or config is None or not config.enabled or config.validation_errors()
                        or actor.oauth_issuer not in config.trusted_issuers
                        or actor.oauth_client_id not in config.client_allowlist
                        or dict(config.issuer_jwks).get(actor.oauth_issuer or "") != actor.oauth_jwks_uri
                        or not actor.oauth_jwks_uri or not actor.oauth_resource or not actor.oauth_audiences
                        or any(config.canonical_resource(aud) != actor.oauth_resource for aud in actor.oauth_audiences)
                        or not actor.external_expires_at
                        or datetime.fromisoformat(actor.external_expires_at) <= datetime.now(timezone.utc)
                        or not actor.oauth_issuer or not actor.oauth_subject
                        or store.resolve_subject(actor.oauth_issuer, actor.oauth_subject) != actor.id):
                    raise ValueError("oauth_unavailable")
                grant = store.get_active_grant(actor.id, actor.oauth_client_id or "", datetime.now(timezone.utc))
                if grant["id"] != actor.external_grant_id:
                    raise ValueError("oauth_grant_changed")
                refreshed = replace(actor, external_server_ids=tuple(grant["server_allowlist"]),
                    external_tool_ids=tuple(grant["tool_allowlist"]), external_access=tuple(grant["access"]),
                    external_rate_per_minute=min(actor.external_rate_per_minute, grant["rate_per_minute"]),
                    external_concurrency=min(actor.external_concurrency, grant["concurrency"]))
            actor = replace(actor,
                external_server_ids=_intersection(actor.external_server_ids, refreshed.external_server_ids),
                external_tool_ids=_intersection(actor.external_tool_ids, refreshed.external_tool_ids),
                external_access=_intersection(actor.external_access, refreshed.external_access),
                external_rate_per_minute=refreshed.external_rate_per_minute,
                external_concurrency=refreshed.external_concurrency,
                delegated_scopes=_intersection(actor.delegated_scopes or (), refreshed.delegated_scopes or ()))
            scopes = _intersection(scopes, refreshed.scopes)
        else:
            raise ValueError("unsupported_identity")
        roles = _intersection(actor.roles or (actor.role,), current.roles)
        if not roles:
            raise ValueError("roles_unavailable")
        return replace(actor, role="admin" if "admin" in roles else roles[0], roles=roles,
            permissions=_intersection(actor.permissions, current.permissions), scopes=scopes)
    except (HTTPException, OAuthError, ValueError, TypeError, KeyError, PermissionError):
        raise McpGroupError("group_connection_invalid", "The current connection is unavailable or was revoked.", 403) from None

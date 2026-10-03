"""Default-disabled external trust and personal delegation management."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator, model_validator

from lingshu_gate.access_control import AccessControlStore, AccessDeniedError
from lingshu_gate.auth import AuthPrincipal, AuthStore
from lingshu_gate.external_connection import ExternalConnectionConfig, _https_resource
from lingshu_gate.external_connection_store import DraftRevisionConflict, ExternalConnectionStore
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.registry import ToolRegistry


class ConnectionDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool = False
    mode: Literal["disabled", "direct", "secure_mcp_tunnel"] = "disabled"
    endpoint: str | None = Field(default=None, max_length=2048)
    canonical_resource_url: str | None = Field(default=None, max_length=2048)
    tunnel_reference: str | None = Field(default=None, pattern=r"^tunnel:[A-Za-z0-9_.-]{1,128}$")
    runtime_secret_reference: str | None = Field(default=None, pattern=r"^credential:[A-Za-z0-9_.-]{1,128}$")
    trusted_issuers: list[str] = Field(default_factory=list, max_length=20)
    issuer_jwks: list[tuple[str, str]] = Field(default_factory=list, max_length=20)
    client_allowlist: list[str] = Field(default_factory=list, max_length=100)
    resource_mappings: list[tuple[str, str]] = Field(default_factory=list, max_length=20)
    expected_revision: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_resources(self) -> ConnectionDraftRequest:
        values = ([self.endpoint] if self.endpoint else []) + self.trusted_issuers
        values += [self.canonical_resource_url] if self.canonical_resource_url else []
        values += [resource for pair in self.issuer_jwks for resource in pair]
        values += [resource for pair in self.resource_mappings for resource in pair]
        if any(not _https_resource(value) for value in values):
            raise ValueError("resources must be HTTPS URLs without credentials, query or fragment")
        if len(dict(self.resource_mappings)) != len(self.resource_mappings):
            raise ValueError("resource mappings must be unambiguous")
        config = ExternalConnectionConfig(**self.model_dump(exclude={"expected_revision"}))
        if self.enabled and config.validation_errors():
            raise ValueError("incomplete external trust configuration: " + ", ".join(config.validation_errors()))
        return self


class GrantDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool = False
    client_id: str = Field(min_length=1, max_length=256, pattern=r"^[A-Za-z0-9_.:/-]+$")
    server_allowlist: list[str] = Field(min_length=1, max_length=100)
    tool_allowlist: list[str] = Field(min_length=1, max_length=1000)
    access: list[Literal["read", "write"]] = Field(min_length=1, max_length=2)
    expires_at: datetime
    rate_per_minute: int = Field(default=30, ge=1, le=10000)
    concurrency: int = Field(default=1, ge=1, le=100)

    @field_validator("server_allowlist", "tool_allowlist")
    @classmethod
    def exact_ids(cls, values: list[str]) -> list[str]:
        if any(not value or len(value) > 256 or "*" in value or value != value.strip() for value in values):
            raise ValueError("use exact non-empty resource IDs")
        return sorted(set(values))

    @field_validator("expires_at")
    @classmethod
    def future_expiry(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value <= datetime.now(timezone.utc):
            raise ValueError("expiration must be timezone-aware and in the future")
        return value


class GrantDraftUpdateRequest(GrantDraftRequest):
    expected_revision: int = Field(ge=1)


class GrantDisableRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: Literal[False]
    expected_revision: int = Field(ge=1)


class SubjectLinkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issuer: str = Field(max_length=2048)
    subject: str = Field(min_length=1, max_length=512)
    user_id: str = Field(min_length=1, max_length=256)
    enabled: StrictBool = False


class SubjectLinkUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool
    expected_revision: int = Field(ge=1)


def register_external_connection_routes(app: FastAPI, *, auth_store: AuthStore,
                                        access_store: AccessControlStore, registry: ToolRegistry,
                                        store: ExternalConnectionStore,
                                        observability_store: ObservabilityStore) -> None:
    def require_self(request: Request) -> AuthPrincipal:
        principal = auth_store.authenticate_request(request)
        try:
            access_store.require_control_permission(principal, "credentials.manage.self")
        except AccessDeniedError as exc:
            raise HTTPException(403, detail=exc.reason) from exc
        return principal

    def require_admin(request: Request) -> AuthPrincipal:
        principal = auth_store.authenticate_request(request)
        try:
            access_store.require_control_permission(principal, "external_connections.manage")
        except AccessDeniedError as exc:
            raise HTTPException(403, detail=exc.reason) from exc
        return principal

    def current_tools(principal: AuthPrincipal) -> dict[str, Any]:
        return {definition.id: definition for definition in
                access_store.visible_tools(principal, registry.list_definitions())
                if definition.source == "mcp"
                and definition.metadata.get("gate_access", {}).get("classification_status") == "published"}

    def allowed(payload: dict[str, Any], principal: AuthPrincipal,
                definitions: dict[str, Any] | None = None) -> bool:
        definitions = current_tools(principal) if definitions is None else definitions
        servers: set[str] = set()
        for tool_id in payload["tool_allowlist"]:
            definition = definitions.get(tool_id)
            if definition is None:
                return False
            server_id = definition.metadata.get("server_id")
            if server_id not in payload["server_allowlist"]:
                return False
            servers.add(str(server_id))
            if definition.metadata["gate_access"]["required_access"] not in payload["access"]:
                return False
            # Write intent still needs the global write capability; each selected
            # write tool has already passed the current resource/tool policy above.
            if "write" in payload["access"] and (
                not access_store.has_control_permission(principal, "tools.invoke")
            ):
                return False
        return servers == set(payload["server_allowlist"])

    def describe(grant: dict[str, Any], principal: AuthPrincipal,
                 definitions: dict[str, Any] | None = None) -> dict[str, Any]:
        expired = datetime.fromisoformat(grant["expires_at"]) <= datetime.now(timezone.utc)
        valid = allowed(grant, principal, definitions)
        errors = activation_errors(grant, principal)
        if not valid:
            errors.append("scope_not_currently_authorized")
        state = ("revoked" if grant["revoked_at"] else "expired" if expired else
                 "enabled" if grant["enabled"] and not errors else "disabled")
        return {**grant, "connected": False, "state": state, "activation_errors": errors,
                "scope_currently_authorized": valid, "oauth_authorized": False,
                "limits_enforced": state == "enabled"}

    def activation_errors(payload: dict[str, Any], principal: AuthPrincipal) -> list[str]:
        config = store.configuration()
        errors = list(config.validation_errors())
        if not config.enabled:
            errors.append("external_connection_disabled")
        if payload["client_id"] not in config.client_allowlist:
            errors.append("client_not_allowed")
        if not store.has_active_subject(principal.id):
            errors.append("subject_link_required")
        return errors

    def checked(payload: dict[str, Any], principal: AuthPrincipal) -> dict[str, Any]:
        if not allowed(payload, principal):
            raise HTTPException(403, detail="requested external scope is not currently authorized")
        if payload.get("enabled") and activation_errors(payload, principal):
            raise HTTPException(409, detail={"activation_errors": activation_errors(payload, principal)})
        return payload

    def emit(action: str, principal: AuthPrincipal, object_id: str) -> None:
        observability_store.emit_event(f"gate.external.{action}", source="external_connections",
                                       subject_type="external_draft", subject_id=object_id,
                                       payload={"actor_id": principal.id})

    def get_owned(principal: AuthPrincipal, grant_id: str) -> dict[str, Any]:
        try:
            return store.get_grant(principal.id, grant_id)
        except KeyError as exc:
            raise HTTPException(404, detail="grant not found") from exc

    @app.get("/v1/auth/external-connection/config", tags=["external-connections"])
    def get_config(principal: AuthPrincipal = Depends(require_admin)) -> dict[str, Any]:
        config = store.config()
        fields = {key: value for key, value in config.items() if key not in {"revision", "updated_at"}}
        return {**config, **ExternalConnectionConfig(**fields).status()}

    @app.put("/v1/auth/external-connection/config", tags=["external-connections"])
    def update_config(body: ConnectionDraftRequest,
                      principal: AuthPrincipal = Depends(require_admin)) -> dict[str, Any]:
        if body.enabled and not auth_store.enabled:
            raise HTTPException(409, detail="external connections require Gate authentication")
        builtin = auth_store.builtin_oauth.store.config() if auth_store.builtin_oauth else None
        if body.enabled and builtin and builtin["enabled"] and (body.canonical_resource_url or body.endpoint) != builtin["resource"]:
            raise HTTPException(409, detail="resource_configuration_conflict")
        if body.enabled and builtin and builtin["enabled"] and builtin["issuer"] in body.trusted_issuers:
            raise HTTPException(409, detail="issuer_configuration_conflict")
        try:
            store.save_config(body.model_dump(exclude={"expected_revision"}), body.expected_revision)
        except DraftRevisionConflict as exc:
            raise HTTPException(409, detail=str(exc)) from exc
        emit("config_saved", principal, "connection")
        return get_config(principal)

    @app.get("/v1/auth/external-grants", tags=["external-connections"])
    def list_grants(principal: AuthPrincipal = Depends(require_self)) -> dict[str, Any]:
        definitions = current_tools(principal)
        return {"grants": [describe(grant, principal, definitions) for grant in store.list_grants(principal.id)],
                "enabled": store.configuration().enabled, "oauth_authorized": False,
                "connection_ready": store.configuration().enabled and not store.configuration().validation_errors(),
                "activation_errors": list(store.configuration().validation_errors()) +
                    ([] if store.configuration().enabled else ["external_connection_disabled"]) +
                    ([] if store.has_active_subject(principal.id) else ["subject_link_required"]),
                "allowed_client_ids": list(store.configuration().client_allowlist)}

    @app.post("/v1/auth/external-grants", tags=["external-connections"], status_code=201)
    def create_grant(body: GrantDraftRequest,
                     principal: AuthPrincipal = Depends(require_self)) -> dict[str, Any]:
        payload = checked(body.model_dump(mode="json"), principal)
        payload["policy_version"] = 1
        try:
            grant = store.create_grant(principal.id, payload)
        except DraftRevisionConflict as exc:
            raise HTTPException(409, detail=str(exc)) from exc
        emit("grant_created", principal, grant["id"])
        return describe(grant, principal)

    @app.get("/v1/auth/external-grants/{grant_id}", tags=["external-connections"])
    def get_grant(grant_id: str, principal: AuthPrincipal = Depends(require_self)) -> dict[str, Any]:
        return describe(get_owned(principal, grant_id), principal)

    @app.patch("/v1/auth/external-grants/{grant_id}", tags=["external-connections"])
    def update_grant(grant_id: str, body: GrantDisableRequest | GrantDraftUpdateRequest,
                     principal: AuthPrincipal = Depends(require_self)) -> dict[str, Any]:
        old = get_owned(principal, grant_id)
        if isinstance(body, GrantDisableRequest):
            payload = {key: value for key, value in old.items() if key not in
                       {"id", "user_id", "revision", "revoked_at", "created_at", "updated_at"}}
            payload["enabled"] = False
        else:
            payload = checked(body.model_dump(mode="json", exclude={"expected_revision"}), principal)
        payload["policy_version"] = old["policy_version"] + 1
        try:
            grant = store.update_grant(principal.id, grant_id, payload, body.expected_revision)
        except DraftRevisionConflict as exc:
            raise HTTPException(409, detail=str(exc)) from exc
        except KeyError as exc:
            raise HTTPException(404, detail="grant not found") from exc
        emit("grant_updated", principal, grant_id)
        return describe(grant, principal)

    @app.delete("/v1/auth/external-grants/{grant_id}", tags=["external-connections"])
    def revoke_grant(grant_id: str, principal: AuthPrincipal = Depends(require_self)) -> dict[str, Any]:
        get_owned(principal, grant_id)
        try:
            grant = store.revoke_grant(principal.id, grant_id)
        except KeyError as exc:
            raise HTTPException(404, detail="grant not found") from exc
        emit("grant_revoked", principal, grant_id)
        return describe(grant, principal)


    @app.get("/v1/auth/external-subject-links", tags=["external-connections"])
    def list_subject_links(q: str = Query("", max_length=200), offset: int = Query(0, ge=0),
                           limit: int = Query(50, ge=1, le=100),
                           principal: AuthPrincipal = Depends(require_admin)) -> dict[str, Any]:
        return {"links": store.list_subject_links(q=q, offset=offset, limit=limit),
                "total": store.count_subject_links(q), "offset": offset, "limit": limit}

    @app.get("/v1/auth/external-subject-links/user-options", tags=["external-connections"])
    def subject_user_options(q: str = Query("", max_length=200), offset: int = Query(0, ge=0),
                             limit: int = Query(40, ge=1, le=100),
                             principal: AuthPrincipal = Depends(require_admin)) -> dict[str, Any]:
        # This capability already permits binding any active Gate user. Return
        # only binding labels, never the full user-management/role directory.
        return store.subject_user_options(q=q, offset=offset, limit=limit)

    @app.post("/v1/auth/external-subject-links", tags=["external-connections"], status_code=201)
    def create_subject_link(body: SubjectLinkRequest,
                            principal: AuthPrincipal = Depends(require_admin)) -> dict[str, Any]:
        if body.issuer not in store.configuration().trusted_issuers:
            raise HTTPException(400, detail="subject issuer is not configured")
        user = store.database.query_one("SELECT status FROM users WHERE id=?", (body.user_id,))
        if not user or user["status"] != "active":
            raise HTTPException(400, detail="subject target user is not active")
        try:
            link = store.create_subject_link(body.model_dump())
        except DraftRevisionConflict as exc:
            raise HTTPException(409, detail=str(exc)) from exc
        emit("subject_link_created", principal, link["id"])
        return link

    @app.patch("/v1/auth/external-subject-links/{link_id}", tags=["external-connections"])
    def update_subject_link(link_id: str, body: SubjectLinkUpdateRequest,
                            principal: AuthPrincipal = Depends(require_admin)) -> dict[str, Any]:
        if body.enabled:
            existing = next((item for item in store.list_subject_links() if item["id"] == link_id), None)
            if existing is None:
                raise HTTPException(404, detail="subject link not found")
            user = store.database.query_one("SELECT status FROM users WHERE id=?", (existing["user_id"],))
            if existing["issuer"] not in store.configuration().trusted_issuers or not user or user["status"] != "active":
                raise HTTPException(400, detail="subject trust or target user is not active")
        try:
            link = store.update_subject_link(link_id, enabled=body.enabled, expected_revision=body.expected_revision)
        except KeyError as exc:
            raise HTTPException(404, detail="subject link not found") from exc
        except DraftRevisionConflict as exc:
            raise HTTPException(409, detail=str(exc)) from exc
        emit("subject_link_updated", principal, link_id)
        return link

    @app.delete("/v1/auth/external-subject-links/{link_id}", tags=["external-connections"])
    def disable_subject_link(link_id: str, principal: AuthPrincipal = Depends(require_admin)) -> dict[str, Any]:
        link = next((item for item in store.list_subject_links() if item["id"] == link_id), None)
        if link is None:
            raise HTTPException(404, detail="subject link not found")
        return update_subject_link(link_id, SubjectLinkUpdateRequest(enabled=False, expected_revision=link["revision"]), principal)

"""FastAPI routes for users, roles, grants, classifications, and audits."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, Field

from lingshu_gate.access_control import (
    AccessControlStore,
    AccessDeniedError,
    ClassificationConfirmationConflictError,
)
from lingshu_gate.auth import AuthPrincipal, AuthStore
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.registry import ToolRegistry
from lingshu_gate.user_credential_store import UserCredentialStore


class RegisterRequest(BaseModel):
    username: str
    display_name: str = ""
    password: str


class UserCreateRequest(BaseModel):
    username: str
    display_name: str = ""
    password: str
    status: str = "active"
    roles: list[str] = Field(default_factory=lambda: ["viewer"])
    must_change_password: bool = True


class UserUpdateRequest(BaseModel):
    display_name: str | None = None
    status: str | None = None
    roles: list[str] | None = None


class RoleSaveRequest(BaseModel):
    code: str
    name: str
    description: str = ""
    permissions: list[str] = Field(default_factory=list)
    enabled: bool = True


class PermissionTypeSaveRequest(BaseModel):
    code: str
    name: str
    base_level: str
    description: str = ""
    enabled: bool = True


class GrantSaveRequest(BaseModel):
    subject_type: str
    subject_id: str
    server_id: str
    tool_id: str | None = None
    permission_type_code: str
    expires_at: str | None = None


class ClassificationAnalyzeRequest(BaseModel):
    server_id: str | None = None


class ClassificationUpdateRequest(BaseModel):
    access: str
    destructive: bool = False
    idempotent: bool = False
    note: str = ""


class ClassificationConfirmItem(BaseModel):
    server_id: str = Field(min_length=1)
    tool_id: str = Field(min_length=1)
    expected_fingerprint: str = Field(min_length=1)


class ClassificationConfirmRequest(BaseModel):
    items: list[ClassificationConfirmItem] = Field(min_length=1, max_length=500)
    note: str | None = Field(default=None, max_length=2000)


class ClassificationPublishRequest(BaseModel):
    server_id: str | None = None
    tool_ids: list[str] = Field(default_factory=list)


class PersonalTokenCreateRequest(BaseModel):
    name: str
    scopes: list[str] = Field(default_factory=list)
    expires_at: str | None = None


class PersonalTokenScopeUpdateRequest(BaseModel):
    scopes: list[str] = Field(default_factory=list)


class PasswordChangeRequest(BaseModel):
    password: str


class UserDownstreamCredentialSaveRequest(BaseModel):
    value: str


def register_access_routes(
    app: FastAPI,
    *,
    auth_store: AuthStore,
    access_store: AccessControlStore,
    registry: ToolRegistry,
    mcp_runtime: McpRuntimeManager,
    user_credential_store: UserCredentialStore,
    observability_store: ObservabilityStore,
    require_viewer: Callable[[Request], AuthPrincipal],
) -> None:
    """注册访问治理 API；所有策略写操作在这里集中做控制面权限校验。"""

    @app.post("/v1/auth/register", tags=["auth"])
    def register_user(request: RegisterRequest) -> dict[str, Any]:
        if not auth_store.enabled:
            raise HTTPException(status_code=409, detail="authentication is disabled")
        try:
            user = auth_store.register_user(
                username=request.username,
                display_name=request.display_name,
                password=request.password,
            )
            return {
                "message": "registration_pending",
                "user": user,
            }
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            if "UNIQUE constraint failed: users.username" in str(exc):
                raise HTTPException(status_code=409, detail="username already exists") from exc
            raise

    @app.get("/v1/access/users", tags=["access"])
    def list_users(principal: AuthPrincipal = Depends(require_viewer)) -> dict[str, Any]:
        _require(access_store, principal, "users.manage")
        return {"users": auth_store.list_users()}

    @app.post("/v1/access/users", tags=["access"])
    def create_access_user(
        request: UserCreateRequest,
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        _require(access_store, principal, "users.manage")
        if request.status not in {"pending", "active", "disabled"}:
            raise HTTPException(status_code=400, detail=f"invalid user status: {request.status}")
        role_codes = sorted({code.strip() for code in request.roles if code.strip()})
        if not role_codes:
            raise HTTPException(status_code=400, detail="at least one role is required")
        enabled_roles = {
            str(role["code"])
            for role in access_store.list_roles()
            if role["enabled"]
        }
        unknown_roles = sorted(set(role_codes) - enabled_roles)
        if unknown_roles:
            raise HTTPException(
                status_code=400,
                detail=f"unknown or disabled role(s): {', '.join(unknown_roles)}",
            )
        try:
            initial_role = role_codes[0]
            user = auth_store.create_user(
                username=request.username,
                display_name=request.display_name,
                password=request.password,
                role=initial_role,
                status_value=request.status,
                must_change_password=request.must_change_password,
            )
            access_store.set_user_roles(str(user["id"]), role_codes)
            return auth_store.get_user(str(user["id"]))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            if "UNIQUE constraint failed: users.username" in str(exc):
                raise HTTPException(status_code=409, detail="username already exists") from exc
            raise

    @app.patch("/v1/access/users/{user_id}", tags=["access"])
    def update_user(
        user_id: str,
        request: UserUpdateRequest,
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        _require(access_store, principal, "users.manage")
        if request.status is not None and request.status not in {"pending", "active", "disabled"}:
            raise HTTPException(status_code=400, detail=f"invalid user status: {request.status}")
        try:
            auth_store.validate_admin_transition(
                user_id,
                status_value=request.status,
                roles=request.roles,
            )
            if request.roles is not None:
                access_store.set_user_roles(user_id, request.roles)
            return auth_store.update_user(
                user_id,
                display_name=request.display_name,
                status_value=request.status,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/v1/access/control-permissions", tags=["access"])
    def list_control_permissions(
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        _require(access_store, principal, "roles.manage")
        return {"permissions": access_store.list_control_permissions()}

    @app.get("/v1/access/roles", tags=["access"])
    def list_roles(principal: AuthPrincipal = Depends(require_viewer)) -> dict[str, Any]:
        _require(access_store, principal, "roles.manage")
        return {"roles": access_store.list_roles()}

    @app.post("/v1/access/roles", tags=["access"])
    def create_role(
        request: RoleSaveRequest,
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        _require(access_store, principal, "roles.manage")
        try:
            return access_store.save_role(**request.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/v1/access/roles/{role_id}", tags=["access"])
    def update_role(
        role_id: str,
        request: RoleSaveRequest,
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        _require(access_store, principal, "roles.manage")
        try:
            return access_store.save_role(role_id=role_id, **request.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/v1/access/roles/{role_id}", tags=["access"])
    def delete_role(
        role_id: str,
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, str]:
        _require(access_store, principal, "roles.manage")
        try:
            access_store.delete_role(role_id)
            return {"message": "role_deleted"}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v1/access/permission-types", tags=["access"])
    def list_permission_types(
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        _require(access_store, principal, "roles.manage")
        return {"permission_types": access_store.list_permission_types()}

    @app.post("/v1/access/permission-types", tags=["access"])
    def create_permission_type(
        request: PermissionTypeSaveRequest,
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        _require(access_store, principal, "roles.manage")
        try:
            return access_store.save_permission_type(**request.model_dump())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.put("/v1/access/permission-types/{permission_type_id}", tags=["access"])
    def update_permission_type(
        permission_type_id: str,
        request: PermissionTypeSaveRequest,
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        _require(access_store, principal, "roles.manage")
        try:
            return access_store.save_permission_type(
                permission_type_id=permission_type_id,
                **request.model_dump(),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/v1/access/permission-types/{permission_type_id}", tags=["access"])
    def delete_permission_type(
        permission_type_id: str,
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, str]:
        _require(access_store, principal, "roles.manage")
        try:
            access_store.delete_permission_type(permission_type_id)
            return {"message": "permission_type_deleted"}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/v1/access/grants", tags=["access"])
    def list_grants(
        server_id: str | None = None,
        subject_type: str | None = None,
        subject_id: str | None = None,
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        _require(access_store, principal, "grants.manage")
        return {
            "grants": access_store.list_grants(
                server_id=server_id,
                subject_type=subject_type,
                subject_id=subject_id,
            )
        }

    @app.get("/v1/access/subjects", tags=["access"])
    def list_grant_subjects(
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        _require(access_store, principal, "grants.manage")
        return {
            "users": auth_store.list_users(),
            "roles": access_store.list_roles(),
        }

    @app.get("/v1/access/resources", tags=["access"])
    def list_grant_resources(
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        _require(access_store, principal, "grants.manage")
        definitions = registry.list_definitions()
        access_store.synchronize_tools(definitions)
        classifications = {
            (item["server_id"], item["tool_id"]): item
            for item in access_store.list_classifications()
        }
        return {
            "resources": [
                {
                    "server_id": str(item.metadata.get("server_id") or item.source or "builtin"),
                    "tool_id": item.id,
                    "tool_name": item.name,
                    "classification": classifications.get(
                        (str(item.metadata.get("server_id") or item.source or "builtin"), item.id),
                        {},
                    ).get("effective_access", "unknown"),
                    "classification_status": classifications.get(
                        (str(item.metadata.get("server_id") or item.source or "builtin"), item.id),
                        {},
                    ).get("status", "missing"),
                }
                for item in definitions
            ]
        }

    @app.put("/v1/access/grants", tags=["access"])
    def save_grant(
        request: GrantSaveRequest,
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        _require(access_store, principal, "grants.manage")
        try:
            return access_store.save_grant(
                **request.model_dump(),
                created_by=principal.id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/v1/access/grants/{grant_id}", tags=["access"])
    def delete_grant(
        grant_id: str,
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, str]:
        _require(access_store, principal, "grants.manage")
        try:
            access_store.delete_grant(grant_id)
            return {"message": "grant_deleted"}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/access/tool-classifications", tags=["access"])
    def list_tool_classifications(
        server_id: str | None = None,
        status: str | None = None,
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        _require(access_store, principal, "classifications.manage")
        access_store.synchronize_tools(registry.list_definitions())
        return {
            "classifications": access_store.list_classifications(
                server_id=server_id,
                status=status,
            )
        }

    @app.post("/v1/access/tool-classifications/analyze", tags=["access"])
    def analyze_tool_classifications(
        request: ClassificationAnalyzeRequest,
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        _require(access_store, principal, "classifications.manage")
        definitions = [
            item
            for item in registry.list_definitions()
            if not request.server_id or item.metadata.get("server_id") == request.server_id
        ]
        return {"classifications": access_store.analyze_tools(definitions)}

    @app.put("/v1/access/tool-classifications/{server_id}/{tool_id}", tags=["access"])
    def update_tool_classification(
        server_id: str,
        tool_id: str,
        request: ClassificationUpdateRequest,
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        _require(access_store, principal, "classifications.manage")
        try:
            return access_store.set_classification(
                server_id=server_id,
                tool_id=tool_id,
                access=request.access,
                destructive=request.destructive,
                idempotent=request.idempotent,
                reviewer_id=principal.id,
                note=request.note,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/access/tool-classifications/confirm", tags=["access"])
    def confirm_tool_classifications(
        request: ClassificationConfirmRequest,
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        _require(access_store, principal, "classifications.manage")
        # 直接调用 API 时也先同步最新 Tool 元数据，让 expected_fingerprint 能拦截旧页面提交。
        access_store.synchronize_tools(registry.list_definitions())
        try:
            return access_store.confirm_classifications(
                reviewer_id=principal.id,
                items=[item.model_dump() for item in request.items],
                note=request.note or "",
            )
        except ClassificationConfirmationConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/access/tool-classifications/publish", tags=["access"])
    def publish_tool_classifications(
        request: ClassificationPublishRequest,
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        _require(access_store, principal, "classifications.manage")
        return {
            "classifications": access_store.publish_classifications(
                reviewer_id=principal.id,
                server_id=request.server_id,
                tool_ids=request.tool_ids,
            )
        }

    @app.get("/v1/access/invocation-audits", tags=["access"])
    def list_invocation_audits(
        user_id: str | None = None,
        server_id: str | None = None,
        tool_id: str | None = None,
        decision: str | None = None,
        outcome: str | None = None,
        limit: int = Query(100, ge=1, le=500),
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        _require(access_store, principal, "audit.read")
        return {
            "audits": access_store.list_invocation_audits(
                user_id=user_id,
                server_id=server_id,
                tool_id=tool_id,
                decision=decision,
                outcome=outcome,
                limit=limit,
            ),
            "filter_options": access_store.list_invocation_audit_filter_options(),
        }

    @app.get("/v1/auth/tokens", tags=["auth"])
    def list_personal_tokens(
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        if not auth_store.enabled:
            raise HTTPException(status_code=409, detail="authentication is disabled")
        _require(access_store, principal, "credentials.manage.self")
        return {"tokens": auth_store.list_api_tokens(user_id=principal.id)}

    @app.post("/v1/auth/tokens", tags=["auth"])
    def create_personal_token(
        request: PersonalTokenCreateRequest,
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        if not auth_store.enabled:
            raise HTTPException(status_code=409, detail="authentication is disabled")
        _require(access_store, principal, "credentials.manage.self")
        try:
            return auth_store.create_api_token(
                principal=principal,
                name=request.name,
                scopes=request.scopes,
                expires_at=request.expires_at,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.patch("/v1/auth/tokens/{token_id}", tags=["auth"])
    def update_personal_token_scopes(
        token_id: str,
        request: PersonalTokenScopeUpdateRequest,
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        if not auth_store.enabled:
            raise HTTPException(status_code=409, detail="authentication is disabled")
        _require(access_store, principal, "credentials.manage.self")
        try:
            token, previous_scopes = auth_store.update_api_token_scopes(
                token_id,
                principal=principal,
                scopes=request.scopes,
            )
            observability_store.emit_event(
                "gate.auth.token_scopes_updated",
                source="auth",
                subject_type="token",
                subject_id=token_id,
                payload={
                    "actor_user_id": principal.id,
                    "previous_scopes": previous_scopes,
                    "scopes": token["scopes"],
                },
            )
            return token
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/v1/auth/tokens/{token_id}", tags=["auth"])
    def revoke_personal_token(
        token_id: str,
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        if not auth_store.enabled:
            raise HTTPException(status_code=409, detail="authentication is disabled")
        _require(access_store, principal, "credentials.manage.self")
        try:
            return auth_store.revoke_api_token(token_id, user_id=principal.id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/v1/auth/downstream-credentials", tags=["auth"])
    def list_downstream_credentials(
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        if not auth_store.enabled:
            raise HTTPException(status_code=409, detail="authentication is disabled")
        _require(access_store, principal, "credentials.manage.self")
        bindings = {
            (item["server_id"], item["slot_id"]): item
            for item in user_credential_store.list_bindings(principal.id)
        }
        slots: list[dict[str, Any]] = []
        for slot in mcp_runtime.list_user_credential_slots():
            server_id = str(slot["server_id"])
            if not _has_mcp_resource_access(access_store, registry, principal, server_id):
                continue
            binding = bindings.get((server_id, str(slot["id"])))
            slots.append(
                {
                    **slot,
                    "configured": bool(binding),
                    "created_at": binding.get("created_at") if binding else None,
                    "updated_at": binding.get("updated_at") if binding else None,
                    "last_used_at": binding.get("last_used_at") if binding else None,
                }
            )
        return {"credentials": slots}

    @app.put("/v1/auth/downstream-credentials/{server_id}/{slot_id}", tags=["auth"])
    def save_downstream_credential(
        server_id: str,
        slot_id: str,
        payload: UserDownstreamCredentialSaveRequest,
        request: Request,
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        if not auth_store.enabled:
            raise HTTPException(status_code=409, detail="authentication is disabled")
        _require(access_store, principal, "credentials.manage.self")
        _require_secure_secret_transport(request)
        if not _has_mcp_resource_access(access_store, registry, principal, server_id):
            raise HTTPException(status_code=403, detail="MCP resource access is required before binding credentials")
        try:
            slot = mcp_runtime.get_user_credential_slot(server_id, slot_id)
            binding = user_credential_store.save_binding(
                user_id=principal.id,
                server_id=server_id,
                slot_id=slot_id,
                value=payload.value,
            )
            return {**slot, **binding}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/v1/auth/downstream-credentials/{server_id}/{slot_id}", tags=["auth"])
    def delete_downstream_credential(
        server_id: str,
        slot_id: str,
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, Any]:
        if not auth_store.enabled:
            raise HTTPException(status_code=409, detail="authentication is disabled")
        _require(access_store, principal, "credentials.manage.self")
        try:
            return user_credential_store.delete_binding(
                user_id=principal.id,
                server_id=server_id,
                slot_id=slot_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/v1/auth/password", tags=["auth"])
    def change_password(
        request: PasswordChangeRequest,
        principal: AuthPrincipal = Depends(require_viewer),
    ) -> dict[str, str]:
        try:
            auth_store.change_password(principal.id, request.password)
            return {"message": "password_changed_relogin_required"}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


def _require_secure_secret_transport(request: Request) -> None:
    """除本机开发外，个人秘密只允许经 FastAPI 识别到的 HTTPS 提交。"""

    scheme = request.url.scheme.lower()
    host = request.client.host if request.client else ""
    if scheme != "https" and host not in {"127.0.0.1", "::1", "localhost"}:
        raise HTTPException(
            status_code=400,
            detail="HTTPS is required to submit user downstream credentials",
        )


def _has_mcp_resource_access(
    access_store: AccessControlStore,
    registry: ToolRegistry,
    principal: AuthPrincipal,
    server_id: str,
) -> bool:
    """Server 级或任一 Tool 级授权都允许用户预先绑定该 Server 的个人凭据。"""

    if access_store.effective_access(principal, server_id, "") != "none":
        return True
    for definition in registry.list_definitions():
        definition_server_id = str(
            definition.metadata.get("server_id") or definition.source or "builtin"
        )
        if definition_server_id != server_id:
            continue
        if access_store.effective_access(principal, server_id, definition.id) != "none":
            return True
    return False


def _require(
    access_store: AccessControlStore,
    principal: AuthPrincipal,
    permission_code: str,
) -> None:
    try:
        access_store.require_control_permission(principal, permission_code)
    except AccessDeniedError as exc:
        raise HTTPException(status_code=403, detail=exc.reason) from exc

"""Console/API group metadata; OAuth tools and audiences are unchanged."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Literal, TypeVar

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from lingshu_gate.application.console_session_security import ConsoleCsrfError, ConsoleSessionCsrf
from lingshu_gate.application.mcp_groups import McpGroupService
from lingshu_gate.auth import AuthPrincipal, AuthStore
from lingshu_gate.domain.mcp_groups import McpGroupDelete, McpGroupDraft, McpGroupError, McpGroupUpdate
from lingshu_gate.interfaces.control_api.console_security import console_origin_allowed

Body = TypeVar("Body", bound=BaseModel)


def register_mcp_group_routes(app: FastAPI, *, auth: AuthStore, service: McpGroupService) -> None:
    csrf = ConsoleSessionCsrf(auth)

    def principal(request: Request, body: dict[str, Any] | None = None) -> AuthPrincipal:
        actor = auth.authenticate_request(request)
        service.check(actor)
        if body is not None and actor.auth_type == "session":
            if not console_origin_allowed(request):
                raise HTTPException(403, detail={"code": "cross_origin_denied", "message": "Use the same-origin Console."})
            digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
            try:
                csrf.consume(actor, request.cookies.get(auth.cookie_name, ""), request.headers.get("x-csrf-token", ""),
                             f"{request.method}:{request.url.path}", digest)
            except ConsoleCsrfError as exc:
                raise HTTPException(exc.status, detail={"code": exc.code, "message": "Obtain a new Console request ticket."}) from None
        return actor

    def validated(model: type[Body], body: dict[str, Any]) -> Body:
        try:
            return model.model_validate(body)
        except ValidationError:
            raise HTTPException(422, detail={"code": "invalid_group_request", "message": "Check the name, state, distinct instance IDs, confirmation and revision; unknown fields are not supported."}) from None

    # Scope the handler to this router's service errors, without changing global errors.
    def error(exc: McpGroupError) -> HTTPException:
        return HTTPException(exc.status, detail={"code": exc.code, "message": exc.message})

    @app.post("/v1/mcp/groups/csrf", tags=["mcp-groups"])
    def ticket(request: Request, action: Literal["create", "update", "delete"],
               request_digest: str = Query(pattern=r"^[a-f0-9]{64}$"),
               group_id: str | None = Query(default=None, pattern=r"^[a-f0-9]{32}$")) -> JSONResponse:
        try:
            actor = principal(request)
            if actor.auth_type != "session" or not console_origin_allowed(request):
                raise HTTPException(403, detail={"code": "session_origin_required"})
            if (action == "create") != (group_id is None):
                raise HTTPException(422, detail={"code": "invalid_csrf_target"})
            target = "POST:/v1/mcp/groups" if action == "create" else f"{'PUT' if action == 'update' else 'DELETE'}:/v1/mcp/groups/{group_id}"
            result = csrf.issue(actor, request.cookies.get(auth.cookie_name, ""), target, request_digest)
            return JSONResponse(result, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})
        except McpGroupError as exc:
            raise error(exc) from None
        except ConsoleCsrfError as exc:
            raise HTTPException(exc.status, detail={"code": exc.code}) from None

    @app.get("/v1/mcp/groups", tags=["mcp-groups"])
    def groups(request: Request, q: str = Query(default="", max_length=200),
               status: Literal["active", "archived", "all"] = "active",
               offset: int = Query(default=0, ge=0, le=100000), limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        try:
            return service.list_groups(principal(request), q=q, status=status, offset=offset, limit=limit)
        except McpGroupError as exc:
            raise error(exc) from None

    @app.get("/v1/mcp/groups/instances", tags=["mcp-groups"])
    def instances(request: Request, q: str = Query(default="", max_length=200), group_id: str | None = None,
                  ungrouped: bool = False, offset: int = Query(default=0, ge=0, le=100000),
                  limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
        if group_id is not None and ungrouped:
            raise HTTPException(422, detail={"code": "invalid_group_filter"})
        try:
            return service.instances(principal(request), q=q, group_id=group_id, ungrouped=ungrouped, offset=offset, limit=limit)
        except McpGroupError as exc:
            raise error(exc) from None

    @app.get("/v1/mcp/groups/{group_id}", tags=["mcp-groups"])
    def detail(group_id: str, request: Request) -> dict[str, Any]:
        try:
            return service.detail(group_id, principal(request))
        except McpGroupError as exc:
            raise error(exc) from None

    @app.post("/v1/mcp/groups", tags=["mcp-groups"])
    def create(body: dict[str, Any], request: Request) -> dict[str, Any]:
        try:
            return service.save(validated(McpGroupDraft, body), principal(request, body))
        except McpGroupError as exc:
            raise error(exc) from None

    @app.put("/v1/mcp/groups/{group_id}", tags=["mcp-groups"])
    def update(group_id: str, body: dict[str, Any], request: Request) -> dict[str, Any]:
        try:
            draft = validated(McpGroupUpdate, body)
            return service.save(draft, principal(request, body), group_id=group_id, expected_revision=draft.expected_revision)
        except McpGroupError as exc:
            raise error(exc) from None

    @app.delete("/v1/mcp/groups/{group_id}", tags=["mcp-groups"])
    def delete(group_id: str, body: dict[str, Any], request: Request) -> dict[str, Any]:
        try:
            draft = validated(McpGroupDelete, body)
            return service.delete(group_id, draft.expected_revision, principal(request, body))
        except McpGroupError as exc:
            raise error(exc) from None

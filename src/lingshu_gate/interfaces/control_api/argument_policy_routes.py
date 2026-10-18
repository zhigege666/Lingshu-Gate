"""Explicitly authorized policy writes and pure, bounded draft validation."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.application.console_session_security import ConsoleCsrfError, ConsoleSessionCsrf
from lingshu_gate.application.schema_validation import validate_arguments
from lingshu_gate.application.tool_authority import current_tool_principal
from lingshu_gate.argument_policy import ArgumentPolicy, ArgumentPolicyDenied, PolicyError, PolicyWrite, check_policy
from lingshu_gate.auth import AuthPrincipal, AuthStore
from lingshu_gate.domain.tool_structure import checked_json_size
from lingshu_gate.interfaces.control_api.console_security import console_origin_allowed
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.registry import ToolExecutionError, ToolNotFoundError, ToolRegistry


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


async def _body(request: Request, *, preview: bool = False) -> dict[str, Any]:
    limit = 1_179_648 if preview else 73_728
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > limit:
            raise HTTPException(413, detail={"code": "argument_policy_request_limit"})
    try:
        value = json.loads(raw, object_pairs_hook=_unique)
        if not isinstance(value, dict):
            raise ValueError
        checked_json_size(value, max_bytes=limit, max_nodes=16384, max_depth=36)
        # Bind the exact submitted bytes. Browser and Python JSON serializers
        # differ in number and Unicode-key formatting; neither may rewrite the
        # other's values when issuing a single-use confirmation ticket.
        request.state.argument_policy_body_digest = hashlib.sha256(raw).hexdigest()
        return value
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise HTTPException(422, detail={"code": "argument_policy_request_invalid"}) from None


def register_argument_policy_routes(app: FastAPI, *, auth: AuthStore, access: AccessControlStore,
                                   registry: ToolRegistry, observability: ObservabilityStore) -> None:
    store, csrf = access.argument_policies, ConsoleSessionCsrf(auth)

    def require_manager(actor: AuthPrincipal) -> AuthPrincipal:
        try:
            current = current_tool_principal(auth, actor)
        except Exception:
            raise HTTPException(403, detail={"code": "argument_policy_authority_unavailable"}) from None
        if not access.has_control_permission(current, "grants.manage"):
            raise HTTPException(403, detail={"code": "argument_policy_permission_required"})
        return current

    def principal(request: Request) -> AuthPrincipal:
        if not auth.enabled:
            raise HTTPException(401, detail={"code": "authentication_required"}, headers={"WWW-Authenticate": "Bearer"})
        return require_manager(auth.authenticate_request(request))

    def target(tool_id: str) -> None:
        if not 1 <= len(tool_id) <= 255 or any(ord(c) < 32 for c in tool_id):
            raise HTTPException(404, detail={"code": "tool_unavailable"})
        try:
            registry.get_definition(tool_id)
        except ToolNotFoundError:
            if access.database.query_one("SELECT 1 FROM tool_argument_policies WHERE tool_id=?", (tool_id,)) is None:
                raise HTTPException(404, detail={"code": "tool_unavailable"}) from None

    def parse(body: dict[str, Any]) -> PolicyWrite:
        try:
            return PolicyWrite.model_validate(body)
        except (ValueError, TypeError, RecursionError, OverflowError):
            raise HTTPException(422, detail={"code": "argument_policy_invalid"}) from None

    def reply(value: Any) -> JSONResponse:
        return JSONResponse(value, headers={"Cache-Control": "no-store", "Pragma": "no-cache"})

    @app.get("/v1/tools/{tool_id}/argument-policy", tags=["tools"])
    def detail(tool_id: str, request: Request) -> JSONResponse:
        principal(request)
        target(tool_id)
        try:
            return reply(store.current(tool_id).public(tool_id))
        except ArgumentPolicyDenied as error:
            raise HTTPException(409, detail={"code": "argument_policy_corrupt", **error.details}) from None

    @app.post("/v1/tools/{tool_id}/argument-policy/csrf", tags=["tools"])
    def ticket(tool_id: str, request: Request, request_digest: str = Query(pattern=r"^[a-f0-9]{64}$")) -> JSONResponse:
        actor = principal(request)
        target(tool_id)
        if actor.auth_type != "session" or not console_origin_allowed(request):
            raise HTTPException(403, detail={"code": "session_origin_required"})
        try:
            return reply(csrf.issue(actor, request.cookies.get(auth.cookie_name, ""), f"PUT:argument-policy:{tool_id}", request_digest))
        except ConsoleCsrfError as error:
            raise HTTPException(error.status, detail={"code": error.code}) from None

    @app.put("/v1/tools/{tool_id}/argument-policy", tags=["tools"])
    async def save(tool_id: str, request: Request) -> JSONResponse:
        actor = await run_in_threadpool(principal, request)
        await run_in_threadpool(target, tool_id)
        body = await _body(request)
        draft = parse(body)
        if actor.auth_type == "session":
            if not console_origin_allowed(request):
                raise HTTPException(403, detail={"code": "cross_origin_denied"})
            try:
                await run_in_threadpool(csrf.consume, actor, request.cookies.get(auth.cookie_name, ""),
                    request.headers.get("x-csrf-token", ""), f"PUT:argument-policy:{tool_id}", request.state.argument_policy_body_digest)
            except ConsoleCsrfError as error:
                raise HTTPException(error.status, detail={"code": error.code}) from None
        try:
            return reply(await run_in_threadpool(store.save, tool_id, draft, actor_id=actor.id,
                authorize=lambda connection: require_manager(actor), observability=observability))
        except PolicyError as error:
            raise HTTPException(error.status, detail={"code": error.code}) from None

    @app.post("/v1/tools/{tool_id}/argument-policy/preview", tags=["tools"])
    async def preview(tool_id: str, request: Request) -> JSONResponse:
        await run_in_threadpool(principal, request)
        await run_in_threadpool(target, tool_id)
        body = await _body(request, preview=True)
        arguments = body.pop("arguments", None)
        draft = parse(body)
        if not isinstance(arguments, dict):
            raise HTTPException(422, detail={"code": "tool_arguments_invalid"})
        if "fileRef" in arguments:
            raise HTTPException(409, detail={"code": "argument_policy_preview_requires_runtime",
                "message": "A file reference needs the calling user's live runtime resolution; no tool was invoked."})
        try:
            prepared = await run_in_threadpool(registry.prepare, tool_id, arguments)
            await run_in_threadpool(validate_arguments, prepared.record.definition.input_schema, prepared.arguments)
            check_policy(ArgumentPolicy(draft.enabled, draft.expected_revision, tuple(draft.rules)), prepared.arguments)
            return reply({"allowed": True, "draft": True, "execution": "not_invoked"})
        except ArgumentPolicyDenied as error:
            return reply({"allowed": False, "draft": True, "execution": "not_invoked", **error.details})
        except ToolExecutionError as error:
            raise HTTPException(422, detail={"code": error.code, "message": error.message}) from None
        except ToolNotFoundError:
            raise HTTPException(404, detail={"code": "tool_unavailable"}) from None

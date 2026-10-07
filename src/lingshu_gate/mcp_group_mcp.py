"""Administrator group-management tools; public invocation belongs to the directory."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lingshu_gate.application.mcp_groups import McpGroupService
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.domain.mcp_groups import McpGroupCreate, McpGroupDelete, McpGroupError, McpGroupUpdate
from lingshu_gate.project_delivery_mcp import _definition
from lingshu_gate.registry import ToolExecutionError, ToolInvocationContext, ToolRegistry

GROUP_MANAGEMENT_TOOL_IDS = frozenset({"gate_mcp_group_list", "gate_mcp_group_get", "gate_mcp_group_save", "gate_mcp_group_delete"})


class GroupListInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str = Field(default="", max_length=200)
    status: Literal["active", "archived", "all"] = "active"
    offset: int = Field(default=0, ge=0, le=100_000)
    limit: int = Field(default=20, ge=1, le=100)


class GroupGetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class GroupSaveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    draft: McpGroupCreate | McpGroupUpdate


class GroupDeleteInput(GroupGetInput, McpGroupDelete):
    pass


def _actor(context: ToolInvocationContext) -> AuthPrincipal:
    return AuthPrincipal(id=context.actor_id, username=context.username,
        role="admin" if "admin" in context.roles else next(iter(context.roles), ""), roles=context.roles,
        permissions=context.permissions, auth_type=context.auth_type, token_id=context.token_id,
        session_id=context.session_id, scopes=context.scopes, delegated_scopes=context.delegated_scopes)


def register_mcp_group_tools(registry: ToolRegistry, service: McpGroupService) -> None:
    def dispatch(name: str, model: type[BaseModel], write: bool):
        def invoke(arguments: dict[str, Any], context: ToolInvocationContext) -> dict[str, Any]:
            try:
                actor = _actor(context)
                service.check(actor, write=write)
                if write and context.auth_type == "session":
                    raise McpGroupError("group_session_entry_denied", "Use the dedicated Console API with a fresh CSRF ticket.", 403)
                body = model.model_validate(arguments)
                if isinstance(body, GroupListInput):
                    return service.list_groups(actor, **body.model_dump())
                if isinstance(body, GroupDeleteInput):
                    return service.delete(body.group_id, body.expected_revision, actor)
                if isinstance(body, GroupGetInput):
                    return service.detail(body.group_id, actor)
                if isinstance(body, GroupSaveInput):
                    if body.group_id is None and isinstance(body.draft, McpGroupCreate):
                        return service.save(body.draft, actor)
                    if body.group_id is not None and isinstance(body.draft, McpGroupUpdate):
                        return service.save(body.draft, actor, group_id=body.group_id,
                                            expected_revision=body.draft.expected_revision)
                    raise McpGroupError("invalid_group_request", "Create needs a request key; update needs a group ID and revision.", 422)
                raise AssertionError("Unknown group management tool")
            except ValidationError:
                raise ToolExecutionError("invalid_group_request", "Check the group fields, confirmation and revision.") from None
            except McpGroupError as exc:
                raise ToolExecutionError(exc.code, exc.message) from None
        return invoke

    definitions: list[tuple[str, type[BaseModel], bool, str]] = [
        ("gate_mcp_group_list", GroupListInput, False, "List explicitly configured MCP groups; creates no grants."),
        ("gate_mcp_group_get", GroupGetInput, False, "Read group metadata and existing instance references."),
        ("gate_mcp_group_save", GroupSaveInput, True, "Create or update a confirmed group; does not copy credentials or grant access."),
        ("gate_mcp_group_delete", GroupDeleteInput, True, "Delete confirmed group metadata; leaves its instances running."),
    ]
    for name, model, write, description in definitions:
        definition = _definition(name, name, description, model, permission="write" if write else "read",
                                 read_only=not write, destructive=name.endswith("delete"), open_world=False)
        definition.metadata.update(server_id="gate_mcp_groups", group_management_control_plane=True)
        registry.register(definition, dispatch(name, model, write), contextual=True)

"""Thin MCP adapter for the shared external configuration application service."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from lingshu_gate.application.external_mcp_configuration import (
    ExternalConfigApplyInput,
    ExternalConfigCancelInput,
    ExternalConfigPlanInput,
    ExternalConfigStatusInput,
    ExternalMcpConfigurationService,
)
from lingshu_gate.project_delivery_mcp import _definition
from lingshu_gate.registry import ToolExecutionError, ToolInvocationContext, ToolRegistry


def _management_handler(handler: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    def invoke(arguments: dict[str, Any], context: ToolInvocationContext) -> dict[str, Any]:
        # Registry entry points do not consume the request-bound Console ticket.
        # Session calls must use the dedicated REST adapter that does so.
        if context.auth_type == "session":
            raise ToolExecutionError("external_config_session_entry_denied",
                "Console sessions must use the dedicated external configuration API.",
                next_action="Use /v1/mcp/external-configs with a fresh Origin/session/body-bound CSRF ticket.")
        return handler(arguments, context)
    return invoke


def register_external_mcp_config_tools(registry: ToolRegistry, service: ExternalMcpConfigurationService) -> None:
    tools: list[tuple[str, type[BaseModel], Callable[..., dict[str, Any]], bool, bool]] = [
        ("gate_mcp_config_plan", ExternalConfigPlanInput, service.plan, True, False),
        ("gate_mcp_config_apply", ExternalConfigApplyInput, service.apply, False, False),
        ("gate_mcp_config_status", ExternalConfigStatusInput, service.status, True, False),
        ("gate_mcp_config_cancel", ExternalConfigCancelInput, service.cancel, False, True),
    ]
    for name, model, handler, read_only, destructive in tools:
        definition = _definition(name, name, "Administrator-only external HTTP configuration; never starts a remote process or grants tools.",
                                 model, permission="read" if read_only else "write",
                                 read_only=read_only, destructive=destructive,
                                 open_world=name in {"gate_mcp_config_plan", "gate_mcp_config_apply"},
                                 sensitive_inputs=["manifest"])
        definition.metadata["server_id"] = "gate_mcp_configuration"
        registry.register(definition, _management_handler(handler), contextual=True)

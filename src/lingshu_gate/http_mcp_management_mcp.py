"""Thin MCP adapter for explicitly consented HTTP administration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from lingshu_gate.application.external_mcp_configuration import (
    ExternalConfigApplyInput, ExternalConfigCancelInput, ExternalConfigStatusInput,
    ExternalMcpConfigurationService,
)
from lingshu_gate.argument_preparation import model_preparer
from lingshu_gate.domain.http_mcp_management import HttpMcpPlanInput, HttpMcpTestInput
from lingshu_gate.external_mcp_config_mcp import _management_handler
from lingshu_gate.project_delivery_mcp import _definition
from lingshu_gate.registry import ToolRegistry


class HttpMcpApplyInput(ExternalConfigApplyInput):
    """Apply exactly the approved HTTP management plan."""


class HttpMcpStatusInput(ExternalConfigStatusInput):
    """Read one authorized HTTP target or operation."""


class HttpMcpCancelInput(ExternalConfigCancelInput):
    """Cancel outstanding work; already saved changes remain."""


def register_http_mcp_management_tools(registry: ToolRegistry, service: ExternalMcpConfigurationService) -> None:
    definitions: list[tuple[str, type[BaseModel], Callable[..., dict[str, Any]], bool, bool]] = [
        ("gate_http_mcp_test", HttpMcpTestInput, service.http_test, False, False),
        ("gate_http_mcp_plan", HttpMcpPlanInput, service.http_plan, True, False),
        ("gate_http_mcp_apply", HttpMcpApplyInput, service.http_apply, False, True),
        ("gate_http_mcp_status", HttpMcpStatusInput, service.http_status, True, False),
        ("gate_http_mcp_cancel", HttpMcpCancelInput, service.http_cancel, False, True),
    ]
    for name, model, handler, read_only, destructive in definitions:
        definition = _definition(name, name,
            ("Explicit bounded HTTP connection test: authenticate, negotiate MCP and list tools using an isolated client; "
             "never saves configurations, changes trust, publishes tools or calls business tools." if name == "gate_http_mcp_test" else
            "Administrator HTTP MCP management: offline create/update/delete or exact private-origin revoke/restore plans; "
            "apply never installs or stops a remote service, grants tools or returns credential values."),
            model, permission="read" if read_only else "write", read_only=read_only,
            destructive=destructive, open_world=name in {"gate_http_mcp_apply", "gate_http_mcp_test"}, sensitive_inputs=["manifest"])
        definition.metadata["server_id"] = "gate_mcp_configuration"
        registry.register(definition, _management_handler(handler), contextual=True, argument_preparer=model_preparer(model))

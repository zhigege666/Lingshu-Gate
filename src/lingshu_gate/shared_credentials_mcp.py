"""Sensitive, masked MCP adapters for shared system credential management."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel

from lingshu_gate.application.shared_credentials import (
    CredentialCreateInput, CredentialDeleteInput, CredentialGetInput,
    CredentialListInput, CredentialUpdateInput, SharedCredentialService,
)
from lingshu_gate.argument_preparation import model_preparer
from lingshu_gate.project_delivery_mcp import _definition
from lingshu_gate.registry import ToolExecutionError, ToolInvocationContext, ToolRegistry


def _handler(action: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    def invoke(arguments: dict[str, Any], context: ToolInvocationContext) -> dict[str, Any]:
        if context.auth_type == "session":
            raise ToolExecutionError("credential_session_entry_denied", "Console sessions must use the credential API.",
                                     next_action="Use the dedicated /v1/credentials routes.")
        return action(arguments, context)
    return invoke


def register_credential_tools(registry: ToolRegistry, service: SharedCredentialService) -> None:
    tools: list[tuple[str, type[BaseModel], Callable[..., dict[str, Any]], bool]] = [
        ("gate_credential_list", CredentialListInput, service.list, True),
        ("gate_credential_get", CredentialGetInput, service.get, True),
        ("gate_credential_create", CredentialCreateInput, service.create, False),
        ("gate_credential_update", CredentialUpdateInput, service.update, False),
        ("gate_credential_delete", CredentialDeleteInput, service.delete, False),
    ]
    for name, model, action, read_only in tools:
        definition = _definition(name, name,
            "Manage shared encrypted credentials. Values are write-only; HTTP use needs explicit service/origin scopes. "
            "Writes require an idempotency key; update/delete require the current updated_at revision.",
            model, permission="read" if read_only else "write", read_only=read_only,
            destructive=name == "gate_credential_delete", open_world=False,
            sensitive_inputs=["value"], sensitive_outputs=["value"])
        definition.metadata.update(server_id="gate_credentials", required_control_permission="credentials.manage.system")
        # Credential responses retain the Console's flat masked shape. The
        # delivery helper's required `status` field does not describe them.
        result_key = "credentials" if name == "gate_credential_list" else "id"
        error_schema = definition.metadata["outputSchema"]["properties"]["error"]
        definition.metadata["outputSchema"] = {
            "type": "object",
            "properties": {
                result_key: {"type": "array", "items": {"type": "object"}} if read_only and result_key == "credentials"
                            else {"type": "string"},
                "error": error_schema,
            },
            "oneOf": [{"required": [result_key]}, {"required": ["error"]}],
            "additionalProperties": True,
        }
        registry.register(definition, _handler(action), contextual=True, argument_preparer=model_preparer(model))

"""Authorization-filtered tool projections; execution remains in ToolCatalog."""
from __future__ import annotations

import hashlib
import json
import copy
from dataclasses import dataclass
from typing import Any
from pydantic import BaseModel, ConfigDict, Field
from jsonschema.validators import validator_for

from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.models import ToolDefinition
from lingshu_gate.registry import ToolNotFoundError
from lingshu_gate.tool_catalog import CatalogInvoke, ToolCatalog, schema_revision


class GroupPinArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    instance_id: str = Field(min_length=1, max_length=256)
    session_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    schema_revision: str = Field(pattern=r"^[a-f0-9]{64}$")
    arguments: dict[str, Any]


@dataclass(frozen=True)
class PinnedProjection:
    kind: str
    tool_ref: str
    revision: str
    payload: dict[str, Any]

    def invocation(self, arguments: dict[str, Any]) -> CatalogInvoke:
        if self.kind == "group":
            return CatalogInvoke.model_validate({"tool_ref": self.tool_ref, **GroupPinArguments.model_validate(arguments).model_dump()})
        return CatalogInvoke(tool_ref=self.tool_ref, schema_revision=self.revision, arguments=arguments)


def project_pins(catalog: ToolCatalog, principal: AuthPrincipal, settings: dict[str, Any]) -> list[PinnedProjection]:
    pins = settings.get("pinned_tools", [])
    if settings["tool_discovery_mode"] != "on_demand" or len(pins) > 20:
        return []
    physical = []
    for pin in pins:
        if pin["kind"] == "tool":
            try:
                physical.append(catalog.registry.get_definition(pin["tool_ref"]))
            except ToolNotFoundError:
                pass
    with catalog.database.session() as connection:
        visible = catalog.access.visible_tool_contracts(principal, physical, connection=connection)
    definitions: dict[tuple[str, str], ToolDefinition] = {("tool", item.id): item for item, _ in visible if isinstance(item, ToolDefinition)}
    if catalog.group_router:
        definitions.update({("group", reference): definition for reference, definition in catalog.group_router.pin_contracts(
            principal, [pin["tool_ref"] for pin in pins if pin["kind"] == "group"]).items()})
    result = []
    for pin in pins:
        kind, reference = pin["kind"], pin["tool_ref"]
        definition = definitions.get((kind, reference))
        if definition is None:
            continue
        revision = reference.rsplit(":", 1)[-1] if kind == "group" else schema_revision(definition)
        identity = [kind, reference] if kind == "group" else [kind, reference, revision]
        name = "gate_pinned_" + hashlib.sha256(json.dumps(identity, separators=(",", ":")).encode()).hexdigest()
        schema = definition.input_schema or {"type": "object", "properties": {}}
        if kind == "group":
            # A business schema is its own resource. Preserve root-local refs,
            # nested identifiers and anchors when placing it inside the envelope.
            resource = copy.deepcopy(schema)
            identifier_key = "$id" if validator_for(resource).ID_OF({"$id": "urn:gate:test"}) else "id"
            resource.setdefault(identifier_key, "urn:lingshu-gate:arguments:" + name)
            schema = {"$schema": resource.get("$schema", "https://json-schema.org/draft/2020-12/schema"), "type": "object", "additionalProperties": False,
                      "properties": {"instance_id": {"type": "string", "minLength": 1},
                                     "session_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
                                     "schema_revision": {"type": "string", "enum": [revision]}, "arguments": resource},
                      "required": ["instance_id", "session_id", "schema_revision", "arguments"]}
        from lingshu_gate.mcp_gateway import _tool_annotations

        payload = {"name": name, "title": definition.name, "description": definition.description,
                   "inputSchema": schema, "annotations": _tool_annotations(definition)}
        output = definition.metadata.get("outputSchema", definition.metadata.get("output_schema"))
        if isinstance(output, dict):
            payload["outputSchema"] = output
        result.append(PinnedProjection(kind, reference, revision, payload))
    return result

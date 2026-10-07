"""Request-local contract candidates, never business-equivalence or routing IDs."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from lingshu_gate.domain.mcp_groups import McpGroupError
from lingshu_gate.models import ToolDefinition
from lingshu_gate.domain.tool_structure import checked_json_size
from lingshu_gate.domain.tool_structure import FrozenToolDefinition

MAX_CATALOG_TOOLS = 50_000
MAX_SCHEMA_BYTES = 128 * 1024
MAX_SCHEMA_NODES = 10_000
MAX_SCHEMA_DEPTH = 64
MAX_CATALOG_CONTRACT_BYTES = 32 * 1024 * 1024


def contract_json_size(value: Any, *, max_bytes: int | None = None,
                       max_nodes: int | None = None, max_depth: int | None = None) -> int:
    """Reject before complete serialization; count escaped UTF-8 JSON bytes."""
    byte_limit = MAX_SCHEMA_BYTES if max_bytes is None else max_bytes
    node_limit = MAX_SCHEMA_NODES if max_nodes is None else max_nodes
    depth_limit = MAX_SCHEMA_DEPTH if max_depth is None else max_depth
    try:
        return checked_json_size(value, max_bytes=byte_limit, max_nodes=node_limit, max_depth=depth_limit)
    except ValueError as exc:
        raise ValueError(str(exc).replace("tool_structure_", "schema_")) from None


def canonical_contract(value: Any) -> str:
    """Sort object keys only; preserve arrays, types and every schema keyword."""
    contract_json_size(value)
    result = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if len(result.encode("utf-8")) > MAX_SCHEMA_BYTES:
        raise ValueError("schema_size_limit")
    return result


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class ReviewedToolSafety(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    required_access: Literal["read", "write"]
    destructive: bool
    idempotent: bool
    open_world: bool


class GroupToolVariant(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    variant_id: str
    original_tool_name: str
    compatibility: Literal["reviewed_contract_match", "single_member", "review_required", "uncomparable"]
    input_schema_digest: str | None
    output_schema_present: bool
    output_schema_digest: str | None
    safety_digest: str | None
    safety: ReviewedToolSafety | None
    visible_member_count: int
    visible_variant_count: int = 1


class GroupToolCatalogPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_id: str
    group_revision: int
    business_equivalence: Literal["unverified"] = "unverified"
    variants: list[GroupToolVariant]
    total: int
    visible_tool_count: int
    visible_member_count: int
    offset: int
    limit: int


class GroupToolMember(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    instance_id: str
    instance_name: str
    tool_id: str


class GroupToolVariantPage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    group_id: str
    group_revision: int
    business_equivalence: Literal["unverified"] = "unverified"
    variant: GroupToolVariant
    members: list[GroupToolMember]
    total: int
    offset: int
    limit: int


@dataclass(frozen=True)
class VisibleCatalogTool:
    definition: ToolDefinition | FrozenToolDefinition
    instance_id: str
    instance_name: str
    classification: dict[str, Any] | None
    structure: NormalizedToolContract | None = None


@dataclass(frozen=True, slots=True)
class NormalizedToolContract:
    comparable: bool
    input_text: str
    output_text: str
    policy_text: str
    output_present: bool
    input_digest: str | None
    output_digest: str | None
    byte_count: int


def normalize_tool_contract(definition: ToolDefinition) -> NormalizedToolContract:
    output_present = "outputSchema" in definition.metadata
    if not isinstance(definition.input_schema, dict):
        raise ValueError("schema_non_object")
    if output_present and not isinstance(definition.metadata["outputSchema"], dict):
        raise ValueError("schema_non_object")
    input_text = canonical_contract(definition.input_schema)
    output_text = canonical_contract({"present": output_present, "schema": definition.metadata.get("outputSchema")})
    policy_text = canonical_contract({
        "declared_permission": definition.permission,
        "required_control_permission": definition.metadata.get("required_control_permission"),
        "sensitive_input_fields": definition.metadata.get("sensitive_input_fields"),
        "sensitive_output_fields": definition.metadata.get("sensitive_output_fields"),
        "annotations": definition.metadata.get("annotations", {}),
        "contract_version": definition.metadata.get("contract_version"),
        "protocol_meta": definition.metadata.get("_meta"),
    })
    return NormalizedToolContract(True, input_text, output_text, policy_text, output_present,
        _digest(input_text), _digest(output_text) if output_present else None,
        sum(len(text.encode("utf-8")) for text in (input_text, output_text, policy_text)))


def uncomparable_contract(output_present: bool) -> NormalizedToolContract:
    return NormalizedToolContract(False, "", "", "", output_present, None, None, 0)


def _review_text(safety: ReviewedToolSafety | None) -> str:
    if safety is None:
        return "null"
    return (f'{{"required_access":"{safety.required_access}","destructive":{str(safety.destructive).lower()},'
            f'"idempotent":{str(safety.idempotent).lower()},"open_world":{str(safety.open_world).lower()}' + "}")


def _variant_identifier(group_id: str, key: tuple[str, ...]) -> str:
    digest = hashlib.sha256()
    for part in (group_id, *key):
        raw = part.encode("utf-8")
        digest.update(len(raw).to_bytes(8, "big"))
        digest.update(raw)
    return digest.hexdigest()


@dataclass
class CatalogVariant:
    summary: GroupToolVariant
    members: list[GroupToolMember]
    search_text: str


def _reviewed_safety(row: dict[str, Any] | None) -> ReviewedToolSafety | None:
    if (not row or row["status"] != "published" or not row["reviewed_by"] or not row["reviewed_at"]
            or row["effective_access"] not in {"read", "write"}):
        return None
    return ReviewedToolSafety(required_access=row["effective_access"], destructive=bool(row["destructive"]),
                              idempotent=bool(row["idempotent"]), open_world=bool(row["open_world"]))


def build_catalog(group_id: str, tools: list[VisibleCatalogTool]) -> list[CatalogVariant]:
    """Partition only already-authorized tools. No authorization result is cached."""
    if len(tools) > MAX_CATALOG_TOOLS:
        raise McpGroupError("group_catalog_capacity", "The visible catalog exceeds the bounded comparison capacity.", 503)
    buckets: dict[tuple[str, ...], CatalogVariant] = {}
    used_bytes = 0
    for item in tools:
        definition = item.definition
        name = definition.metadata["original_tool_name"]
        structure = item.structure
        if structure is None:
            try:
                mutable = definition.copy_definition() if isinstance(definition, FrozenToolDefinition) else definition
                structure = normalize_tool_contract(mutable)
            except (ValueError, TypeError, AttributeError):
                structure = uncomparable_contract("outputSchema" in definition.metadata)
        output_present = structure.output_present
        safety = _reviewed_safety(item.classification)
        comparison: Literal["reviewed_contract_match", "review_required", "uncomparable"] = (
            "reviewed_contract_match" if safety else "review_required"
        )
        input_text, output_text = structure.input_text, structure.output_text
        review_text = _review_text(safety)
        safety_text = f"[{structure.policy_text},{review_text}]" if structure.comparable else ""
        if not structure.comparable:
            comparison = "uncomparable"
        used_bytes += structure.byte_count + len(review_text) + 3
        if used_bytes > MAX_CATALOG_CONTRACT_BYTES:
            raise McpGroupError("group_catalog_capacity", "The visible contracts exceed the bounded comparison capacity.", 503)
        # Pending/stale/unrepresentable contracts remain individual variants.
        discriminator = "" if comparison == "reviewed_contract_match" else definition.id
        key = (name, input_text, output_text, safety_text, discriminator)
        member = GroupToolMember(instance_id=item.instance_id, instance_name=item.instance_name, tool_id=definition.id)
        if key not in buckets:
            identifier = _variant_identifier(group_id, key)
            buckets[key] = CatalogVariant(GroupToolVariant(
                variant_id=identifier, original_tool_name=name, compatibility=comparison,
                input_schema_digest=structure.input_digest,
                output_schema_present=output_present,
                output_schema_digest=structure.output_digest,
                safety_digest=_digest(safety_text) if safety_text else None,
                safety=safety, visible_member_count=0,
            ), [], "")
        buckets[key].members.append(member)
    counts = Counter(item.summary.original_tool_name for item in buckets.values())
    for variant in buckets.values():
        variant.members.sort(key=lambda member: (member.instance_id, member.tool_id))
        members = len({member.instance_id for member in variant.members})
        compatibility = variant.summary.compatibility
        if compatibility == "reviewed_contract_match" and members == 1:
            compatibility = "single_member"
        variant.summary = variant.summary.model_copy(update={
            "visible_member_count": members, "visible_variant_count": counts[variant.summary.original_tool_name],
            "compatibility": compatibility,
        })
        variant.search_text = " ".join([variant.summary.original_tool_name, *(
            f"{member.instance_id} {member.instance_name} {member.tool_id}" for member in variant.members
        )]).casefold()
    return sorted(buckets.values(), key=lambda item: (
        item.summary.original_tool_name.casefold(), item.summary.original_tool_name, item.summary.variant_id,
    ))

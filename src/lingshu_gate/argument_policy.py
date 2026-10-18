"""Bounded additional restrictions on the actual tool arguments at dispatch."""
from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError, field_validator, model_validator

from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.domain.tool_structure import checked_json_size
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.registry import ToolDispatchRejectedError

MAX_POLICY_BYTES = 65_536


class RuleBase(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    id: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$")
    pointer: str = Field(max_length=512)

    @field_validator("pointer")
    @classmethod
    def pointer_supported(cls, value: str) -> str:
        if (value and not value.startswith("/") or re.search(r"~(?![01])", value)
                or value.count("/") > 32 or any(ord(c) < 32 for c in value)):
            raise ValueError("policy_pointer_invalid")
        return value


class EqualsRule(RuleBase):
    operator: Literal["equals"]
    value: Any


class AllowedRule(RuleBase):
    operator: Literal["allowed_values"]
    values: list[Any] = Field(min_length=1, max_length=64)


class NumberRule(RuleBase):
    operator: Literal["number_range"]
    minimum: int | float | None = None
    maximum: int | float | None = None

    @model_validator(mode="after")
    def range_supported(self):
        if self.minimum is None and self.maximum is None:
            raise ValueError("policy_range_required")
        if any(value is not None and (type(value) not in {int, float} or isinstance(value, float) and not math.isfinite(value))
               for value in (self.minimum, self.maximum)):
            raise ValueError("policy_range_invalid")
        if self.minimum is not None and self.maximum is not None and self.minimum > self.maximum:
            raise ValueError("policy_range_invalid")
        return self


class PrefixRule(RuleBase):
    operator: Literal["string_prefix"]
    prefix: str = Field(min_length=1, max_length=1024)


Rule = Annotated[EqualsRule | AllowedRule | NumberRule | PrefixRule, Field(discriminator="operator")]
_rules = TypeAdapter(list[Rule])


class PolicyWrite(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_revision: int = Field(ge=0, le=2_147_483_646)
    enabled: bool
    rules: list[Rule] = Field(max_length=64)

    @model_validator(mode="after")
    def supported(self):
        validate_rules([rule.model_dump() for rule in self.rules])
        return self


class PolicyError(ValueError):
    def __init__(self, code: str, status: int = 422):
        self.code, self.status = code, status
        super().__init__(code)


class ArgumentPolicyDenied(ToolDispatchRejectedError):
    def __init__(self, revision: int, *, rule_id: str | None = None, pointer: str | None = None,
                 reason: str = "rule_not_satisfied"):
        super().__init__("argument_policy_denied", "The effective tool arguments do not satisfy the current argument policy.",
            next_action="Review the indicated rule and submit a new, explicitly authorized call.",
            details={"policy_revision": revision, "rule_id": rule_id, "pointer": pointer, "reason": reason})


@dataclass(frozen=True)
class ArgumentPolicy:
    enabled: bool = False
    revision: int = 0
    rules: tuple[EqualsRule | AllowedRule | NumberRule | PrefixRule, ...] = ()

    def public(self, tool_id: str) -> dict[str, Any]:
        return {"tool_id": tool_id, "enabled": self.enabled, "revision": self.revision,
                "rules": [rule.model_dump() for rule in self.rules]}


def validate_rules(value: Any) -> list[EqualsRule | AllowedRule | NumberRule | PrefixRule]:
    try:
        checked_json_size(value, max_bytes=MAX_POLICY_BYTES, max_nodes=8192, max_depth=24)
        parsed = _rules.validate_python(value, strict=True)
        if len(parsed) > 64 or len({rule.id for rule in parsed}) != len(parsed):
            raise ValueError
        return parsed
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise PolicyError("argument_policy_invalid") from None


def _same_json(left: Any, right: Any) -> bool:
    if type(left) is not type(right):
        # JSON has a single number type, but boolean must never equal 0 or 1.
        return type(left) in {int, float} and type(right) in {int, float} and left == right
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_same_json(value, right[key]) for key, value in left.items())
    if isinstance(left, list):
        return len(left) == len(right) and all(_same_json(a, b) for a, b in zip(left, right, strict=True))
    return bool(left == right)


_MISSING = object()


def _unique_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("stored_policy_duplicate_member")
        result[key] = value
    return result


def _at_pointer(arguments: dict[str, Any], pointer: str) -> Any:
    value: Any = arguments
    for part in pointer.split("/")[1:] if pointer else ():
        key = part.replace("~1", "/").replace("~0", "~")
        if isinstance(value, dict):
            value = value.get(key, _MISSING)
        elif isinstance(value, list) and key.isascii() and key.isdecimal() and (key == "0" or not key.startswith("0")) and len(key) <= 8:
            index = int(key)
            value = value[index] if index < len(value) else _MISSING
        else:
            return _MISSING
    return value


def check_policy(policy: ArgumentPolicy, arguments: dict[str, Any]) -> None:
    if not policy.enabled:
        return
    for rule in policy.rules:
        value = _at_pointer(arguments, rule.pointer)
        allowed = False
        if value is not _MISSING:
            if isinstance(rule, EqualsRule):
                allowed = _same_json(value, rule.value)
            elif isinstance(rule, AllowedRule):
                allowed = any(_same_json(value, candidate) for candidate in rule.values)
            elif isinstance(rule, NumberRule):
                allowed = (type(value) in {int, float} and (rule.minimum is None or value >= rule.minimum)
                           and (rule.maximum is None or value <= rule.maximum))
            else:
                allowed = isinstance(value, str) and value.startswith(rule.prefix)
        if not allowed:
            raise ArgumentPolicyDenied(policy.revision, rule_id=rule.id, pointer=rule.pointer,
                                       reason="value_missing" if value is _MISSING else "rule_not_satisfied")


class ArgumentPolicyStore:
    def __init__(self, database: SQLiteDatabase):
        self.database = database

    def current(self, tool_id: str, *, connection: sqlite3.Connection | None = None) -> ArgumentPolicy:
        sql = "SELECT enabled,revision,rules_json FROM tool_argument_policies WHERE tool_id=?"
        row = connection.execute(sql, (tool_id,)).fetchone() if connection is not None else self.database.query_one(sql, (tool_id,))
        if row is None:
            return ArgumentPolicy()
        try:
            if row["enabled"] not in (0, 1) or type(row["revision"]) is not int or row["revision"] < 1 or len(row["rules_json"]) > MAX_POLICY_BYTES:
                raise ValueError
            rules = validate_rules(json.loads(row["rules_json"], object_pairs_hook=_unique_members))
            return ArgumentPolicy(bool(row["enabled"]), row["revision"], tuple(rules))
        except (ValueError, TypeError, KeyError, RecursionError, ValidationError):
            revision = row["revision"] if type(row["revision"]) is int else 0
            raise ArgumentPolicyDenied(revision, reason="stored_policy_invalid") from None

    def save(self, tool_id: str, body: PolicyWrite, *, actor_id: str,
             authorize: Any, observability: ObservabilityStore) -> dict[str, Any]:
        rules = json.dumps([rule.model_dump() for rule in body.rules], ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        with self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            authorize(connection)
            row = connection.execute("SELECT revision FROM tool_argument_policies WHERE tool_id=?", (tool_id,)).fetchone()
            revision = row[0] if row else 0
            if revision != body.expected_revision:
                raise PolicyError("argument_policy_revision_conflict", 409)
            revision += 1
            connection.execute("INSERT INTO tool_argument_policies(tool_id,enabled,revision,rules_json) VALUES(?,?,?,?) "
                "ON CONFLICT(tool_id) DO UPDATE SET enabled=excluded.enabled,revision=excluded.revision,rules_json=excluded.rules_json",
                (tool_id, int(body.enabled), revision, rules))
            observability.emit_event("gate.tool.argument_policy.updated", source="authorization", subject_type="tool", subject_id=tool_id,
                payload={"actor_id": actor_id, "revision": revision, "enabled": body.enabled, "rule_count": len(body.rules)}, connection=connection)
        return ArgumentPolicy(body.enabled, revision, tuple(body.rules)).public(tool_id)

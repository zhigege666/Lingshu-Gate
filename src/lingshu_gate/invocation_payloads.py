"""Bounded, redacted invocation snapshots; never serialize arbitrary objects."""
from __future__ import annotations

import json
import math
from http.cookies import CookieError, SimpleCookie
import re
from collections.abc import Iterable, Mapping
from typing import Any

from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.redaction import REDACTED, SENSITIVE_KEY_PATTERN, redact_text

MAX_PAYLOAD_BYTES = 32_768
MAX_DEPTH = 12
MAX_NODES = 1_000
_HEADER = re.compile(r"(?im)\b(authorization|cookie|set-cookie)\s*:\s*[^\r\n]*")


def audit_header_values(headers: Mapping[str, str]) -> tuple[str, ...]:
    """Extract secret values only from the current client's resolved headers."""
    values = list(headers.values())
    for name, value in headers.items():
        if name.lower() not in {"cookie", "set-cookie"}:
            continue
        cookies: SimpleCookie = SimpleCookie()
        try:
            cookies.load(value)
        except CookieError:
            cookies = SimpleCookie()
        values.extend(morsel.value for morsel in cookies.values() if morsel.value)
        # Preserve fail-closed redaction even for a noncanonical header that the
        # downstream server accepts but SimpleCookie rejects.
        for part in value.split(";"):
            _, separator, candidate = part.partition("=")
            if separator and candidate.strip():
                values.append(candidate.strip().strip('"'))
    return audit_secret_values(values)


def audit_secret_values(values: Iterable[str]) -> tuple[str, ...]:
    """Also recognize an authorization scheme's credential without its prefix."""
    result: set[str] = set()
    for value in values:
        if value:
            result.add(value)
            match = re.fullmatch(r"(?i)(?:bearer|basic)\s+(.+)", value)
            if match:
                result.add(match.group(1))
    return tuple(sorted(result, key=len, reverse=True))


def snapshot(value: Any, *, known_secrets: Iterable[str] = ()) -> dict[str, Any]:
    """Produce a bounded JSON envelope, retaining JSON null, false and zero."""
    secrets = audit_secret_values(known_secrets)
    reasons: set[str] = set()
    active: set[int] = set()
    nodes = 0
    budget = MAX_PAYLOAD_BYTES - 1024

    def text(value: str) -> str:
        nonlocal budget
        if len(value) > budget:
            reasons.add("bytes")
        # Include the longest known secret beyond the budget so a boundary cannot
        # leave an unrecognizable credential prefix in the persisted snapshot.
        value = value[:max(0, budget) + max((len(secret) for secret in secrets), default=0)]
        value = redact_text(_HEADER.sub(lambda m: m.group(1) + ": " + REDACTED, value), limit=MAX_PAYLOAD_BYTES, known_secrets=secrets)
        encoded = json.dumps(value, ensure_ascii=True)
        if len(encoded) > budget:
            reasons.add("bytes")
            value = value[:max(0, budget // 6 - 2)]
            encoded = json.dumps(value, ensure_ascii=True)
        budget -= len(encoded)
        return value

    def visit(item: Any, depth: int) -> Any:
        nonlocal nodes, budget
        nodes += 1
        if nodes > MAX_NODES or budget < 64 or depth > MAX_DEPTH:
            reasons.add("nodes" if nodes > MAX_NODES else "depth" if depth > MAX_DEPTH else "bytes")
            return "[TRUNCATED]"
        budget -= 16
        if item is None or type(item) in (bool, int):
            if type(item) is int and item.bit_length() > 256:
                reasons.add("unsupported_number")
                return "[UNSUPPORTED]"
            return item
        if type(item) is float:
            if math.isfinite(item):
                return item
            reasons.add("unsupported_number")
            return "[UNSUPPORTED]"
        if type(item) is str:
            return text(item)
        if type(item) not in (dict, list, tuple):
            reasons.add("unsupported_type")
            return "[UNSUPPORTED]"
        if id(item) in active:
            reasons.add("cycle")
            return "[CYCLE]"
        active.add(id(item))
        try:
            if type(item) is dict:
                result: dict[str, Any] = {}
                for key, child in item.items():
                    if nodes >= MAX_NODES or budget < 128:
                        reasons.add("nodes" if nodes >= MAX_NODES else "bytes")
                        break
                    if type(key) is not str:
                        reasons.add("unsupported_key")
                        continue
                    safe_key = text(key)
                    result[safe_key] = REDACTED if SENSITIVE_KEY_PATTERN.search(key) else visit(child, depth + 1)
                return result
            values = []
            for child in item:
                if nodes >= MAX_NODES or budget < 64:
                    reasons.add("nodes" if nodes >= MAX_NODES else "bytes")
                    break
                values.append(visit(child, depth + 1))
            return values
        finally:
            active.remove(id(item))

    try:
        safe = visit(value, 0)
        errors = {"cycle", "unsupported_type", "unsupported_key", "unsupported_number"}
        status = "serialization_error" if reasons & errors else "truncated" if reasons else "recorded"
        envelope = {"status": status, "value": safe, "reasons": sorted(reasons)}
        if len(json.dumps(envelope, ensure_ascii=True).encode()) > MAX_PAYLOAD_BYTES:
            return {"status": "truncated", "reasons": ["bytes"]}
        return envelope
    except Exception:  # noqa: BLE001 - no repr/error text from arbitrary payload objects
        return {"status": "serialization_error", "reasons": ["serialization_failed"]}


def invocation_detail(database: SQLiteDatabase, audit_id: str, *, user_id: str | None) -> dict[str, Any] | None:
    clauses = "a.id = ?" + (" AND a.user_id = ?" if user_id is not None else "")
    args = (audit_id, user_id) if user_id is not None else (audit_id,)
    row = database.query_one(f"""SELECT a.*, p.input_json, p.output_json FROM invocation_audits a
        LEFT JOIN invocation_payloads p ON p.audit_id = a.id AND p.user_id = a.user_id
        WHERE {clauses}""", args)
    if row is None:
        return None
    missing = {"status": "not_invoked" if row["outcome"] == "not_invoked" else "not_recorded"}
    fields = ("id", "correlation_id", "server_id", "tool_id", "required_access", "decision", "outcome", "duration_ms", "created_at")
    return {"audit": {key: row[key] for key in fields},
            "input": json.loads(row["input_json"]) if row["input_json"] else missing,
            "output": json.loads(row["output_json"]) if row["output_json"] else missing,
            "recording_mode": "redacted" if row["input_json"] else "metadata_only"}

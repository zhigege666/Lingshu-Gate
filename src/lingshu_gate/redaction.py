"""Fail-closed helpers for keeping credentials out of logs and diagnostics."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

REDACTED = "[REDACTED]"
SENSITIVE_KEY_PATTERN = re.compile(
    r"(?:password|passwd|secret|token|api[_-]?key|authorization|cookie|credential|private[_-]?key|client[_-]?secret|refresh[_-]?token)",
    re.IGNORECASE,
)
SENSITIVE_FLAG_PATTERN = re.compile(
    r"^--?(?:api[-_]?key|token|secret|password|passwd|credential|client[-_]?secret|refresh[-_]?token)$",
    re.IGNORECASE,
)
SENSITIVE_FLAG_VALUE_PATTERN = re.compile(
    r"^(--?(?:api[-_]?key|token|secret|password|passwd|credential|client[-_]?secret|refresh[-_]?token)(?:=|:)).+$",
    re.IGNORECASE,
)
BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
INLINE_SECRET_PATTERN = re.compile(
    r"(?i)(?<![A-Za-z0-9])"
    r"([A-Za-z0-9_.-]*(?:password|passwd|secret|token|api[_-]?key|authorization|cookie|credential|private[_-]?key|client[_-]?secret|refresh[_-]?token))"
    r"(\s*[:=]\s*)(\"[^\"]*\"|'[^']*'|[^\s,;]+)"
)
HTTP_URL_PATTERN = re.compile(r"(?i)\bhttps?://[^\s\"'<>]+")


def redact_text(value: str, *, known_secrets: Iterable[str] = (), limit: int = 16_000) -> str:
    redacted = value
    for secret in known_secrets:
        if secret:
            redacted = redacted.replace(secret, REDACTED)
    redacted = BEARER_PATTERN.sub(f"Bearer {REDACTED}", redacted)
    redacted = INLINE_SECRET_PATTERN.sub(rf"\1\2{REDACTED}", redacted)
    redacted = HTTP_URL_PATTERN.sub(REDACTED, redacted)
    if len(redacted) > limit:
        return f"{redacted[:limit]}…[TRUNCATED]"
    return redacted


def redact_validation_errors(errors: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep useful validation context without returning rejected input values."""

    safe_errors: list[dict[str, Any]] = []
    for error in errors:
        safe_errors.append(
            {
                "type": str(error.get("type") or "value_error"),
                "loc": [str(item) for item in error.get("loc") or ()],
                "msg": redact_text(str(error.get("msg") or "Validation failed")),
            }
        )
    return safe_errors


def redact_value(value: Any, *, key: str | None = None, known_secrets: Iterable[str] = ()) -> Any:
    if key and SENSITIVE_KEY_PATTERN.search(key):
        return REDACTED
    if isinstance(value, dict):
        return {
            str(item_key): redact_value(item_value, key=str(item_key), known_secrets=known_secrets)
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item, known_secrets=known_secrets) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item, known_secrets=known_secrets) for item in value)
    if isinstance(value, str):
        return redact_text(value, known_secrets=known_secrets)
    return value


def redact_command(command: Iterable[str]) -> list[str]:
    """Return an argv preview with secret flags and Docker env values removed."""

    items = [str(item) for item in command]
    result: list[str] = []
    redact_next = False
    for index, item in enumerate(items):
        if redact_next:
            result.append(REDACTED)
            redact_next = False
            continue
        if SENSITIVE_FLAG_PATTERN.fullmatch(item):
            result.append(item)
            redact_next = index + 1 < len(items)
            continue
        if SENSITIVE_FLAG_VALUE_PATTERN.fullmatch(item):
            result.append(SENSITIVE_FLAG_VALUE_PATTERN.sub(rf"\1{REDACTED}", item))
            continue
        if index > 0 and items[index - 1] in {"-e", "--env"} and "=" in item:
            name, _, _ = item.partition("=")
            result.append(f"{name}={REDACTED}")
            continue
        result.append(redact_text(item))
    return result

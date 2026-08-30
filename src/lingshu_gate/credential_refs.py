"""Credential reference helpers for MCP manifests.

Supported syntax:

    ${credential:credential_id}

The value can be the whole env value or embedded in a larger string. Resolved
values are only used at process launch time and should never be logged.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from lingshu_gate.credential_store import CredentialStore

CREDENTIAL_REF_RE = re.compile(r"\$\{credential:([a-zA-Z0-9_.-]+)\}")


@dataclass
class CredentialRefScan:
    references: dict[str, list[str]] = field(default_factory=dict)
    missing: dict[str, list[str]] = field(default_factory=dict)

    @property
    def has_references(self) -> bool:
        return bool(self.references)

    @property
    def has_missing(self) -> bool:
        return bool(self.missing)


def scan_env_credential_refs(env: dict[str, str], store: CredentialStore) -> CredentialRefScan:
    """Scan env values for credential refs without resolving secret values."""

    result = CredentialRefScan()
    for key, value in env.items():
        refs = extract_credential_refs(str(value))
        for ref in refs:
            result.references.setdefault(ref, []).append(key)
            try:
                store.get_credential(ref)
            except KeyError:
                result.missing.setdefault(ref, []).append(key)
    return result


def extract_credential_refs(value: str) -> list[str]:
    return CREDENTIAL_REF_RE.findall(value or "")


def resolve_env_credential_refs(env: dict[str, str], store: CredentialStore) -> tuple[dict[str, str], dict[str, Any]]:
    """Resolve credential refs in env values.

    Returns a tuple of `(resolved_env, safe_metadata)`. The metadata contains only
    credential ids and env keys, never resolved secret values.
    """

    resolved: dict[str, str] = {}
    used: dict[str, list[str]] = {}
    missing: dict[str, list[str]] = {}

    for key, value in env.items():
        text = str(value)
        refs = extract_credential_refs(text)
        if not refs:
            resolved[key] = text
            continue

        next_value = text
        for ref in refs:
            used.setdefault(ref, []).append(key)
            try:
                secret = store.resolve_value(ref)
            except KeyError:
                missing.setdefault(ref, []).append(key)
                continue
            next_value = next_value.replace(f"${{credential:{ref}}}", secret or "")
        resolved[key] = next_value

    if missing:
        missing_text = ", ".join(f"{ref} -> {', '.join(keys)}" for ref, keys in sorted(missing.items()))
        raise KeyError(f"Missing credential reference(s): {missing_text}")

    return resolved, {"used_credentials": used, "credential_ref_count": sum(len(keys) for keys in used.values())}


def mask_credential_ref_values(env: dict[str, str]) -> dict[str, str]:
    """Return a log-safe env map that keeps credential refs visible but masks plaintext secrets."""

    masked: dict[str, str] = {}
    for key, value in env.items():
        text = str(value)
        if extract_credential_refs(text):
            masked[key] = text
        else:
            masked[key] = "***"
    return masked

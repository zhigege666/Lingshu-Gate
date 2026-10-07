"""Read-only instance resolution seam; actual registry/ACL ids remain authoritative."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class CatalogTarget:
    tool_id: str
    server_id: str
    instance_id: str
    service_id: str | None = None
    group_id: str | None = None


class CatalogTargetResolver(Protocol):
    def resolve(self, tool_ref: str, instance_id: str | None = None) -> CatalogTarget:
        """Resolve to exactly one real tool/instance; never grant access or invoke."""
        ...

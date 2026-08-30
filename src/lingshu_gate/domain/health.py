"""Health probe values independent from FastAPI and infrastructure details."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class ComponentStatus:
    """Read-only status returned by a control-plane port."""

    name: str
    ok: bool
    detail: str
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "detail": self.detail,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ProbeReport:
    """Application-level probe result consumed by HTTP or future CLI adapters."""

    status: str
    service: str
    version: str
    checks: tuple[ComponentStatus, ...] = ()

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "service": self.service,
            "version": self.version,
            "checks": {check.name: check.to_payload() for check in self.checks},
        }

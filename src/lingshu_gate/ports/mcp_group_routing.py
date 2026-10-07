"""Group resolution port shared with the on-demand tool directory."""
from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol

from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.domain.mcp_group_routing import CatalogTarget, GroupToolCall, GroupToolSelection


class McpGroupRouter(Protocol):
    def resolve(self, actor: AuthPrincipal, *, tool_ref: str, instance_id: str) -> CatalogTarget: ...

    def open_session(self, actor: AuthPrincipal, selection: GroupToolSelection) -> dict[str, object]: ...

    def dispatch_guard(self, actor: AuthPrincipal, call: GroupToolCall) -> AbstractContextManager[tuple[AuthPrincipal, CatalogTarget]]:
        """Yield live authority and the exact physical target; never dispatch/retry."""
        ...

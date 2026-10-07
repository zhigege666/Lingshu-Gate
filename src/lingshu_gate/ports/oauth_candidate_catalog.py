"""OAuth browsing shares the incremental index, without owning another directory."""
from __future__ import annotations

import sqlite3
from typing import Any, Protocol

from lingshu_gate.auth import AuthPrincipal


class SharedCatalogIndex(Protocol):
    def synchronize(self) -> int: ...

    def revision_marker(self, connection: sqlite3.Connection) -> tuple[int, int]: ...


class OAuthCandidateCatalogPort(Protocol):
    def synchronize(self) -> int: ...

    def revision_marker(self, connection: sqlite3.Connection, owner: AuthPrincipal) -> tuple[int, int, int]: ...

    def page(self, connection: sqlite3.Connection, owner: AuthPrincipal, scopes: set[str], *,
             query: str, server_id: str, access: str, view: str, after: str, limit: int, grant_scopes: set[str]) -> dict[str, Any]: ...

    def selected(self, connection: sqlite3.Connection, owner: AuthPrincipal, scopes: set[str],
                 ids: list[str]) -> dict[str, dict[str, Any]]: ...

    def resolve(self, connection: sqlite3.Connection, owner: AuthPrincipal, scopes: set[str], *,
                mode: str, server_ids: list[str]) -> list[str]: ...

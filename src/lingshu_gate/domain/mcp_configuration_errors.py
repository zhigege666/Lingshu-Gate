"""Safe failure facts shared by configuration storage and application policy."""

from __future__ import annotations

from typing import Any


class McpConfigPartialError(RuntimeError):
    """The durable file changed but a later management step failed."""

    def __init__(self, server_id: str, config_digest: str | None, *, deleted: bool = False) -> None:
        super().__init__("Configuration changed, but management did not complete; read its current state before retrying")
        self.server_id, self.config_digest, self.deleted = server_id, config_digest, deleted

    def to_payload(self) -> dict[str, Any]:
        return {"code": "mcp_config_partial", "status": "partial", "server_id": self.server_id,
                "config_applied": True, "config_deleted": self.deleted, "config_digest": self.config_digest,
                "requires_reconciliation": True,
                "next_action": "Read the current configuration and HTTP permission; plan recovery using their current revisions."}

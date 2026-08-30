"""Gateway capability policy.

Downstream server capabilities are deliberately not passed through.  Gate
only advertises operations implemented by the gateway itself; this prevents a
client from invoking resources/prompts merely because one downstream happened
to advertise them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def intersect_capabilities(
    offered: dict[str, Any],
    accepted: dict[str, Any],
) -> dict[str, Any]:
    """Return a conservative recursive intersection of capability documents."""

    result: dict[str, Any] = {}
    for key in sorted(offered.keys() & accepted.keys()):
        left = offered[key]
        right = accepted[key]
        if isinstance(left, dict) and isinstance(right, dict):
            # Empty objects are capability markers.  When both peers advertise
            # the marker, the intersection remains present.
            result[key] = intersect_capabilities(left, right) if left and right else {}
        elif isinstance(left, bool) and isinstance(right, bool):
            if left and right:
                result[key] = True
        elif left == right:
            result[key] = left
    return result


@dataclass(frozen=True)
class GatewayCapabilityPolicy:
    """Capabilities implemented by Gate at its public MCP boundary."""

    server_capabilities: dict[str, Any] = field(
        default_factory=lambda: {"tools": {"listChanged": False}}
    )

    def advertised(self) -> dict[str, Any]:
        return {
            key: dict(value) if isinstance(value, dict) else value
            for key, value in self.server_capabilities.items()
        }

    def advertised_for(self, client_capabilities: dict[str, Any]) -> dict[str, Any]:
        """Advertise server features and only mutually supported extensions."""

        advertised = self.advertised()
        if "extensions" not in advertised:
            return advertised
        extensions = self.effective_extensions(client_capabilities)
        if extensions:
            advertised["extensions"] = extensions
        else:
            advertised.pop("extensions", None)
        return advertised

    def effective_extensions(
        self, client_capabilities: dict[str, Any]
    ) -> dict[str, Any]:
        """Intersect only extension capabilities that are meaningful on both sides."""

        server_extensions = self.server_capabilities.get("extensions", {})
        client_extensions = client_capabilities.get("extensions", {})
        if not isinstance(server_extensions, dict) or not isinstance(
            client_extensions, dict
        ):
            return {}
        return intersect_capabilities(server_extensions, client_extensions)

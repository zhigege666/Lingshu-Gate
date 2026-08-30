"""FastAPI control-plane route modules."""

from lingshu_gate.interfaces.control_api.auth_routes import register_auth_routes
from lingshu_gate.interfaces.control_api.credential_routes import (
    register_credential_routes,
)
from lingshu_gate.interfaces.control_api.diagnostics_routes import (
    register_diagnostics_routes,
)
from lingshu_gate.interfaces.control_api.mcp_config_routes import (
    register_mcp_config_routes,
)
from lingshu_gate.interfaces.control_api.mcp_runtime_routes import (
    register_mcp_runtime_routes,
)
from lingshu_gate.interfaces.control_api.meta_routes import register_meta_routes
from lingshu_gate.interfaces.control_api.observability_routes import (
    register_observability_routes,
)
from lingshu_gate.interfaces.control_api.project_routes import register_project_routes
from lingshu_gate.interfaces.control_api.runtime_routes import register_runtime_routes
from lingshu_gate.interfaces.control_api.tool_routes import register_tool_routes

__all__ = [
    "register_auth_routes",
    "register_credential_routes",
    "register_diagnostics_routes",
    "register_mcp_config_routes",
    "register_mcp_runtime_routes",
    "register_meta_routes",
    "register_observability_routes",
    "register_project_routes",
    "register_runtime_routes",
    "register_tool_routes",
]

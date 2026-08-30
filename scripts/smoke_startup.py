"""Minimal startup smoke check."""

from lingshu_gate import __version__
from lingshu_gate.build_deploy import BuildDeployStore
from lingshu_gate.build_deploy_routes import register_build_deploy_routes
from lingshu_gate.build_preflight import run_build_preflight
from lingshu_gate.main import create_app
from lingshu_gate.models import DiagnosticsCheck, DiagnosticsResponse
from lingshu_gate.project_delivery_mcp import (
    PROJECT_DELIVERY_TOOL_DEFINITIONS,
    ProjectDeliveryMcpService,
    register_project_delivery_tools,
)
from lingshu_gate.system_debug import SystemDebugService
from lingshu_gate.mcp_gateway import register_mcp_gateway_route

assert __version__
assert DiagnosticsResponse(ok=True, checks=[DiagnosticsCheck(name="startup", ok=True)]).ok
assert callable(BuildDeployStore)
assert callable(register_build_deploy_routes)
assert callable(run_build_preflight)
assert len(PROJECT_DELIVERY_TOOL_DEFINITIONS) == 14
assert callable(ProjectDeliveryMcpService)
assert callable(register_project_delivery_tools)
assert callable(create_app)
assert callable(SystemDebugService)
assert callable(register_mcp_gateway_route)

print("startup smoke check ok")

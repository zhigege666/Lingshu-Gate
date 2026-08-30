"""Architecture guardrails for the FastAPI composition root."""

from __future__ import annotations

import ast
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from fastapi.routing import APIRoute


MAIN_PATH = Path(__file__).resolve().parents[1] / "src" / "lingshu_gate" / "main.py"
HTTP_DECORATORS = {
    "delete",
    "get",
    "head",
    "options",
    "patch",
    "post",
    "put",
    "trace",
}
EXPECTED_ROUTE_REGISTRATIONS = {
    "register_access_routes",
    "register_auth_routes",
    "register_build_deploy_routes",
    "register_credential_routes",
    "register_diagnostics_routes",
    "register_mcp_config_routes",
    "register_mcp_gateway_route",
    "register_mcp_runtime_routes",
    "register_meta_routes",
    "register_observability_routes",
    "register_project_routes",
    "register_runtime_routes",
    "register_tool_routes",
}
OPERATIONS_PREFIXES = (
    "/v1/logs",
    "/v1/events",
    "/v1/runtime",
    "/v1/diagnostics",
    "/v1/credentials",
    "/v1/mcp/configs",
    "/v1/mcp/servers",
    "/v1/projects",
)


def _main_tree() -> ast.Module:
    return ast.parse(MAIN_PATH.read_text(encoding="utf-8"), filename=str(MAIN_PATH))


def test_main_contains_no_http_endpoint_handlers() -> None:
    """Endpoint decorators belong to interface adapters, not composition."""

    violations: list[tuple[int, str]] = []
    for node in ast.walk(_main_tree()):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            function = decorator.func
            if (
                isinstance(function, ast.Attribute)
                and isinstance(function.value, ast.Name)
                and function.value.id == "app"
                and function.attr in HTTP_DECORATORS
            ):
                violations.append((node.lineno, node.name))
    assert violations == []


def test_main_registers_each_control_api_boundary() -> None:
    """The composition root remains the single route-wiring location."""

    calls = {
        node.func.id
        for node in ast.walk(_main_tree())
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert EXPECTED_ROUTE_REGISTRATIONS <= calls


def test_extracted_routes_preserve_authentication_boundaries() -> None:
    """Operational adapters remain manager-only; tool routes stay authenticated."""

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temporary:
        root = Path(temporary)
        with patch.dict(
            os.environ,
            {
                "LINGSHU_GATE_DATA_DIR": str(root / "data"),
                "LINGSHU_GATE_CONFIG_DIR": str(root / "mcp.d"),
                "LINGSHU_GATE_ALLOWED_ROOT": str(root),
                "LINGSHU_GATE_ADMIN_USERNAME": "composition-admin",
                "LINGSHU_GATE_ADMIN_PASSWORD": "CompositionAdmin123!",
                "LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE": "",
            },
        ):
            from lingshu_gate.main import create_app

            app = create_app()

        operation_routes = 0
        tool_routes = 0
        for route in app.routes:
            if not isinstance(route, APIRoute):
                continue
            dependencies = {
                getattr(dependency.call, "__name__", "")
                for dependency in route.dependant.dependencies
            }
            if route.path.startswith(OPERATIONS_PREFIXES):
                operation_routes += 1
                assert "require_operations_manager" in dependencies, route.path
            if route.path.startswith("/v1/tools") or route.path == "/v1/invoke":
                tool_routes += 1
                assert "authenticate_request" in dependencies, route.path

        assert operation_routes == 37
        assert tool_routes == 4

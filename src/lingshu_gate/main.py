"""Application composition root for Lingshu Gate."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.access_routes import register_access_routes
from lingshu_gate.adapters.control_plane import (
    FileConfigurationSourceAdapter,
    McpRuntimeDriverAdapter,
    SQLiteStateStoreAdapter,
)
from lingshu_gate.application.health import HealthService, StartupState
from lingshu_gate.application.mcp_configuration import McpConfigurationService
from lingshu_gate.auth import AuthStore
from lingshu_gate.build_deploy import BuildDeployStore
from lingshu_gate.build_deploy_routes import register_build_deploy_routes
from lingshu_gate.config import Settings
from lingshu_gate.credential_store import CredentialStore
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.interfaces.control_api import (
    register_auth_routes,
    register_credential_routes,
    register_diagnostics_routes,
    register_mcp_config_routes,
    register_mcp_runtime_routes,
    register_meta_routes,
    register_observability_routes,
    register_project_routes,
    register_runtime_routes,
    register_tool_routes,
)
from lingshu_gate.interfaces.control_api.dependencies import (
    create_operations_manager_dependency,
)
from lingshu_gate.logging import configure_logging, log_event
from lingshu_gate.mcp_config_store import McpConfigStore
from lingshu_gate.mcp_gateway import register_mcp_gateway_route
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.mcp_runtime_state_store import McpRuntimeStateStore
from lingshu_gate.memory_diagnostics import log_memory_snapshot
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.project_delivery_mcp import (
    ProjectDeliveryMcpService,
    register_project_delivery_tools,
)
from lingshu_gate.project_uploads import ProjectUploadStore
from lingshu_gate.registry import ToolRegistry
from lingshu_gate.system_debug import SystemDebugService, register_system_debug_tool
from lingshu_gate.tool_classification_mcp import (
    ToolClassificationMcpService,
    register_tool_classification_tools,
)
from lingshu_gate.tool_file_mcp import ToolFileMcpService, register_tool_file_tools
from lingshu_gate.tool_files import ToolFileStore
from lingshu_gate.user_credential_store import UserCredentialStore

logger = logging.getLogger(__name__)


def create_registry() -> ToolRegistry:
    return ToolRegistry()


def create_app() -> FastAPI:
    """Assemble application services, adapters, lifecycle, and HTTP routes."""

    settings = Settings.from_env()
    configure_logging(settings.log_level)

    registry = create_registry()
    database = SQLiteDatabase(settings.db_url, settings.data_dir)
    access_store = AccessControlStore(database)
    auth_store = AuthStore(settings, database)
    observability_store = ObservabilityStore(database)
    project_upload_store = ProjectUploadStore(database, settings.data_dir)
    tool_file_store = ToolFileStore(database, settings.data_dir)
    user_credential_store = UserCredentialStore(database, settings.data_dir)
    credential_store = CredentialStore(settings.data_dir)
    mcp_config_store = McpConfigStore(settings.config_dir)

    mcp_runtime = McpRuntimeManager(
        settings,
        registry,
        state_store=McpRuntimeStateStore(database),
        user_credential_store=user_credential_store,
        tool_file_store=tool_file_store,
    )
    access_store.attach_mcp_runtime(mcp_runtime)

    tool_classification_service = ToolClassificationMcpService(
        access_store,
        registry,
    )
    register_tool_classification_tools(registry, tool_classification_service)

    build_deploy_store = BuildDeployStore(
        database,
        settings.data_dir,
        project_upload_store,
        mcp_config_store,
        mcp_runtime,
        observability_store,
        runtime_role=settings.runtime_role,
    )
    project_delivery_service = ProjectDeliveryMcpService(
        database,
        settings.data_dir,
        project_upload_store,
        build_deploy_store,
        mcp_config_store,
        mcp_runtime,
        observability_store,
        target_access_checker=access_store.delivery_target_access,
        credential_store=credential_store,
        user_credential_store=user_credential_store,
        tool_classification_reconciler=access_store.reconcile_server_tools,
    )
    register_project_delivery_tools(registry, project_delivery_service)

    tool_file_service = ToolFileMcpService(tool_file_store)
    register_tool_file_tools(registry, tool_file_service)

    system_debug_service = SystemDebugService(
        settings,
        registry,
        mcp_runtime,
        observability_store,
    )
    if settings.system_debug_mcp_enabled:
        register_system_debug_tool(registry, system_debug_service)

    mcp_configuration_service = McpConfigurationService(
        mcp_config_store,
        mcp_runtime,
        user_credential_store,
    )
    startup_state = StartupState()
    health_service = HealthService(
        service_name=settings.service_name,
        version=settings.version,
        startup_state=startup_state,
        state_store=SQLiteStateStoreAdapter(database),
        configuration_source=FileConfigurationSourceAdapter(settings.config_dir),
        runtime_driver=McpRuntimeDriverAdapter(mcp_runtime),
    )

    require_authenticated = auth_store.authenticate_request
    require_operations_manager = create_operations_manager_dependency(
        auth_store,
        access_store,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        startup_failed = False
        startup_state.mark_starting()
        try:
            log_event(
                logger,
                logging.INFO,
                "gate.startup",
                "Lingshu Gate startup",
                service=settings.service_name,
                version=settings.version,
                allowed_root=str(settings.allowed_root),
                config_dir=str(settings.config_dir),
                data_dir=str(settings.data_dir),
                db_type=settings.db_type,
                auth_enabled=settings.auth_enabled,
                log_level=settings.log_level,
            )
            observability_store.emit_event(
                "gate.startup",
                source="system",
                payload={"version": settings.version},
            )
            observability_store.add_log(
                "info",
                "Lingshu Gate startup",
                source="system",
                event_type="gate.startup",
            )
            log_memory_snapshot(
                logger,
                "gate.diagnostics.memory_snapshot_startup_before_mcp",
                "Memory snapshot before MCP startup",
            )
            settings.data_dir.mkdir(parents=True, exist_ok=True)
            mcp_runtime.load_manifests()
            mcp_runtime.start_auto_servers()
            log_event(
                logger,
                logging.INFO,
                "gate.startup_complete",
                "Lingshu Gate startup complete",
                tool_count=len(registry.list_definitions()),
                mcp_server_count=len(mcp_runtime.list_servers().servers),
                auth_initialized=auth_store.has_users(),
            )
            observability_store.emit_event(
                "gate.startup_complete",
                source="system",
                payload={
                    "tool_count": len(registry.list_definitions()),
                    "mcp_server_count": len(mcp_runtime.list_servers().servers),
                },
            )
            log_memory_snapshot(
                logger,
                "gate.diagnostics.memory_snapshot_startup_complete",
                "Memory snapshot after MCP startup",
            )
            startup_state.mark_ready()
            yield
        except BaseException as exc:
            startup_failed = True
            startup_state.mark_failed(exc)
            raise
        finally:
            if not startup_failed:
                startup_state.mark_stopping()
            log_event(
                logger,
                logging.INFO,
                "gate.shutdown",
                "Lingshu Gate shutdown started",
            )
            observability_store.emit_event("gate.shutdown", source="system")
            observability_store.add_log(
                "info",
                "Lingshu Gate shutdown started",
                source="system",
                event_type="gate.shutdown",
            )
            log_memory_snapshot(
                logger,
                "gate.diagnostics.memory_snapshot_shutdown_before_mcp_stop",
                "Memory snapshot before MCP shutdown",
            )
            mcp_runtime.shutdown()
            log_memory_snapshot(
                logger,
                "gate.diagnostics.memory_snapshot_shutdown_complete",
                "Memory snapshot after MCP shutdown",
            )
            log_event(
                logger,
                logging.INFO,
                "gate.shutdown_complete",
                "Lingshu Gate shutdown complete",
            )

    app = FastAPI(
        title="Lingshu Gate",
        description="A self-hosted MCP gateway, tool registry, and runtime control plane.",
        version=settings.version,
        lifespan=lifespan,
    )

    state = app.state
    state.settings = settings
    state.registry = registry
    state.database = database
    state.access_store = access_store
    state.auth_store = auth_store
    state.observability_store = observability_store
    state.project_upload_store = project_upload_store
    state.mcp_runtime = mcp_runtime
    state.mcp_config_store = mcp_config_store
    state.mcp_configuration_service = mcp_configuration_service
    state.credential_store = credential_store
    state.user_credential_store = user_credential_store
    state.tool_classification_service = tool_classification_service
    state.build_deploy_store = build_deploy_store
    state.project_delivery_service = project_delivery_service
    state.system_debug_service = system_debug_service
    state.tool_file_store = tool_file_store
    state.startup_state = startup_state
    state.health_service = health_service

    register_meta_routes(
        app,
        settings=settings,
        auth_store=auth_store,
        health_service=health_service,
    )
    register_auth_routes(
        app,
        settings=settings,
        auth_store=auth_store,
        observability_store=observability_store,
        require_viewer=require_authenticated,
    )
    register_build_deploy_routes(
        app,
        build_deploy_store,
        require_operations_manager,
    )
    register_access_routes(
        app,
        auth_store=auth_store,
        access_store=access_store,
        registry=registry,
        mcp_runtime=mcp_runtime,
        user_credential_store=user_credential_store,
        observability_store=observability_store,
        require_viewer=require_authenticated,
    )
    register_observability_routes(
        app,
        observability_store=observability_store,
        require_operations_manager=require_operations_manager,
    )
    register_runtime_routes(
        app,
        settings=settings,
        observability_store=observability_store,
        require_operations_manager=require_operations_manager,
    )
    register_diagnostics_routes(
        app,
        settings=settings,
        registry=registry,
        mcp_runtime=mcp_runtime,
        observability_store=observability_store,
        require_operations_manager=require_operations_manager,
    )
    register_credential_routes(
        app,
        credential_store=credential_store,
        observability_store=observability_store,
        require_operations_manager=require_operations_manager,
    )
    register_tool_routes(
        app,
        registry=registry,
        access_store=access_store,
        observability_store=observability_store,
        require_authenticated=require_authenticated,
    )
    register_mcp_config_routes(
        app,
        settings=settings,
        auth_store=auth_store,
        mcp_config_store=mcp_config_store,
        configuration_service=mcp_configuration_service,
        observability_store=observability_store,
        require_operations_manager=require_operations_manager,
    )
    register_mcp_runtime_routes(
        app,
        settings=settings,
        mcp_runtime=mcp_runtime,
        observability_store=observability_store,
        require_operations_manager=require_operations_manager,
    )
    register_project_routes(
        app,
        project_upload_store=project_upload_store,
        observability_store=observability_store,
        require_operations_manager=require_operations_manager,
    )
    register_mcp_gateway_route(
        app,
        settings,
        registry,
        access_store,
        require_authenticated,
    )
    return app


app = create_app()


if __name__ == "__main__":
    from lingshu_gate.cli import main

    main()

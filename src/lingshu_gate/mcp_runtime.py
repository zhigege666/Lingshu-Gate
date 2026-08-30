"""MCP runtime manager and registry bridge."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any

from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.endpoint_security import redact_endpoint
from lingshu_gate.logging import log_event
from lingshu_gate.mcp_config_loader import McpConfigLoader
from lingshu_gate.mcp_container import docker_available
from lingshu_gate.mcp_managed_http_client import ManagedHttpMcpClient
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_http_client import StreamableHttpMcpClient
from lingshu_gate.mcp_restart_history import McpRestartHistoryStore
from lingshu_gate.mcp_runtime_state_store import (
    DesiredState,
    McpRuntimeIntent,
    McpRuntimeStateStore,
)
from lingshu_gate.mcp_stdio_client import StdioMcpClient
from lingshu_gate.models import McpServerListResponse, McpServerStatusResponse, ToolDefinition
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.registry import ToolRecord, ToolRegistry
from lingshu_gate.redaction import redact_text
from lingshu_gate.tool_files import ToolFileError, ToolFileStore
from lingshu_gate.user_credential_store import UserCredentialBindingError, UserCredentialStore

logger = logging.getLogger(__name__)
RuntimeLogSink = Callable[[str, str, str | None, str, dict[str, Any]], None]
McpClient = StdioMcpClient | StreamableHttpMcpClient | ManagedHttpMcpClient


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now_plus(seconds: float) -> str:
    return (_now_dt() + timedelta(seconds=seconds)).isoformat()


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


class McpServerState(StrEnum):
    LOADED = "loaded"
    STARTING = "starting"
    RUNNING = "running"
    FAILED = "failed"
    STOPPED = "stopped"
    EXTERNAL = "external"
    UNSUPPORTED = "unsupported"


class McpTargetApplyError(RuntimeError):
    """目标 Manifest 应用或目标级补偿失败。"""

    def __init__(
        self,
        server_id: str,
        message: str,
        *,
        status: str | None = None,
        rollback_status: str | None = None,
    ) -> None:
        super().__init__(message)
        self.server_id = server_id
        self.status = status
        self.rollback_status = rollback_status


class McpManifestDigestConflict(RuntimeError):
    """启动确认的摘要与 Runtime 中实际 Manifest 不一致。"""

    def __init__(self, server_id: str, expected_digest: str, actual_digest: str) -> None:
        super().__init__(f"MCP runtime manifest digest conflict: {server_id}")
        self.server_id = server_id
        self.expected_digest = expected_digest
        self.actual_digest = actual_digest


def _runtime_combination_supported(manifest: McpServerManifest) -> bool:
    if manifest.launch.type == "external":
        return manifest.transport.type == "streamable_http"
    if manifest.launch.type == "managed_process":
        return manifest.transport.type in {"stdio", "streamable_http"}
    if manifest.launch.type == "managed_container":
        return manifest.transport.type == "stdio"
    return False


def _restore_blocked_reason(
    manifest: McpServerManifest,
    runtime_role: str = "local",
    docker_binary: str = "docker",
) -> str | None:
    if not manifest.enabled:
        return "Server is disabled"
    if runtime_role == "core" and manifest.launch.type in {
        "managed_process",
        "managed_container",
    }:
        return (
            "Secure Core cannot execute managed workloads; use an external HTTP MCP, "
            "or the local runtime role"
        )
    if not _runtime_combination_supported(manifest):
        return "Only managed_process + stdio/streamable_http, managed_container + stdio, or external + streamable_http is implemented"
    if manifest.launch.type == "managed_container" and not docker_available(docker_binary):
        return "Configured Docker CLI is unavailable"
    return None


def _allowed_actions(
    state: McpServerState,
    manifest: McpServerManifest,
    desired_state: str,
    runtime_role: str = "local",
    docker_binary: str = "docker",
) -> list[str]:
    if _restore_blocked_reason(manifest, runtime_role, docker_binary):
        return []
    if state == McpServerState.RUNNING:
        return ["restart", "stop"]
    if state == McpServerState.STARTING:
        return ["stop"]
    if state == McpServerState.FAILED and desired_state == "running":
        return ["restart", "stop"]
    return ["start"]


@dataclass
class McpServerRuntime:
    manifest: McpServerManifest
    state: McpServerState = McpServerState.LOADED
    client: McpClient | None = None
    last_error: str | None = None
    tools: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)
    monitor_thread: threading.Thread | None = None
    health_thread: threading.Thread | None = None
    restart_scheduled: bool = False
    restart_count: int = 0
    restart_attempts: int = 0
    last_exit_code: int | None = None
    last_started_at: str | None = None
    last_exited_at: str | None = None
    last_restart_at: str | None = None
    next_restart_at: str | None = None
    consecutive_health_failures: int = 0
    last_health_check_at: str | None = None
    last_health_ok_at: str | None = None
    health_status: str = "unknown"
    desired_intent: McpRuntimeIntent | None = None
    runtime_role: str = "local"
    docker_binary: str = "docker"

    @property
    def pid(self) -> int | None:
        return self.client.pid if self.client else None

    def to_response(self) -> McpServerStatusResponse:
        intent = self.desired_intent or McpRuntimeIntent(self.manifest.id, "running" if self.manifest.auto_start else "stopped", "manifest_default", None)
        blocked_reason = _restore_blocked_reason(
            self.manifest,
            self.runtime_role,
            self.docker_binary,
        )
        effective_should_run = intent.desired_state == "running" and blocked_reason is None
        return McpServerStatusResponse(
            id=self.manifest.id,
            name=self.manifest.name,
            enabled=self.manifest.enabled,
            launch_type=self.manifest.launch.type,
            transport_type=self.manifest.transport.type,
            endpoint=redact_endpoint(self.manifest.transport.endpoint),
            status=self.state.value,
            pid=self.pid,
            tool_count=len(self.tools),
            last_error=redact_text(self.last_error) if self.last_error else None,
            manifest_path=str(self.manifest.manifest_path) if self.manifest.manifest_path else None,
            restart_policy=self.manifest.restart_policy.model_dump(mode="json"),
            restart_count=self.restart_count,
            restart_attempts=self.restart_attempts,
            last_exit_code=self.last_exit_code,
            last_started_at=self.last_started_at,
            last_exited_at=self.last_exited_at,
            last_restart_at=self.last_restart_at,
            next_restart_at=self.next_restart_at,
            consecutive_health_failures=self.consecutive_health_failures,
            last_health_check_at=self.last_health_check_at,
            last_health_ok_at=self.last_health_ok_at,
            health_status=self.health_status,
            desired_state=intent.desired_state,
            desired_state_source=intent.source,
            desired_state_updated_at=intent.updated_at,
            desired_state_revision=intent.revision,
            effective_should_run=effective_should_run,
            restore_blocked_reason=blocked_reason,
            allowed_actions=_allowed_actions(
                self.state,
                self.manifest,
                intent.desired_state,
                self.runtime_role,
                self.docker_binary,
            ),
        )


class McpRuntimeManager:
    """Load, start, discover, and invoke configured MCP servers."""

    def __init__(
        self,
        settings: Settings,
        registry: ToolRegistry,
        log_sink: RuntimeLogSink | None = None,
        state_store: McpRuntimeStateStore | None = None,
        user_credential_store: UserCredentialStore | None = None,
        tool_file_store: ToolFileStore | None = None,
    ) -> None:
        self.settings = settings
        self.registry = registry
        self.log_sink = log_sink
        self.user_credential_store = user_credential_store
        self.tool_file_store = tool_file_store
        self.restart_history = McpRestartHistoryStore(settings.data_dir)
        self._fallback_observability: ObservabilityStore | None = None
        self.state_store = state_store or McpRuntimeStateStore(SQLiteDatabase(settings.db_url, settings.data_dir))
        self._servers: dict[str, McpServerRuntime] = {}
        self.load_errors: list[str] = []
        self._manager_lock = threading.RLock()

    def load_manifests(self) -> None:
        loader = McpConfigLoader(self.settings.config_dir)
        result = loader.load()
        with self._manager_lock:
            self.load_errors = result.errors
            self._servers.clear()
            for manifest in result.manifests:
                state = McpServerState.LOADED if manifest.enabled else McpServerState.STOPPED
                if manifest.launch.type == "external":
                    state = McpServerState.EXTERNAL
                intent = self.state_store.resolve(manifest.id, auto_start=manifest.auto_start)
                self._servers[manifest.id] = McpServerRuntime(
                    manifest=manifest,
                    state=state,
                    desired_intent=intent,
                    runtime_role=self.settings.runtime_role,
                    docker_binary=self.settings.docker_bin,
                )
                log_event(logger, logging.INFO, "gate.mcp.server_registered", "MCP server registered", server_id=manifest.id, launch_type=manifest.launch.type, transport_type=manifest.transport.type, state=state.value, enabled=manifest.enabled, auto_start=manifest.auto_start, restart_policy=manifest.restart_policy.model_dump(mode="json"))
                self._log_runtime(manifest.id, "info", "MCP server registered", "gate.mcp.server_registered", {"launch_type": manifest.launch.type, "transport_type": manifest.transport.type, "state": state.value, "restart_policy": manifest.restart_policy.model_dump(mode="json")})

    def reload_manifests(self, *, server_id_to_start: str | None = None, start: bool = False) -> McpServerStatusResponse | None:
        """Stop current runtimes, rescan config_dir, and optionally start one server."""
        with self._manager_lock:
            log_event(logger, logging.INFO, "gate.mcp.runtime_reload_started", "Reloading MCP runtime manifests", server_id=server_id_to_start, start=start)
            self._stop_all_locked()
            self.load_manifests()
            if server_id_to_start:
                self._set_desired_state_locked(server_id_to_start, "running" if start else "stopped", source="config_apply")
            self.reconcile_desired_states()
            if server_id_to_start:
                response = self.get_server(server_id_to_start)
                log_event(logger, logging.INFO, "gate.mcp.runtime_reload_completed", "MCP runtime reload completed", server_id=server_id_to_start)
                return response
            log_event(logger, logging.INFO, "gate.mcp.runtime_reload_completed", "MCP runtime reload completed", server_count=len(self._servers))
            return None

    def apply_manifest(
        self,
        manifest: McpServerManifest,
        *,
        start: bool,
        source: str = "config_apply",
    ) -> McpServerStatusResponse:
        """只替换目标 Server；启动失败时只恢复该目标的旧运行态。"""

        candidate = McpServerManifest.model_validate(
            manifest.model_dump(mode="json", exclude={"manifest_path"})
        )
        candidate.manifest_path = manifest.manifest_path
        server_id = candidate.id

        with self._manager_lock:
            previous = self._servers.get(server_id)
            previous_manifest = previous.manifest if previous else None
            previous_intent = previous.desired_intent if previous else None
            current: McpServerRuntime | None = None

            try:
                if previous:
                    previous_intent = previous_intent or self.state_store.resolve(
                        server_id,
                        auto_start=previous.manifest.auto_start,
                    )
                    with previous.lock:
                        self._stop_runtime_locked(server_id, previous, clear_error=False)

                desired_state: DesiredState = "running" if start else "stopped"
                candidate_intent = self.state_store.set(
                    server_id,
                    desired_state,
                    source=source,
                )
                current = self._new_runtime(candidate, candidate_intent)
                self._servers[server_id] = current
                log_event(
                    logger,
                    logging.INFO,
                    "gate.mcp.target_apply_started",
                    "Applying one MCP server manifest",
                    server_id=server_id,
                    start=start,
                    previous_present=previous_manifest is not None,
                )
                response = self.start_server(server_id) if start else current.to_response()
                if start and response.status != McpServerState.RUNNING.value:
                    raise McpTargetApplyError(
                        server_id,
                        f"MCP server did not reach running state: {response.status}; "
                        f"error={response.last_error or 'none'}",
                        status=response.status,
                    )
            except Exception as apply_error:
                rollback_response: McpServerStatusResponse | None = None
                rollback_errors: list[str] = []
                target_stop_failed = False
                registered = self._servers.get(server_id)
                if registered is not None:
                    try:
                        with registered.lock:
                            self._stop_runtime_locked(
                                server_id,
                                registered,
                                clear_error=False,
                            )
                    except Exception as exc:  # noqa: BLE001 - 继续恢复目标状态
                        target_stop_failed = True
                        rollback_errors.append(f"stop current target: {exc}")

                if previous_manifest is None:
                    self._servers.pop(server_id, None)
                    try:
                        self.state_store.delete(server_id)
                    except Exception as exc:  # noqa: BLE001 - 合并目标补偿错误
                        rollback_errors.append(f"delete target intent: {exc}")
                else:
                    restored_desired_state = (
                        previous_intent.desired_state
                        if previous_intent is not None
                        else ("running" if previous_manifest.auto_start else "stopped")
                    )
                    try:
                        restored_intent = self.state_store.set(
                            server_id,
                            restored_desired_state,
                            source="apply_rollback",
                        )
                    except Exception as exc:  # noqa: BLE001 - 仍尝试恢复内存运行态
                        rollback_errors.append(f"restore target intent: {exc}")
                        restored_intent = previous_intent or McpRuntimeIntent(
                            server_id=server_id,
                            desired_state=restored_desired_state,
                            source="apply_rollback_fallback",
                            updated_at=None,
                        )

                    if not target_stop_failed:
                        try:
                            restored = self._new_runtime(previous_manifest, restored_intent)
                            self._servers[server_id] = restored
                            rollback_response = (
                                self.start_server(server_id)
                                if restored_desired_state == "running"
                                else restored.to_response()
                            )
                            if (
                                restored_desired_state == "running"
                                and rollback_response.status != McpServerState.RUNNING.value
                            ):
                                raise RuntimeError(
                                    "previous MCP server did not return to running state: "
                                    f"{rollback_response.status}; "
                                    f"error={rollback_response.last_error or 'none'}"
                                )
                        except Exception as exc:  # noqa: BLE001 - 合并目标补偿错误
                            rollback_errors.append(f"restore target runtime: {exc}")

                rollback_status = rollback_response.status if rollback_response else None
                rollback_error = "; ".join(rollback_errors) or None
                log_event(
                    logger,
                    logging.ERROR,
                    "gate.mcp.target_apply_failed",
                    "Applying one MCP server manifest failed",
                    server_id=server_id,
                    error=str(apply_error),
                    rollback_status=rollback_status,
                    rollback_error=rollback_error,
                )
                message = str(apply_error)
                if rollback_error:
                    message = f"{message}; target rollback failed: {rollback_error}"
                raise McpTargetApplyError(
                    server_id,
                    message,
                    status=getattr(apply_error, "status", None),
                    rollback_status=rollback_status,
                ) from apply_error

            log_event(
                logger,
                logging.INFO,
                "gate.mcp.target_apply_completed",
                "One MCP server manifest applied",
                server_id=server_id,
                status=response.status,
                desired_state=response.desired_state,
            )
            return response

    def remove_manifest(self, server_id: str) -> McpServerStatusResponse | None:
        """只移除目标 Runtime 和期望状态，不扫描或重载其他 Manifest。"""

        with self._manager_lock:
            runtime = self._servers.get(server_id)
            response: McpServerStatusResponse | None = None
            if runtime is not None:
                with runtime.lock:
                    self._stop_runtime_locked(server_id, runtime, clear_error=False)
                    response = runtime.to_response()
                self._servers.pop(server_id, None)
            self.state_store.delete(server_id)
            log_event(
                logger,
                logging.INFO,
                "gate.mcp.target_removed",
                "One MCP server runtime removed",
                server_id=server_id,
                runtime_present=runtime is not None,
            )
            return response

    def _new_runtime(
        self,
        manifest: McpServerManifest,
        intent: McpRuntimeIntent,
    ) -> McpServerRuntime:
        state = McpServerState.LOADED if manifest.enabled else McpServerState.STOPPED
        if manifest.launch.type == "external":
            state = McpServerState.EXTERNAL
        return McpServerRuntime(
            manifest=manifest,
            state=state,
            desired_intent=intent,
            runtime_role=self.settings.runtime_role,
            docker_binary=self.settings.docker_bin,
        )

    def start_auto_servers(self) -> None:
        """Reconcile persisted desired state for every configured server."""
        self.reconcile_desired_states()

    def reconcile_desired_states(self) -> None:
        with self._manager_lock:
            for server_id, runtime in list(self._servers.items()):
                with runtime.lock:
                    manifest = runtime.manifest
                    intent = runtime.desired_intent or self.state_store.resolve(server_id, auto_start=manifest.auto_start)
                    runtime.desired_intent = intent
                    if intent.desired_state == "stopped":
                        if runtime.state in {McpServerState.RUNNING, McpServerState.STARTING, McpServerState.FAILED}:
                            self.stop_server(server_id)
                        continue
                    if not manifest.enabled:
                        log_event(logger, logging.INFO, "gate.mcp.server_skipped_disabled", "Skipping disabled MCP server", server_id=server_id)
                        continue
                    blocked_reason = _restore_blocked_reason(
                        manifest,
                        self.settings.runtime_role,
                        self.settings.docker_bin,
                    )
                    if blocked_reason:
                        runtime.state = McpServerState.UNSUPPORTED
                        runtime.last_error = blocked_reason
                        log_event(logger, logging.WARNING, "gate.mcp.server_unsupported", "MCP server is blocked by the runtime role or transport policy", server_id=server_id, launch_type=manifest.launch.type, transport_type=manifest.transport.type, runtime_role=self.settings.runtime_role, reason=blocked_reason)
                        self._log_runtime(server_id, "warning", "MCP server is blocked by the runtime role or transport policy", "gate.mcp.server_unsupported", {"launch_type": manifest.launch.type, "transport_type": manifest.transport.type, "runtime_role": self.settings.runtime_role, "reason": blocked_reason})
                        continue
                    self.start_server(server_id)

    def request_start(self, server_id: str) -> McpServerStatusResponse:
        with self._manager_lock:
            self._set_desired_state_locked(server_id, "running", source="user")
            return self.start_server(server_id)

    def request_start_if_manifest_digest(
        self,
        server_id: str,
        expected_manifest_digest: str,
    ) -> McpServerStatusResponse:
        """在同一 Runtime 锁内校验实际 Manifest 后启动，避免确认窗口竞态。"""

        expected = expected_manifest_digest.lower()
        with self._manager_lock:
            runtime = self._get_runtime(server_id)
            with runtime.lock:
                actual = self._manifest_digest(runtime.manifest)
                if actual != expected:
                    raise McpManifestDigestConflict(server_id, expected, actual)
                self._set_desired_state_locked(server_id, "running", source="user")
                return self.start_server(server_id)

    def request_stop(self, server_id: str) -> McpServerStatusResponse:
        with self._manager_lock:
            self._set_desired_state_locked(server_id, "stopped", source="user")
            return self.stop_server(server_id)

    def request_restart(self, server_id: str) -> McpServerStatusResponse:
        with self._manager_lock:
            self._set_desired_state_locked(server_id, "running", source="user")
            return self.restart_server(server_id)

    def forget_desired_state(self, server_id: str) -> None:
        self.state_store.delete(server_id)

    def _set_desired_state_locked(
        self,
        server_id: str,
        desired_state: DesiredState,
        *,
        source: str,
    ) -> None:
        runtime = self._get_runtime(server_id)
        runtime.desired_intent = self.state_store.set(server_id, desired_state, source=source)

    def start_server(self, server_id: str, *, reset_restart_attempts: bool = True) -> McpServerStatusResponse:
        runtime = self._get_runtime(server_id)
        with runtime.lock:
            manifest = runtime.manifest
            if runtime.state == McpServerState.RUNNING and runtime.client:
                log_event(logger, logging.INFO, "gate.mcp.server_start_skipped_running", "MCP server already running", server_id=server_id, pid=runtime.pid)
                return runtime.to_response()
            if runtime.state == McpServerState.STARTING:
                log_event(logger, logging.INFO, "gate.mcp.server_start_skipped_starting", "MCP server is already starting", server_id=server_id)
                return runtime.to_response()
            if not manifest.enabled:
                runtime.state = McpServerState.STOPPED
                runtime.last_error = "Server is disabled"
                return runtime.to_response()
            if manifest.launch.type == "external":
                return self._connect_external_locked(server_id, runtime)
            if self.settings.runtime_role == "core" and manifest.launch.type in {
                "managed_process",
                "managed_container",
            }:
                runtime.state = McpServerState.UNSUPPORTED
                runtime.last_error = _restore_blocked_reason(
                    manifest,
                    self.settings.runtime_role,
                    self.settings.docker_bin,
                )
                log_event(
                    logger,
                    logging.WARNING,
                    "gate.mcp.server_runtime_role_blocked",
                    "Secure Core refused to execute a managed workload",
                    server_id=server_id,
                    launch_type=manifest.launch.type,
                    runtime_role=self.settings.runtime_role,
                )
                return runtime.to_response()
            if not _runtime_combination_supported(manifest):
                runtime.state = McpServerState.UNSUPPORTED
                runtime.last_error = "Only managed_process + stdio/streamable_http, managed_container + stdio, or external + streamable_http is implemented"
                return runtime.to_response()
            if manifest.launch.type == "managed_container" and not docker_available(
                self.settings.docker_bin
            ):
                runtime.state = McpServerState.FAILED
                runtime.last_error = (
                    "Configured Docker CLI is unavailable; managed_container requires Docker to run"
                )
                log_event(logger, logging.ERROR, "gate.mcp.server_docker_unavailable", "Docker CLI not available for managed_container server", server_id=server_id, image=manifest.launch.image)
                self._log_runtime(server_id, "error", "Docker CLI not available for managed_container server", "gate.mcp.server_docker_unavailable", {"image": manifest.launch.image})
                return runtime.to_response()

            runtime.state = McpServerState.STARTING
            runtime.last_error = None
            runtime.next_restart_at = None
            runtime.restart_scheduled = False
            runtime.health_status = "unknown"
            runtime.consecutive_health_failures = 0
            if reset_restart_attempts:
                runtime.restart_attempts = 0
            log_event(logger, logging.INFO, "gate.mcp.server_starting", "Starting MCP server", server_id=server_id, manifest=manifest.safe_dict())
            self._log_runtime(server_id, "info", "Starting MCP server", "gate.mcp.server_starting", {"manifest": manifest.safe_dict()})
            try:
                client: McpClient
                if manifest.launch.type == "managed_process" and manifest.transport.type == "streamable_http":
                    client = ManagedHttpMcpClient(
                        manifest,
                        self.settings,
                        log_sink=lambda level, message, event_type, payload: self._log_runtime(server_id, level, message, event_type, payload),
                    )
                else:
                    client = StdioMcpClient(
                        manifest,
                        self.settings,
                        log_sink=lambda level, message, event_type, payload: self._log_runtime(server_id, level, message, event_type, payload),
                    )
                runtime.client = client
                client.start()
                runtime.tools = client.list_tools()
                self._register_mcp_tools(runtime)
                runtime.state = McpServerState.RUNNING
                runtime.last_started_at = _now()
                runtime.health_status = "unknown"
                log_event(logger, logging.INFO, "gate.mcp.server_running", "MCP server is running", server_id=server_id, pid=runtime.pid, tool_count=len(runtime.tools), restart_attempts=runtime.restart_attempts)
                self._log_runtime(server_id, "info", "MCP server is running", "gate.mcp.server_running", {"pid": runtime.pid, "tool_count": len(runtime.tools), "restart_attempts": runtime.restart_attempts})
                if client.process is not None:
                    self._start_process_monitor(server_id, runtime, client)
                self._start_health_monitor(server_id, runtime, client)
            except Exception as exc:  # noqa: BLE001 - runtime boundary records and continues
                runtime.state = McpServerState.FAILED
                safe_error = redact_text(
                    str(exc),
                    known_secrets=(manifest.transport.endpoint or "",),
                )
                runtime.last_error = safe_error
                if runtime.client:
                    runtime.client.stop()
                    runtime.client = None
                runtime.tools = []
                self.registry.unregister_by_metadata("server_id", server_id, source="mcp")
                self._log_runtime(server_id, "error", "Failed to start MCP server", "gate.mcp.server_start_failed", {"error": safe_error})
                self._record_recovery_event(server_id, "gate.mcp.server_start_failed", "Failed to start MCP server", {"error": safe_error}, level="error")
                log_event(logger, logging.ERROR, "gate.mcp.server_start_failed", "Failed to start MCP server", server_id=server_id, error=safe_error, exc_info=True)
                self._schedule_restart_locked(server_id, runtime, reason="start_failure", returncode=None)
            return runtime.to_response()

    def _connect_external_locked(self, server_id: str, runtime: McpServerRuntime) -> McpServerStatusResponse:
        """Connect to an external MCP server. Caller must hold runtime.lock."""
        manifest = runtime.manifest
        if manifest.transport.type != "streamable_http":
            runtime.state = McpServerState.EXTERNAL
            runtime.last_error = "Only external + streamable_http transport is implemented"
            log_event(logger, logging.WARNING, "gate.mcp.external_transport_unsupported", "External MCP transport is not implemented yet", server_id=server_id, transport_type=manifest.transport.type)
            self._log_runtime(server_id, "warning", "External MCP transport is not implemented yet", "gate.mcp.external_transport_unsupported", {"transport_type": manifest.transport.type})
            return runtime.to_response()

        runtime.state = McpServerState.STARTING
        runtime.last_error = None
        runtime.health_status = "unknown"
        safe_endpoint = redact_endpoint(manifest.transport.endpoint)
        log_event(logger, logging.INFO, "gate.mcp.external_connecting", "Connecting external MCP server", server_id=server_id, endpoint=safe_endpoint, manifest=manifest.safe_dict())
        self._log_runtime(server_id, "info", "Connecting external MCP server", "gate.mcp.external_connecting", {"endpoint": safe_endpoint})
        try:
            client = StreamableHttpMcpClient(manifest, self.settings, log_sink=lambda level, message, event_type, payload: self._log_runtime(server_id, level, message, event_type, payload))
            runtime.client = client
            client.start()
            runtime.tools = client.list_tools()
            self._register_mcp_tools(runtime)
            runtime.state = McpServerState.RUNNING
            runtime.last_started_at = _now()
            log_event(logger, logging.INFO, "gate.mcp.server_running", "External MCP server is connected", server_id=server_id, endpoint=safe_endpoint, tool_count=len(runtime.tools))
            self._log_runtime(server_id, "info", "External MCP server is connected", "gate.mcp.server_running", {"endpoint": safe_endpoint, "tool_count": len(runtime.tools)})
        except Exception as exc:  # noqa: BLE001 - runtime boundary records and continues
            runtime.state = McpServerState.FAILED
            safe_error = redact_text(
                str(exc),
                known_secrets=(manifest.transport.endpoint or "",),
            )
            runtime.last_error = safe_error
            if runtime.client:
                runtime.client.stop()
                runtime.client = None
            runtime.tools = []
            self.registry.unregister_by_metadata("server_id", server_id, source="mcp")
            log_event(logger, logging.ERROR, "gate.mcp.server_start_failed", "Failed to connect external MCP server", server_id=server_id, endpoint=safe_endpoint, error=safe_error, exc_info=True)
            self._log_runtime(server_id, "error", "Failed to connect external MCP server", "gate.mcp.server_start_failed", {"endpoint": safe_endpoint, "error": safe_error})
        return runtime.to_response()

    def stop_server(self, server_id: str) -> McpServerStatusResponse:
        runtime = self._get_runtime(server_id)
        with runtime.lock:
            self._stop_runtime_locked(server_id, runtime, clear_error=True)
            log_event(logger, logging.INFO, "gate.mcp.server_stopped", "MCP server stopped", server_id=server_id)
            self._log_runtime(server_id, "info", "MCP server stopped", "gate.mcp.server_stopped", {})
            return runtime.to_response()

    def restart_server(self, server_id: str) -> McpServerStatusResponse:
        runtime = self._get_runtime(server_id)
        with runtime.lock:
            self._stop_runtime_locked(server_id, runtime, clear_error=True)
            runtime.restart_attempts = 0
            runtime.next_restart_at = None
            runtime.restart_scheduled = False
            log_event(logger, logging.INFO, "gate.mcp.server_restarting", "Restarting MCP server", server_id=server_id)
            self._log_runtime(server_id, "info", "Restarting MCP server", "gate.mcp.server_restarting", {})
            return self.start_server(server_id)

    def list_servers(self) -> McpServerListResponse:
        with self._manager_lock:
            servers = []
            for runtime in self._servers.values():
                with runtime.lock:
                    servers.append(runtime.to_response())
            load_errors = list(self.load_errors)
        return McpServerListResponse(
            servers=servers,
            load_errors=load_errors,
        )

    def get_server(self, server_id: str) -> McpServerStatusResponse:
        with self._manager_lock:
            runtime = self._get_runtime(server_id)
            with runtime.lock:
                return runtime.to_response()

    def get_manifest_digest(self, server_id: str) -> str:
        """返回 Runtime 当前实际使用的 Manifest 摘要。"""

        with self._manager_lock:
            runtime = self._get_runtime(server_id)
            with runtime.lock:
                return self._manifest_digest(runtime.manifest)

    def list_server_tools(self, server_id: str) -> list[dict[str, Any]]:
        with self._manager_lock:
            runtime = self._get_runtime(server_id)
            with runtime.lock:
                return copy.deepcopy(runtime.tools)

    def list_restart_history(self, server_id: str, *, limit: int = 80) -> list[dict[str, Any]]:
        return self.restart_history.list(server_id, limit=limit)

    def has_server(self, server_id: str) -> bool:
        with self._manager_lock:
            return server_id in self._servers

    def iter_manifests(self) -> dict[str, McpServerManifest]:
        """Return configured manifests keyed by server id for read-only diagnostics."""
        with self._manager_lock:
            manifests: dict[str, McpServerManifest] = {}
            for server_id, runtime in self._servers.items():
                with runtime.lock:
                    manifests[server_id] = runtime.manifest.model_copy(deep=True)
            return manifests

    def shutdown(self) -> None:
        with self._manager_lock:
            self._stop_all_locked()
        log_event(logger, logging.INFO, "gate.mcp.runtime_shutdown", "MCP runtime shutdown completed")

    def _stop_all_locked(self) -> None:
        for server_id, runtime in list(self._servers.items()):
            with runtime.lock:
                self._stop_runtime_locked(server_id, runtime, clear_error=False)

    def _stop_runtime_locked(self, server_id: str, runtime: McpServerRuntime, *, clear_error: bool) -> None:
        self.registry.unregister_by_metadata("server_id", server_id, source="mcp")
        runtime.restart_scheduled = False
        runtime.next_restart_at = None
        runtime.health_status = "unknown"
        if runtime.client:
            runtime.client.stop()
            runtime.client = None
        runtime.state = McpServerState.STOPPED
        runtime.tools = []
        if clear_error:
            runtime.last_error = None
            runtime.restart_attempts = 0
            runtime.consecutive_health_failures = 0

    def _start_process_monitor(self, server_id: str, runtime: McpServerRuntime, client: McpClient) -> None:
        thread = threading.Thread(target=self._monitor_process, args=(server_id, runtime, client), name=f"mcp-monitor-{server_id}", daemon=True)
        runtime.monitor_thread = thread
        thread.start()

    def _start_health_monitor(self, server_id: str, runtime: McpServerRuntime, client: McpClient) -> None:
        policy = runtime.manifest.restart_policy
        health = policy.health_check
        if not policy.enabled or not health.enabled:
            return
        thread = threading.Thread(target=self._health_loop, args=(server_id, runtime, client), name=f"mcp-health-{server_id}", daemon=True)
        runtime.health_thread = thread
        thread.start()

    def _monitor_process(self, server_id: str, runtime: McpServerRuntime, client: McpClient) -> None:
        process = client.process
        if process is None:
            return
        returncode = process.wait()
        with runtime.lock:
            if runtime.client is not client:
                return
            runtime.client = None
            runtime.tools = []
            runtime.last_exit_code = returncode
            runtime.last_exited_at = _now()
            runtime.health_status = "unknown"
            self.registry.unregister_by_metadata("server_id", server_id, source="mcp")
            if runtime.state == McpServerState.STOPPED:
                return
            runtime.state = McpServerState.FAILED
            runtime.last_error = f"MCP process exited unexpectedly: returncode={returncode}"
            self._maybe_reset_restart_attempts_locked(server_id, runtime, reason="stable_runtime_before_exit")
            log_event(logger, logging.ERROR, "gate.mcp.process_exited_unexpectedly", "MCP process exited unexpectedly", server_id=server_id, returncode=returncode)
            self._log_runtime(server_id, "error", "MCP process exited unexpectedly", "gate.mcp.process_exited_unexpectedly", {"returncode": returncode})
            self._record_recovery_event(server_id, "gate.mcp.process_exited_unexpectedly", "MCP process exited unexpectedly", {"returncode": returncode}, level="error")
            self._schedule_restart_locked(server_id, runtime, reason="unexpected_exit", returncode=returncode)

    def _health_loop(self, server_id: str, runtime: McpServerRuntime, client: McpClient) -> None:
        health = runtime.manifest.restart_policy.health_check
        while True:
            if self._sleep_or_cancel(runtime, client, health.interval_seconds):
                return
            with runtime.lock:
                if runtime.client is not client or runtime.state != McpServerState.RUNNING:
                    return
            ok = False
            error: str | None = None
            try:
                if health.method == "tools_list":
                    client.request("tools/list", {}, timeout=int(health.timeout_seconds))
                ok = True
            except Exception as exc:  # noqa: BLE001 - health check boundary
                error = redact_text(
                    str(exc),
                    known_secrets=(runtime.manifest.transport.endpoint or "",),
                )
            client_to_stop: McpClient | None = None
            with runtime.lock:
                if runtime.client is not client or runtime.state != McpServerState.RUNNING:
                    return
                runtime.last_health_check_at = _now()
                if ok:
                    had_failures = runtime.consecutive_health_failures > 0 or runtime.health_status == "failed"
                    runtime.consecutive_health_failures = 0
                    runtime.health_status = "ok"
                    runtime.last_health_ok_at = runtime.last_health_check_at
                    self._maybe_reset_restart_attempts_locked(server_id, runtime, reason="stable_runtime_health_check")
                    if had_failures:
                        log_event(logger, logging.INFO, "gate.mcp.health_check_recovered", "MCP health check recovered", server_id=server_id)
                        self._log_runtime(server_id, "info", "MCP health check recovered", "gate.mcp.health_check_recovered", {})
                        self._record_recovery_event(server_id, "gate.mcp.health_check_recovered", "MCP health check recovered", {}, level="info")
                    continue
                runtime.consecutive_health_failures += 1
                runtime.health_status = "failed"
                failure_payload = {"failure_count": runtime.consecutive_health_failures, "failure_threshold": health.failure_threshold, "error": error}
                log_event(logger, logging.WARNING, "gate.mcp.health_check_failed", "MCP health check failed", server_id=server_id, **failure_payload)
                self._log_runtime(server_id, "warning", "MCP health check failed", "gate.mcp.health_check_failed", failure_payload)
                self._record_recovery_event(server_id, "gate.mcp.health_check_failed", "MCP health check failed", failure_payload, level="warning")
                if runtime.consecutive_health_failures < health.failure_threshold:
                    continue
                runtime.state = McpServerState.FAILED
                runtime.last_error = f"MCP health check failed {runtime.consecutive_health_failures} time(s): {error}"
                runtime.client = None
                runtime.tools = []
                self.registry.unregister_by_metadata("server_id", server_id, source="mcp")
                threshold_payload = {**failure_payload, "reason": "health_check_failed"}
                log_event(logger, logging.ERROR, "gate.mcp.health_check_threshold_exceeded", "MCP health check failure threshold exceeded", server_id=server_id, **threshold_payload)
                self._log_runtime(server_id, "error", "MCP health check failure threshold exceeded", "gate.mcp.health_check_threshold_exceeded", threshold_payload)
                self._record_recovery_event(server_id, "gate.mcp.health_check_threshold_exceeded", "MCP health check failure threshold exceeded", threshold_payload, level="error")
                client_to_stop = client
                self._schedule_restart_locked(server_id, runtime, reason="health_check_failed", returncode=None)
            if client_to_stop:
                client_to_stop.stop()
                return

    def _sleep_or_cancel(self, runtime: McpServerRuntime, client: McpClient, seconds: float) -> bool:
        deadline = time.monotonic() + max(0.0, seconds)
        while True:
            with runtime.lock:
                if runtime.client is not client or runtime.state != McpServerState.RUNNING:
                    return True
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.5, remaining))

    def _schedule_restart_locked(self, server_id: str, runtime: McpServerRuntime, *, reason: str, returncode: int | None) -> None:
        policy = runtime.manifest.restart_policy
        if not policy.enabled or not policy.restart_on_exit or not runtime.manifest.enabled or not runtime.desired_intent or runtime.desired_intent.desired_state != "running":
            return
        if runtime.restart_scheduled:
            return
        if not self._exit_code_allows_restart(server_id, runtime, returncode):
            return
        if runtime.restart_attempts >= policy.max_attempts:
            payload = {"attempts": runtime.restart_attempts, "max_attempts": policy.max_attempts, "reason": reason, "returncode": returncode}
            log_event(logger, logging.WARNING, "gate.mcp.restart_exhausted", "MCP restart attempts exhausted", server_id=server_id, **payload)
            self._log_runtime(server_id, "warning", "MCP restart attempts exhausted", "gate.mcp.restart_exhausted", payload)
            self._record_recovery_event(server_id, "gate.mcp.restart_exhausted", "MCP restart attempts exhausted", payload, level="warning")
            return
        attempt = runtime.restart_attempts + 1
        delay = self._restart_delay_seconds(policy.delay_seconds, policy.backoff_multiplier, policy.max_delay_seconds, attempt)
        runtime.restart_attempts = attempt
        runtime.restart_scheduled = True
        runtime.next_restart_at = _now_plus(delay)
        payload = {"attempt": attempt, "max_attempts": policy.max_attempts, "delay_seconds": delay, "reason": reason, "returncode": returncode}
        log_event(logger, logging.WARNING, "gate.mcp.restart_scheduled", "MCP restart scheduled", server_id=server_id, **payload)
        self._log_runtime(server_id, "warning", "MCP restart scheduled", "gate.mcp.restart_scheduled", payload)
        self._record_recovery_event(server_id, "gate.mcp.restart_scheduled", "MCP restart scheduled", payload, level="warning")
        thread = threading.Thread(target=self._delayed_restart, args=(server_id, attempt, delay), name=f"mcp-restart-{server_id}-{attempt}", daemon=True)
        thread.start()

    def _exit_code_allows_restart(self, server_id: str, runtime: McpServerRuntime, returncode: int | None) -> bool:
        if returncode is None:
            return True
        policy = runtime.manifest.restart_policy
        blocked = returncode in policy.exit_code_blocklist
        not_allowed = bool(policy.exit_code_allowlist) and returncode not in policy.exit_code_allowlist
        if not blocked and not not_allowed:
            return True
        reason = "blocked" if blocked else "not_in_allowlist"
        payload = {"returncode": returncode, "reason": reason, "exit_code_allowlist": policy.exit_code_allowlist, "exit_code_blocklist": policy.exit_code_blocklist}
        log_event(logger, logging.WARNING, "gate.mcp.restart_skipped_exit_code", "MCP restart skipped by exit code policy", server_id=server_id, **payload)
        self._log_runtime(server_id, "warning", "MCP restart skipped by exit code policy", "gate.mcp.restart_skipped_exit_code", payload)
        self._record_recovery_event(server_id, "gate.mcp.restart_skipped_exit_code", "MCP restart skipped by exit code policy", payload, level="warning")
        return False

    def _maybe_reset_restart_attempts_locked(self, server_id: str, runtime: McpServerRuntime, *, reason: str) -> None:
        policy = runtime.manifest.restart_policy
        if not policy.enabled or policy.reset_after_seconds <= 0 or runtime.restart_attempts <= 0:
            return
        started_at = _parse_dt(runtime.last_started_at)
        if not started_at:
            return
        uptime_seconds = (_now_dt() - started_at).total_seconds()
        if uptime_seconds < policy.reset_after_seconds:
            return
        previous_attempts = runtime.restart_attempts
        runtime.restart_attempts = 0
        payload = {"previous_attempts": previous_attempts, "reset_after_seconds": policy.reset_after_seconds, "uptime_seconds": round(uptime_seconds, 3), "reason": reason}
        log_event(logger, logging.INFO, "gate.mcp.restart_attempts_reset", "MCP restart attempts reset after stable runtime", server_id=server_id, **payload)
        self._log_runtime(server_id, "info", "MCP restart attempts reset after stable runtime", "gate.mcp.restart_attempts_reset", payload)
        self._record_recovery_event(server_id, "gate.mcp.restart_attempts_reset", "MCP restart attempts reset after stable runtime", payload, level="info")

    def _delayed_restart(self, server_id: str, attempt: int, delay: float) -> None:
        deadline = time.monotonic() + delay
        while True:
            try:
                runtime = self._get_runtime(server_id)
            except KeyError:
                return
            with runtime.lock:
                if not runtime.restart_scheduled or runtime.state == McpServerState.STOPPED or runtime.client is not None:
                    return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            time.sleep(min(0.5, remaining))
        try:
            runtime = self._get_runtime(server_id)
        except KeyError:
            return
        with runtime.lock:
            if not runtime.restart_scheduled or runtime.state == McpServerState.STOPPED or runtime.client is not None:
                return
            runtime.restart_scheduled = False
            runtime.next_restart_at = None
            runtime.restart_count += 1
            runtime.last_restart_at = _now()
            payload = {"attempt": attempt, "restart_count": runtime.restart_count}
            log_event(logger, logging.WARNING, "gate.mcp.auto_restart", "Auto restarting MCP server", server_id=server_id, **payload)
            self._log_runtime(server_id, "warning", "Auto restarting MCP server", "gate.mcp.auto_restart", payload)
            self._record_recovery_event(server_id, "gate.mcp.auto_restart", "Auto restarting MCP server", payload, level="warning")
        self.start_server(server_id, reset_restart_attempts=False)

    @staticmethod
    def _restart_delay_seconds(delay_seconds: float, backoff_multiplier: float, max_delay_seconds: float, attempt: int) -> float:
        delay = delay_seconds * (backoff_multiplier ** max(attempt - 1, 0))
        if max_delay_seconds > 0:
            delay = min(delay, max_delay_seconds)
        return max(0.0, delay)

    def _register_mcp_tools(self, runtime: McpServerRuntime) -> None:
        manifest = runtime.manifest
        records = self._mcp_tool_records(runtime, runtime.tools, strict=False)
        self.registry.replace_by_metadata(
            "server_id",
            manifest.id,
            records,
            source="mcp",
        )
        log_event(logger, logging.INFO, "gate.mcp.tools_registered", "MCP tools registered into Gate registry", server_id=manifest.id, tool_count=len(records))
        self._log_runtime(manifest.id, "info", "MCP tools registered into Gate registry", "gate.mcp.tools_registered", {"tool_count": len(records)})

    def refresh_server_tools(
        self,
        server_id: str,
        *,
        before_replace: Callable[[list[ToolDefinition]], None] | None = None,
    ) -> dict[str, Any]:
        """重新发现工具；可先执行失败关闭的分类门禁，再原子替换快照。"""

        with self._manager_lock:
            return self._refresh_server_tools_locked(
                server_id,
                before_replace=before_replace,
            )

    def _refresh_server_tools_locked(
        self,
        server_id: str,
        *,
        before_replace: Callable[[list[ToolDefinition]], None] | None = None,
    ) -> dict[str, Any]:
        """Refresh tools while the caller holds the manager lock."""

        runtime = self._get_runtime(server_id)
        with runtime.lock:
            if runtime.state != McpServerState.RUNNING or not runtime.client:
                raise RuntimeError(
                    f"MCP server is not running: {server_id} ({runtime.state.value})"
                )
            discovered = runtime.client.list_tools()
            records = self._mcp_tool_records(runtime, discovered, strict=True)
            snapshot_payload = [
                {
                    "id": record.definition.id,
                    "name": record.definition.name,
                    "description": record.definition.description,
                    "input_schema": record.definition.input_schema,
                    "annotations": record.definition.metadata.get("annotations", {}),
                }
                for record in records
            ]
            snapshot_digest = hashlib.sha256(
                json.dumps(
                    snapshot_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            definitions = [record.definition for record in records]
            if before_replace is not None:
                # 分类门禁先于 Registry 提交：门禁失败最多收紧旧分类，不能让新工具
                # 暂时沿用旧发布结论，也不会暴露半完成的新 Registry 快照。
                before_replace(definitions)
            replace_result = self.registry.replace_by_metadata(
                "server_id",
                server_id,
                records,
                source="mcp",
            )
            runtime.tools = discovered
            payload = {
                "server_id": server_id,
                "tool_count": len(records),
                "tool_snapshot_digest": snapshot_digest,
                **replace_result,
            }
            log_event(
                logger,
                logging.INFO,
                "gate.mcp.tools_refreshed",
                "MCP tools refreshed",
                **payload,
            )
            self._log_runtime(
                server_id,
                "info",
                "MCP tools refreshed",
                "gate.mcp.tools_refreshed",
                payload,
            )
            return {
                **payload,
                "definitions": definitions,
            }

    def _mcp_tool_records(
        self,
        runtime: McpServerRuntime,
        tools: list[dict[str, Any]],
        *,
        strict: bool,
    ) -> list[ToolRecord]:
        manifest = runtime.manifest
        records: list[ToolRecord] = []
        seen_names: set[str] = set()
        for tool in tools:
            if not isinstance(tool, dict):
                if strict:
                    raise ValueError("MCP tools/list returned a non-object tool")
                continue
            original_name = tool.get("name")
            if not isinstance(original_name, str) or not original_name.strip():
                if strict:
                    raise ValueError("MCP tools/list returned a tool without a valid name")
                log_event(logger, logging.WARNING, "gate.mcp.tool_skipped_missing_name", "Skipping MCP tool without name", server_id=manifest.id, tool=tool)
                continue
            normalized_name: str = original_name.strip()
            if normalized_name in seen_names:
                if strict:
                    raise ValueError(f"MCP tools/list returned duplicate tool name: {normalized_name}")
                records = [
                    record
                    for record in records
                    if record.definition.metadata.get("original_tool_name") != normalized_name
                ]
            seen_names.add(normalized_name)
            tool_id = f"mcp.{manifest.id}.{normalized_name}"
            input_schema = tool.get("inputSchema")
            if input_schema is None:
                input_schema = {"type": "object", "properties": {}}
            if not isinstance(input_schema, dict):
                if strict:
                    raise ValueError(
                        f"MCP tool inputSchema must be an object: {normalized_name}"
                    )
                input_schema = {"type": "object", "properties": {}}
            annotations = tool.get("annotations", {})
            if not isinstance(annotations, dict):
                if strict:
                    raise ValueError(
                        f"MCP tool annotations must be an object: {normalized_name}"
                    )
                annotations = {}
            definition = ToolDefinition(
                id=tool_id,
                name=tool.get("title") or normalized_name,
                description=tool.get("description") or f"MCP tool {normalized_name} from {manifest.id}",
                permission=self._permission_from_manifest(manifest),
                input_schema=input_schema,
                source="mcp",
                metadata={"server_id": manifest.id, "launch_type": manifest.launch.type, "transport_type": manifest.transport.type, "original_tool_name": normalized_name, "annotations": annotations},
            )

            def handler(arguments: dict[str, Any], *, server_id: str = manifest.id, tool_name: str = normalized_name) -> dict[str, Any]:
                return self.invoke_mcp_tool(server_id, tool_name, arguments)

            records.append(ToolRecord(definition=definition, handler=handler))
        return records

    def invoke_mcp_tool(self, server_id: str, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        runtime = self._get_runtime(server_id)
        with runtime.lock:
            if runtime.state != McpServerState.RUNNING or not runtime.client:
                raise RuntimeError(f"MCP server is not running: {server_id} ({runtime.state.value})")
            return runtime.client.call_tool(tool_name, arguments)

    def list_user_credential_slots(self) -> list[dict[str, Any]]:
        """返回 Manifest 中不含秘密的用户凭据槽位。"""

        slots: list[dict[str, Any]] = []
        with self._manager_lock:
            for runtime in self._servers.values():
                with runtime.lock:
                    for slot in runtime.manifest.user_credentials:
                        slots.append(
                            {
                                "server_id": runtime.manifest.id,
                                "server_name": runtime.manifest.display_name,
                                "transport_type": runtime.manifest.transport.type,
                                **slot.model_dump(mode="json"),
                            }
                        )
        return slots

    def get_user_credential_slot(self, server_id: str, slot_id: str) -> dict[str, Any]:
        with self._manager_lock:
            runtime = self._get_runtime(server_id)
            with runtime.lock:
                for slot in runtime.manifest.user_credentials:
                    if slot.id == slot_id:
                        return {
                            "server_id": runtime.manifest.id,
                            "server_name": runtime.manifest.display_name,
                            "transport_type": runtime.manifest.transport.type,
                            **slot.model_dump(mode="json"),
                        }
        raise KeyError(f"user credential slot not found: {server_id}/{slot_id}")

    def invoke_mcp_tool_for_user(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        user_id: str,
    ) -> dict[str, Any]:
        """解析用户文件引用，并在需要时使用当前用户自己的下游凭据。"""

        runtime = self._get_runtime(server_id)
        with runtime.lock:
            if runtime.state != McpServerState.RUNNING or not runtime.client:
                raise RuntimeError(f"MCP server is not running: {server_id} ({runtime.state.value})")
            manifest = runtime.manifest
            slots = list(manifest.user_credentials)
        prepared_arguments = arguments
        if "fileRef" in arguments:
            if not self.tool_file_store:
                raise RuntimeError("fileRef is not enabled on this Gate instance")
            if manifest.launch.type != "managed_process":
                raise RuntimeError(
                    "fileRef currently requires a managed_process target that shares the Gate filesystem; "
                    f"target {server_id} uses {manifest.launch.type}/{manifest.transport.type}"
                )
            try:
                prepared_arguments = self.tool_file_store.prepare_tool_arguments(
                    actor_id=user_id,
                    arguments=arguments,
                )
            except ToolFileError as exc:
                raise RuntimeError(f"fileRef resolution failed ({exc.code}): {exc}") from exc
        if not slots:
            return self.invoke_mcp_tool(server_id, tool_name, prepared_arguments)
        if manifest.launch.type != "external" or manifest.transport.type != "streamable_http":
            raise UserCredentialBindingError(
                f"user credentials are not supported for {manifest.launch.type}/{manifest.transport.type}: {server_id}"
            )
        if not self.user_credential_store:
            raise UserCredentialBindingError("user credential store is not configured")

        values, missing = self.user_credential_store.resolve_slots(
            user_id=user_id,
            server_id=server_id,
            slots=slots,
        )
        if missing:
            raise UserCredentialBindingError(
                f"required user credential is missing: {server_id}/" + ", ".join(sorted(missing))
            )

        call_manifest = manifest.model_copy(deep=True)
        headers = dict(call_manifest.transport.headers)
        used_slot_ids: list[str] = []
        for slot in slots:
            value = values.get(slot.id)
            if value is None:
                continue
            headers[slot.injection.name] = slot.injection.template.replace("{value}", value)
            used_slot_ids.append(slot.id)
        call_manifest.transport.headers = headers

        client = StreamableHttpMcpClient(
            call_manifest,
            self.settings,
            log_sink=lambda level, message, event_type, payload: self._log_runtime(
                server_id, level, message, event_type, payload
            ),
            redaction_values=values.values(),
        )
        session_started = False
        try:
            client.start()
            session_started = True
            return client.call_tool(tool_name, prepared_arguments)
        finally:
            try:
                client.stop()
            finally:
                if session_started and used_slot_ids:
                    self.user_credential_store.mark_used(
                        user_id=user_id,
                        server_id=server_id,
                        slot_ids=used_slot_ids,
                    )

    def _get_runtime(self, server_id: str) -> McpServerRuntime:
        try:
            return self._servers[server_id]
        except KeyError as exc:
            raise KeyError(f"MCP server not found: {server_id}") from exc

    @staticmethod
    def _manifest_digest(manifest: McpServerManifest) -> str:
        """与项目交付 MCP 的配置摘要保持同一序列化口径。"""

        payload = manifest.model_dump(mode="json", exclude={"manifest_path"})
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _permission_from_manifest(self, manifest: McpServerManifest) -> str:
        if not manifest.permissions:
            return "mcp"
        return ",".join(f"{key}:{value}" for key, value in sorted(manifest.permissions.items()))

    def _record_recovery_event(self, server_id: str, event_type: str, message: str, payload: dict[str, Any], *, level: str) -> None:
        try:
            self.restart_history.append(server_id, event_type, message, payload, level=level)
        except Exception:  # noqa: BLE001 - history must not break recovery
            logger.exception("Failed to persist MCP restart history", extra={"server_id": server_id, "event_type": event_type})

    def _log_runtime(self, server_id: str, level: str, message: str, event_type: str | None, payload: dict[str, Any]) -> None:
        try:
            if self.log_sink:
                self.log_sink(level, message, server_id, event_type or "gate.runtime.log", payload)
                return
            if self._fallback_observability is None:
                self._fallback_observability = ObservabilityStore(SQLiteDatabase(self.settings.db_url, self.settings.data_dir))
            self._fallback_observability.add_log(level, message, source="runtime", server_id=server_id, event_type=event_type or "gate.runtime.log", payload=payload)
        except Exception:  # noqa: BLE001 - logging must not break runtime
            logger.exception("Failed to write runtime log", extra={"server_id": server_id, "event_type": event_type})

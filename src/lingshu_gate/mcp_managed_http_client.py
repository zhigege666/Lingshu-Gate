"""Managed process plus Streamable HTTP MCP client."""

from __future__ import annotations

import logging
import subprocess
import threading
import time
from collections.abc import Callable
from math import ceil
from pathlib import Path
from typing import Any

from lingshu_gate.config import Settings
from lingshu_gate.credential_refs import resolve_env_credential_refs
from lingshu_gate.credential_store import CredentialStore
from lingshu_gate.endpoint_security import redact_endpoint
from lingshu_gate.logging import log_event
from lingshu_gate.mcp_http_client import StreamableHttpMcpClient
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_runtime_cache import McpRuntimeCacheResolver
from lingshu_gate.redaction import redact_command, redact_text, redact_value
from lingshu_gate.subprocess_environment import build_subprocess_environment

logger = logging.getLogger(__name__)
LogSink = Callable[[str, str, str, dict[str, Any]], None]


class ManagedHttpMcpClient:
    """Own one foreground child process and connect to its HTTP MCP endpoint."""

    def __init__(
        self,
        manifest: McpServerManifest,
        settings: Settings,
        log_sink: LogSink | None = None,
    ) -> None:
        self.manifest = manifest
        self.settings = settings
        self.log_sink = log_sink
        self.process: subprocess.Popen[str] | None = None
        self.last_stdout: list[str] = []
        self.last_stderr: list[str] = []
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._http_client: StreamableHttpMcpClient | None = None
        self.runtime_cache = McpRuntimeCacheResolver(settings.data_dir)
        self.credential_store = CredentialStore(settings.data_dir)
        self._redaction_values: tuple[str, ...] = tuple(
            value for value in (manifest.transport.endpoint,) if value
        )

    @property
    def pid(self) -> int | None:
        return self.process.pid if self.process else None

    @property
    def initialized(self) -> bool:
        return bool(self._http_client and self._http_client.initialized)

    @property
    def session_id(self) -> str | None:
        return self._http_client.session_id if self._http_client else None

    @property
    def server_info(self) -> dict[str, Any]:
        return self._http_client.server_info if self._http_client else {}

    @property
    def server_capabilities(self) -> dict[str, Any]:
        return self._http_client.server_capabilities if self._http_client else {}

    def start(self) -> None:
        self._start_process()
        startup_timeout = max(
            1,
            self.manifest.timeout_seconds
            or self.settings.mcp_startup_timeout_seconds,
        )
        deadline = time.monotonic() + startup_timeout
        last_error: Exception | None = None
        safe_endpoint = redact_endpoint(self.manifest.transport.endpoint)
        log_event(
            logger,
            logging.INFO,
            "gate.mcp.managed_http_wait_started",
            "Waiting for managed HTTP MCP endpoint",
            server_id=self.manifest.id,
            endpoint=safe_endpoint,
            timeout_seconds=startup_timeout,
            pid=self.pid,
        )
        self._store_log(
            "info",
            "Waiting for managed HTTP MCP endpoint",
            "gate.mcp.managed_http_wait_started",
            {
                "endpoint": safe_endpoint,
                "timeout_seconds": startup_timeout,
                "pid": self.pid,
            },
        )

        while time.monotonic() < deadline:
            returncode = self.process.poll() if self.process else None
            if returncode is not None:
                error = RuntimeError(
                    "Managed HTTP MCP process exited before initialization: "
                    f"returncode={returncode}; recent_stderr={self.last_stderr[-5:]}; "
                    f"recent_stdout={self.last_stdout[-5:]}"
                )
                self.stop()
                raise error
            remaining = max(0.0, deadline - time.monotonic())
            attempt_manifest = self.manifest.model_copy(deep=True)
            attempt_manifest.timeout_seconds = max(1, min(2, ceil(remaining)))
            client = StreamableHttpMcpClient(
                attempt_manifest,
                self.settings,
                log_sink=self.log_sink,
                redaction_values=self._redaction_values,
            )
            self._http_client = client
            try:
                client.start()
                # 初始化重试使用短超时；成功后恢复 Manifest 的正常请求超时。
                attempt_manifest.timeout_seconds = self.manifest.timeout_seconds
                if self.process and self.process.poll() is not None:
                    raise RuntimeError(
                        "Managed HTTP MCP process exited immediately after initialization: "
                        f"returncode={self.process.returncode}"
                    )
                log_event(
                    logger,
                    logging.INFO,
                    "gate.mcp.managed_http_ready",
                    "Managed HTTP MCP endpoint is ready",
                    server_id=self.manifest.id,
                    endpoint=safe_endpoint,
                    pid=self.pid,
                )
                self._store_log(
                    "info",
                    "Managed HTTP MCP endpoint is ready",
                    "gate.mcp.managed_http_ready",
                    {"endpoint": safe_endpoint, "pid": self.pid},
                )
                return
            except Exception as exc:  # noqa: BLE001 - retry until startup deadline
                last_error = exc
                try:
                    client.stop()
                except Exception:  # noqa: BLE001 - best-effort cleanup between attempts
                    logger.debug("Failed to close managed HTTP startup attempt", exc_info=True)
                self._http_client = None
                if self.process and self.process.poll() is not None:
                    break
                time.sleep(min(0.25, max(0.0, deadline - time.monotonic())))

        error_text = (
            redact_text(str(last_error), known_secrets=self._redaction_values)
            if last_error
            else "endpoint did not become ready"
        )
        self.stop()
        raise TimeoutError(
            f"Managed HTTP MCP startup timed out after {startup_timeout}s: {error_text}"
        )

    def list_tools(self) -> list[dict[str, Any]]:
        return self._require_http_client().list_tools()

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self._require_http_client().call_tool(name, arguments)

    def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        return self._require_http_client().request(method, params, timeout=timeout)

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._require_http_client().notify(method, params)

    def stop(self) -> None:
        # HTTP Session 属于当前子进程，必须先断开协议会话，再回收进程。
        if self._http_client:
            try:
                self._http_client.stop()
            except Exception:  # noqa: BLE001 - process cleanup must still continue
                logger.debug("Failed to close managed HTTP MCP session", exc_info=True)
            finally:
                self._http_client = None

        process = self.process
        if not process:
            return
        log_event(
            logger,
            logging.INFO,
            "gate.mcp.managed_http_process_stopping",
            "Stopping managed HTTP MCP process",
            server_id=self.manifest.id,
            pid=process.pid,
        )
        self._store_log(
            "info",
            "Stopping managed HTTP MCP process",
            "gate.mcp.managed_http_process_stopping",
            {"pid": process.pid},
        )
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log_event(
                    logger,
                    logging.WARNING,
                    "gate.mcp.managed_http_process_killed",
                    "Killing managed HTTP MCP process after timeout",
                    server_id=self.manifest.id,
                    pid=process.pid,
                )
                process.kill()
                process.wait(timeout=5)
        self.process = None
        self._store_log(
            "info",
            "Managed HTTP MCP process stopped",
            "gate.mcp.managed_http_process_stopped",
            {"returncode": process.returncode},
        )

    def _start_process(self) -> None:
        if self.process and self.process.poll() is None:
            return
        launch = self.manifest.launch
        if launch.type != "managed_process" or not launch.command:
            raise ValueError(
                "ManagedHttpMcpClient requires launch.type=managed_process and launch.command"
            )

        env = build_subprocess_environment()
        cache_plan = self.runtime_cache.resolve(self.manifest)
        if cache_plan.enabled:
            self.runtime_cache.prepare(cache_plan)
            env.update(cache_plan.env)
        resolved_env, credential_metadata = resolve_env_credential_refs(
            launch.env,
            self.credential_store,
        )
        env.update(resolved_env)
        self._redaction_values = tuple(
            sorted(
                {
                    *self._redaction_values,
                    *(value for value in resolved_env.values() if value),
                },
                key=len,
                reverse=True,
            )
        )
        command = cache_plan.command or [launch.command, *launch.args]
        safe_command = redact_command(command)
        cwd = Path(launch.cwd).resolve() if launch.cwd else None
        log_event(
            logger,
            logging.INFO,
            "gate.mcp.managed_http_process_started",
            "Starting managed HTTP MCP process",
            server_id=self.manifest.id,
            command=safe_command,
            cwd=str(cwd) if cwd else None,
            runtime_cache=cache_plan.safe_dict() if cache_plan.enabled else None,
        )
        if credential_metadata.get("credential_ref_count"):
            self._store_log(
                "info",
                "Credential refs resolved for managed HTTP MCP env",
                "gate.mcp.credentials_resolved",
                credential_metadata,
            )
        self.process = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        assert self.process.stdout is not None and self.process.stderr is not None
        self._stdout_thread = threading.Thread(
            target=self._read_stream,
            args=(self.process.stdout, "stdout"),
            name=f"mcp-managed-http-stdout-{self.manifest.id}",
            daemon=True,
        )
        self._stderr_thread = threading.Thread(
            target=self._read_stream,
            args=(self.process.stderr, "stderr"),
            name=f"mcp-managed-http-stderr-{self.manifest.id}",
            daemon=True,
        )
        self._stdout_thread.start()
        self._stderr_thread.start()
        self._store_log(
            "info",
            "Managed HTTP MCP process started",
            "gate.mcp.managed_http_process_ready",
            {"pid": self.pid},
        )

    def _read_stream(self, stream: Any, stream_name: str) -> None:
        target = self.last_stdout if stream_name == "stdout" else self.last_stderr
        for line in stream:
            raw = line.rstrip("\r\n")
            if not raw:
                continue
            safe_raw = (
                redact_text(raw, known_secrets=self._redaction_values, limit=4000)
                if self.settings.mcp_log_payloads
                else f"[MCP managed HTTP {stream_name} payload suppressed]"
            )
            target.append(safe_raw)
            del target[:-100]
            self._store_log(
                "info" if stream_name == "stdout" else "warning",
                f"MCP managed HTTP {stream_name} output",
                f"gate.mcp.managed_http_{stream_name}",
                {stream_name: safe_raw, "stream": stream_name},
            )

    def _require_http_client(self) -> StreamableHttpMcpClient:
        if not self._http_client or not self._http_client.initialized:
            raise RuntimeError("Managed HTTP MCP session is not initialized")
        return self._http_client

    def _store_log(
        self,
        level: str,
        message: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        if not self.log_sink:
            return
        try:
            self.log_sink(
                level,
                redact_text(message, known_secrets=self._redaction_values),
                event_type,
                redact_value(payload, known_secrets=self._redaction_values),
            )
        except Exception:  # noqa: BLE001 - logging must not break runtime threads
            logger.debug("Failed to write managed HTTP MCP log", exc_info=True)

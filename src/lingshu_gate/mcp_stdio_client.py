"""Minimal synchronous stdio MCP client.

This intentionally avoids depending on a specific MCP SDK runtime. It implements
the current protocol discovery, tools/list, and tools/call operations over
newline-delimited JSON-RPC messages.
"""

from __future__ import annotations

import json
import logging
import queue
import subprocess
import threading
import time
from collections.abc import Callable, Iterable
from itertools import count
from pathlib import Path
from typing import Any

from lingshu_gate.config import Settings
from lingshu_gate.credential_refs import resolve_env_credential_refs
from lingshu_gate.credential_store import CredentialStore
from lingshu_gate.logging import log_event
from lingshu_gate.mcp_container import build_docker_command, resolve_docker_binary
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_runtime_cache import McpRuntimeCacheResolver
from lingshu_gate.protocol.request import build_request_params
from lingshu_gate.protocol.version import (
    MCP_PROTOCOL_VERSION,
    require_current_protocol_version,
)
from lingshu_gate.redaction import redact_command, redact_text, redact_value
from lingshu_gate.subprocess_environment import (
    build_docker_subprocess_environment,
    build_subprocess_environment,
)

logger = logging.getLogger(__name__)

LogSink = Callable[[str, str, str, dict[str, Any]], None]

MAX_STDIO_MESSAGE_BYTES = 8 * 1024 * 1024
MAX_TOOL_LIST_PAGES = 100
MAX_DISCOVERED_TOOLS = 10_000


class McpProtocolError(RuntimeError):
    """Raised when an MCP server returns an invalid or error response."""


class StdioMcpClient:
    """Manage one stdio MCP server process and JSON-RPC session."""

    def __init__(self, manifest: McpServerManifest, settings: Settings, log_sink: LogSink | None = None) -> None:
        self.manifest = manifest
        self.settings = settings
        self.protocol_version = require_current_protocol_version(
            manifest.transport.protocol_version or MCP_PROTOCOL_VERSION
        )
        self.log_sink = log_sink
        self.process: subprocess.Popen[str] | None = None
        self._responses: dict[int, queue.Queue[dict[str, Any]]] = {}
        self._ids = count(1)
        self._stdout_thread: threading.Thread | None = None
        self._stderr_thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.initialized = False
        self.server_info: dict[str, Any] = {}
        self.server_capabilities: dict[str, Any] = {}
        self.last_stdout: list[str] = []
        self.last_stderr: list[str] = []
        self.runtime_cache = McpRuntimeCacheResolver(settings.data_dir)
        self.credential_store = CredentialStore(settings.data_dir)
        self._redaction_values: tuple[str, ...] = ()
        self._fatal_protocol_error: str | None = None

    @property
    def pid(self) -> int | None:
        return self.process.pid if self.process else None

    def start(self) -> None:
        if self.process and self.process.poll() is None:
            log_event(logger, logging.INFO, "gate.mcp.stdio_already_running", "MCP stdio process already running", server_id=self.manifest.id, pid=self.pid)
            return
        self._fatal_protocol_error = None
        launch = self.manifest.launch
        env = build_subprocess_environment()
        cwd: Path | None = None
        runtime_cache_payload: dict[str, Any] | None = None
        if launch.type == "managed_container":
            resolved_environment, credential_metadata = resolve_env_credential_refs(launch.environment, self.credential_store)
            env = build_docker_subprocess_environment(resolved_environment)
            self._redaction_values = tuple(resolved_environment.values())
            command = build_docker_command(
                self.manifest,
                resolved_environment,
                docker_binary=resolve_docker_binary(self.settings.docker_bin),
                allowed_root=self.settings.allowed_root,
            )
            if credential_metadata.get("credential_ref_count"):
                log_event(logger, logging.INFO, "gate.mcp.credentials_resolved", "Credential refs resolved for MCP container env", server_id=self.manifest.id, **credential_metadata)
                self._store_log("info", "Credential refs resolved for MCP container env", "gate.mcp.credentials_resolved", credential_metadata)
        else:
            if not launch.command:
                raise ValueError("launch.command is required")
            cache_plan = self.runtime_cache.resolve(self.manifest)
            if cache_plan.enabled:
                self.runtime_cache.prepare(cache_plan)
                log_event(logger, logging.INFO, "gate.mcp.runtime_cache_ready", "Dynamic MCP runtime cache ready", server_id=self.manifest.id, **cache_plan.safe_dict())
                self._store_log("info", "Dynamic MCP runtime cache ready", "gate.mcp.runtime_cache_ready", cache_plan.safe_dict())
                runtime_cache_payload = cache_plan.safe_dict()
            env.update(cache_plan.env)
            resolved_launch_env, credential_metadata = resolve_env_credential_refs(launch.env, self.credential_store)
            env.update(resolved_launch_env)
            self._redaction_values = tuple(resolved_launch_env.values())
            if credential_metadata.get("credential_ref_count"):
                log_event(logger, logging.INFO, "gate.mcp.credentials_resolved", "Credential refs resolved for MCP env", server_id=self.manifest.id, **credential_metadata)
                self._store_log("info", "Credential refs resolved for MCP env", "gate.mcp.credentials_resolved", credential_metadata)
            cwd = Path(launch.cwd).resolve() if launch.cwd else None
            command = cache_plan.command or [launch.command, *launch.args]
        safe_command = redact_command(command)
        log_event(logger, logging.INFO, "gate.mcp.stdio_process_started", "Starting MCP stdio process", server_id=self.manifest.id, command=safe_command, cwd=str(cwd) if cwd else None, runtime_cache=runtime_cache_payload)
        self._store_log("info", "Starting MCP stdio process", "gate.mcp.stdio_process_started", {"command": safe_command, "cwd": str(cwd) if cwd else None, "runtime_cache": runtime_cache_payload})
        self.process = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd else None,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        self._stdout_thread = threading.Thread(target=self._read_stdout, name=f"mcp-stdout-{self.manifest.id}", daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, name=f"mcp-stderr-{self.manifest.id}", daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()
        log_event(logger, logging.INFO, "gate.mcp.stdio_process_ready", "MCP stdio process started", server_id=self.manifest.id, pid=self.pid)
        self._store_log("info", "MCP stdio process started", "gate.mcp.stdio_process_ready", {"pid": self.pid})
        self.discover()

    def discover(self) -> dict[str, Any]:
        startup_timeout = self.manifest.timeout_seconds or self.settings.mcp_startup_timeout_seconds
        log_event(logger, logging.INFO, "gate.mcp.discovery_started", "Discovering MCP server", server_id=self.manifest.id, timeout_seconds=startup_timeout)
        result = self.request("server/discover", {}, timeout=startup_timeout)
        supported = result.get("supportedVersions") if isinstance(result, dict) else None
        if not isinstance(supported, list) or self.protocol_version not in supported:
            raise McpProtocolError(
                f"MCP server did not advertise requested version {self.protocol_version}"
            )
        self.server_capabilities = result.get("capabilities", {}) if isinstance(result, dict) else {}
        raw_result_meta = result.get("_meta")
        result_meta: dict[str, Any] = raw_result_meta if isinstance(raw_result_meta, dict) else {}
        server_info = result_meta.get("io.modelcontextprotocol/serverInfo")
        self.server_info = server_info if isinstance(server_info, dict) else {}
        self.initialized = True
        capability_names = sorted(str(name) for name in self.server_capabilities)
        log_event(
            logger,
            logging.INFO,
            "gate.mcp.discovery_succeeded",
            "MCP server discovered",
            server_id=self.manifest.id,
            capability_names=capability_names,
        )
        self._store_log(
            "info",
            "MCP server discovered",
            "gate.mcp.discovery_succeeded",
            {"capability_names": capability_names},
        )
        if self.settings.mcp_log_payloads:
            log_event(
                logger,
                logging.DEBUG,
                "gate.mcp.discovery_payload_received",
                "MCP discovery payload",
                server_id=self.manifest.id,
                server_info=redact_value(
                    self.server_info,
                    known_secrets=self._redaction_values,
                ),
                capabilities=redact_value(
                    self.server_capabilities,
                    known_secrets=self._redaction_values,
                ),
            )
        return result

    def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()
        page_count = 0
        while True:
            if page_count >= MAX_TOOL_LIST_PAGES:
                raise McpProtocolError(
                    f"tools/list exceeded the {MAX_TOOL_LIST_PAGES}-page limit"
                )
            params: dict[str, Any] = {}
            if cursor:
                params["cursor"] = cursor
            result = self.request("tools/list", params)
            page_count += 1
            batch = result.get("tools", []) if isinstance(result, dict) else []
            if not isinstance(batch, list):
                raise McpProtocolError("tools/list result.tools must be a list")
            if len(tools) + len(batch) > MAX_DISCOVERED_TOOLS:
                raise McpProtocolError(
                    f"tools/list exceeded the {MAX_DISCOVERED_TOOLS}-tool limit"
                )
            tools.extend(batch)
            next_cursor = result.get("nextCursor") if isinstance(result, dict) else None
            if next_cursor is not None and not isinstance(next_cursor, str):
                raise McpProtocolError("tools/list result.nextCursor must be a string")
            cursor = next_cursor or None
            if cursor:
                if cursor in seen_cursors:
                    raise McpProtocolError("tools/list returned a repeated cursor")
                seen_cursors.add(cursor)
            log_event(logger, logging.INFO, "gate.mcp.tools_page_received", "MCP tools/list page received", server_id=self.manifest.id, batch_count=len(batch), next_cursor=cursor)
            if not cursor:
                break
        log_event(logger, logging.INFO, "gate.mcp.tools_discovered", "MCP tools discovered", server_id=self.manifest.id, tool_count=len(tools))
        self._store_log("info", "MCP tools discovered", "gate.mcp.tools_discovered", {"tool_count": len(tools)})
        if self.settings.mcp_log_payloads:
            log_event(
                logger,
                logging.DEBUG,
                "gate.mcp.tools_payload_received",
                "MCP tool definitions received",
                server_id=self.manifest.id,
                tools=redact_value(tools, known_secrets=self._redaction_values),
            )
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        log_event(logger, logging.INFO, "gate.mcp.tool_call_started", "Calling MCP tool", server_id=self.manifest.id, tool_name=name)
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        log_event(logger, logging.INFO, "gate.mcp.tool_call_succeeded", "MCP tool call completed", server_id=self.manifest.id, tool_name=name)
        self._store_log("info", f"MCP tool call completed: {name}", "gate.mcp.tool_call_succeeded", {"tool_name": name})
        return result

    def request(self, method: str, params: dict[str, Any] | None = None, *, timeout: int | None = None) -> dict[str, Any]:
        if not self.process or not self.process.stdin:
            raise RuntimeError("MCP stdio process is not running")
        if self.process.poll() is not None:
            raise RuntimeError(self._process_exit_error(method))
        if self._fatal_protocol_error:
            raise McpProtocolError(self._fatal_protocol_error)

        request_id = next(self._ids)
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        request_params = build_request_params(
            params,
            client_name="lingshu-gate",
            client_version=self.settings.version,
            protocol_version=self.protocol_version,
        )
        message["params"] = request_params
        response_queue: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
        self._responses[request_id] = response_queue
        request_timeout = timeout or self.manifest.timeout_seconds or self.settings.mcp_request_timeout_seconds
        deadline = time.monotonic() + request_timeout
        try:
            self._write_message(message)
        except Exception:
            self._responses.pop(request_id, None)
            raise
        while True:
            if self._fatal_protocol_error:
                self._responses.pop(request_id, None)
                raise McpProtocolError(self._fatal_protocol_error)
            if self.process and self.process.poll() is not None:
                self._responses.pop(request_id, None)
                error = self._process_exit_error(method)
                log_event(logger, logging.ERROR, "gate.mcp.process_exited_during_request", "MCP stdio process exited while waiting for response", server_id=self.manifest.id, method=method, request_id=request_id, returncode=self.process.returncode, recent_stdout=self.last_stdout[-20:], recent_stderr=self.last_stderr[-20:])
                self._store_log("error", "MCP stdio process exited while waiting for response", "gate.mcp.process_exited_during_request", {"method": method, "request_id": request_id, "returncode": self.process.returncode, "recent_stdout": self.last_stdout[-20:], "recent_stderr": self.last_stderr[-20:]})
                raise RuntimeError(error)

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._responses.pop(request_id, None)
                log_event(logger, logging.ERROR, "gate.mcp.request_timed_out", "MCP request timed out", server_id=self.manifest.id, method=method, request_id=request_id, timeout_seconds=request_timeout, recent_stdout=self.last_stdout[-20:], recent_stderr=self.last_stderr[-20:])
                self._store_log("error", "MCP request timed out", "gate.mcp.request_timed_out", {"method": method, "request_id": request_id, "timeout_seconds": request_timeout, "recent_stdout": self.last_stdout[-20:], "recent_stderr": self.last_stderr[-20:]})
                raise TimeoutError(f"MCP request timed out: {method}; recent_stderr={self.last_stderr[-5:]}; recent_stdout={self.last_stdout[-5:]}")

            try:
                response = response_queue.get(timeout=min(0.5, remaining))
                break
            except queue.Empty:
                continue
        if "error" in response:
            safe_error = redact_value(response["error"], known_secrets=self._redaction_values)
            log_event(logger, logging.ERROR, "gate.mcp.request_error_received", "MCP request returned error", server_id=self.manifest.id, method=method, request_id=request_id, error=safe_error)
            self._store_log("error", "MCP request returned error", "gate.mcp.request_error_received", {"method": method, "request_id": request_id, "error": safe_error})
            raise McpProtocolError(str(safe_error))
        result = response.get("result")
        return result if isinstance(result, dict) else {"result": result}

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        request_params = build_request_params(
            params,
            client_name="lingshu-gate",
            client_version=self.settings.version,
            protocol_version=self.protocol_version,
        )
        message["params"] = request_params
        self._write_message(message)

    def stop(self) -> None:
        if not self.process:
            return
        process = self.process
        log_event(logger, logging.INFO, "gate.mcp.stdio_process_stopping", "Stopping MCP stdio process", server_id=self.manifest.id, pid=process.pid)
        self._store_log("info", "Stopping MCP stdio process", "gate.mcp.stdio_process_stopping", {"pid": process.pid})
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                log_event(logger, logging.WARNING, "gate.mcp.stdio_process_killed", "Killing MCP stdio process after timeout", server_id=self.manifest.id, pid=process.pid)
                self._store_log("warning", "Killing MCP stdio process after timeout", "gate.mcp.stdio_process_killed", {"pid": process.pid})
                process.kill()
        log_event(logger, logging.INFO, "gate.mcp.stdio_process_stopped", "MCP stdio process stopped", server_id=self.manifest.id, returncode=process.returncode)
        self._store_log("info", "MCP stdio process stopped", "gate.mcp.stdio_process_stopped", {"returncode": process.returncode})
        self.process = None
        self.initialized = False

    def _write_message(self, message: dict[str, Any]) -> None:
        if not self.process or not self.process.stdin:
            raise RuntimeError("MCP stdio process is not running")
        encoded = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        encoded_size = len(encoded.encode("utf-8")) + 1
        if encoded_size > MAX_STDIO_MESSAGE_BYTES:
            raise McpProtocolError(
                f"MCP stdio message exceeded the {MAX_STDIO_MESSAGE_BYTES}-byte limit"
            )
        with self._lock:
            self.process.stdin.write(encoded + "\n")
            self.process.stdin.flush()
        if self.settings.mcp_log_payloads:
            log_event(logger, logging.DEBUG, "gate.mcp.stdio_message_sent", "MCP stdio message sent", server_id=self.manifest.id, payload=redact_value(message, known_secrets=self._redaction_values))

    def _process_exit_error(self, method: str) -> str:
        returncode = self.process.returncode if self.process else None
        recent_stderr = self.last_stderr[-5:]
        recent_stdout = self.last_stdout[-5:]
        return f"MCP stdio process exited while waiting for {method}: returncode={returncode}; recent_stderr={recent_stderr}; recent_stdout={recent_stdout}"

    def _read_stdout(self) -> None:
        assert self.process and self.process.stdout
        for line, oversized in _iter_bounded_text_lines(
            self.process.stdout,
            MAX_STDIO_MESSAGE_BYTES,
        ):
            if oversized:
                self._set_fatal_protocol_error(
                    f"MCP stdio message exceeded the {MAX_STDIO_MESSAGE_BYTES}-byte limit"
                )
                break
            raw = line.rstrip("\n")
            if not raw:
                continue
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                safe_raw = (
                    redact_text(raw, known_secrets=self._redaction_values, limit=4000)
                    if self.settings.mcp_log_payloads
                    else "[MCP stdout payload suppressed]"
                )
                self.last_stdout.append(safe_raw)
                self.last_stdout = self.last_stdout[-100:]
                log_event(logger, logging.ERROR, "gate.mcp.stdio_invalid_json", "Invalid JSON from MCP stdout", server_id=self.manifest.id, raw=safe_raw)
                self._store_log("error", "Invalid JSON from MCP stdout", "gate.mcp.stdio_invalid_json", {"stream": "stdout", "raw": safe_raw})
                continue
            self.last_stdout.append(
                "[MCP JSON-RPC payload suppressed]"
                if not self.settings.mcp_log_payloads
                else redact_text(raw, known_secrets=self._redaction_values, limit=4000)
            )
            self.last_stdout = self.last_stdout[-100:]
            if self.settings.mcp_log_payloads:
                safe_message = redact_value(message, known_secrets=self._redaction_values)
                log_event(logger, logging.DEBUG, "gate.mcp.stdio_message_received", "MCP stdio message received", server_id=self.manifest.id, payload=safe_message)
                self._store_log("debug", "MCP stdout JSON-RPC message", "gate.mcp.stdio_stdout", {"stream": "stdout", "payload": safe_message})
            if isinstance(message, dict) and "id" in message:
                response_id = message.get("id")
                q = (
                    self._responses.pop(response_id, None)
                    if isinstance(response_id, int) and not isinstance(response_id, bool)
                    else None
                )
                if q:
                    q.put(message)
                else:
                    log_event(logger, logging.WARNING, "gate.mcp.stdio_unmatched_response", "Received response without pending request", server_id=self.manifest.id, response_id=response_id)
                    self._store_log("warning", "Received response without pending request", "gate.mcp.stdio_unmatched_response", {"response_id": response_id})
            else:
                log_event(logger, logging.INFO, "gate.mcp.stdio_notification_received", "Received MCP notification/request", server_id=self.manifest.id)
        log_event(logger, logging.WARNING, "gate.mcp.stdio_stdout_closed", "MCP stdout closed", server_id=self.manifest.id, returncode=self.process.poll() if self.process else None)
        self._store_log("warning", "MCP stdout closed", "gate.mcp.stdio_stdout_closed", {"returncode": self.process.poll() if self.process else None})

    def _read_stderr(self) -> None:
        assert self.process and self.process.stderr
        for line, oversized in _iter_bounded_text_lines(
            self.process.stderr,
            MAX_STDIO_MESSAGE_BYTES,
        ):
            if oversized:
                safe_raw = "[MCP stderr line exceeded the size limit]"
                self.last_stderr.append(safe_raw)
                self.last_stderr = self.last_stderr[-100:]
                log_event(
                    logger,
                    logging.WARNING,
                    "gate.mcp.stdio_stderr_limit_exceeded",
                    "MCP stderr line exceeded the size limit",
                    server_id=self.manifest.id,
                )
                self._store_log(
                    "warning",
                    "MCP stderr line exceeded the size limit",
                    "gate.mcp.stdio_stderr_limit_exceeded",
                    {"stream": "stderr", "limit_bytes": MAX_STDIO_MESSAGE_BYTES},
                )
                continue
            raw = line.rstrip("\n")
            if not raw:
                continue
            safe_raw = (
                redact_text(raw, known_secrets=self._redaction_values, limit=4000)
                if self.settings.mcp_log_payloads
                else "[MCP stderr payload suppressed]"
            )
            self.last_stderr.append(safe_raw)
            self.last_stderr = self.last_stderr[-100:]
            log_event(logger, logging.INFO, "gate.mcp.stdio_stderr_received", "MCP stderr", server_id=self.manifest.id, stderr=safe_raw)
            self._store_log("warning", "MCP stderr output", "gate.mcp.stdio_stderr_received", {"stream": "stderr", "stderr": safe_raw})
        log_event(logger, logging.WARNING, "gate.mcp.stdio_stderr_closed", "MCP stderr closed", server_id=self.manifest.id, returncode=self.process.poll() if self.process else None)
        self._store_log("warning", "MCP stderr closed", "gate.mcp.stdio_stderr_closed", {"returncode": self.process.poll() if self.process else None})

    def _store_log(self, level: str, message: str, event_type: str, payload: dict[str, Any]) -> None:
        if not self.log_sink:
            return
        try:
            self.log_sink(
                level,
                redact_text(message, known_secrets=self._redaction_values),
                event_type,
                redact_value(payload, known_secrets=self._redaction_values),
            )
        except Exception:  # noqa: BLE001 - logging must not break MCP IO threads
            logger.debug("Failed to write MCP stdio log", exc_info=True)

    def _set_fatal_protocol_error(self, message: str) -> None:
        self._fatal_protocol_error = message
        log_event(
            logger,
            logging.ERROR,
            "gate.mcp.stdio_message_limit_exceeded",
            "MCP stdio message exceeded the size limit",
            server_id=self.manifest.id,
            limit_bytes=MAX_STDIO_MESSAGE_BYTES,
        )
        self._store_log(
            "error",
            "MCP stdio message exceeded the size limit",
            "gate.mcp.stdio_message_limit_exceeded",
            {"stream": "stdout", "limit_bytes": MAX_STDIO_MESSAGE_BYTES},
        )
        process = self.process
        if process is not None and process.poll() is None:
            terminate = getattr(process, "terminate", None)
            if callable(terminate):
                try:
                    terminate()
                except OSError:
                    pass


def _iter_bounded_text_lines(stream: Any, limit_bytes: int) -> Iterable[tuple[str, bool]]:
    """Yield text lines without ever retaining an unbounded peer-controlled line."""

    readline = getattr(stream, "readline", None)
    if not callable(readline):
        for line in stream:
            yield line, len(line.encode("utf-8")) > limit_bytes
        return

    while True:
        chunk = readline(limit_bytes + 1)
        if chunk == "":
            return
        oversized = len(chunk.encode("utf-8")) > limit_bytes
        if oversized and not chunk.endswith("\n"):
            while chunk and not chunk.endswith("\n"):
                chunk = readline(limit_bytes + 1)
        yield ("" if oversized else chunk), oversized

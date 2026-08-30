"""Minimal synchronous Streamable HTTP MCP client.

This connects to an MCP server that is already running behind an HTTP endpoint
(``launch.type=external`` + ``transport.type=streamable_http``). Protocol
validation and HTTP framing are delegated to the shared transport adapter.

HTTP is done with the standard library ``urllib`` to avoid new dependencies. Each
request is a single POST carrying a JSON-RPC message; the response is either a
single ``application/json`` body or an SSE (``text/event-stream``) stream from
which the matching JSON-RPC response is extracted.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from itertools import count
from typing import Any

from lingshu_gate.config import Settings
from lingshu_gate.credential_refs import resolve_env_credential_refs
from lingshu_gate.credential_store import CredentialStore
from lingshu_gate.endpoint_security import REDACTED_ENDPOINT
from lingshu_gate.logging import log_event
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_stdio_client import McpProtocolError
from lingshu_gate.protocol.version import (
    MCP_PROTOCOL_VERSION,
    require_current_protocol_version,
)
from lingshu_gate.redaction import redact_text, redact_value
from lingshu_gate.transports.http import build_protocol_request

logger = logging.getLogger(__name__)

LogSink = Callable[[str, str, str, dict[str, Any]], None]

# These are protocol-boundary safety limits, not operator-tunable performance
# knobs. A peer cannot make the control plane retain an unbounded response or
# keep a request alive indefinitely by slowly emitting SSE keepalives.
MAX_HTTP_RESPONSE_BYTES = 8 * 1024 * 1024
MAX_SSE_EVENT_BYTES = 1024 * 1024
MAX_SSE_EVENTS = 10_000
MAX_TOOL_LIST_PAGES = 100
MAX_DISCOVERED_TOOLS = 10_000
HTTP_READ_CHUNK_BYTES = 64 * 1024


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Turn every redirect into an HTTPError without forwarding headers."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        del req, fp, code, msg, headers, newurl
        return None


class McpHttpAuthenticationError(McpProtocolError):
    """The remote MCP endpoint requires or rejected credentials."""

    def __init__(self, status_code: int, endpoint: str, detail: str = "") -> None:
        self.status_code = status_code
        self.endpoint = REDACTED_ENDPOINT
        safe_detail = redact_text(detail, known_secrets=(endpoint,))
        super().__init__(f"HTTP {status_code} authentication failure from MCP endpoint: {safe_detail}")


class StreamableHttpMcpClient:
    """Talk to one external MCP server over Streamable HTTP JSON-RPC."""

    def __init__(
        self,
        manifest: McpServerManifest,
        settings: Settings,
        log_sink: LogSink | None = None,
        redaction_values: Iterable[str] = (),
    ) -> None:
        self.manifest = manifest
        self.settings = settings
        self.log_sink = log_sink
        self.endpoint = manifest.transport.endpoint or ""
        configured_protocol = manifest.transport.protocol_version or MCP_PROTOCOL_VERSION
        self.protocol_version = require_current_protocol_version(configured_protocol)
        # The current HTTP protocol is stateless; this property remains useful
        # to callers that expose connection details.
        self.session_id: str | None = None
        self.initialized = False
        self.server_info: dict[str, Any] = {}
        self.server_capabilities: dict[str, Any] = {}
        # Kept for API parity with the stdio client (server detail reads these).
        self.last_stdout: list[str] = []
        self.last_stderr: list[str] = []
        self._ids = count(1)
        self._resolved_headers: dict[str, str] = {}
        self._redaction_values = tuple(
            sorted(
                {self.endpoint, *(value for value in redaction_values if value)},
                key=len,
                reverse=True,
            )
        )
        self.credential_store = CredentialStore(settings.data_dir)
        self._opener = urllib.request.build_opener(_NoRedirectHandler())

    @property
    def pid(self) -> int | None:
        """External servers have no local process."""
        return None

    @property
    def process(self) -> None:
        return None

    def start(self) -> None:
        if not self.endpoint:
            raise ValueError("transport.endpoint is required for streamable_http")
        self._resolve_headers()
        startup_timeout = self.manifest.timeout_seconds or self.settings.mcp_startup_timeout_seconds
        log_event(logger, logging.INFO, "gate.mcp.http_connect_started", "Connecting to external MCP endpoint", server_id=self.manifest.id, timeout_seconds=startup_timeout)
        self._store_log("info", "Connecting to external MCP endpoint", "gate.mcp.http_connect_started", {"timeout_seconds": startup_timeout})
        self._start_current(startup_timeout)
        self.initialized = True
        connection_summary = {
            "capability_count": len(self.server_capabilities),
            "protocol_version": self.protocol_version,
        }
        log_event(logger, logging.INFO, "gate.mcp.http_connect_succeeded", "External MCP endpoint connected", server_id=self.manifest.id, **connection_summary)
        self._store_log("info", "External MCP endpoint connected", "gate.mcp.http_connect_succeeded", connection_summary)

    def _start_current(self, startup_timeout: int) -> None:
        result = self.request("server/discover", {}, timeout=startup_timeout)
        supported = result.get("supportedVersions") if isinstance(result, dict) else None
        if not isinstance(supported, list) or self.protocol_version not in supported:
            raise McpProtocolError(
                f"MCP endpoint did not advertise requested version {self.protocol_version}"
            )
        self.server_capabilities = result.get("capabilities", {}) if isinstance(result, dict) else {}
        raw_result_meta = result.get("_meta")
        result_meta: dict[str, Any] = raw_result_meta if isinstance(raw_result_meta, dict) else {}
        server_info = result_meta.get("io.modelcontextprotocol/serverInfo")
        self.server_info = server_info if isinstance(server_info, dict) else {}

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
            log_event(logger, logging.INFO, "gate.mcp.tools_page_received", "MCP tools/list page received", server_id=self.manifest.id, batch_count=len(batch), has_next_page=bool(cursor))
            if not cursor:
                break
        log_event(logger, logging.INFO, "gate.mcp.tools_discovered", "MCP tools discovered", server_id=self.manifest.id, tool_count=len(tools))
        self._store_log("info", "MCP tools discovered", "gate.mcp.tools_discovered", {"tool_count": len(tools)})
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        log_event(logger, logging.INFO, "gate.mcp.tool_call_started", "Calling MCP tool", server_id=self.manifest.id, tool_name=name)
        result = self.request("tools/call", {"name": name, "arguments": arguments})
        log_event(logger, logging.INFO, "gate.mcp.tool_call_succeeded", "MCP tool call completed", server_id=self.manifest.id, tool_name=name)
        self._store_log("info", f"MCP tool call completed: {name}", "gate.mcp.tool_call_succeeded", {"tool_name": name})
        return result

    def request(self, method: str, params: dict[str, Any] | None = None, *, timeout: int | None = None) -> dict[str, Any]:
        request_id = next(self._ids)
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        protocol_headers: dict[str, str] = {}
        request_params, protocol_headers = build_protocol_request(
            method,
            params,
            client_name="lingshu-gate",
            client_version=self.settings.version,
            protocol_version=self.protocol_version,
        )
        message["params"] = request_params
        request_timeout = timeout or self.manifest.timeout_seconds or self.settings.mcp_request_timeout_seconds
        response = self._post(
            message,
            request_timeout,
            expect_response=True,
            request_id=request_id,
            protocol_headers=protocol_headers,
        )
        if response is None:
            raise McpProtocolError(f"No JSON-RPC response for MCP request: {method}")
        if "error" in response:
            safe_error = self._redact(response["error"])
            error_code = safe_error.get("code") if isinstance(safe_error, dict) else None
            error_summary = {
                "method": method,
                "request_id": request_id,
                "error_code": error_code,
            }
            log_event(logger, logging.ERROR, "gate.mcp.request_error_received", "MCP request returned error", server_id=self.manifest.id, **error_summary)
            self._store_log("error", "MCP request returned error", "gate.mcp.request_error_received", error_summary)
            raise McpProtocolError(str(safe_error))
        result = response.get("result")
        return result if isinstance(result, dict) else {"result": result}

    def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        message: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        protocol_headers: dict[str, str] = {}
        request_params, protocol_headers = build_protocol_request(
            method,
            params,
            client_name="lingshu-gate",
            client_version=self.settings.version,
            protocol_version=self.protocol_version,
        )
        message["params"] = request_params
        request_timeout = self.manifest.timeout_seconds or self.settings.mcp_request_timeout_seconds
        self._post(
            message,
            request_timeout,
            expect_response=False,
            request_id=None,
            protocol_headers=protocol_headers,
        )

    def stop(self) -> None:
        log_event(logger, logging.INFO, "gate.mcp.http_disconnected", "External MCP endpoint disconnected", server_id=self.manifest.id)
        self._store_log("info", "External MCP endpoint disconnected", "gate.mcp.http_disconnected", {})
        self.initialized = False
        self.session_id = None

    def _resolve_headers(self) -> None:
        raw_headers = dict(self.manifest.transport.headers or {})
        if not raw_headers:
            self._resolved_headers = {}
            return
        resolved, metadata = resolve_env_credential_refs(raw_headers, self.credential_store)
        self._resolved_headers = resolved
        self._redaction_values = tuple(
            sorted(
                {
                    *self._redaction_values,
                    *(value for value in resolved.values() if value),
                },
                key=len,
                reverse=True,
            )
        )
        if metadata.get("credential_ref_count"):
            log_event(logger, logging.INFO, "gate.mcp.credentials_resolved", "Credential refs resolved for MCP HTTP headers", server_id=self.manifest.id, **metadata)
            self._store_log("info", "Credential refs resolved for MCP HTTP headers", "gate.mcp.credentials_resolved", metadata)

    def _post(
        self,
        message: dict[str, Any],
        timeout: float,
        *,
        expect_response: bool,
        request_id: int | None,
        protocol_headers: dict[str, str],
    ) -> dict[str, Any] | None:
        deadline = time.monotonic() + max(float(timeout), 0.001)
        body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        headers.update(self._resolved_headers)
        headers.update(protocol_headers)
        if self.settings.mcp_log_payloads:
            log_event(logger, logging.DEBUG, "gate.mcp.http_message_sent", "MCP HTTP message sent", server_id=self.manifest.id, payload=self._redact(message))
        request = urllib.request.Request(self.endpoint, data=body, headers=headers, method="POST")
        try:
            response = self._opener.open(  # noqa: S310 - endpoint is operator-configured
                request,
                timeout=_remaining_seconds(deadline),
            )
        except urllib.error.HTTPError as exc:
            if 300 <= exc.code < 400:
                exc.close()
                raise McpProtocolError(
                    "HTTP redirects are not allowed for the MCP endpoint"
                ) from exc
            detail = ""
            try:
                detail = _read_bounded_response(exc, deadline).decode(
                    "utf-8", "ignore"
                )[:2000]
            except Exception:  # noqa: BLE001 - error body is best-effort
                detail = ""
            finally:
                exc.close()
            safe_detail = self._redact_text(detail)
            if exc.code in {401, 403}:
                raise McpHttpAuthenticationError(exc.code, self.endpoint, safe_detail) from exc
            raise McpProtocolError(f"HTTP {exc.code} from MCP endpoint: {safe_detail}") from exc
        except urllib.error.URLError as exc:
            safe_reason = self._redact_text(str(exc.reason))
            raise McpProtocolError(f"Failed to reach MCP endpoint: {safe_reason}") from exc
        except TimeoutError as exc:
            raise McpProtocolError(
                "MCP HTTP request exceeded its absolute deadline"
            ) from exc
        with response:
            content_type = (response.headers.get("Content-Type") or "").lower()
            if not expect_response or response.status == 202:
                return None
            if "text/event-stream" in content_type:
                return self._read_sse_response(response, request_id, deadline)
            raw = _read_bounded_response(response, deadline).decode(
                "utf-8", "ignore"
            ).strip()
            if not raw:
                return None
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise McpProtocolError(
                    f"Invalid JSON from MCP endpoint: {self._redact_text(raw[:500])}"
                ) from exc
            if self.settings.mcp_log_payloads:
                log_event(logger, logging.DEBUG, "gate.mcp.http_message_received", "MCP HTTP message received", server_id=self.manifest.id, payload=self._redact(parsed))
            return parsed if isinstance(parsed, dict) else {"result": parsed}

    def _read_sse_response(
        self,
        response: Any,
        request_id: int | None,
        deadline: float,
    ) -> dict[str, Any] | None:
        """Read an SSE stream and return the JSON-RPC message matching request_id."""
        data_lines: list[str] = []
        pending = bytearray()
        response_bytes = 0
        event_bytes = 0
        event_count = 0

        def process_line(raw_line: bytes) -> dict[str, Any] | None:
            nonlocal data_lines, event_bytes, event_count
            line_bytes = raw_line.rstrip(b"\r")
            line = line_bytes.decode("utf-8", "ignore")
            if line == "":
                if not data_lines:
                    return None
                event_count += 1
                if event_count > MAX_SSE_EVENTS:
                    raise McpProtocolError(
                        f"MCP SSE response exceeded the {MAX_SSE_EVENTS}-event limit"
                    )
                match = self._match_sse_event(data_lines, request_id)
                data_lines = []
                event_bytes = 0
                if match is not None:
                    return match
                return None
            if line.startswith(":"):
                return None
            if line.startswith("data:"):
                data = line[len("data:"):].lstrip(" ")
                event_bytes += len(line_bytes) + 1
                if event_bytes > MAX_SSE_EVENT_BYTES:
                    raise McpProtocolError(
                        f"MCP SSE event exceeded the {MAX_SSE_EVENT_BYTES}-byte limit"
                    )
                data_lines.append(data)
            return None

        while True:
            chunk = _read_response_chunk(response, deadline)
            if not chunk:
                break
            response_bytes += len(chunk)
            if response_bytes > MAX_HTTP_RESPONSE_BYTES:
                raise McpProtocolError(
                    f"MCP HTTP response exceeded the {MAX_HTTP_RESPONSE_BYTES}-byte limit"
                )
            pending.extend(chunk)
            while True:
                newline = pending.find(b"\n")
                if newline < 0:
                    if len(pending) > MAX_SSE_EVENT_BYTES:
                        raise McpProtocolError(
                            f"MCP SSE line exceeded the {MAX_SSE_EVENT_BYTES}-byte limit"
                        )
                    break
                raw_line = bytes(pending[:newline])
                del pending[: newline + 1]
                match = process_line(raw_line)
                if match is not None:
                    return match

        if pending:
            match = process_line(bytes(pending))
            if match is not None:
                return match
        if data_lines:
            event_count += 1
            if event_count > MAX_SSE_EVENTS:
                raise McpProtocolError(
                    f"MCP SSE response exceeded the {MAX_SSE_EVENTS}-event limit"
                )
            return self._match_sse_event(data_lines, request_id)
        return None

    def _match_sse_event(self, data_lines: list[str], request_id: int | None) -> dict[str, Any] | None:
        if not data_lines:
            return None
        try:
            message = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            return None
        if not isinstance(message, dict):
            return None
        if self.settings.mcp_log_payloads:
            log_event(logger, logging.DEBUG, "gate.mcp.http_message_received", "MCP HTTP SSE message received", server_id=self.manifest.id, payload=self._redact(message))
        if request_id is None or message.get("id") == request_id:
            return message
        return None

    def _store_log(self, level: str, message: str, event_type: str, payload: dict[str, Any]) -> None:
        if not self.log_sink:
            return
        try:
            self.log_sink(level, message, event_type, self._redact(payload))
        except Exception:  # noqa: BLE001 - logging must not break MCP IO
            logger.debug("Failed to write MCP HTTP log", exc_info=True)

    def _redact_text(self, value: str) -> str:
        return redact_text(value, known_secrets=self._redaction_values)

    def _redact(self, value: Any) -> Any:
        return redact_value(value, known_secrets=self._redaction_values)


def _remaining_seconds(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("MCP HTTP request deadline expired")
    return remaining


def _set_response_timeout(response: Any, timeout: float) -> None:
    """Best-effort tightening of urllib's per-read socket timeout.

    ``urlopen(timeout=...)`` applies a socket-operation timeout, which a slow
    peer can repeatedly reset. Updating it to the remaining wall-clock budget
    before every read turns that into an absolute request deadline.
    """

    candidates = (
        getattr(response, "fp", None),
        getattr(getattr(response, "fp", None), "raw", None),
        getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None),
    )
    for candidate in reversed(candidates):
        setter = getattr(candidate, "settimeout", None)
        if callable(setter):
            try:
                setter(timeout)
            except (OSError, ValueError):
                pass
            return


def _read_response_chunk(response: Any, deadline: float) -> bytes:
    remaining = _remaining_seconds(deadline)
    _set_response_timeout(response, remaining)
    reader = getattr(response, "read1", None)
    if not callable(reader):
        reader = response.read
    try:
        chunk = reader(HTTP_READ_CHUNK_BYTES)
    except TimeoutError as exc:
        raise McpProtocolError(
            "MCP HTTP response exceeded its absolute deadline"
        ) from exc
    _remaining_seconds(deadline)
    if not isinstance(chunk, (bytes, bytearray)):
        raise McpProtocolError("Invalid byte stream from MCP endpoint")
    return bytes(chunk)


def _read_bounded_response(response: Any, deadline: float) -> bytes:
    raw_length = response.headers.get("Content-Length") if response.headers else None
    if raw_length:
        try:
            declared_length = int(raw_length)
        except (TypeError, ValueError):
            declared_length = -1
        if declared_length > MAX_HTTP_RESPONSE_BYTES:
            raise McpProtocolError(
                f"MCP HTTP response exceeded the {MAX_HTTP_RESPONSE_BYTES}-byte limit"
            )

    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = _read_response_chunk(response, deadline)
        if not chunk:
            break
        total += len(chunk)
        if total > MAX_HTTP_RESPONSE_BYTES:
            raise McpProtocolError(
                f"MCP HTTP response exceeded the {MAX_HTTP_RESPONSE_BYTES}-byte limit"
            )
        chunks.append(chunk)
    return b"".join(chunks)

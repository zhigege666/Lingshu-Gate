"""Safe timeout context and bounded, process-local late MCP responses.

These receipts describe protocol responses. They do not establish whether a
remote process has stopped, and they are never a durable job implementation.
"""
from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from lingshu_gate.domain.tool_structure import checked_json_size

REQUEST_OUTCOME_TTL_SECONDS = 300.0
MAX_REQUEST_OUTCOMES = 128
MAX_REQUEST_OUTCOME_BYTES = 8 * 1024 * 1024
MAX_REQUEST_OUTCOME_DEPTH = 64
MAX_REQUEST_OUTCOME_NODES = 100_000


class McpRequestTimeout(TimeoutError):
    """A waiting deadline expired without confirming the execution outcome."""

    code = "mcp_request_timeout"
    retryable = False

    def __init__(
        self,
        *,
        method: str,
        timeout_seconds: float,
        request_handle: str | None = None,
        connection_generation: str | None = None,
        transport: str = "stdio",
        dispatch_state: str = "sent",
        recovery_supported: bool = True,
        recovery_expires_after_seconds: float | None = None,
        phase: str | None = None,
        business_request: bool | None = None,
        outcome_reader: Callable[[], dict[str, Any] | None] | None = None,
    ) -> None:
        self.method = method
        self.request_handle = request_handle
        self.connection_generation = connection_generation
        self.timeout_seconds = float(timeout_seconds)
        # A capability for the in-process application adapter only. It must
        # never enter error details, logs, or persistent request records.
        self.outcome_reader = outcome_reader
        self.business_request = method == "tools/call" if business_request is None else business_request
        execution_unknown = self.business_request and dispatch_state != "not_dispatched"
        self.details: dict[str, Any] = {
            "transport": transport,
            "method": method,
            "phase": phase or "downstream_response",
            "request_handle": request_handle,
            "connection_generation": connection_generation,
            "timeout_seconds": self.timeout_seconds,
            "dispatch_state": dispatch_state,
            "business_request": self.business_request,
            "execution_state": "unknown" if execution_unknown else "not_started",
            "execution_terminated": False,
            "recovery_supported": recovery_supported,
            "recovery_scope": "current_process" if recovery_supported else "none",
            "recovery_expires_after_seconds": recovery_expires_after_seconds if recovery_supported else None,
        }
        self.next_action = (
            "Query the original request outcome while this Gate process is available; "
            "do not automatically replay the operation."
            if recovery_supported else
            "Reconcile the original operation with its execution service before retrying."
        )
        # Never interpolate peer output or request arguments in the public error.
        super().__init__(
            "MCP request timed out; the remote execution outcome is unknown."
            if execution_unknown else
            "MCP request timed out before the business operation was dispatched."
        )


def find_request_timeout(error: BaseException) -> McpRequestTimeout | None:
    """Recognize explicit wrapping without guessing from text or hidden context."""
    current: BaseException | None = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, McpRequestTimeout):
            return current
        current = current.__cause__
    return None


@dataclass
class _Outcome:
    request_handle: str
    connection_generation: str
    request_id: int
    method: str
    expires_at: float
    state: str = "waiting"
    response_json: bytes | None = None
    response_bytes: int = 0
    unavailable_reason: str | None = None


class RequestOutcomeStore:
    """Keep only timed-out requests, with count, byte and time bounds.

    The caller serializes ``retain`` with response delivery so a response cannot
    fall between removal of its synchronous waiter and registration here.
    Reads decode detached snapshots from bounded UTF-8 JSON. The depth and node
    limits also keep later API serialization safe. Request arguments are never retained;
    original response payloads stay in memory and require application-level
    authorization before they can be exposed to a caller.
    """

    def __init__(
        self,
        *,
        max_entries: int = MAX_REQUEST_OUTCOMES,
        max_response_bytes: int = MAX_REQUEST_OUTCOME_BYTES,
        ttl_seconds: float = REQUEST_OUTCOME_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_entries < 1 or max_response_bytes < 1 or ttl_seconds <= 0:
            raise ValueError("Request outcome limits must be positive")
        self.max_entries = max_entries
        self.max_response_bytes = max_response_bytes
        self.ttl_seconds = ttl_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, _Outcome] = OrderedDict()
        self._pending: dict[tuple[str, int], str] = {}
        self._response_bytes = 0

    def retain(self, request_handle: str, connection_generation: str, request_id: int, method: str) -> None:
        with self._lock:
            self._purge()
            if request_handle in self._entries:
                self._remove(request_handle)
            while len(self._entries) >= self.max_entries:
                self._remove(next(iter(self._entries)))
            outcome = _Outcome(request_handle, connection_generation, request_id, method,
                               self._clock() + self.ttl_seconds)
            self._entries[request_handle] = outcome
            self._pending[(connection_generation, request_id)] = request_handle

    def complete(self, connection_generation: str, request_id: int, response: dict[str, Any]) -> bool:
        with self._lock:
            self._purge()
            key = (connection_generation, request_id)
            handle = self._pending.get(key)
            outcome = self._entries.get(handle) if handle is not None else None
            if outcome is None:
                return False
            try:
                if not isinstance(response, dict):
                    raise ValueError("tool_structure_non_json")
                checked_json_size(response, max_bytes=self.max_response_bytes - self._response_bytes,
                                  max_nodes=MAX_REQUEST_OUTCOME_NODES, max_depth=MAX_REQUEST_OUTCOME_DEPTH)
                encoded = json.dumps(response, ensure_ascii=False, allow_nan=False,
                                     separators=(",", ":")).encode("utf-8")
            except RecursionError:
                reason = "response_complexity_limit"
            except UnicodeError:
                reason = "response_invalid_unicode"
            except (TypeError, ValueError) as exc:
                reason = {
                    "tool_structure_size_limit": "response_byte_limit",
                    "tool_structure_complexity_limit": "response_complexity_limit",
                }.get(str(exc), "response_invalid_json")
            else:
                # Measure the immutable representation actually retained. A
                # malformed peer response must not kill the stdout reader or
                # publish a completed receipt before its snapshot exists.
                size = len(encoded)
                if size <= self.max_response_bytes - self._response_bytes:
                    self._pending.pop(key, None)
                    outcome.response_json = encoded
                    outcome.response_bytes = size
                    self._response_bytes += size
                    outcome.state = "completed"
                    return True
                reason = "response_byte_limit"
            self._pending.pop(key, None)
            self._mark_unavailable(outcome, reason)
            return True

    def _mark_unavailable(self, outcome: _Outcome, reason: str) -> None:
        self._response_bytes -= outcome.response_bytes
        outcome.response_json = None
        outcome.response_bytes = 0
        outcome.state = "unavailable"
        outcome.unavailable_reason = reason

    def interrupt_generation(self, connection_generation: str) -> None:
        with self._lock:
            self._purge()
            for outcome in self._entries.values():
                if outcome.connection_generation == connection_generation and outcome.state == "waiting":
                    outcome.state = "interrupted"
                    outcome.unavailable_reason = "connection_closed"
                    self._pending.pop((connection_generation, outcome.request_id), None)

    def get(self, request_handle: str) -> dict[str, Any] | None:
        with self._lock:
            self._purge()
            outcome = self._entries.get(request_handle)
            if outcome is None:
                return None
            response: dict[str, Any] | None = None
            if outcome.response_json is not None:
                try:
                    response = json.loads(outcome.response_json)
                except (TypeError, ValueError, RecursionError):
                    # Stored JSON was validated before commit. Keep querying
                    # fail-closed even if a snapshot cannot be decoded later.
                    self._mark_unavailable(outcome, "response_snapshot_unavailable")
            return {
                "request_handle": outcome.request_handle,
                "connection_generation": outcome.connection_generation,
                "request_id": outcome.request_id,
                "method": outcome.method,
                "state": outcome.state,
                "response": response,
                "unavailable_reason": outcome.unavailable_reason,
                "recovery_scope": "current_process",
                "expires_after_seconds": max(0.0, outcome.expires_at - self._clock()),
            }

    def _purge(self) -> None:
        now = self._clock()
        for handle, outcome in list(self._entries.items()):
            if outcome.expires_at <= now:
                self._remove(handle)

    def _remove(self, handle: str) -> None:
        outcome = self._entries.pop(handle)
        self._pending.pop((outcome.connection_generation, outcome.request_id), None)
        self._response_bytes -= outcome.response_bytes

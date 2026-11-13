"""Bounded, request-authenticated MCP tool-list notification streams."""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import HTTPException, Request
from mcp_types.methods import serialize_server_result
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse
from starlette.types import Receive, Scope, Send

from lingshu_gate.config import Settings
from lingshu_gate.protocol.version import MCP_PROTOCOL_VERSION

NOTIFICATION_CHECK_SECONDS = 5.0
NOTIFICATION_HEARTBEAT_SECONDS = 15.0
NOTIFICATION_LIFETIME_SECONDS = 300.0
MAX_NOTIFICATION_STREAMS = 64
MAX_NOTIFICATION_STREAMS_PER_IDENTITY = 4
SUBSCRIPTION_ID_META_KEY = "io.modelcontextprotocol/subscriptionId"


def visible_tools_fingerprint(tools: list[dict[str, Any]], limit_bytes: int) -> str:
    """Compare the exact authorized projection without exposing its contents."""
    digest = hashlib.sha256()
    size = 0
    encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    for part in encoder.iterencode(sorted(tools, key=lambda tool: str(tool.get("name", "")))):
        data = part.encode()
        size += len(data)
        if size > limit_bytes:
            raise ValueError("MCP notification snapshot exceeded the byte limit")
        digest.update(data)
    return digest.hexdigest()


def subscription_tools_requested(params: Any) -> bool:
    """Validate the standard opt-in filter; only tools changes are implemented."""
    notifications = params.get("notifications") if isinstance(params, dict) else None
    if not isinstance(notifications, dict):
        raise ValueError("subscriptions/listen requires a notifications object")
    boolean_keys = {"toolsListChanged", "promptsListChanged", "resourcesListChanged"}
    if set(notifications) - boolean_keys - {"resourceSubscriptions"}:
        raise ValueError("Unsupported subscription notification field")
    if any(type(notifications[key]) is not bool for key in boolean_keys & notifications.keys()):
        raise ValueError("Subscription notification flags must be booleans")
    resources = notifications.get("resourceSubscriptions", [])
    if not isinstance(resources, list) or any(not isinstance(uri, str) or not uri for uri in resources):
        raise ValueError("Resource subscriptions must be a list of resource URIs")
    return notifications.get("toolsListChanged") is True


class _NotificationResponse(StreamingResponse):
    """Release admission even if the ASGI response is cancelled before iteration."""

    def __init__(self, *args: Any, release: Callable[[], None], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._release = release

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            self._release()


class GatewayToolNotifications:
    """Each stream rechecks the caller; no shared event payload or replay log."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        self._active: dict[tuple[Any, ...], int] = {}

    async def open(
        self, request: Request, *, identity: tuple[Any, ...], protocol_version: str,
        request_id: str | int | None, snapshot: Callable[[], str], tools_requested: bool,
    ) -> StreamingResponse:
        with self._lock:
            if (sum(self._active.values()) >= MAX_NOTIFICATION_STREAMS
                    or self._active.get(identity, 0) >= MAX_NOTIFICATION_STREAMS_PER_IDENTITY):
                raise HTTPException(429, detail="Too many MCP notification streams", headers={"Retry-After": "5"})
            self._active[identity] = self._active.get(identity, 0) + 1
        released = False

        def release() -> None:
            nonlocal released
            with self._lock:
                if released:
                    return
                released = True
                remaining = self._active[identity] - 1
                if remaining:
                    self._active[identity] = remaining
                else:
                    self._active.pop(identity)

        try:
            fingerprint = await run_in_threadpool(snapshot)
        except BaseException:
            release()
            raise
        return _NotificationResponse(
            self._events(request, protocol_version, request_id, snapshot, fingerprint, tools_requested),
            release=release, media_type="text/event-stream",
            headers={"MCP-Protocol-Version": protocol_version, "Cache-Control": "no-cache, no-store",
                     "X-Accel-Buffering": "no"},
        )

    async def _events(
        self, request: Request, protocol_version: str, request_id: str | int | None,
        snapshot: Callable[[], str], fingerprint: str, tools_requested: bool,
    ) -> AsyncIterator[bytes]:
        modern = protocol_version == MCP_PROTOCOL_VERSION
        meta = {SUBSCRIPTION_ID_META_KEY: request_id} if modern else {}
        if modern:
            yield _sse({"jsonrpc": "2.0", "method": "notifications/subscriptions/acknowledged", "params": {
                "notifications": {"toolsListChanged": True} if tools_requested else {}, "_meta": meta,
            }})
        else:
            yield b": connected\n\n"
        started = last_heartbeat = time.monotonic()
        while tools_requested and time.monotonic() - started < NOTIFICATION_LIFETIME_SECONDS:
            await asyncio.sleep(NOTIFICATION_CHECK_SECONDS)
            if await request.is_disconnected():
                return
            try:
                current = await run_in_threadpool(snapshot)
            except Exception:
                # Authentication, policy and projection failures all close the
                # stream. Never serialize private errors, names or tool counts.
                return
            if current != fingerprint:
                fingerprint = current
                message: dict[str, Any] = {"jsonrpc": "2.0", "method": "notifications/tools/list_changed"}
                if modern:
                    message["params"] = {"_meta": meta}
                yield _sse(message)
            if time.monotonic() - last_heartbeat >= NOTIFICATION_HEARTBEAT_SECONDS:
                yield b": keepalive\n\n"
                last_heartbeat = time.monotonic()
        if modern:
            result = serialize_server_result("subscriptions/listen", protocol_version, {"resultType": "complete", "_meta": {
                **meta, "io.modelcontextprotocol/serverInfo": {"name": "lingshu_gate", "version": self.settings.version},
            }})
            yield _sse({"jsonrpc": "2.0", "id": request_id, "result": result})


def _sse(message: dict[str, Any]) -> bytes:
    return ("data: " + json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n\n").encode()

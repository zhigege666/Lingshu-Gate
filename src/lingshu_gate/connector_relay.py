"""Authenticated relay: fixed targets, isolated sessions, no business replay."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import secrets
import time
from contextlib import asynccontextmanager, suppress
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from lingshu_gate.service_io import ServiceConfigError
from lingshu_gate.connector_protocol import (
    FRAME_BYTES, IN_FLIGHT, REQUEST_BYTES, RESPONSE_BYTES, SESSION_TTL,
    ConnectorIdentity, Hello, HelloAck, RelayConfig, RelayRequest, RelayResponse,
    credential_hash, decode_body, encode_body, filtered_headers, parse_frame, request_rpc,
)


class RelayFailure(Exception):
    def __init__(self, code: str, status: int = 503, *, forwarded: bool = False):
        self.code, self.status, self.forwarded = code, status, forwarded


@dataclass(eq=False)
class AgentConnection:
    identity: ConnectorIdentity
    websocket: WebSocket
    targets: dict[str, str]
    generation: str = field(default_factory=lambda: secrets.token_hex(16))
    pending: dict[str, asyncio.Future[RelayResponse]] = field(default_factory=dict)
    pending_owners: dict[str, tuple[str, str]] = field(default_factory=dict)
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_seen: float = field(default_factory=time.monotonic)

    async def send(self, value: dict[str, Any], guard: Callable[[], None] | None = None) -> None:
        async with self.send_lock:
            if guard is not None:
                guard()
            await self.websocket.send_json(value)


@dataclass
class SavedSession:
    consumer: str
    target: str
    revision: str
    generation: str
    upstream: str
    deadline: float


class ConnectorRelay:
    def __init__(self, config: RelayConfig):
        self.config = config
        self.agents = {identity.id: identity for identity in config.agents}
        self.agent_hashes = {identity.id: credential_hash(identity.token_file) for identity in config.agents}
        self.consumers = {credential_hash(identity.token_file): identity for identity in config.consumers}
        values = [*self.agent_hashes.values(), *self.consumers]
        if len(values) != len(config.agents) + len(config.consumers) or len(set(values)) != len(values):
            raise ServiceConfigError("connector_credentials_must_be_distinct")
        self.connections: dict[str, AgentConnection] = {}
        self.targets: dict[str, AgentConnection] = {}
        self.sessions: dict[str, SavedSession] = {}
        self.reservations: dict[str, int] = {}
        self.handshakes = 0
        self.exchanges: dict[tuple[str, str], tuple[str, int, str | None]] = {}

    def record_exchange(self, consumer: ConnectorIdentity | None, target: str | None,
                        outcome: str, status: int, code: str | None) -> None:
        # Only configured pairs can allocate an entry (at most 64 x 64).
        if consumer is not None and target is not None and target in consumer.targets:
            self.exchanges[(consumer.id, target)] = (outcome, status, code)

    @staticmethod
    def bearer(scope: Mapping[str, Any]) -> str:
        values = [value for key, value in scope.get("headers", []) if key.lower() == b"authorization"]
        if (len(values) != 1 or not values[0].startswith(b"Bearer ") or not 39 <= len(values[0]) <= 4103
                or any(c < 33 or c > 126 for c in values[0][7:])):
            raise RelayFailure("connector_authentication_required", 401)
        return hashlib.sha256(values[0][7:]).hexdigest()

    def consumer(self, scope: Mapping[str, Any]) -> ConnectorIdentity:
        identity = self.consumers.get(self.bearer(scope))
        if identity is None:
            raise RelayFailure("connector_authentication_required", 401)
        return identity

    def prune(self) -> None:
        now = time.monotonic()
        for handle in [key for key, value in self.sessions.items() if value.deadline <= now]:
            del self.sessions[handle]

    def reserve(self, consumer: str) -> None:
        self.prune()
        occupied = sum(item.consumer == consumer for item in self.sessions.values())
        reserved = self.reservations.get(consumer, 0)
        if occupied + reserved >= 32 or len(self.sessions) + sum(self.reservations.values()) >= 1024:
            raise RelayFailure("connector_session_capacity", 429)
        self.reservations[consumer] = reserved + 1

    def session(self, handle: str, consumer: str, target: str, connection: AgentConnection) -> SavedSession:
        self.prune()
        saved = self.sessions.get(handle)
        if (saved is None or saved.consumer != consumer or saved.target != target
                or saved.generation != connection.generation or saved.revision != connection.targets[target]):
            raise RelayFailure("connector_session_unavailable", 404)
        return saved

    def forget(self, connection: AgentConnection) -> None:
        if self.connections.get(connection.identity.id) is connection:
            self.connections.pop(connection.identity.id, None)
        for target in connection.targets:
            if self.targets.get(target) is connection:
                self.targets.pop(target, None)
        for handle in [key for key, value in self.sessions.items() if value.generation == connection.generation]:
            del self.sessions[handle]
        for future in connection.pending.values():
            if not future.done():
                future.set_exception(RelayFailure("connector_disconnected_result_unknown", forwarded=True))

    async def agent(self, websocket: WebSocket) -> None:
        connection: AgentConnection | None = None
        reserved = False
        try:
            supplied = self.bearer(websocket.scope)
            ids = websocket.headers.getlist("x-gate-agent-id")
            identity = self.agents.get(ids[0]) if len(ids) == 1 else None
            if identity is None or not hmac.compare_digest(supplied, self.agent_hashes[identity.id]):
                raise RelayFailure("connector_authentication_required", 401)
            if identity.id in self.connections or self.handshakes >= 32:
                raise RelayFailure("connector_agent_already_connected_or_busy", 409)
            self.handshakes += 1
            reserved = True
            await websocket.accept()
            hello = parse_frame(await asyncio.wait_for(websocket.receive_text(), 5), Hello, limit=16384)
            if not set(hello.targets).issubset(identity.targets):
                raise RelayFailure("connector_target_not_allowed", 403)
            if identity.id in self.connections or any(target in self.targets for target in hello.targets):
                raise RelayFailure("connector_target_already_connected", 409)
            connection = AgentConnection(identity, websocket, hello.targets)
            self.connections[identity.id] = connection
            self.targets.update(dict.fromkeys(hello.targets, connection))
            self.handshakes -= 1
            reserved = False
            await connection.send(HelloAck(generation=connection.generation).model_dump())
            while True:
                raw = await asyncio.wait_for(websocket.receive_text(), 35)
                if len(raw) > FRAME_BYTES:
                    raise ServiceConfigError("connector_frame_size_limit")
                if raw == '{"kind":"heartbeat"}':
                    connection.last_seen = time.monotonic()
                    await connection.send({"kind": "heartbeat_ack"})
                    continue
                reply = parse_frame(raw, RelayResponse)
                # The connection object owns this future; a frame cannot claim
                # another generation or complete a request after its timeout.
                future = connection.pending.get(reply.request_id)
                connection.last_seen = time.monotonic()
                if future is not None and not future.done():
                    future.set_result(reply)
        except (RelayFailure, ServiceConfigError, TimeoutError, WebSocketDisconnect, RuntimeError, ValueError, KeyError, TypeError):
            with suppress(RuntimeError, OSError):
                await websocket.close(code=1008)
        finally:
            if reserved:
                self.handshakes -= 1
            if connection is not None:
                self.forget(connection)

    async def forward(self, request: Request) -> Response:
        forwarded = False
        state = request.scope.setdefault("state", {})
        deadline = min(time.monotonic() + 60, state.get("connector_deadline", float("inf")))
        reserved = False
        connection: AgentConnection | None = None
        request_id: str | None = None
        consumer: ConnectorIdentity | None = None
        target: str | None = None
        try:
            consumer = self.consumer(request.scope)
            target = request.path_params["target"]
            if target not in consumer.targets:
                raise RelayFailure("connector_target_unavailable", 404)
            connection = self.targets.get(target)
            if connection is None:
                raise RelayFailure("connector_target_offline", 503)
            if len(connection.pending) >= IN_FLIGHT or sum(len(c.pending) for c in self.connections.values()) >= 64:
                raise RelayFailure("connector_busy", 429)
            headers = filtered_headers(list(request.headers.items()))
            if request.headers.get("content-encoding", "identity") != "identity":
                raise RelayFailure("connector_content_encoding_unsupported", 415)
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > REQUEST_BYTES:
                    raise RelayFailure("connector_request_size_limit", 413)
            handle = headers.pop("mcp-session-id", "")
            saved = self.session(handle, consumer.id, target, connection) if handle else None
            if request.method == "DELETE":
                if saved is None or body:
                    raise RelayFailure("connector_session_unavailable", 404)
                # Further calls cannot reuse a handle whose deletion is pending.
                self.sessions.pop(handle, None)
            else:
                if headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise RelayFailure("connector_json_required", 415)
                rpc = request_rpc(bytes(body))
                if "mcp-method" in headers and headers["mcp-method"] != rpc["method"]:
                    raise RelayFailure("connector_method_header_mismatch", 400)
                if saved is None and rpc["method"] in {"initialize", "server/discover"}:
                    self.reserve(consumer.id)
                    reserved = True
            if saved is not None:
                headers["mcp-session-id"] = saved.upstream
            # Reading the incoming body may yield. Recheck admission just before
            # dispatch rather than retaining a stale free slot or connection.
            if self.targets.get(target) is not connection:
                raise RelayFailure("connector_target_offline")
            if len(connection.pending) >= IN_FLIGHT or sum(len(c.pending) for c in self.connections.values()) >= 64:
                raise RelayFailure("connector_busy", 429)
            request_id = secrets.token_hex(16)
            future: asyncio.Future[RelayResponse] = asyncio.get_running_loop().create_future()
            connection.pending[request_id] = future
            connection.pending_owners[request_id] = (consumer.id, target)
            frame = RelayRequest(request_id=request_id, target_id=target, revision=connection.targets[target],
                method="DELETE" if request.method == "DELETE" else "POST", timeout_ms=60000,
                expires_at_ms=int(time.time() * 1000) + max(1, int((deadline - time.monotonic()) * 1000)),
                headers=headers, body=encode_body(bytes(body)))
            wire = frame.model_dump()
            selected_connection = connection
            def dispatch_guard() -> None:
                nonlocal forwarded
                if self.targets.get(target) is not selected_connection:
                    raise RelayFailure("connector_target_offline")
                if saved is not None and request.method != "DELETE" and (
                        self.sessions.get(handle) is not saved or saved.deadline <= time.monotonic()):
                    raise RelayFailure("connector_session_unavailable", 404)
                remaining = int((deadline - time.monotonic()) * 1000)
                if remaining < 1:
                    raise RelayFailure("connector_dispatch_deadline")
                if saved is not None and request.method != "DELETE":
                    # A dispatched call is activity. Queueing alone must not
                    # keep an idle session alive, and DELETE/forget still win.
                    saved.deadline = time.monotonic() + SESSION_TTL
                wire["timeout_ms"] = min(60000, remaining)
                wire["expires_at_ms"] = int(time.time() * 1000) + remaining
                forwarded = True
                state["connector_dispatched"] = True
            # A send failure cannot prove that the remote side received nothing.
            async with asyncio.timeout_at(deadline):
                await connection.send(wire, dispatch_guard)
                reply = await future
            if self.targets.get(target) is not connection:
                raise RelayFailure("connector_disconnected_result_unknown", forwarded=True)
            response_headers = filtered_headers(list(reply.headers.items()), response=True)
            if len(response_headers) != len(reply.headers):
                raise ServiceConfigError("connector_response_headers_invalid")
            response_body = decode_body(reply.body, RESPONSE_BYTES)
            upstream = response_headers.pop("mcp-session-id", None)
            if upstream and (len(upstream) > 512 or not upstream or any(ord(c) < 33 or ord(c) > 126 for c in upstream)):
                raise ServiceConfigError("connector_upstream_session_invalid")
            self.record_exchange(consumer, target, reply.outcome, reply.status,
                                 reply.error_code or ("connector_upstream_http_error" if reply.status >= 400 else None))
            if request.method == "DELETE":
                if reply.status == 405:
                    self.record_exchange(consumer, target, reply.outcome, 405, "connector_upstream_delete_unsupported")
                    return JSONResponse({"code": "connector_upstream_delete_unsupported", "local_session_released": True,
                                         "upstream_stopped": False}, status_code=405)
            elif upstream and reply.status < 300:
                if saved is not None:
                    if self.sessions.get(handle) is not saved:
                        raise RelayFailure("connector_session_unavailable", 404, forwarded=True)
                    saved.upstream, saved.deadline = upstream, time.monotonic() + SESSION_TTL
                elif reserved and reply.status < 300:
                    handle = secrets.token_urlsafe(32)
                    self.sessions[handle] = SavedSession(consumer.id, target, connection.targets[target],
                        connection.generation, upstream, time.monotonic() + SESSION_TTL)
                else:
                    raise ServiceConfigError("connector_unexpected_upstream_session")
                assert handle
                response_headers["mcp-session-id"] = handle
            if saved is not None and request.method != "DELETE" and self.sessions.get(handle) is saved:
                if reply.status == 404:
                    self.sessions.pop(handle, None)
                else:
                    saved.deadline = time.monotonic() + SESSION_TTL
            return Response(response_body, status_code=reply.status, headers=response_headers)
        except RelayFailure as error:
            self.record_exchange(consumer, target, "unknown" if forwarded or error.forwarded else "not_forwarded", error.status, error.code)
            return JSONResponse({"code": error.code, "execution": "unknown" if forwarded or error.forwarded else "not_forwarded"},
                status_code=error.status, headers={"WWW-Authenticate": "Bearer"} if error.status == 401 else {})
        except (ServiceConfigError, TimeoutError, ValueError, RuntimeError, OSError):
            self.record_exchange(consumer, target, "unknown" if forwarded else "not_forwarded", 502 if forwarded else 400, "connector_exchange_failed")
            return JSONResponse({"code": "connector_exchange_failed", "execution": "unknown" if forwarded else "not_forwarded"},
                                status_code=502 if forwarded else 400)
        finally:
            if connection is not None and request_id is not None:
                pending = connection.pending.pop(request_id, None)
                connection.pending_owners.pop(request_id, None)
                if pending is not None and not pending.done():
                    pending.cancel()
            if reserved and consumer is not None:
                remaining = self.reservations[consumer.id] - 1
                if remaining:
                    self.reservations[consumer.id] = remaining
                else:
                    self.reservations.pop(consumer.id, None)

    async def status(self, request: Request) -> Response:
        try:
            consumer = self.consumer(request.scope)
        except RelayFailure as error:
            return JSONResponse({"code": error.code}, status_code=error.status, headers={"WWW-Authenticate": "Bearer"})
        self.prune()
        targets = []
        for target in consumer.targets:
            connection = self.targets.get(target)
            last = self.exchanges.get((consumer.id, target))
            targets.append({"target_id": target, "connected": connection is not None,
                "last_heartbeat_seconds": round(time.monotonic() - connection.last_seen, 1) if connection else None,
                "in_flight": sum(owner == (consumer.id, target) for owner in connection.pending_owners.values()) if connection else 0,
                "last_exchange": last[0] if last else None,
                "last_status": last[1] if last else None,
                "last_error_code": last[2] if last else None})
        return JSONResponse({"schema_version": 1, "targets": targets,
            "sessions": sum(item.consumer == consumer.id for item in self.sessions.values()),
            "configuration_updates": "restart_required"}, headers={"Cache-Control": "no-store"})

    async def maintain(self) -> None:
        while True:
            await asyncio.sleep(10)
            self.prune()
            for connection in list(self.connections.values()):
                if time.monotonic() - connection.last_seen > 35:
                    self.forget(connection)
                    with suppress(RuntimeError, OSError):
                        await connection.websocket.close(code=1001)


class RelayBoundary:
    """Apply Host/Origin and body-time bounds before HTTP or WebSocket dispatch."""
    def __init__(self, app, config: RelayConfig):
        self.app, self.config = app, config

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        hosts = [value.decode("latin1").lower() for key, value in scope.get("headers", []) if key.lower() == b"host"]
        origins = [value.decode("latin1") for key, value in scope.get("headers", []) if key.lower() == b"origin"]
        if len(hosts) != 1 or hosts[0] not in self.config.allowed_hosts or origins and (
                len(origins) != 1 or origins[0] not in self.config.allowed_origins):
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await JSONResponse({"code": "connector_host_or_origin_rejected"}, status_code=403)(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return
        started = False
        state = scope.setdefault("state", {})
        state["connector_deadline"] = time.monotonic() + 65
        state["connector_dispatched"] = False
        async def bounded_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)
        try:
            async with asyncio.timeout(65):
                await self.app(scope, receive, bounded_send)
        except TimeoutError:
            if not started:
                await JSONResponse({"code": "connector_deadline_exceeded",
                                    "execution": "unknown" if state["connector_dispatched"] else "not_forwarded"},
                                   status_code=504)(scope, receive, send)


def create_relay_app(config: RelayConfig):
    relay = ConnectorRelay(config)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(relay.maintain())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            for connection in list(relay.connections.values()):
                relay.forget(connection)
                with suppress(RuntimeError, OSError):
                    await connection.websocket.close(code=1001)
            relay.sessions.clear()

    app = Starlette(routes=[
        WebSocketRoute("/connector/agent", relay.agent),
        Route("/connector/mcp/{target}", relay.forward, methods=["POST", "DELETE"]),
        Route("/connector/status", relay.status, methods=["GET"]),
    ], lifespan=lifespan)
    app.state.connector_relay = relay
    return RelayBoundary(app, config)

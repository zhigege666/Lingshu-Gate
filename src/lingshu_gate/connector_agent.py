"""Outbound-only connector agent. Every business request is attempted once."""
from __future__ import annotations

import asyncio
import json
import ssl
import time
from pathlib import Path
from typing import Any

import httpx2
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from lingshu_gate.service_io import ServiceConfigError, bounded, canonical, secret_file, unique_pairs
from lingshu_gate.connector_protocol import (
    FRAME_BYTES, IN_FLIGHT, REQUEST_BYTES, RESPONSE_BYTES,
    AgentConfig, Hello, HelloAck, RelayRequest, RelayResponse, SseReply, credential_hash,
    decode_body, encode_body, failure_response, filtered_headers, parse_frame, request_rpc, response_matches,
)


class NoRedirectConnect(connect):
    # websockets 15 follows redirects even when using the single connect
    # context manager. Reject in its redirect hook, not its retry classifier.
    def process_redirect(self, exc: Exception) -> Exception:
        return exc


class ConnectorAgent:
    def __init__(self, config: AgentConfig, *, transport: Any = None):
        self.config, self.transport = config, transport
        self.targets = {target.id: target for target in config.targets}
        credential_hash(config.token_file)
        self.relay_tls = ssl.create_default_context(cafile=config.ca_file)
        self.target_tls = {target.id: ssl.create_default_context(cafile=target.ca_file) for target in config.targets}
        for target in config.targets:
            if target.token_file:
                secret_file(Path(target.token_file))

    async def exchange(self, frame: RelayRequest) -> RelayResponse:
        forwarded = False
        try:
            remaining = min(frame.timeout_ms, frame.expires_at_ms - int(time.time() * 1000)) / 1000
            if remaining <= 0:
                raise ServiceConfigError("connector_request_expired")
            deadline = time.monotonic() + remaining
            target = self.targets.get(frame.target_id)
            if target is None or frame.revision != target.revision:
                raise ServiceConfigError("connector_target_contract_unavailable")
            headers = filtered_headers(list(frame.headers.items()))
            if len(headers) != len(frame.headers):
                raise ServiceConfigError("connector_request_headers_invalid")
            body = decode_body(frame.body, REQUEST_BYTES)
            rpc = request_rpc(body) if frame.method == "POST" else None
            if frame.method == "DELETE" and (body or not headers.get("mcp-session-id")):
                raise ServiceConfigError("connector_delete_requires_session")
            if rpc and "mcp-method" in headers and headers["mcp-method"] != rpc["method"]:
                raise ServiceConfigError("connector_method_header_mismatch")
            headers["accept-encoding"] = "identity"
            if target.token_file:
                headers["authorization"] = "Bearer " + secret_file(Path(target.token_file))
            deadline = min(deadline, time.monotonic() + target.timeout_seconds)
            timeout = min(deadline - time.monotonic(), (frame.expires_at_ms - int(time.time() * 1000)) / 1000)
            if timeout <= 0:
                raise ServiceConfigError("connector_request_expired")
            # One client per exchange prevents cookies or consumer-specific
            # transport state from carrying over to another request.
            async with asyncio.timeout_at(deadline), httpx2.AsyncClient(verify=self.target_tls[target.id],
                    trust_env=False, follow_redirects=False, timeout=timeout, transport=self.transport) as client:
                if time.monotonic() >= deadline or time.time() * 1000 >= frame.expires_at_ms:
                    raise ServiceConfigError("connector_request_expired")
                forwarded = True
                async with client.stream(frame.method, target.url, headers=headers, content=body) as response:
                    if 300 <= response.status_code < 400:
                        raise ServiceConfigError("connector_upstream_redirect_rejected")
                    if response.headers.get("content-encoding", "identity").lower() != "identity" and response.status_code >= 400:
                        return RelayResponse(request_id=frame.request_id, status=response.status_code,
                            error_code="connector_upstream_http_error",
                            headers={"content-type": "application/json"}, body=encode_body(canonical(
                                {"code": "connector_upstream_http_error", "upstream_status": response.status_code})))
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise ServiceConfigError("connector_upstream_encoding_unsupported")
                    returned = filtered_headers(list(response.headers.multi_items()), response=True)
                    media = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                    payload = bytearray()
                    parser = SseReply(rpc["id"]) if response.status_code < 300 and media == "text/event-stream" and rpc and "id" in rpc else None
                    if response.status_code < 300 and media == "text/event-stream" and parser is None:
                        raise ServiceConfigError("connector_sse_without_request_id")
                    async for chunk in response.aiter_bytes():
                        if parser is not None:
                            selected = parser.feed(chunk)
                            if selected is not None:
                                returned["content-type"] = "application/json"
                                return RelayResponse(request_id=frame.request_id, status=response.status_code,
                                    headers=returned, body=encode_body(selected))
                        else:
                            payload.extend(chunk)
                            if len(payload) > RESPONSE_BYTES:
                                raise ServiceConfigError("connector_response_size_limit")
                    if parser is not None:
                        raise ServiceConfigError("connector_matching_response_unavailable")
                    if response.status_code >= 400:
                        if payload:
                            try:
                                if media != "application/json":
                                    raise ValueError
                                bounded(json.loads(payload, object_pairs_hook=unique_pairs), max_nodes=100000)
                            except (ValueError, UnicodeError, RecursionError):
                                payload = bytearray(canonical({"code": "connector_upstream_http_error",
                                                              "upstream_status": response.status_code}))
                                returned["content-type"] = "application/json"
                        return RelayResponse(request_id=frame.request_id, status=response.status_code,
                            headers=returned, body=encode_body(bytes(payload)), error_code="connector_upstream_http_error")
                    if payload:
                        if media != "application/json":
                            raise ServiceConfigError("connector_upstream_media_unsupported")
                        value = json.loads(payload, object_pairs_hook=unique_pairs)
                        bounded(value, max_nodes=100000)
                        if rpc and "id" in rpc and not response_matches(value, rpc["id"]):
                            raise ServiceConfigError("connector_response_id_mismatch")
                    elif rpc and "id" in rpc:
                        raise ServiceConfigError("connector_matching_response_unavailable")
                    return RelayResponse(request_id=frame.request_id, status=response.status_code,
                        headers=returned, body=encode_body(bytes(payload)))
        except ServiceConfigError as error:
            return failure_response(frame.request_id, error.code, forwarded=forwarded)
        except (TimeoutError, httpx2.TimeoutException):
            return failure_response(frame.request_id, "connector_upstream_timeout_result_unknown", forwarded=forwarded)
        except (httpx2.HTTPError, OSError, ValueError, UnicodeError, RecursionError):
            return failure_response(frame.request_id, "connector_upstream_unavailable_result_unknown", forwarded=forwarded)

    async def connection(self) -> None:
        headers = {"Authorization": "Bearer " + secret_file(Path(self.config.token_file)),
                   "X-Gate-Agent-Id": self.config.agent_id}
        options: dict[str, Any] = {"ssl": self.relay_tls} if self.config.relay_url.startswith("wss:") else {}
        async with NoRedirectConnect(self.config.relay_url, additional_headers=headers, proxy=None, compression=None,
                open_timeout=10, ping_interval=15, ping_timeout=10, close_timeout=2, max_size=FRAME_BYTES,
                max_queue=4, **options) as websocket:
            await websocket.send(Hello(targets={key: target.revision for key, target in self.targets.items()}).model_dump_json())
            parse_frame(await asyncio.wait_for(websocket.recv(), 5), HelloAck, limit=4096)
            pending: dict[str, asyncio.Task[None]] = {}
            send_lock = asyncio.Lock()

            async def send(raw: str) -> None:
                async with send_lock:
                    await websocket.send(raw)

            async def heartbeat() -> None:
                while True:
                    await asyncio.sleep(10)
                    await send('{"kind":"heartbeat"}')

            async def deliver(frame: RelayRequest) -> None:
                try:
                    reply = await self.exchange(frame)
                    await send(reply.model_dump_json())
                except (ConnectionClosed, OSError):
                    pass  # Never retry an exchange after an uncertain send.
                finally:
                    pending.pop(frame.request_id, None)

            beats = asyncio.create_task(heartbeat())
            try:
                while True:
                    raw = await asyncio.wait_for(websocket.recv(), 40)
                    if raw == '{"kind":"heartbeat_ack"}':
                        continue
                    frame = parse_frame(raw, RelayRequest)
                    if len(pending) >= IN_FLIGHT or frame.request_id in pending:
                        raise ServiceConfigError("connector_request_capacity_or_duplicate")
                    pending[frame.request_id] = asyncio.create_task(deliver(frame))
            finally:
                beats.cancel()
                tasks = [beats, *pending.values()]
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)

    async def run(self) -> None:
        delay = 1
        while True:
            try:
                await self.connection()
                delay = 1
            except InvalidStatus as error:
                if 300 <= error.response.status_code < 500:
                    raise ServiceConfigError("connector_relay_handshake_rejected") from None
            except (ConnectionClosed, TimeoutError, OSError):
                pass
            # Reconnect only the transport. No business frame survives the
            # connection coroutine, and no previous request is replayed.
            print('{"event":"connector_reconnect_scheduled"}', flush=True)
            await asyncio.sleep(delay)
            delay = min(30, delay * 2)

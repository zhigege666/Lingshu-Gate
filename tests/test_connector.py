"""Real loopback HTTP + WebSocket acceptance for the standalone connector."""
from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import replace

import httpx2
import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route, WebSocketRoute

from lingshu_gate.service_io import ServiceConfigError, canonical
from lingshu_gate.connector_agent import ConnectorAgent, NoRedirectConnect
from lingshu_gate.connector_protocol import (
    AgentConfig, AgentTarget, ConnectorIdentity, RelayConfig, RelayRequest, RelayResponse, SseReply, encode_body, parse_model,
)
from lingshu_gate.connector_relay import AgentConnection, ConnectorRelay, RelayFailure, SavedSession, create_relay_app


@contextmanager
def listener(factory):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    app = factory(port)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="critical",
        access_log=False, forwarded_allow_ips="", lifespan="on", timeout_graceful_shutdown=1,
        ws_max_size=12 * 1024 * 1024, ws_per_message_deflate=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    try:
        yield f"http://127.0.0.1:{port}", app
    finally:
        server.should_exit = True
        thread.join(4)
        if thread.is_alive():
            server.force_exit = True
            thread.join(2)
        sock.close()
        assert not thread.is_alive()


def private(tmp_path, name, value):
    path = tmp_path / name
    path.write_text(value)
    path.chmod(0o600)
    return str(path)


@pytest.fixture
def connector(tmp_path):
    state = {"calls": [], "writes": 0, "sessions": 0, "sentinel": 0, "closed_streams": 0}
    agent_token, first, second = "a" * 40, "b" * 40, "c" * 40
    upstream = "synthetic-upstream-credential"
    paths = {name: private(tmp_path, name, value) for name, value in
             (("agent", agent_token), ("first", first), ("second", second), ("upstream", upstream))}

    async def peer(request):
        if request.url.path == "/sentinel":
            state["sentinel"] += 1
            return Response(status_code=204)
        if request.method == "DELETE":
            state["calls"].append({"method": "DELETE", "headers": dict(request.headers)})
            return Response("Synthetic upstream does not support deletion", status_code=405, media_type="text/plain")
        raw = await request.body()
        rpc = json.loads(raw)
        state["calls"].append({"method": rpc["method"], "raw": raw, "headers": dict(request.headers)})
        if rpc["method"] == "initialize":
            state["sessions"] += 1
            return JSONResponse({"jsonrpc": "2.0", "id": rpc["id"], "result": {"protocolVersion": "2025-06-18",
                "capabilities": {"tools": {}}, "serverInfo": {"name": "synthetic", "version": "1"}}},
                headers={"Mcp-Session-Id": f"upstream-private-session-{state['sessions']}", "Set-Cookie": "private=do-not-forward"})
        if rpc["method"] == "notifications/initialized":
            return Response(status_code=202)
        params = rpc.get("params", {})
        action = params.get("arguments", {}).get("action")
        if rpc["method"] == "tools/call":
            state["writes"] += 1
        reply = {"jsonrpc": "2.0", "id": rpc.get("id"), "result": {"content": [{"type": "text", "text": "completed"}]}}
        if action == "redirect":
            return Response(status_code=307, headers={"Location": "/sentinel"})
        if action == "oversize":
            return Response(b"x" * (8 * 1024 * 1024 + 1), media_type="application/json")
        if action in {"http401", "http404"}:
            return Response("synthetic private error detail", status_code=int(action[4:]), media_type="text/plain")
        if action == "empty":
            return Response(status_code=202)
        if action == "timeout":
            await asyncio.sleep(4)
        if action == "sse":
            async def stream():
                try:
                    yield b": keepalive\r\n\r\n"
                    yield b"data: " + canonical({"jsonrpc": "2.0", "id": rpc["id"], "method": "elicitation/create", "params": {}}) + b"\n\n"
                    yield b"data: " + canonical({"jsonrpc": "2.0", "method": "notifications/message", "params": {}}) + b"\n\n"
                    yield b"data: " + canonical(reply) + b"\n\n"
                    await asyncio.sleep(30)
                finally:
                    state["closed_streams"] += 1
            return StreamingResponse(stream(), media_type="text/event-stream")
        return JSONResponse(reply, headers={"Set-Cookie": "private=do-not-forward"})

    with listener(lambda _: Starlette(routes=[Route("/mcp", peer, methods=["POST", "DELETE"]), Route("/sentinel", peer)])) as (upstream_url, _):
        def relay_factory(port):
            config = RelayConfig(port=port, agents=[ConnectorIdentity(id="private-agent", token_file=paths["agent"], targets=["private-mcp"])],
                consumers=[ConnectorIdentity(id=name, token_file=paths[name], targets=["private-mcp"]) for name in ("first", "second")])
            return create_relay_app(config)
        with listener(relay_factory) as (url, app):
            config = AgentConfig(agent_id="private-agent", relay_url=url.replace("http:", "ws:") + "/connector/agent", token_file=paths["agent"],
                targets=[AgentTarget(id="private-mcp", url=upstream_url + "/mcp", token_file=paths["upstream"], timeout_seconds=2)])
            yield {"url": url, "agent": ConnectorAgent(config), "relay": app.app.state.connector_relay, "state": state,
                   "first": first, "second": second, "upstream": upstream, "paths": paths}


@asynccontextmanager
async def connected(connector):
    task = asyncio.create_task(connector["agent"].connection())
    async with httpx2.AsyncClient(timeout=8, trust_env=False) as client:
        headers = {"Authorization": "Bearer " + connector["first"]}
        try:
            for _ in range(100):
                if task.done():
                    task.result()
                    pytest.fail("Agent exited before connecting")
                status = await client.get(connector["url"] + "/connector/status", headers=headers)
                if status.json()["targets"][0]["connected"]:
                    break
                await asyncio.sleep(0.01)
            else:
                pytest.fail("Agent did not register")
            yield client, headers
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


def rpc(method="tools/call", *, params=None, identifier=1):
    result = {"jsonrpc": "2.0", "method": method, "params": params or {}}
    if identifier is not None:
        result["id"] = identifier
    return result


def test_real_forwarding_preserves_protocol_and_isolates_session_and_headers(connector):
    async def run():
        async with connected(connector) as (client, authorization):
            url = connector["url"] + "/connector/mcp/private-mcp"
            headers = {**authorization, "Content-Type": "application/json"}
            current = rpc("server/discover", params={"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientInfo": {"name": "synthetic", "version": "1"}}})
            response = await client.post(url, headers={**headers, "Mcp-Method": "server/discover", "Mcp-Protocol-Version": "2026-07-28",
                "Cookie": "consumer-secret=never-forward", "X-Untrusted": "drop"}, content=canonical(current))
            assert response.status_code == 200 and "set-cookie" not in response.headers
            recorded = connector["state"]["calls"][-1]
            assert recorded["raw"] == canonical(current)
            assert recorded["headers"]["mcp-method"] == "server/discover"
            assert recorded["headers"]["authorization"] == "Bearer " + connector["upstream"]
            assert "cookie" not in recorded["headers"] and "x-untrusted" not in recorded["headers"]
            initialized = await client.post(url, headers=headers, json=rpc("initialize"))
            handle = initialized.headers["mcp-session-id"]
            assert len(handle) == 43 and "upstream" not in handle and "set-cookie" not in initialized.headers
            owned = {**headers, "Mcp-Session-Id": handle}
            result = await client.post(url, headers=owned, json=rpc("notifications/initialized", identifier=None))
            assert result.status_code == 202 and result.content == b""
            assert connector["state"]["calls"][-1]["headers"]["mcp-session-id"].startswith("upstream-private-session-")
            count = len(connector["state"]["calls"])
            foreign = await client.post(url, headers={**owned, "Authorization": "Bearer " + connector["second"]}, json=rpc())
            assert foreign.status_code == 404 and len(connector["state"]["calls"]) == count
            deleted = await client.delete(url, headers=owned)
            assert deleted.status_code == 405 and deleted.json()["local_session_released"] is True
            assert deleted.json()["upstream_stopped"] is False
            count = len(connector["state"]["calls"])
            assert (await client.post(url, headers=owned, json=rpc())).status_code == 404
            assert len(connector["state"]["calls"]) == count
    asyncio.run(run())


@pytest.mark.parametrize("action", ["sse", "redirect", "oversize", "timeout", "http401", "http404", "empty"])
def test_sse_finishes_without_eof_and_failed_calls_never_replay(connector, action):
    async def run():
        async with connected(connector) as (client, headers):
            start = time.monotonic()
            result = await client.post(connector["url"] + "/connector/mcp/private-mcp", headers=headers,
                json=rpc(params={"name": "write", "arguments": {"action": action}}))
            if action == "sse":
                assert result.status_code == 200 and result.json()["result"]["content"][0]["text"] == "completed"
                assert time.monotonic() - start < 1.5
                for _ in range(50):
                    if connector["state"]["closed_streams"]:
                        break
                    await asyncio.sleep(0.01)
                assert connector["state"]["closed_streams"] == 1
            elif action.startswith("http"):
                assert result.status_code == int(action[4:])
                assert result.json()["upstream_status"] == result.status_code
                assert "private error" not in result.text
            else:
                assert result.status_code == 502 and result.json()["execution"] == "unknown"
            assert connector["state"]["writes"] == 1 and connector["state"]["sentinel"] == 0
    asyncio.run(run())


def test_old_generation_and_expired_sessions_never_reach_upstream(connector):
    async def run():
        url = connector["url"] + "/connector/mcp/private-mcp"
        async with connected(connector) as (client, headers):
            reply = await client.post(url, headers=headers, json=rpc("initialize"))
            old = reply.headers["mcp-session-id"]
            second = await client.post(url, headers=headers, json=rpc("initialize"))
            expired = second.headers["mcp-session-id"]
            connector["relay"].sessions[expired].deadline = 0
            count = len(connector["state"]["calls"])
            assert (await client.post(url, headers={**headers, "Mcp-Session-Id": expired}, json=rpc())).status_code == 404
            assert len(connector["state"]["calls"]) == count
        for _ in range(100):
            if not connector["relay"].connections:
                break
            await asyncio.sleep(0.01)
        async with connected(connector) as (client, headers):
            count = len(connector["state"]["calls"])
            assert (await client.post(url, headers={**headers, "Mcp-Session-Id": old}, json=rpc())).status_code == 404
            assert len(connector["state"]["calls"]) == count
    asyncio.run(run())


def test_relay_authentication_target_and_http_websocket_origin_boundary(connector):
    async def run():
        async with connected(connector) as (client, headers):
            url = connector["url"]
            assert (await client.get(url + "/connector/status")).status_code == 401
            assert (await client.get(url + "/connector/status", headers={**headers, "Origin": "https://other.example"})).status_code == 403
            assert (await client.get(url + "/connector/status", headers={**headers, "Host": "other.example"})).status_code == 403
            assert (await client.post(url + "/connector/mcp/unknown", headers=headers, json=rpc())).status_code == 404
            from websockets.exceptions import InvalidStatus
            with pytest.raises(InvalidStatus) as denied:
                async with NoRedirectConnect(url.replace("http:", "ws:") + "/connector/agent", proxy=None, origin="https://other.example"):
                    pytest.fail("Cross-origin WebSocket accepted")
            assert denied.value.response.status_code == 403
            assert connector["state"]["calls"] == []
    asyncio.run(run())


def test_session_reservations_are_counted_before_creation(connector):
    relay: ConnectorRelay = connector["relay"]
    for _ in range(32):
        relay.reserve("first")
    with pytest.raises(RelayFailure):
        relay.reserve("first")
    relay.reservations.clear()
    sample = SavedSession("first", "private-mcp", "a" * 64, "b" * 32, "private", time.monotonic() + 3600)
    relay.sessions = {str(i): replace(sample, consumer=f"owner-{i}") for i in range(1024)}
    with pytest.raises(RelayFailure):
        relay.reserve("first")


@pytest.mark.parametrize("value", [
    {"agent_id": "a", "token_file": "token", "relay_url": "ws://public.example/connector/agent", "targets": []},
    {"id": "target", "url": "https://example.test/mcp?destination=http://other.example"},
    {"id": "target", "url": "http://192.168.20.2/mcp"},
])
def test_fixed_target_trust_rejects_ambient_destinations(value):
    with pytest.raises(ServiceConfigError):
        parse_model(AgentConfig if "agent_id" in value else AgentTarget, value)


def test_sse_exact_id_type_skips_reverse_requests_and_partial_utf8():
    parser = SseReply(1)
    wrong = {"jsonrpc": "2.0", "id": True, "result": {}}
    reverse = {"jsonrpc": "2.0", "id": 1, "method": "elicitation/create", "params": {}}
    wanted = {"jsonrpc": "2.0", "id": 1, "result": {"text": "精确原文🌏"}}
    raw = b"".join(b"data: " + canonical(value) + b"\r\n\r\n" for value in (wrong, reverse, wanted))
    result = None
    for byte in raw:
        response = parser.feed(bytes([byte]))
        if response is not None:
            result = response
    assert result == canonical(wanted)


@pytest.mark.parametrize("separator", [b"\r", b"\n", b"\r\n"])
@pytest.mark.parametrize("bom", [b"", b"\xef\xbb\xbf"])
def test_sse_complete_event_never_requires_eof_or_another_byte(separator, bom):
    wanted = canonical({"jsonrpc": "2.0", "id": 1, "result": {"text": "原文"}})
    stream = bom + b"data: " + wanted + separator + separator
    parser = SseReply(1)
    found = None
    for byte in stream:
        found = parser.feed(bytes([byte])) or found
    assert found == wanted


def test_frame_expired_in_transit_never_starts_http(connector):
    async def run():
        agent = connector["agent"]
        target = agent.config.targets[0]
        frame = RelayRequest(request_id="a" * 32, target_id=target.id, revision=target.revision, method="POST",
            timeout_ms=20, expires_at_ms=int(time.time() * 1000) - 1, headers={"content-type": "application/json"},
            body=encode_body(canonical(rpc())))
        result = await agent.exchange(frame)
        assert result.status == 503 and result.outcome == "not_forwarded"
        assert connector["state"]["calls"] == []
    asyncio.run(run())


def test_large_sse_line_in_small_chunks_has_bounded_processing_cost():
    wanted = canonical({"jsonrpc": "2.0", "id": 1, "result": {"text": "x" * (1024 * 1024)}})
    stream = b"data: " + wanted + b"\n\n"
    parser = SseReply(1)
    started = time.process_time()
    found = None
    for offset in range(0, len(stream), 256):
        found = parser.feed(stream[offset:offset + 256]) or found
    assert found == SseReply(1).feed(stream) == wanted
    assert time.process_time() - started < 2.0


@pytest.mark.parametrize("queued", [False, True])
def test_session_activity_begins_at_dispatch_and_queueing_does_not_extend_ttl(tmp_path, queued):
    async def run():
        config = RelayConfig(agents=[ConnectorIdentity(id="agent", token_file=private(tmp_path, "agent", "a" * 40), targets=["target"])],
            consumers=[ConnectorIdentity(id="owner", token_file=private(tmp_path, "owner", "b" * 40), targets=["target"])])
        relay = ConnectorRelay(config)
        sent = []

        class Wire:
            async def send_json(self, frame):
                sent.append(frame)
                await asyncio.sleep(0.02)
                relay.prune()
                connection.pending[frame["request_id"]].set_result(RelayResponse(request_id=frame["request_id"], status=200,
                    headers={"content-type": "application/json", "mcp-session-id": "private"},
                    body=encode_body(canonical({"jsonrpc": "2.0", "id": 1, "result": {}}))))

        connection = AgentConnection(config.agents[0], Wire(), {"target": "a" * 64})
        relay.targets["target"] = connection
        relay.connections["agent"] = connection
        saved = SavedSession("owner", "target", "a" * 64, connection.generation, "private", time.monotonic() + (1 if queued else 0.01))
        relay.sessions["owned"] = saved
        async def receive():
            return {"type": "http.request", "body": canonical(rpc()), "more_body": False}
        request = Request({"type": "http", "method": "POST", "path": "/connector/mcp/target", "path_params": {"target": "target"},
            "headers": [(b"authorization", b"Bearer " + b"b" * 40), (b"content-type", b"application/json"),
                        (b"mcp-session-id", b"owned")]}, receive)
        if queued:
            await connection.send_lock.acquire()
            task = asyncio.create_task(relay.forward(request))
            await asyncio.sleep(0)
            assert connection.pending
            saved.deadline = time.monotonic() - 1
            connection.send_lock.release()
            result = await task
            assert result.status_code == 404 and sent == []
            assert json.loads(result.body)["execution"] == "not_forwarded"
        else:
            result = await relay.forward(request)
            assert result.status_code == 200 and len(sent) == 1
            assert result.headers["mcp-session-id"] == "owned" and relay.sessions["owned"] is saved
    asyncio.run(run())


def test_status_shows_safe_latest_failure_only_for_own_consumer(connector):
    async def run():
        async with connected(connector) as (client, headers):
            url = connector["url"]
            await client.post(url + "/connector/mcp/private-mcp", headers=headers, json=rpc())
            status = (await client.get(url + "/connector/status", headers=headers)).json()["targets"][0]
            assert (status["last_exchange"], status["last_status"], status["last_error_code"]) == ("completed", 200, None)
            await client.post(url + "/connector/mcp/private-mcp", headers=headers,
                json=rpc(params={"arguments": {"action": "http401"}}))
            status = (await client.get(url + "/connector/status", headers=headers)).json()["targets"][0]
            assert (status["last_exchange"], status["last_status"], status["last_error_code"]) == ("completed", 401, "connector_upstream_http_error")
            before = len(connector["state"]["calls"])
            await client.post(url + "/connector/mcp/private-mcp", headers={**headers, "Mcp-Session-Id": "unavailable"}, json=rpc())
            status = (await client.get(url + "/connector/status", headers=headers)).json()["targets"][0]
            assert (status["last_exchange"], status["last_status"], status["last_error_code"]) == ("not_forwarded", 404, "connector_session_unavailable")
            assert len(connector["state"]["calls"]) == before
            foreign = (await client.get(url + "/connector/status", headers={"Authorization": "Bearer " + connector["second"]})).json()
            assert foreign["targets"][0]["last_exchange"] is None
            assert foreign["targets"][0]["last_error_code"] is None
            assert "private error" not in json.dumps(status)
    asyncio.run(run())


def test_websocket_redirect_never_forwards_agent_credential():
    seen = []
    async def redirect(websocket):
        await websocket.send_denial_response(Response(status_code=307, headers={"Location": "/sentinel"}))
    async def sentinel(websocket):
        seen.append(dict(websocket.headers))
        await websocket.accept()
        await websocket.close()
    with listener(lambda _: Starlette(routes=[WebSocketRoute("/redirect", redirect), WebSocketRoute("/sentinel", sentinel)])) as (url, _):
        async def run():
            from websockets.exceptions import InvalidStatus
            with pytest.raises(InvalidStatus) as rejected:
                async with NoRedirectConnect(url.replace("http:", "ws:") + "/redirect", proxy=None,
                        additional_headers={"Authorization": "Bearer synthetic-must-stay-at-original-origin"}):
                    pytest.fail("Redirected WebSocket was accepted")
            assert rejected.value.response.status_code == 307
            assert seen == []
        asyncio.run(run())

"""Sensitive native MCP transports suppress diagnostics even in debug mode.

All subprocesses and HTTP I/O are in-memory peers. The real client request,
response, log, stream-reader, and runtime restart boundaries remain exercised.
"""
from __future__ import annotations

import io
import json
import logging
import urllib.error
from typing import Any, Callable

import pytest

from lingshu_gate.business_credential_store import BusinessCredentialStore
from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.logging import JsonFormatter
from lingshu_gate.mcp_http_client import StreamableHttpMcpClient
from lingshu_gate.mcp_managed_http_client import ManagedHttpMcpClient
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_runtime import McpRuntimeManager, McpServerRuntime, McpServerState
from lingshu_gate.mcp_runtime_state_store import McpRuntimeStateStore
from lingshu_gate.mcp_stdio_client import McpProtocolError, StdioMcpClient
from lingshu_gate.protocol.lifecycle import discovery_requires_initialize
from lingshu_gate.protocol.version import MCP_PROTOCOL_VERSION
from lingshu_gate.registry import ToolRegistry
from test_business_credentials_service import bind, create, native_tools
from test_business_credentials_service import gate as service_gate  # noqa: F401 - shared real-app fixture

SECRET = "synthetic-business-echo-q7e3"
SERVER = "synthetic-private-browser"


@pytest.fixture
def settings(tmp_path):
    return Settings(data_dir=tmp_path / "data", config_dir=tmp_path / "mcp.d", allowed_root=tmp_path,
        db_url=f"sqlite:///{tmp_path / 'data' / 'gate.db'}", mcp_log_payloads=True)


def manifest(kind: str) -> McpServerManifest:
    return McpServerManifest.model_validate({"id": SERVER, "enabled": True, "timeout_seconds": 2,
        "launch": ({"type": "external"} if kind == "http" else
            {"type": "managed_process", "command": "synthetic-browser"}),
        "transport": ({"type": "stdio"} if kind == "stdio" else {"type": "streamable_http",
            "endpoint": "https://browser.example.test/mcp" if kind == "http" else "http://127.0.0.1:3917/mcp"})})


def success(request: dict[str, Any]) -> dict[str, Any]:
    if request["method"] == "server/discover":
        result = {"supportedVersions": [MCP_PROTOCOL_VERSION], "capabilities": {}, "unexpected_echo": SECRET}
    elif request["method"] == "tools/list":
        result = {"tools": [], "unexpected_echo": SECRET}
    else:
        result = {"unexpected_echo": SECRET}
    return {"jsonrpc": "2.0", "id": request["id"], "result": result}


class Process:
    """No process is launched; the actual client readers consume these pipes."""

    pid = 4321

    def __init__(self) -> None:
        self.returncode = None
        self.stdin: Any = io.StringIO()
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()

    def poll(self):
        return self.returncode

    def terminate(self):
        self.returncode = -15

    def kill(self):
        self.returncode = -9

    def wait(self, timeout=None):
        return self.returncode if self.returncode is not None else 0


def stdio_wire(client: StdioMcpClient, reply: Callable[[dict[str, Any]], dict[str, Any]] = success):
    process = Process()
    sent = []

    class Input(io.StringIO):
        def flush(self):
            request = json.loads(self.getvalue())
            self.seek(0)
            self.truncate(0)
            sent.append(request)
            process.stdout = io.StringIO(json.dumps(reply(request)) + "\nnot-json " + SECRET + "\n")
            process.stderr = io.StringIO("stderr echo " + SECRET + "\n")
            client._read_stdout()
            client._read_stderr()

    process.stdin = Input()
    client.process = process
    return sent


class HttpResponse(io.BytesIO):
    def __init__(self, body: bytes, content_type="application/json"):
        super().__init__(body)
        self.headers = {"Content-Type": content_type, "Content-Length": str(len(body))}
        self.status = 200


def http_wire(client: StreamableHttpMcpClient, reply: Callable[[dict[str, Any]], dict[str, Any]] = success):
    sent = []

    class Opener:
        def open(self, request, *, timeout):
            message = json.loads(request.data)
            sent.append(message)
            return HttpResponse(json.dumps(reply(message)).encode())

    client._opener = Opener()
    return sent


def make_sensitive_transport(kind, settings, logs, reply=success):
    def sink(*entry):
        logs.append(entry)

    declaration = manifest(kind)
    if kind == "stdio":
        client = StdioMcpClient(declaration, settings, log_sink=sink)
        sent = stdio_wire(client, reply)
        native_clients = [client]
    else:
        http = StreamableHttpMcpClient(declaration, settings, log_sink=sink)
        http.initialized = True
        sent = http_wire(http, reply)
        if kind == "http":
            client, native_clients = http, [http]
        else:
            client = ManagedHttpMcpClient(declaration, settings, log_sink=sink)
            client._http_client = http
            native_clients = [client, http]
    client.suppress_payload_logging()
    if isinstance(client, ManagedHttpMcpClient):
        client._read_stream(io.StringIO("stdout echo " + SECRET + "\n"), "stdout")
        client._read_stream(io.StringIO("stderr echo " + SECRET + "\n"), "stderr")
    return client, native_clients, sent


def assert_private(logs, caplog, clients=(), errors=()):
    # caplog.text alone excludes structured gate_* fields. Format the actual
    # records, including any exception chains, exactly as production logs do.
    formatter = JsonFormatter()
    exposed = [repr(logs), *(formatter.format(record) for record in caplog.records)]
    for client in clients:
        exposed.extend((repr(client.last_stdout), repr(client.last_stderr)))
    for error in errors:
        exposed.extend((str(error), repr(vars(error))))
    assert SECRET not in "\n".join(exposed)


@pytest.mark.parametrize("kind", ["stdio", "http", "managed_http"])
@pytest.mark.parametrize("message,allowed", [("unknown method: server/discover", True),
    ("method not found: server/discover", True), ("unknown method: server/discover " + SECRET, False)])
def test_sensitive_legacy_discovery_keeps_only_a_verified_safe_signal(kind, message, allowed, settings, caplog):
    caplog.set_level(logging.DEBUG)
    logs = []
    def reply(request):
        return {"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32000, "message": message, "data": SECRET}}
    client, natives, _ = make_sensitive_transport(kind, settings, logs, reply)
    with pytest.raises(McpProtocolError) as caught:
        client.request("server/discover", {})
    assert discovery_requires_initialize(caught.value.code, caught.value.rpc_message) is allowed
    assert_private(logs, caplog, natives, [caught.value])


@pytest.mark.parametrize("kind", ["stdio", "http", "managed_http"])
def test_sensitive_transports_preserve_internal_results_without_recording_payloads(kind, settings, caplog):
    caplog.set_level(logging.DEBUG)
    logs = []
    client, natives, sent = make_sensitive_transport(kind, settings, logs)
    assert settings.mcp_log_payloads is True
    # The value is intentionally not registered with generic secret redaction:
    # suppression must cover arbitrary downstream echoes in otherwise safe keys.
    assert all(SECRET not in native.audit_redaction_values() for native in natives)
    result = client.request("tools/call", {"name": "synthetic_action", "arguments": {"value": SECRET}})
    assert sent[0]["params"]["arguments"]["value"] == SECRET
    assert result["unexpected_echo"] == SECRET
    assert_private(logs, caplog, natives)


@pytest.mark.parametrize("kind", ["stdio", "http", "managed_http"])
@pytest.mark.parametrize("error_code", [-32602, SECRET, {"unexpected_echo": SECRET}, True])
def test_sensitive_rpc_errors_never_echo_message_data_or_noninteger_codes(kind, error_code, settings, caplog):
    caplog.set_level(logging.DEBUG)
    logs = []

    def reply(request):
        return {"jsonrpc": "2.0", "id": request["id"], "error": {
            "code": error_code, "message": SECRET, "data": {"unexpected_echo": SECRET}}}

    client, natives, sent = make_sensitive_transport(kind, settings, logs, reply)
    with pytest.raises(McpProtocolError) as caught:
        client.request("tools/call", {"name": "synthetic_action", "arguments": {"value": SECRET}})
    assert len(sent) == 1
    assert caught.value.code == (error_code if type(error_code) is int else None)
    assert caught.value.rpc_message == "Sensitive MCP response suppressed"
    assert_private(logs, caplog, natives, [caught.value])


def test_sensitive_stdio_unmatched_response_identifier_is_not_a_log_channel(settings, caplog):
    caplog.set_level(logging.DEBUG)
    logs = []
    client = StdioMcpClient(manifest("stdio"), settings, log_sink=lambda *entry: logs.append(entry))
    client.suppress_payload_logging()
    client.process = Process()
    client.process.stdout = io.StringIO(json.dumps({"jsonrpc": "2.0", "id": SECRET,
        "result": {"unexpected_echo": SECRET}}) + "\n")
    client._read_stdout()
    assert_private(logs, caplog, [client])


@pytest.mark.parametrize("failure", ["http-body", "invalid-json", "network-reason"])
def test_sensitive_http_transport_failure_messages_suppress_unregistered_echoes(failure, settings, caplog):
    caplog.set_level(logging.DEBUG)
    logs = []
    client, natives, _ = make_sensitive_transport("http", settings, logs)

    class Opener:
        def open(self, request, *, timeout):
            if failure == "http-body":
                raise urllib.error.HTTPError(client.endpoint, 500, "Synthetic failure",
                    {"Content-Type": "text/plain"}, io.BytesIO(SECRET.encode()))
            if failure == "network-reason":
                raise urllib.error.URLError(SECRET)
            return HttpResponse(("not-json " + SECRET).encode())

    client._opener = Opener()
    with pytest.raises(McpProtocolError) as caught:
        client.request("tools/call", {"name": "synthetic_action", "arguments": {"value": SECRET}})
    assert_private(logs, caplog, natives, [caught.value])


@pytest.mark.parametrize("kind", ["stdio", "http", "managed_http"])
@pytest.mark.parametrize("marker", ["persisted", "runtime"])
def test_runtime_replacements_are_sensitive_before_discovery_or_pipe_reads(kind, marker, settings, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    logs, clients = [], []
    database = SQLiteDatabase(settings.db_url, settings.data_dir)
    store = BusinessCredentialStore(database, settings.data_dir)
    manager = McpRuntimeManager(settings, ToolRegistry(), log_sink=lambda *entry: logs.append(entry),
        state_store=McpRuntimeStateStore(database))
    target = McpServerRuntime(manifest=manifest(kind), state=McpServerState.STOPPED)
    manager._servers[SERVER] = target
    if marker == "persisted":
        database.execute("INSERT INTO business_credential_targets(server_id,adapter,tool_prefix,created_at) "
            "VALUES (?,'agent_browser','agent_browser_','synthetic')", (SERVER,))
        manager.credential_sensitive_target = store.is_managed_server
    else:
        target.client = StdioMcpClient(manifest("stdio"), settings)
        manager.suppress_credential_payloads(SERVER)

    def start_stdio(client):
        assert client._sensitive_payloads, "Runtime must protect a replacement before any discovery or pipe I/O"
        clients.append(client)
        stdio_wire(client)
        client.request("server/discover", {})
        client.initialized = True

    def start_http(client):
        assert client._sensitive_payloads, "Both external and nested managed HTTP clients must inherit suppression"
        clients.append(client)
        http_wire(client)
        client.request("server/discover", {})
        client.initialized = True

    def start_process(client):
        assert client._sensitive_payloads, "Managed process pipes must be protected before they are read"
        clients.append(client)
        client.process = Process()
        for name in ("stdout", "stderr"):
            client._read_stream(io.StringIO("startup echo " + SECRET + "\n"), name)

    monkeypatch.setattr(StdioMcpClient, "start", start_stdio)
    monkeypatch.setattr(StreamableHttpMcpClient, "start", start_http)
    monkeypatch.setattr(ManagedHttpMcpClient, "_start_process", start_process)
    monkeypatch.setattr(manager, "_start_process_monitor", lambda *args: None)
    try:
        manager.start_server(SERVER)
        assert target.state == McpServerState.RUNNING
        first = target.client
        manager.restart_server(SERVER)
        assert target.state == McpServerState.RUNNING and target.client is not first
        assert len(clients) == (4 if kind == "managed_http" else 2)
        assert all(client._sensitive_payloads for client in clients)
        assert_private(logs, caplog, clients)
    finally:
        manager.shutdown()


def test_sensitive_external_start_failure_does_not_leak_exception_chain(settings, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    logs = []
    manager = McpRuntimeManager(settings, ToolRegistry(), log_sink=lambda *entry: logs.append(entry))
    manager.credential_sensitive_target = lambda server_id: server_id == SERVER
    target = McpServerRuntime(manifest=manifest("http"), state=McpServerState.STOPPED)
    manager._servers[SERVER] = target

    class Opener:
        def open(self, request, *, timeout):
            raise urllib.error.URLError(SECRET)

    monkeypatch.setattr("lingshu_gate.mcp_http_client.urllib.request.build_opener", lambda *args: Opener())
    try:
        manager.start_server(SERVER)
        assert target.state == McpServerState.FAILED
        assert SECRET not in (target.last_error or "")
        assert_private(logs, caplog)
    finally:
        manager.shutdown()


def test_sensitive_managed_start_failure_does_not_leak_exception_chain(settings, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    logs = []
    manager = McpRuntimeManager(settings, ToolRegistry(), log_sink=lambda *entry: logs.append(entry))
    manager.credential_sensitive_target = lambda server_id: server_id == SERVER
    target = McpServerRuntime(manifest=manifest("managed_http"), state=McpServerState.STOPPED)
    manager._servers[SERVER] = target

    def fail_process_start(client):
        assert client._sensitive_payloads
        try:
            raise ValueError("Synthetic startup cause: " + SECRET)
        except ValueError as cause:
            raise RuntimeError("Synthetic startup diagnostic: " + SECRET) from cause

    monkeypatch.setattr(ManagedHttpMcpClient, "_start_process", fail_process_start)
    try:
        manager.start_server(SERVER)
        assert target.state == McpServerState.FAILED
        assert target.last_error == "Sensitive MCP startup error suppressed"
        assert_private(logs, caplog)
    finally:
        manager.shutdown()


def test_sensitive_health_failure_does_not_store_or_log_downstream_exception(settings, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    logs = []
    manager = McpRuntimeManager(settings, ToolRegistry(), log_sink=lambda *entry: logs.append(entry))
    declaration = manifest("stdio")
    declaration.restart_policy.health_check.failure_threshold = 1
    client = StdioMcpClient(declaration, settings, log_sink=lambda *entry: logs.append(entry))
    stdio_wire(client)
    target = McpServerRuntime(manifest=declaration, state=McpServerState.RUNNING, client=client)
    manager._servers[SERVER] = target
    manager.suppress_credential_payloads(SERVER)

    def fail_health(*args, **kwargs):
        raise RuntimeError("Synthetic health diagnostic: " + SECRET)

    monkeypatch.setattr(client, "request", fail_health)
    monkeypatch.setattr(manager, "_sleep_or_cancel", lambda *args: False)
    try:
        manager._health_loop(SERVER, target, client)
        assert target.state == McpServerState.FAILED and target.health_status == "failed"
        assert target.consecutive_health_failures == 1
        assert "Sensitive MCP health error suppressed" in target.last_error
        assert_private(logs, caplog, [client])
        history = manager.restart_history.list(SERVER)
        assert history and SECRET not in json.dumps(history)
    finally:
        manager.shutdown()


def test_targets_offer_short_prefix_explicitly_and_keep_managed_contract_pinned(request):
    gate = request.getfixturevalue("service_gate")
    actor = gate["actors"]["admin"]
    server_id = gate["target"].manifest.id
    short_tools = [{**tool, "name": tool["name"].removeprefix("agent_browser_")} for tool in native_tools()]

    def publish(tools):
        gate["target"].tools = tools
        gate["runtime"]._register_mcp_tools(gate["target"])
        definitions = [item for item in gate["registry"].list_definitions() if item.metadata.get("server_id") == server_id]
        gate["access"].synchronize_tools(definitions)
        for definition in definitions:
            gate["access"].set_classification(server_id=server_id, tool_id=definition.id, access="write",
                destructive=False, idempotent=False, reviewer_id=actor.id)
        gate["access"].publish_classifications(reviewer_id=actor.id, server_id=server_id)

    publish(short_tools)
    target = gate["service"].targets(actor, "personal")["servers"][0]
    assert target["compatible"] and target["tool_prefix"] == "" and target["compatible_prefixes"] == [""]
    record = create(gate)
    binding = bind(gate, record, tool_prefix="")
    assert binding["tool_prefix"] == ""
    publish([*short_tools, *native_tools()])
    target = gate["service"].targets(actor, "personal")["servers"][0]
    assert target["managed"] and target["compatible_prefixes"] == [""]

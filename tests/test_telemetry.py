"""Real OTLP protobuf peers, gateway permissions and invocation observations."""
from __future__ import annotations

import ipaddress
import json
import logging
import ssl
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.error import URLError

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.interfaces.control_api.telemetry_routes import register_telemetry_routes
from lingshu_gate.mcp_http_client import McpProtocolError
from lingshu_gate.telemetry import CAPACITY, TelemetryService, exception_outcome, phase, valid_correlation
from lingshu_gate.telemetry_config import TelemetryConfig
from lingshu_gate.telemetry_http import TelemetryMiddleware
from test_argument_policy import configured as configured, rule, save_policy
from test_authorization_discovery import ISSUER, browser as browser, gate as gate, legacy, rpc, set_mode
from test_builtin_oauth import PASSWORD
from test_mcp_session_recovery import connected_runtime
from test_tool_preferences import update


def wait_until(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate(), "bounded telemetry observation did not complete"


@contextmanager
def collector(*, response="accepted", tls=None, hold=None):
    state = {"requests": [], "protobuf": [], "arrived": threading.Event()}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers["Content-Length"]))
            message = ExportTraceServiceRequest()
            message.ParseFromString(raw)
            state["requests"].append({"path": self.path, "headers": dict(self.headers)})
            state["protobuf"].append(message)
            state["arrived"].set()
            if hold is not None:
                hold.wait(5)
            if response == "malformed":
                self.wfile.write(b"HTTP/1.1 200 OK\r\ncollector-header-private-canary\r\nContent-Length: 0\r\n\r\n")
            elif response == "redirect":
                self.send_response(307, "collector-reason-private-canary")
                self.send_header("Location", "/collector-redirect-private-canary")
                self.send_header("Content-Length", str(2 ** 31))
                self.end_headers()
            else:
                self.send_response(200)
                self.send_header("Set-Cookie", "private=collector-cookie-private-canary")
                self.send_header("Content-Length", "0")
                self.end_headers()
            self.close_connection = True

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    if tls is not None:
        server.socket = tls.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    thread.start()
    try:
        yield f"{'https' if tls else 'http'}://127.0.0.1:{server.server_port}/collector-path-private-canary/v1/traces", state
    finally:
        if hold is not None:
            hold.set()
        server.shutdown()
        server.server_close()
        thread.join(2)
        assert not thread.is_alive()


@contextmanager
def tracing(endpoint, **options):
    service = TelemetryService(TelemetryConfig(metrics_enabled=True, traces_enabled=True, otlp_endpoint=endpoint, **options))
    service.start()
    try:
        yield service
    finally:
        service.stop()


def all_spans(state):
    return [span for message in state["protobuf"] for resource in message.resource_spans
            for scope in resource.scope_spans for span in scope.spans]


def emit(service, count=1):
    with service.activate("a" * 32):
        for _ in range(count):
            with phase("prepare"):
                pass


@pytest.mark.parametrize("value", [
    '{"metrics_enabled":1}', '{"traces_enabled":true}', '{"sample_ratio":true}', '{"sample_ratio":1e999}',
    '{"sample_ratio":-1}', '{"sample_ratio":2}', '{"sample_ratio":' + "9" * 400 + '}',
    '{"unknown":1}', '{"metrics_enabled":false,"metrics_enabled":true}',
    '{"otlp_endpoint":"http://collector.example.test/v1/traces"}',
    '{"otlp_endpoint":"https://collector.example.test/v1/traces?secret=value"}',
    '{"otlp_endpoint":"https://user:secret@collector.example.test/v1/traces"}',
    '{"otlp_token_file":"relative"}',
])
def test_configuration_is_explicit_and_bounded(value):
    with pytest.raises(ValueError, match="telemetry_configuration_invalid"):
        TelemetryConfig.parse(value)


def test_default_off_creates_no_exporter_and_disabled_metrics_are_404(gate, monkeypatch):
    import lingshu_gate.telemetry as implementation
    def forbidden(*_args):
        pytest.fail("default-off must not construct the SDK")
    monkeypatch.setattr(implementation, "_standard_provider", forbidden)
    service = TelemetryService(TelemetryConfig())
    service.start()
    register_telemetry_routes(gate["app"], service=service, auth=gate["auth"], access=gate["access"])
    with TestClient(gate["app"], base_url=ISSUER) as client:
        assert client.get("/v1/observability/metrics").status_code == 404
        assert client.get("/v1/observability/telemetry").status_code == 404
    assert service._provider is None and not service.status()["traces_ready"]
    service.stop()


@pytest.mark.parametrize("value", ["true", " TRUE ", " true "])
def test_disabled_sdk_reports_unavailable_without_exporter(monkeypatch, value):
    monkeypatch.setenv("OTEL_SDK_DISABLED", value)
    service = TelemetryService(TelemetryConfig(traces_enabled=True, otlp_endpoint="http://127.0.0.1:1/v1/traces"))
    service.start()
    assert not service.status()["traces_ready"] and service._provider is None
    assert service.status()["last_failure_code"] == "sdk_environment_disabled"
    service.stop()


def test_real_otlp_parent_privacy_fixed_resource_and_no_ambient_destination(tmp_path, monkeypatch, caplog):
    private = tmp_path / "collector-token"
    private.write_text("synthetic-export-token")
    private.chmod(0o600)
    for name, value in {
        "HTTP_PROXY": "http://127.0.0.1:1", "HTTPS_PROXY": "http://127.0.0.1:1", "NO_PROXY": "",
        "OTEL_EXPORTER_OTLP_HEADERS": "Authorization=ambient-private-canary",
        "OTEL_EXPORTER_OTLP_TRACES_HEADERS": "Cookie=ambient-private-canary",
        "OTEL_RESOURCE_ATTRIBUTES": "secret=resource-private-canary",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://127.0.0.1:1/private-canary",
        "OTEL_TRACES_SAMPLER": "always_off",
        "OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE": "/ambient-private-canary",
        "OTEL_EXPORTER_OTLP_TRACES_CLIENT_CERTIFICATE": "/ambient-client-private-canary",
        "OTEL_EXPORTER_OTLP_TRACES_CLIENT_KEY": "/ambient-key-private-canary",
    }.items():
        monkeypatch.setenv(name, value)
    caplog.set_level(logging.DEBUG, logger="urllib3")
    with collector() as (endpoint, state), tracing(endpoint, otlp_token_file=private) as service:
        app = FastAPI()
        @app.post("/probe/{item}")
        def probe(item: str, body: dict):
            with phase("prepare") as observed:
                observed.attributes["secret"] = body["secret"]
            return {"ok": True}
        app.add_middleware(TelemetryMiddleware, service=service, routes=app.routes)
        incoming = "00-" + "f" * 32 + "-" + "e" * 16 + "-01"
        # The test driver's request log contains its own synthetic URL before
        # the application's JSON formatter redacts it. Keep exporter/app logs
        # and urllib3 DEBUG visible without treating driver INFO as export.
        driver_loggers = [logging.getLogger(name) for name in ("httpx", "httpx2")]
        driver_levels = [logger.level for logger in driver_loggers]
        try:
            for logger in driver_loggers:
                logger.setLevel(logging.WARNING)
            with TestClient(app) as client:
                result = client.post("/probe/path-private-canary?query=query-private-canary",
                    headers={"traceparent": incoming, "tracestate": "vendor=trace-state-private-canary",
                             "baggage": "secret=baggage-private-canary", "Authorization": "Bearer inbound-private-canary",
                             "X-Correlation-ID": "A" * 32}, json={"secret": "argument-private-canary"})
                assert result.status_code == 200 and result.headers["x-correlation-id"] == "a" * 32
        finally:
            for logger, level in zip(driver_loggers, driver_levels, strict=True):
                logger.setLevel(level)
        wait_until(lambda: service.status()["export_accepted_spans"] >= 2)
        spans = all_spans(state)
        request = next(span for span in spans if span.name == "gate.request")
        assert request.trace_id.hex() == "f" * 32 and request.parent_span_id.hex() == "e" * 16
        assert {span.name for span in spans} == {"gate.request", "gate.prepare"}
        for message in state["protobuf"]:
            for resource in message.resource_spans:
                assert {attribute.key for attribute in resource.resource.attributes} == {"service.name", "service.version"}
        assert state["requests"][0]["headers"]["Authorization"] == "Bearer synthetic-export-token"
        exported = json.dumps([MessageToDict(message) for message in state["protobuf"]]) + service.prometheus_text()
        for canary in ("argument-private-canary", "path-private-canary", "query-private-canary", "inbound-private-canary",
                       "ambient-private-canary", "resource-private-canary", "trace-state-private-canary",
                       "baggage-private-canary", "synthetic-export-token"):
            assert canary not in exported
            assert canary not in caplog.text
        assert 'route="/probe/{item}"' in service.prometheus_text()
        assert not any(span.events or span.status.message for span in spans)
        emit(service)
        wait_until(lambda: service.status()["export_accepted_spans"] >= 3)
        assert len(state["requests"]) == 2
        assert all("Cookie" not in item["headers"] for item in state["requests"])


@pytest.mark.parametrize("response,accepted", [("redirect", False), ("malformed", True)])
def test_collector_response_never_redirects_reads_unbounded_body_or_logs_private_text(response, accepted, caplog):
    caplog.set_level(logging.DEBUG)
    with collector(response=response) as (endpoint, state), tracing(endpoint) as service:
        emit(service)
        wait_until(lambda: service.status()["export_accepted_spans"] + service.status()["failed_spans"] == 1)
        assert len(state["requests"]) == 1
        assert bool(service.status()["export_accepted_spans"]) is accepted
        assert "private-canary" not in caplog.text
    logging.getLogger("urllib3.connection").warning("unrelated-business-http-log")
    assert "unrelated-business-http-log" in caplog.text


def tls_files(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "Synthetic telemetry CA")])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1)).add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), False)
        .sign(key, hashes.SHA256()))
    certificate, private_key = tmp_path / "ca.pem", tmp_path / "key.pem"
    certificate.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    private_key.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                              serialization.NoEncryption()))
    private_key.chmod(0o600)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, private_key)
    return certificate, context


def test_tls_certificate_verification_and_explicit_ca(tmp_path, monkeypatch):
    certificate, context = tls_files(tmp_path)
    with collector(tls=context) as (endpoint, state):
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(certificate))
        monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_CERTIFICATE", str(certificate))
        with tracing(endpoint) as service:
            emit(service)
            wait_until(lambda: service.status()["failed_spans"] == 1)
            assert not state["requests"]
        with tracing(endpoint, otlp_ca_file=certificate) as service:
            emit(service)
            wait_until(lambda: service.status()["export_accepted_spans"] == 1)
            assert len(state["protobuf"]) == 1


def test_slow_collector_capacity_and_bounded_shutdown_do_not_wait_on_business():
    hold = threading.Event()
    with collector(hold=hold) as (endpoint, state):
        service = TelemetryService(TelemetryConfig(traces_enabled=True, metrics_enabled=True, otlp_endpoint=endpoint))
        service.start()
        try:
            emit(service, 64)
            assert state["arrived"].wait(3)
            started = time.monotonic()
            emit(service, CAPACITY * 2)
            assert time.monotonic() - started < 1
            status = service.status()
            assert status["pending"] + status["inflight"] <= CAPACITY and status["dropped_queue_full"] > 0
            assert status["inflight"] > 0
            started = time.monotonic()
            service.stop()
            assert time.monotonic() - started < 1.4
            assert service.status()["closed"] and service.status()["shutdown_timed_out"]
            before = len(state["requests"])
            emit(service, 64)
            hold.set()
            wait_until(lambda: service.status()["pending"] + service.status()["inflight"] == 0)
            assert len(state["requests"]) == before
        finally:
            hold.set()
            service.stop()


def test_metric_permission_requires_both_scopes_and_no_auth_disabled_bypass(gate):
    service = TelemetryService(TelemetryConfig(metrics_enabled=True))
    register_telemetry_routes(gate["app"], service=service, auth=gate["auth"], access=gate["access"])
    admin, session, _ = gate["auth"].login(username="synthetic-admin", password=PASSWORD)
    with TestClient(gate["app"], base_url=ISSUER) as client:
        assert client.get("/v1/observability/metrics").status_code == 401
        client.cookies.set(gate["auth"].cookie_name, gate["sessions"]["alice"])
        assert client.get("/v1/observability/metrics").status_code == 403
        client.cookies.set(gate["auth"].cookie_name, session)
        for scopes in (["operations.manage"], ["observability.read.all"], ["operations.manage", "observability.read.all"]):
            token = gate["auth"].create_api_token(principal=admin, name="Synthetic scrape", scopes=scopes)
            headers = {"Authorization": "Bearer " + token["token"]}
            result = client.get("/v1/observability/metrics", headers=headers)
            assert result.status_code == (200 if len(scopes) == 2 else 403)
            if result.status_code == 200:
                assert result.headers["cache-control"] == "no-store"
                assert "text/plain; version=0.0.4" in result.headers["content-type"]
                assert "gate_telemetry_pending 0" in result.text
                gate["auth"].revoke_api_token(token["id"], user_id=admin.id)
                assert client.get("/v1/observability/metrics", headers=headers).status_code == 401
        assert client.get("/v1/observability/telemetry").status_code == 200
        gate["auth"].enabled = False
        assert client.get("/v1/observability/metrics").status_code == 401
    limited = replace(admin, delegated_scopes=("operations.manage",))
    assert not gate["access"].has_control_permission(limited, "observability.read.all")


@pytest.fixture
def observed(gate, configured):
    service = TelemetryService(TelemetryConfig(metrics_enabled=True))
    gate["app"].add_middleware(TelemetryMiddleware, service=service, routes=gate["app"].routes)
    service.start()
    yield service
    service.stop()


@pytest.mark.parametrize("entry", ["rest", "direct", "catalog", "pin"])
def test_gateway_correlation_and_logical_mcp_error_metrics(observed, browser, gate, configured, entry):
    calls, catalog = configured
    token = legacy(gate)
    if entry == "direct":
        set_mode(browser, "api", token["id"], "direct")
    if entry == "pin":
        update(browser, token, pinned_tools=[{"kind": "tool", "tool_ref": "mcp.A.read"}])
        pin = next(item["name"] for item in rpc(browser, token["token"]).json()["result"]["tools"]
                   if item["name"].startswith("gate_pinned_"))
    save_policy(gate, [rule()])
    correlation = "12345678-1234-4321-abcd-123456789abc"
    headers = {"Authorization": "Bearer " + token["token"], "X-Correlation-ID": correlation}
    if entry == "rest":
        result = browser.post("/v1/invoke", headers=headers, json={"tool_id": "mcp.A.read", "arguments": {"limit": 99}})
        assert not result.json()["ok"]
    else:
        arguments = {"limit": 99}
        name = pin if entry == "pin" else "mcp__A__read" if entry == "direct" else "gate_tool_invoke"
        if entry == "catalog":
            described = rpc(browser, token["token"], "tools/call",
                            {"name": "gate_tool_describe", "arguments": {"tool_ref": "mcp.A.read"}}).json()["result"]["structuredContent"]
            arguments = {"tool_ref": "mcp.A.read", "schema_revision": described["schema_revision"], "arguments": arguments}
        result = rpc(browser, token["token"], "tools/call", {"name": name, "arguments": arguments},
                     mode_headers=(("X-Correlation-ID", correlation),))
        assert result.json()["result"]["isError"]
    assert result.status_code == 200 and result.headers["x-correlation-id"] == correlation
    assert calls == []
    audit = gate["db"].query_one("SELECT correlation_id,outcome FROM invocation_audits")
    assert audit["correlation_id"] == correlation and audit["outcome"] == "not_invoked"
    label = "mcp" if entry == "direct" else entry
    metrics = observed.prometheus_text()
    assert f'gate_tool_total{{entry="{label}",outcome="denied",transport="unknown"}} 1' in metrics
    assert 'outcome="denied"' in metrics and 'gate_execution_total{' not in metrics
    duplicate = browser.get("/missing-private-canary", headers=[("X-Correlation-ID", correlation), ("X-Correlation-ID", correlation)])
    assert valid_correlation(duplicate.headers["x-correlation-id"]) and duplicate.headers["x-correlation-id"] != correlation
    assert "missing-private-canary" not in observed.prometheus_text()


def test_real_http_retry_has_two_attempts_one_logical_call_and_fresh_trace_headers(tmp_path):
    with collector() as (endpoint, state), tracing(endpoint) as service:
        with connected_runtime(tmp_path) as (manager, runtime, client, peer):
            client._resolved_headers.update({"TraceParent": "configured-private-canary", "Baggage": "configured-private-canary",
                                             "X-Correlation-ID": "configured-private-canary"})
            access = AccessControlStore(SQLiteDatabase(manager.settings.db_url, tmp_path))
            access.attach_mcp_runtime(manager)
            tool_id = "mcp.legacy-http.echo"
            access.synchronize_tools([manager.registry.get_definition(tool_id)])
            access.set_classification(server_id=runtime.manifest.id, tool_id=tool_id, access="read",
                                      destructive=False, idempotent=True, reviewer_id="synthetic-admin")
            access.publish_classifications(server_id=runtime.manifest.id, reviewer_id="synthetic-admin")
            actor = AuthPrincipal(id="synthetic-admin", username="admin", role="admin")
            with service.activate("b" * 32, "mcp"):
                response = access.invoke_tool(manager.registry, actor, tool_id, {})
            assert response.ok and peer["writes"] == 2
            headers = [headers for message, headers in peer["messages"] if message["method"] == "tools/call"]
            assert len(headers) == 2
            assert all(next(value for key, value in item.items() if key.lower() == "x-correlation-id") == "b" * 32 for item in headers)
            assert all("Baggage" not in item and "TraceParent" not in item for item in headers)
            traceparents = [next(value for key, value in item.items() if key.lower() == "traceparent") for item in headers]
            assert traceparents[0] != traceparents[1]
            assert traceparents[0].split("-")[1] == traceparents[1].split("-")[1]
            metrics = service.prometheus_text()
            assert 'gate_tool_total{entry="mcp",outcome="success",transport="streamable_http"} 1' in metrics
            assert 'gate_execution_total{attempt="initial",outcome="error",transport="streamable_http"} 1' in metrics
            assert 'gate_execution_total{attempt="retry",outcome="success",transport="streamable_http"} 1' in metrics
            assert not any(key.lower() == "traceparent" for key in client._http_headers({}))
        wait_until(lambda: len(all_spans(state)) >= 9)
        assert len([span for span in all_spans(state) if span.name == "gate.downstream"]) == 2


def test_wrapped_timeout_and_aggregation_failure_preserve_business_result(observed, browser, gate, configured, monkeypatch):
    cause = URLError(TimeoutError("private-timeout-canary"))
    wrapped = McpProtocolError("generic protocol failure")
    wrapped.__cause__ = cause
    assert exception_outcome(wrapped) == "timeout"
    definition = gate["registry"].get_definition("mcp.A.read")
    def timeout(_arguments):
        raise wrapped
    gate["registry"].register(definition, timeout, replace=True)
    token = legacy(gate)
    result = browser.post("/v1/invoke", headers={"Authorization": "Bearer " + token["token"]},
                          json={"tool_id": "mcp.A.read", "arguments": {"limit": 2}})
    assert result.status_code == 200 and not result.json()["ok"]
    assert 'outcome="timeout"' in observed.prometheus_text()
    def broken_aggregation(*_args):
        raise RuntimeError("private-aggregation-canary")
    monkeypatch.setattr(observed, "_record", broken_aggregation)
    result = browser.get("/no-such-route")
    assert result.status_code == 404 and observed.status()["last_failure_code"] == "aggregation_failed"


@pytest.mark.parametrize("kind,outcome", [("unknown", "invalid"), ("empty", "invalid"), ("stale_pin", "denied"), ("revision", "invalid")])
def test_mcp_200_protocol_and_contract_errors_are_not_recorded_as_success(observed, browser, gate, configured, kind, outcome):
    token = legacy(gate)
    if kind in {"unknown", "empty"}:
        set_mode(browser, "api", token["id"], "direct")
        params = {"name": "unregistered-private-canary" if kind == "unknown" else "", "arguments": {}}
    elif kind == "stale_pin":
        params = {"name": "gate_pinned_missing", "arguments": {}}
    else:
        params = {"name": "gate_tool_invoke", "arguments": {"tool_ref": "mcp.A.read", "schema_revision": "f" * 64, "arguments": {}}}
    response = rpc(browser, token["token"], "tools/call", params)
    assert response.status_code == 200
    assert response.json().get("error") or response.json()["result"]["isError"]
    assert f'gate_http_total{{method="POST",outcome="{outcome}",route="/mcp"}} 1' in observed.prometheus_text()
    if kind == "revision":
        assert 'gate_tool_total{entry="catalog",outcome="invalid",transport="unknown"} 1' in observed.prometheus_text()
    else:
        assert "gate_tool_total{" not in observed.prometheus_text()
    assert configured[0] == [] and 'gate_execution_total{' not in observed.prometheus_text()


def test_resource_authorization_denial_has_denied_standard_span(gate, configured):
    with collector() as (endpoint, state), tracing(endpoint) as service:
        gate["app"].add_middleware(TelemetryMiddleware, service=service, routes=gate["app"].routes)
        token = legacy(gate)
        with TestClient(gate["app"], base_url=ISSUER) as client:
            response = client.post("/v1/invoke", headers={"Authorization": "Bearer " + token["token"]},
                                   json={"tool_id": "mcp.B.read", "arguments": {}})
        assert response.status_code == 403
        wait_until(lambda: service.status()["export_accepted_spans"] >= 4)
        resource_denials = [span for span in all_spans(state) if span.name == "gate.authorization"
            and any(attribute.key == "gate.outcome" and attribute.value.string_value == "denied" for attribute in span.attributes)]
        assert len(resource_denials) == 1 and resource_denials[0].status.code == 2

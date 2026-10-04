"""Opt-in handshake/list-only interop against the fixed Playwright MCP runtime.

Set GATE_PLAYWRIGHT_MCP_ROOT to an isolated @playwright/mcp@0.0.83 installation.
No browser tool is invoked, no profile is reused and no browser is downloaded.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

from lingshu_gate.mcp_stdio_client import McpProtocolError
from lingshu_gate.protocol.version import MCP_PROTOCOL_VERSION
from lingshu_gate.transports.http import build_protocol_request
from test_mcp_downstream_legacy import http_client


@pytest.fixture(scope="module")
def playwright_peer(tmp_path_factory):
    package_path = os.environ.get("GATE_PLAYWRIGHT_MCP_ROOT")
    if not package_path:
        pytest.skip("fixed Playwright MCP test installation not supplied")
    root = Path(package_path).resolve()
    assert json.loads((root / "package.json").read_text())["version"] == "0.0.83"
    core = root.parents[1] / "playwright-core"
    assert json.loads((core / "package.json").read_text())["version"] == "1.64.0-alpha-1790635538000"
    work = tmp_path_factory.mktemp("gate-playwright-interop")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    endpoint = f"http://localhost:{port}/mcp"
    with (work / "peer.log").open("w") as log:
        process = subprocess.Popen(
            ["node", str(root / "cli.js"), "--host", "127.0.0.1", "--port", str(port),
             "--headless", "--isolated", "--output-dir", str(work / "output")],
            cwd=work, stdout=log, stderr=subprocess.STDOUT,
            env={**os.environ, "PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD": "1", "XDG_CACHE_HOME": str(work / "cache")},
        )
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                assert process.poll() is None, (work / "peer.log").read_text()
                try:
                    with urllib.request.urlopen(endpoint, timeout=0.3):
                        break
                except urllib.error.HTTPError:
                    break
                except urllib.error.URLError:
                    time.sleep(0.1)
            else:
                pytest.fail("fixed Playwright MCP did not bind within 10 seconds")
            yield endpoint, work
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def test_fixed_peer_rejects_modern_discovery_with_real_http_400_null_id(playwright_peer, tmp_path):
    endpoint, work = playwright_peer
    params, headers = build_protocol_request("server/discover", {}, client_name="synthetic-test",
                                             client_version="test", protocol_version=MCP_PROTOCOL_VERSION)
    request = urllib.request.Request(endpoint, method="POST",
        data=json.dumps({"jsonrpc": "2.0", "id": 17, "method": "server/discover", "params": params}).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **headers})
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request, timeout=3)
    with caught.value as error:
        wire = json.loads(error.read(4096))
        assert error.code == 400
        assert error.headers["Content-Type"].split(";", 1)[0] == "application/json"
    assert wire == {"jsonrpc": "2.0", "id": None,
                    "error": {"code": -32000, "message": "Bad Request: Server not initialized"}}
    (work / "discovery-rejection.json").write_text(json.dumps({"http_status": 400, "body": wire}, indent=2))
    client = http_client(tmp_path, endpoint, MCP_PROTOCOL_VERSION)
    with pytest.raises(McpProtocolError, match="HTTP 400"):
        client.start()
    assert not client.initialized and client.session_id is None


@pytest.mark.parametrize("version", [None, "auto"])
def test_fixed_peer_auto_initializes_and_lists_without_any_browser_call(playwright_peer, tmp_path, version):
    endpoint, work = playwright_peer
    client = http_client(tmp_path, endpoint, version)
    client.manifest.timeout_seconds = 8
    methods = []
    real_open = client._opener.open

    def recorded_open(request, *, timeout):
        methods.append(json.loads(request.data)["method"] if request.data else request.get_method())
        return real_open(request, timeout=timeout)

    with patch.object(client._opener, "open", side_effect=recorded_open):
        try:
            client.start()
            assert client.protocol_version == "2025-11-25"
            assert client.session_id and client.initialized
            tools = client.list_tools()
            assert tools and all(isinstance(tool.get("name"), str) for tool in tools)
            assert methods == ["server/discover", "initialize", "notifications/initialized", "tools/list"]
            (work / f"auto-{version}.json").write_text(json.dumps({
                "manifest_protocol_version": version, "negotiated_protocol_version": client.protocol_version,
                "tool_count": len(tools), "methods": methods,
                "mcp_package_version": "0.0.83", "playwright_core_version": "1.64.0-alpha-1790635538000",
            }, indent=2))
        finally:
            client.stop()
    assert methods[-1] == "DELETE"
    assert methods.count("initialize") == 1 and "tools/call" not in methods
    assert not client.initialized and client.session_id is None

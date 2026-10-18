from starlette.testclient import TestClient

from lingshu_gate.demo_mcp import create_demo_app
from lingshu_gate.transports.http import build_protocol_request


def rpc(client, method, params):
    prepared, headers = build_protocol_request(method, params, client_name="demo-test", client_version="1")
    response = client.post("/mcp", headers=headers,
                           json={"jsonrpc": "2.0", "id": 1, "method": method, "params": prepared})
    assert response.status_code == 200
    return response.json()["result"]


def test_demo_is_real_mcp_and_only_mutates_its_own_memory():
    with TestClient(create_demo_app(), base_url="http://127.0.0.1:18880") as client:
        tools = rpc(client, "tools/list", {})["tools"]
        assert {tool["name"] for tool in tools} == {
            "gate_demo_echo", "gate_demo_note_read", "gate_demo_note_write"}
        echo = rpc(client, "tools/call", {"name": "gate_demo_echo", "arguments": {"message": "你好 Gate"}})
        assert echo["content"][0]["text"] == "你好 Gate"
        assert not echo.get("isError")
        before = rpc(client, "tools/call", {"name": "gate_demo_note_read", "arguments": {}})
        assert before["structuredContent"]["write_count"] == 0
        written = rpc(client, "tools/call", {"name": "gate_demo_note_write", "arguments": {"text": "a note"}})
        assert written["structuredContent"] == {"text": "a note", "revision": 1, "write_count": 1}
        rejected = rpc(client, "tools/call", {"name": "gate_demo_note_write", "arguments": {"text": "x" * 4097}})
        assert rejected["isError"]
        after = rpc(client, "tools/call", {"name": "gate_demo_note_read", "arguments": {}})
        assert after["structuredContent"]["write_count"] == 1
    with TestClient(create_demo_app(), base_url="http://127.0.0.1:18880") as fresh:
        assert rpc(fresh, "tools/call", {"name": "gate_demo_note_read", "arguments": {}})["structuredContent"]["write_count"] == 0

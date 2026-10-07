"""Reviewed loopback-only modern MCP peer for real browser connection tests."""
import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


@contextmanager
def synthetic_http_peer(root: Path):
    state = {"discoveries": 0, "lists": 0, "calls": 0}
    state_file = root / "http-peer-state.json"
    lock = threading.Lock()

    def publish():
        with lock:
            temporary = root / "http-peer-state.tmp"
            temporary.write_text(json.dumps(state))
            temporary.replace(state_file)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            method = request["method"]
            if method == "server/discover":
                state["discoveries"] += 1
                result = {"supportedVersions": ["2026-07-28"], "capabilities": {"tools": {}}}
            elif method == "tools/list":
                state["lists"] += 1
                state["last_list_path"] = self.path
                result = {"tools": [{"name": "echo", "description": "Synthetic loopback echo", "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}}]}
            elif method == "tools/call":
                state["calls"] += 1
                state["last_call_path"] = self.path
                result = {"content": [{"type": "text", "text": "synthetic-loopback-ok"}], "isError": False}
            else:
                self.send_error(400)
                return
            publish()
            payload = json.dumps({"jsonrpc": "2.0", "id": request["id"], "result": result}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    publish()
    (root / "http-peer.json").write_text(json.dumps({"endpoint": f"http://127.0.0.1:{server.server_port}/mcp"}))
    try:
        yield
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)

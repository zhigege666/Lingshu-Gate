"""Synthetic local MCP subprocess + authorization + SQLite audit; no network."""

import json
import tempfile
import time
import sys
import statistics
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.config import Settings
from lingshu_gate.models import ToolDefinition
from lingshu_gate.registry import ToolRegistry
from lingshu_gate.mcp_stdio_client import StdioMcpClient
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.protocol.version import MCP_PROTOCOL_VERSION

with tempfile.TemporaryDirectory(prefix="gate-stdio-bench-") as temporary:
    root = Path(temporary)
    server = root / "synthetic_echo.py"
    server.write_text("""import sys,json
for line in sys.stdin:
 message=json.loads(line)
 if 'id' not in message:continue
 method=message.get('method')
 if method=='server/discover':result={'supportedVersions':[sys.argv[1]],'capabilities':{'tools':{}}}
 elif method=='tools/call':result={'content':[{'type':'text','text':str(message['params']['arguments']['index'])}]}
 elif method=='tools/list':result={'tools':[]}
 else:result={}
 print(json.dumps({'jsonrpc':'2.0','id':message['id'],'result':result}),flush=True)
""")
    manifest = McpServerManifest.model_validate(
        {
            "id": "synthetic",
            "launch": {
                "type": "managed_process",
                "command": sys.executable,
                "args": [str(server), MCP_PROTOCOL_VERSION],
            },
            "transport": {"type": "stdio"},
            "timeout_seconds": 5,
        }
    )
    client = StdioMcpClient(manifest, Settings(data_dir=root, allowed_root=root))
    database = SQLiteDatabase("", root)
    access = AccessControlStore(database)
    database.execute(
        "INSERT INTO users(id,username,password_hash,created_at,updated_at) VALUES('bench','bench','not-a-login-hash','now','now')"
    )
    definition = ToolDefinition(
        id="mcp.synthetic.echo",
        name="Echo",
        description="Synthetic read-only echo",
        source="mcp",
        metadata={"server_id": "synthetic", "annotations": {"readOnlyHint": True}},
    )
    registry = ToolRegistry()
    registry.register(definition, lambda arguments: client.call_tool("echo", arguments))
    access.synchronize_tools([definition])
    database.execute("UPDATE mcp_tool_classifications SET effective_access='read',status='published'")
    access.save_grant(
        subject_type="user", subject_id="bench", server_id="synthetic", permission_type_code="read", created_by="bench"
    )
    principal = AuthPrincipal(
        id="bench", username="bench", role="operator", roles=("operator",), permissions=("tools.read",)
    )
    client.start()
    try:
        started = time.perf_counter()

        def invoke(index):
            tick = time.perf_counter()
            result = access.invoke_tool(registry, principal, definition.id, {"index": index})
            duration = (time.perf_counter() - tick) * 1000
            assert result.ok, (index, result.error)
            assert result.output["content"][0]["text"] == str(index)
            return duration

        with ThreadPoolExecutor(max_workers=8) as pool:
            times = list(pool.map(invoke, range(500)))
        total = time.perf_counter() - started
        audit = database.query_one("SELECT count(*) AS total,sum(outcome='success') AS success FROM invocation_audits")
        assert audit["total"] == audit["success"] == 500
        output = {
            "synthetic": True,
            "transport": "local stdio echo subprocess",
            "workers": 8,
            "calls": 500,
            "audit_successes": audit["success"],
            "duration_seconds": round(total, 3),
            "median_ms": round(statistics.median(times), 3),
            "p95_ms": round(sorted(times)[474], 3),
            "limits": "Includes Gate authorization and SQLite audit. Excludes real external services, HTTP/OAuth, application workload and sustained production load.",
        }
        print(json.dumps(output))
    finally:
        client.stop()

"""Isolated repeated discovery; no external MCP calls or production data."""

import gc
import json
import tempfile
import time
import statistics
import argparse
from pathlib import Path
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.models import ToolDefinition


def rss_kib():
    if not Path("/proc/self/status").exists():
        return None
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    return None


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--iterations", type=int, default=300)
args = parser.parse_args()
iterations = args.iterations
if not 1 <= iterations <= 5000:
    parser.error("iterations must be 1..5000")
with tempfile.TemporaryDirectory(prefix="gate-discovery-soak-") as directory:
    db = SQLiteDatabase("", Path(directory))
    store = AccessControlStore(db)
    db.execute(
        "INSERT INTO users(id,username,password_hash,created_at,updated_at) VALUES('bench','bench','not-a-login-hash','now','now')"
    )
    definitions = [
        ToolDefinition(
            id=f"mcp.server-{i // 50}.read-{i % 50}",
            name=f"Read {i}",
            description="Synthetic read-only tool",
            source="mcp",
            metadata={"server_id": f"server-{i // 50}", "annotations": {"readOnlyHint": True}},
        )
        for i in range(5000)
    ]
    store.synchronize_tools(definitions)
    db.execute("UPDATE mcp_tool_classifications SET effective_access='read',status='published'")
    for index in range(100):
        store.save_grant(
            subject_type="user",
            subject_id="bench",
            server_id=f"server-{index}",
            permission_type_code="read",
            created_by="bench",
        )
    principal = AuthPrincipal(
        id="bench", username="bench", role="operator", roles=("operator",), permissions=("tools.read",)
    )
    timings = []
    samples = []
    started = time.perf_counter()
    for index in range(iterations):
        tick = time.perf_counter()
        result = store.visible_tools(principal, definitions)
        timings.append((time.perf_counter() - tick) * 1000)
        assert len(result) == 5000
        del result
        if (index + 1) % 50 == 0:
            gc.collect()
            samples.append(
                {
                    "requests": index + 1,
                    "rss_kib": rss_kib(),
                    "elapsed_seconds": round(time.perf_counter() - started, 2),
                }
            )
            print(json.dumps(samples[-1]), flush=True)
    output = {
        "synthetic": True,
        "services": 100,
        "tools": 5000,
        "requests": iterations,
        "duration_seconds": round(time.perf_counter() - started, 2),
        "median_ms": round(statistics.median(timings), 3),
        "p95_ms": round(sorted(timings)[max(0, int(iterations * 0.95) - 1)], 3),
        "samples": samples,
        "limits": "In-process repeated authorization/discovery only; not actual MCP transport, full-system capacity or long-duration leak proof.",
    }
    print(json.dumps(output), flush=True)

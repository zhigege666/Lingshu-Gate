"""Disposable 5000-service/50000-tool discovery benchmark; never contacts a downstream."""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import logging
import platform
import statistics
import subprocess
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.mcp_gateway import register_mcp_gateway_route
from lingshu_gate.models import ToolDefinition
from lingshu_gate.oauth_server import OAuthError, OAuthServer
from lingshu_gate.protocol.version import MCP_PROTOCOL_VERSION
from lingshu_gate.registry import ToolExecutionError, ToolRegistry
from lingshu_gate.tool_catalog import CatalogDescribe, CatalogSearch, ToolCatalog
from lingshu_gate.transports.http import build_protocol_request


def rss_kib() -> int | None:
    path = Path("/proc/self/status")
    if path.exists():
        for line in path.read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    return None


def measure(action, repetitions: int) -> dict:
    timings, sizes = [], []
    for _ in range(repetitions):
        started = time.perf_counter()
        output = action()
        timings.append((time.perf_counter() - started) * 1000)
        sizes.append(len(output) if isinstance(output, bytes) else
                     len(json.dumps(output, ensure_ascii=False, separators=(",", ":")).encode()))
    return {"requests": repetitions, "median_ms": round(statistics.median(timings), 3),
            "p95_ms": round(sorted(timings)[max(0, int(len(timings) * .95) - 1)], 3),
            "max_response_bytes": max(sizes), "rss_kib": rss_kib()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--services", type=int, default=5000)
    parser.add_argument("--tools-per-service", type=int, default=10)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if (not 5000 <= args.services <= 10000 or not 10 <= args.tools_per_service <= 100
            or args.services * args.tools_per_service > 200000 or not 1 <= args.iterations <= 500):
        parser.error("Use 5000..10000 services, 10..100 tools/service, at most 200000 tools and 1..500 iterations")
    logging.disable(logging.CRITICAL)
    started = time.perf_counter()
    baseline_rss = rss_kib()
    with tempfile.TemporaryDirectory(prefix="gate-catalog-benchmark-") as directory:
        db = SQLiteDatabase("", Path(directory))
        access, registry = AccessControlStore(db), ToolRegistry()
        catalog = ToolCatalog(registry, access)
        db.execute("INSERT INTO users(id,username,password_hash,created_at,updated_at) VALUES('bench','bench','unused','now','now')")
        for service in range(args.services):
            server_id = f"service{service:05d}"
            for tool in range(args.tools_per_service):
                registry.register(ToolDefinition(id=f"mcp.{server_id}.read_{tool}", name=f"Read report {tool} {server_id}",
                    description=f"Synthetic read-only report for {server_id}; no downstream connection",
                    source="mcp", input_schema={"type": "object", "properties": {
                        f"field_{field}": {"type": "string", "description": "Synthetic input field"} for field in range(20)
                    }, "additionalProperties": False}, metadata={"server_id": server_id}), lambda arguments: arguments)
        registry_rss = rss_kib()
        indexed = time.perf_counter()
        catalog.synchronize()
        index_seconds = round(time.perf_counter() - indexed, 3)
        with db.session() as connection:
            connection.execute("UPDATE mcp_tool_classifications SET effective_access='read',status='published'")
            permission_id = connection.execute("SELECT id FROM permission_types WHERE code='read'").fetchone()[0]
            none_permission_id = connection.execute("SELECT id FROM permission_types WHERE code='none'").fetchone()[0]
            connection.executemany("""INSERT INTO mcp_resource_grants
                (id,subject_type,subject_id,server_id,tool_id,permission_type_id,created_by,created_at,updated_at)
                VALUES(?,'user','bench',?,'',?,'bench','now','now')""",
                [(f"grant-{index}", f"service{index:05d}", permission_id if index < args.services - 1 else none_permission_id)
                 for index in range(args.services)])
        principal = AuthPrincipal(id="bench", username="bench", role="operator", roles=("operator",), permissions=("tools.read",),
            auth_type="token", token_id="synthetic", scopes=("tools.read",))
        db.execute("INSERT INTO users(id,username,password_hash,created_at,updated_at) VALUES('subset','subset','unused','now','now')")
        subset_servers = {f"service{index:05d}" for index in range(5)}
        for server_id in subset_servers:
            access.save_grant(subject_type="user", subject_id="subset", server_id=server_id,
                permission_type_code="read", created_by="bench")
        subset = replace(principal, id="subset", username="subset", token_id="synthetic-subset")
        admin = replace(principal, role="admin", roles=("admin",), token_id="synthetic-admin")
        assert db.query_one("SELECT COUNT(*) FROM mcp_resource_grants WHERE subject_id='bench'")[0] == args.services
        subset_instances = catalog.search(subset, CatalogSearch(), instances=True)["instances"]
        assert {item["instance_id"] for item in subset_instances} == subset_servers
        subset_page = catalog.search(subset, CatalogSearch(query="read", limit=1))
        subset_next = catalog.search(subset, CatalogSearch(query="read", limit=1, cursor=subset_page["next_cursor"]))
        assert subset_page["tools"][0] != subset_next["tools"][0]
        assert subset_page["tools"][0]["instance_id"] in subset_servers
        hidden_server = f"service{args.services - 1:05d}"
        assert catalog.search(principal, CatalogSearch(instance_id=hidden_server))["tools"] == []
        assert len(catalog.search(admin, CatalogSearch(instance_id=hidden_server, limit=100, max_bytes=65_536))["tools"]) == args.tools_per_service
        revoke_page = catalog.search(principal, CatalogSearch(query="read", limit=1))
        access.delete_grant("grant-0")
        try:
            catalog.search(principal, CatalogSearch(query="read", limit=1, cursor=revoke_page["next_cursor"]))
            raise AssertionError("Revoked cursor returned data")
        except ToolExecutionError as error:
            assert error.code == "catalog_cursor_invalid"
        assert catalog.search(principal, CatalogSearch(instance_id="service00000"))["tools"] == []
        access.save_grant(subject_type="user", subject_id="bench", server_id="service00000", permission_type_code="read", created_by="bench")
        oauth_started = time.perf_counter()
        try:
            # Real consent-catalog code, without issuing credentials/keys.
            OAuthServer.catalog(SimpleNamespace(access=access, registry=registry), principal, ["tools.read"])
            raise AssertionError("Existing OAuth catalog ceiling was unexpectedly widened")
        except OAuthError as error:
            assert error.code == "tool_catalog_limit"
            oauth_ceiling = {"code": error.code, "elapsed_ms": round((time.perf_counter() - oauth_started) * 1000, 3)}
        scope_cases = {"primary_explicit_grants": args.services, "primary_visible_services": args.services - 1,
            "subset_explicit_services": 5, "subset_visible_tools": 5 * args.tools_per_service,
            "admin_hidden_instance_visible": True, "revoked_instance_hidden": True,
            "revoked_cursor_rejected": True, "subset_pagination_distinct": True, "oauth_catalog_ceiling": oauth_ceiling}
        app = FastAPI()
        def require(request: Request) -> AuthPrincipal:
            return principal
        register_mcp_gateway_route(app, Settings(), registry, access, require, catalog=catalog)
        client = TestClient(app)
        def rpc(method, params, mode):
            current, headers = build_protocol_request(method, params, client_name="benchmark", client_version="1.0",
                protocol_version=MCP_PROTOCOL_VERSION)
            response = client.post(f"/mcp?tool_mode={mode}", headers={"accept": "application/json,text/event-stream", **headers},
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": current})
            assert response.status_code == 200, response.text[:500]
            assert "error" not in response.json()
            return response.content
        profiles = {}
        profiles["mcp_on_demand_list"] = measure(lambda: rpc("tools/list", {}, "on_demand"), args.iterations)
        profiles["indexed_narrow_search"] = measure(lambda: catalog.search(principal, CatalogSearch(query="service00042 read")), args.iterations)
        profiles["broad_keyword_search"] = measure(lambda: catalog.search(principal, CatalogSearch(query="read")), args.iterations)
        profiles["empty_query_search"] = measure(lambda: catalog.search(principal, CatalogSearch()), args.iterations)
        profiles["subset_broad_search"] = measure(lambda: catalog.search(subset, CatalogSearch(query="read")), args.iterations)
        profiles["admin_broad_search"] = measure(lambda: catalog.search(admin, CatalogSearch(query="read")), args.iterations)
        profiles["unauthorized_instance_search"] = measure(lambda: catalog.search(principal, CatalogSearch(instance_id=f"service{args.services - 1:05d}")), args.iterations)
        profiles["one_schema_describe"] = measure(lambda: catalog.describe(principal, CatalogDescribe(tool_ref="mcp.service00042.read_0")), args.iterations)
        profiles["mcp_on_demand_search"] = measure(lambda: rpc("tools/call", {"name": "gate_catalog_search", "arguments": {"query": "service00042 read"}}, "on_demand"), args.iterations)
        described = catalog.describe(principal, CatalogDescribe(tool_ref="mcp.service00042.read_0"))
        profiles["mcp_on_demand_echo_invoke"] = measure(lambda: rpc("tools/call", {"name": "gate_tool_invoke", "arguments": {
            "tool_ref": described["tool_ref"], "schema_revision": described["schema_revision"],
            "instance_id": "service00042", "arguments": {"field_0": "synthetic"}}}, "on_demand"), args.iterations)
        print(json.dumps({"stage": "on_demand_complete", "rss_kib": rss_kib(), "profiles": profiles}), flush=True)
        profiles["legacy_mcp_full_list"] = measure(lambda: rpc("tools/list", {}, "direct"), 3)
        gc.collect()
        soak = []
        for index in range(args.iterations):
            catalog.search(principal, CatalogSearch(query="service00042 read"))
            if index in {0, args.iterations // 2, args.iterations - 1}:
                gc.collect()
                soak.append({"request": index + 1, "rss_kib": rss_kib()})
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        output = {"synthetic": True, "source_sha": revision, "python": platform.python_version(), "platform": platform.platform(),
            "benchmark_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "services": args.services, "tools": args.services * args.tools_per_service, "input_fields_per_tool": 20,
            "baseline_rss_kib": baseline_rss, "registry_rss_kib": registry_rss, "index_build_seconds": index_seconds,
            "database_bytes": db.path.stat().st_size, "profiles": profiles, "soak": soak,
            "scope_cases": scope_cases,
            "duration_seconds": round(time.perf_counter() - started, 3),
            "limits": "Synthetic single-process, warm-cache SQLite/function and loopback ASGI timings. Echo handlers only; no real MCP connections, production SLA, downstream latency, sustained throughput or long-duration leak certification."}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(output, indent=2) + "\n")
        print(json.dumps(output), flush=True)


if __name__ == "__main__":
    main()

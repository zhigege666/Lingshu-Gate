"""Disposable 1000-instance/50000-tool public logical-directory benchmark."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import platform
import statistics
import subprocess
import tempfile
import threading
import time
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.application.mcp_group_routing import McpGroupRoutingService
from lingshu_gate.application.mcp_groups import McpGroupService
from lingshu_gate.application import schema_validation
from lingshu_gate.auth import AuthStore
from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.domain.mcp_group_catalog import MAX_CATALOG_CONTRACT_BYTES
from lingshu_gate.domain.mcp_group_routing import logical_service_id
from lingshu_gate.domain.mcp_groups import McpGroupCreate
from lingshu_gate.interfaces.control_api.catalog_routes import register_catalog_routes
from lingshu_gate.mcp_config_store import McpConfigStore
from lingshu_gate.mcp_gateway import register_mcp_gateway_route
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_runtime import McpRuntimeManager, McpServerRuntime, McpServerState
from lingshu_gate.mcp_runtime_state_store import McpRuntimeStateStore
from lingshu_gate.models import ToolDefinition
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.persistence.mcp_groups import McpGroupStore
from lingshu_gate.protocol.version import MCP_PROTOCOL_VERSION
from lingshu_gate.registry import ToolExecutionError, ToolRegistry
from lingshu_gate.tool_catalog import CatalogDescribe, CatalogSearch, ToolCatalog
from lingshu_gate.transports.http import build_protocol_request


def rss_kib(pid: int | str = "self") -> int:
    try:
        return next(int(line.split()[1]) for line in Path(f"/proc/{pid}/status").read_text().splitlines()
                    if line.startswith("VmRSS:"))
    except (FileNotFoundError, StopIteration):
        return 0


def measure(action, repetitions: int) -> dict:
    times, sizes = [], []
    for _ in range(repetitions):
        start = time.perf_counter()
        output = action()
        times.append((time.perf_counter() - start) * 1000)
        sizes.append(len(output) if isinstance(output, bytes) else
                     len(json.dumps(output, ensure_ascii=False, separators=(",", ":")).encode()))
    return {"requests": repetitions, "median_ms": round(statistics.median(times), 3),
        "p95_ms": round(sorted(times)[math.ceil(len(times) * .95) - 1], 3),
        "max_response_bytes": max(sizes), "parent_rss_kib": rss_kib()}


class SyntheticPeer:
    pid = None

    def __init__(self, instance: str) -> None:
        self.instance, self.calls = instance, 0

    def call_tool(self, name, arguments):
        self.calls += 1
        return {"instance": self.instance, "name": name, "arguments": arguments}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 1 <= args.iterations <= 100:
        parser.error("Use 1..100 iterations; the fixture is always 1000 instances and 50000 tools")
    logging.disable(logging.CRITICAL)
    # Synthetic local identities only. No network or deployment is configured.
    password = "Synthetic-Group-Benchmark-123!"
    os.environ["LINGSHU_GATE_ADMIN_USERNAME"] = "synthetic-benchmark-admin"
    os.environ["LINGSHU_GATE_ADMIN_PASSWORD"] = password
    started, baseline_rss = time.perf_counter(), rss_kib()
    peaks, stop = {"parent_rss_kib": baseline_rss, "validation_child_rss_kib": 0}, threading.Event()
    children = []
    original_spawn = schema_validation.subprocess.Popen
    def observed_spawn(*values, **options):
        process = original_spawn(*values, **options)
        if values and isinstance(values[0], list) and "--worker" in values[0]:
            children.append(process)
        return process
    schema_validation.subprocess.Popen = observed_spawn
    def sample_memory():
        while not stop.wait(.01):
            peaks["parent_rss_kib"] = max(peaks["parent_rss_kib"], rss_kib())
            # This kernel does not expose /proc task children. Observe the real
            # Popen objects without changing launch, validation or cancellation.
            for process in tuple(children):
                if process.poll() is None:
                    peaks["validation_child_rss_kib"] = max(peaks["validation_child_rss_kib"], rss_kib(process.pid))
    sampler = threading.Thread(target=sample_memory, daemon=True)
    sampler.start()
    try:
        with tempfile.TemporaryDirectory(prefix="gate-group-benchmark-") as directory:
            root = Path(directory)
            settings = Settings(data_dir=root, config_dir=root / "mcp.d")
            db = SQLiteDatabase("", root)
            access, registry = AccessControlStore(db), ToolRegistry()
            auth = AuthStore(settings, db)
            admin_id = str(auth.list_users()[0]["id"])
            auth.change_password(admin_id, password)
            admin, _, _ = auth.login(username="synthetic-benchmark-admin", password=password)
            configs = McpConfigStore(settings.config_dir)
            runtime = McpRuntimeManager(settings, registry, state_store=McpRuntimeStateStore(db))
            groups = McpGroupService(McpGroupStore(db, ObservabilityStore(db)), configs, runtime)
            router = McpGroupRoutingService(groups, registry, access, auth)
            catalog = ToolCatalog(registry, access, group_router=router)
            access.attach_mcp_runtime(runtime)
            instances = [f"member{index:04d}" for index in range(1000)]
            configs.config_dir.mkdir(parents=True, exist_ok=True)
            for instance in instances:
                # Fixture seeding is not an administrative-save benchmark.
                # The normal config/group loaders still validate these files.
                manifest = McpServerManifest.model_validate({"id": instance, "name": instance,
                    "launch": {"type": "external"}, "transport": {"type": "streamable_http",
                    "endpoint": "https://mcp.example.test/mcp"}})
                (configs.config_dir / f"{instance}.json").write_text(manifest.model_dump_json(exclude={"manifest_path"}))
                for tool in range(50):
                    name = f"query{tool:02d}"
                    registry.register(ToolDefinition(id=f"mcp.{instance}.{name}", name=name,
                        description="Synthetic grouped report", source="mcp", input_schema={"type": "object",
                            "properties": {"key": {"type": "string"}}, "additionalProperties": False},
                        metadata={"server_id": instance, "original_tool_name": name,
                                  "annotations": {"readOnlyHint": True}}), lambda arguments: arguments)
            registry_rss = rss_kib()
            structural_bytes = sum(entry.structure.byte_count for entry in registry.mcp_snapshot(instances, max_tools=50_000).tools)
            assert structural_bytes <= MAX_CATALOG_CONTRACT_BYTES
            indexed = time.perf_counter()
            catalog.synchronize()
            index_seconds = time.perf_counter() - indexed
            db.execute("UPDATE mcp_tool_classifications SET effective_access='read',status='published',"
                "reviewed_by=?,reviewed_at='2026-10-05T00:00:00Z',destructive=0,idempotent=1,open_world=0", (admin.id,))
            group = groups.save(McpGroupCreate(name="Synthetic benchmark group", members=instances,
                status="active", confirmed=True, request_key=uuid4().hex), admin)
            owner = auth.create_user(username="synthetic-group-reader", password=password, role="operator")
            owner_actor, _, _ = auth.login(username=owner["username"], password=password)
            token = auth.create_api_token(principal=owner_actor, name="Synthetic benchmark", scopes=["tools.read", "tools.invoke"])
            actor = auth._principal_from_api_token(token["token"])
            assert actor is not None
            with db.session() as connection:
                read = connection.execute("SELECT id FROM permission_types WHERE code='read'").fetchone()[0]
                none = connection.execute("SELECT id FROM permission_types WHERE code='none'").fetchone()[0]
                connection.executemany("INSERT INTO mcp_resource_grants "
                    "(id,subject_type,subject_id,server_id,tool_id,permission_type_id,created_by,created_at,updated_at) "
                    "VALUES(?,'user',?,?,'',?,?, 'now','now')",
                    [(f"physical-{index}", actor.id, instance, read if index < 999 else none, admin.id)
                     for index, instance in enumerate(instances)])
            logical = access.save_grant(subject_type="user", subject_id=actor.id, server_id=logical_service_id(group["id"]),
                permission_type_code="read", created_by=admin.id)
            print(json.dumps({"stage": "fixture_ready", "tools": 50_000, "instances": 1000,
                "structural_bytes": structural_bytes, "parent_rss_kib": rss_kib()}), flush=True)
            profiles = {"cold_group_search": measure(lambda: catalog.search(actor, CatalogSearch(group_id=group["id"])), 1)}
            # A hidden member cannot affect query matching, summaries, counts or recommendations.
            assert catalog.search(actor, CatalogSearch(group_id=group["id"], query="member0999"))["tools"] == []
            page = catalog.search(actor, CatalogSearch(group_id=group["id"], limit=1))
            later = catalog.search(actor, CatalogSearch(group_id=group["id"], limit=1, cursor=page["next_cursor"]))
            assert page["tools"][0]["tool_ref"] != later["tools"][0]["tool_ref"]
            ref = page["tools"][0]["tool_ref"]
            described = catalog.describe(actor, CatalogDescribe(tool_ref=ref, instance_id="member0000"))
            access.delete_grant(logical["id"])
            try:
                catalog.search(actor, CatalogSearch(group_id=group["id"], limit=1, cursor=page["next_cursor"]))
                raise AssertionError("Logical-grant revocation did not invalidate cursor")
            except ToolExecutionError as error:
                assert error.code == "catalog_cursor_invalid"
            assert catalog.search(actor, CatalogSearch(group_id=group["id"]))["tools"] == []
            access.save_grant(subject_type="user", subject_id=actor.id, server_id=logical_service_id(group["id"]),
                permission_type_code="read", created_by=admin.id)
            peers = {}
            for instance in ("member0000", "member0001"):
                peers[instance] = SyntheticPeer(instance)
                runtime._servers[instance] = McpServerRuntime(configs.load_manifest(instance),
                    state=McpServerState.RUNNING, client=peers[instance])
            # Session binding requires an already selected runtime generation.
            session = catalog.call("gate_instance_session_open", {key: described[key]
                for key in ("tool_ref", "instance_id", "schema_revision")}, actor).output
            subset_record = auth.create_user(username="synthetic-group-subset", password=password, role="operator")
            subset, _, _ = auth.login(username=subset_record["username"], password=password)
            for server in ("member0000", "member0001", logical_service_id(group["id"])):
                access.save_grant(subject_type="user", subject_id=subset.id, server_id=server,
                    permission_type_code="read", created_by=admin.id)
            subset_instances = catalog.search(subset, CatalogSearch(group_id=group["id"], tool_ref=ref, limit=100), instances=True)
            assert {item["instance_id"] for item in subset_instances["instances"]} == {"member0000", "member0001"}
            app = FastAPI()
            def require(request: Request):
                current = auth._principal_from_api_token(token["token"])
                assert current is not None
                return current
            register_catalog_routes(app, catalog=catalog, require_authenticated=require)
            register_mcp_gateway_route(app, settings, registry, access, require, catalog=catalog)
            with TestClient(app) as client:
                def api(path, body):
                    response = client.post(f"/v1/catalog/{path}", json=body)
                    assert response.status_code == 200, response.text[:500]
                    return response.content
                def rpc(name, arguments):
                    params, headers = build_protocol_request("tools/call", {"name": name, "arguments": arguments},
                        client_name="group-benchmark", client_version="1.0", protocol_version=MCP_PROTOCOL_VERSION)
                    response = client.post("/mcp?tool_mode=on_demand", headers={"accept": "application/json,text/event-stream", **headers},
                        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
                    assert response.status_code == 200 and "error" not in response.json(), response.text[:500]
                    assert not response.json()["result"].get("isError")
                    return response.content
                profiles["warm_group_search"] = measure(lambda: catalog.search(actor, CatalogSearch(group_id=group["id"])), args.iterations)
                profiles["narrow_group_search"] = measure(lambda: catalog.search(actor, CatalogSearch(group_id=group["id"], query="query00")), args.iterations)
                profiles["subset_group_search"] = measure(lambda: catalog.search(subset, CatalogSearch(group_id=group["id"])), args.iterations)
                profiles["selected_instance_describe"] = measure(lambda: catalog.describe(actor, CatalogDescribe(tool_ref=ref,
                    instance_id="member0000")), args.iterations)
                selection = {key: described[key] for key in ("tool_ref", "instance_id", "schema_revision")}
                profiles["public_api_search"] = measure(lambda: api("search", {"group_id": group["id"], "query": "query00"}), args.iterations)
                profiles["public_mcp_describe"] = measure(lambda: rpc("gate_tool_describe",
                    {"tool_ref": ref, "instance_id": "member0000"}), args.iterations)
                body = {**selection, "session_id": session["session_id"], "arguments": {"key": "synthetic"}}
                profiles["public_mcp_invoke"] = measure(lambda: rpc("gate_tool_invoke", body), args.iterations)
            assert peers["member0000"].calls == args.iterations and peers["member0001"].calls == 0
            audits = db.query_all("SELECT tool_id,server_id,outcome FROM invocation_audits")
            assert len(audits) == args.iterations and all(tuple(row) == ("mcp.member0000.query00", "member0000", "success") for row in audits)
            output = {"synthetic": True, "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "benchmark_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                "python": platform.python_version(), "platform": platform.platform(), "group_instances": 1000,
                "tools": 50_000, "tools_per_instance": 50, "input_fields_per_tool": 1,
                "primary_visible_instances": 999, "primary_visible_tools": 49_950, "logical_variants": 50,
                "subset_instances": 2, "subset_tools": 100, "structural_bytes": structural_bytes,
                "group_contract_capacity_bytes": MAX_CATALOG_CONTRACT_BYTES, "baseline_parent_rss_kib": baseline_rss,
                "registry_parent_rss_kib": registry_rss, "index_seconds": round(index_seconds, 3),
                "memory_sampled_peaks": peaks, "structure_cache_usage": router.structures.usage(),
                "database_bytes": db.path.stat().st_size, "profiles": profiles,
                "scope_cases": {"hidden_member_query_empty": True, "logical_revocation_hides_directory": True,
                    "old_cursor_rejected": True, "subset_instance_isolation": True, "distinct_pages": True,
                    "original_physical_audit": True, "unselected_peer_calls": 0},
                "duration_seconds": round(time.perf_counter() - started, 3),
                "limits": "Synthetic token/session identities and reviewed contracts; local ASGI and echo peers only. "
                    "Selected resolution scans 50 tools in one instance; search re-authorizes the bounded full group. "
                    "RSS is Linux sampled residency, not address space; worker peaks are separate. "
                    "No real OAuth verification, downstream network, production SLA, sustained load or deployment claim."}
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(output, indent=2) + "\n")
            print(json.dumps(output), flush=True)
    finally:
        stop.set()
        sampler.join(timeout=1)
        schema_validation.subprocess.Popen = original_spawn


if __name__ == "__main__":
    main()

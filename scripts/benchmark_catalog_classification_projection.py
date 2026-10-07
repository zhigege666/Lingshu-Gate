"""Controlled complete-row / narrow-row comparison; synthetic data is not an SLA.

Run each mode in its own process, with the same evidence size and sample count.
The complete mode replays the unchanged pre-optimization classification loader.
This measures classification/policy projection, not the whole group snapshot.
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import inspect
import json
import math
import os
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from unittest.mock import patch

from lingshu_gate.access_control import AccessControlStore, _tool_fingerprint
from lingshu_gate.auth import AuthStore
from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.models import ToolDefinition


def rss_kib():
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"):
            return int(line.split()[1])
    raise RuntimeError("Linux process RSS was not available")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["complete", "catalog"], required=True)
    parser.add_argument("--evidence-bytes", type=int, default=1024)
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "linux":
        parser.error("This benchmark reports Linux /proc RSS and Linux ru_maxrss units")
    if not 1 <= args.samples <= 30 or not 0 <= args.evidence_bytes <= 65536:
        parser.error("Use 1..30 samples and 0..65536 synthetic evidence payload bytes")
    started = time.perf_counter()
    baseline_rss = rss_kib()
    password = "Synthetic-Projection-Benchmark-123!"
    with tempfile.TemporaryDirectory(prefix="gate-classification-benchmark-") as directory, patch.dict(os.environ, {
        "LINGSHU_GATE_ADMIN_USERNAME": "synthetic-projection-admin", "LINGSHU_GATE_ADMIN_PASSWORD": password,
    }):
        root = Path(directory)
        database = SQLiteDatabase("", root)
        access = AccessControlStore(database)
        auth = AuthStore(Settings(data_dir=root, config_dir=root / "mcp.d"), database)
        reviewer = str(auth.list_users()[0]["id"])
        reader = auth.create_user(username="synthetic-projection-reader", password=password, role="operator")
        actor, _, _ = auth.login(username=reader["username"], password=password)
        definitions, fingerprints, keys = [], {}, []
        for service in range(5000):
            instance = f"synthetic-{service:04}"
            for number in range(10):
                name = f"query-{number:02}"
                definition = ToolDefinition(id=f"mcp.{instance}.{name}", name=name, description="Synthetic catalog contract",
                    source="mcp", input_schema={"type": "object", "properties": {"id": {"type": "string"}}},
                    metadata={"server_id": instance, "original_tool_name": name, "annotations": {"readOnlyHint": True}})
                definitions.append(definition)
                fingerprints[definition.id] = _tool_fingerprint(definition)
                keys.append((instance, definition.id))
        evidence = json.dumps({"synthetic_analysis": "x" * args.evidence_bytes}, separators=(",", ":"))
        with database.session() as connection:
            connection.executemany("INSERT INTO mcp_tool_classifications "
                "(id,server_id,tool_id,tool_name,fingerprint,suggested_access,effective_access,status,confidence,source,"
                "destructive,idempotent,open_world,evidence_json,reviewed_by,reviewed_at,created_at,updated_at) "
                "VALUES(?,?,?,?,?,'read','read','published',0.9,'manual',0,1,0,?,?,?,'now','now')",
                ((f"synthetic-review-{index}", instance, definition.id, definition.name, fingerprints[definition.id],
                  evidence, reviewer, "2026-10-06T00:00:00Z") for index, (instance, _) in enumerate(keys)
                 for definition in (definitions[index],)))
            read = connection.execute("SELECT id FROM permission_types WHERE code='read'").fetchone()[0]
            none = connection.execute("SELECT id FROM permission_types WHERE code='none'").fetchone()[0]
            connection.executemany("INSERT INTO mcp_resource_grants "
                "(id,subject_type,subject_id,server_id,tool_id,permission_type_id,created_by,created_at,updated_at) "
                "VALUES(?,'user',?,?,'',?,?,'now','now')",
                ((f"synthetic-grant-{index}", actor.id, f"synthetic-{index:04}", read if index < 4999 else none, reviewer)
                 for index in range(5000)))
            connection.execute("INSERT INTO mcp_resource_grants "
                "(id,subject_type,subject_id,server_id,tool_id,permission_type_id,created_by,created_at,updated_at) "
                "VALUES('synthetic-tool-denial','user',?,?,?,?,?,'now','now')", (actor.id, *keys[0], none, reviewer))
        fixture_seconds = time.perf_counter() - started
        loader = access._load_classifications if args.mode == "complete" else access._load_catalog_classifications
        # One change only: replay the unchanged original loader for the baseline.
        if args.mode == "complete":
            access._load_catalog_classifications = access._load_classifications

        def load():
            with database.session() as connection:
                connection.execute("BEGIN")
                return loader(connection, keys)

        def project():
            with database.session() as connection:
                connection.execute("BEGIN")
                return access.visible_tool_contracts(actor, definitions, connection=connection, fingerprints=fingerprints)

        def measure(call, expected_count):
            warm = call()
            assert len(warm) == expected_count
            del warm
            samples = []
            for _ in range(args.samples):
                gc.collect()
                before = time.perf_counter()
                result = call()
                samples.append((time.perf_counter() - before) * 1000)
                assert len(result) == expected_count
                del result
            # Allocation probes are separate from the ordinary latency samples.
            gc.collect()
            before_rss = rss_kib()
            tracemalloc.start()
            result = call()
            current_bytes, peak_bytes = tracemalloc.get_traced_memory()
            retained_rss = rss_kib()
            if isinstance(result, dict):
                signature = "\n".join(f"{key[0]}/{key[1]}:{row['fingerprint']}:{row['status']}:{row['effective_access']}"
                                      for key, row in sorted(result.items()))
            else:
                signature = "\n".join(f"{item.id}:{row['fingerprint']}:{row['status']}:{row['effective_access']}"
                                      for item, row in result)
            digest = hashlib.sha256(signature.encode()).hexdigest()
            tracemalloc.stop()
            del result, signature
            return {"samples": args.samples, "median_ms": round(statistics.median(samples), 3),
                "p95_ms": round(sorted(samples)[math.ceil(len(samples) * .95) - 1], 3),
                "samples_ms": [round(value, 3) for value in samples], "result_count": expected_count,
                "policy_result_sha256": digest, "allocation_probe_retained_bytes": current_bytes,
                "allocation_probe_peak_bytes": peak_bytes, "allocation_probe_rss_before_kib": before_rss,
                "allocation_probe_rss_while_result_retained_kib": retained_rss}

        print(json.dumps({"stage": "fixture_ready", "services": 5000, "tools": 50000,
                          "fixture_seconds": round(fixture_seconds, 3), "rss_kib": rss_kib()}), flush=True)
        profiles = {"classification_load": measure(load, 50_000), "visible_policy_projection": measure(project, 49_989)}
        statements = []
        with database.session() as connection:
            connection.set_trace_callback(statements.append)
            rows = loader(connection, keys)
            selected_columns = sorted(next(iter(rows.values())))
            del rows
        source_sha = subprocess.run(["git", "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        output = {"source_sha": source_sha, "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "complete_loader_sha256": hashlib.sha256(inspect.getsource(AccessControlStore._load_classifications).encode()).hexdigest(),
            "mode": args.mode, "python": platform.python_version(), "platform": platform.platform(),
            "services": 5000, "tools": 50_000, "evidence_payload_bytes_per_row": args.evidence_bytes,
            "evidence_json_bytes_per_row": len(evidence.encode()), "selected_columns": selected_columns,
            "classification_selects_per_load": len(statements), "fixture_seconds": round(fixture_seconds, 3),
            "baseline_rss_kib": baseline_rss, "profiles": profiles,
            "process_lifetime_ru_maxrss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "scope": "Same synthetic 5000-service/50000-tool classification and current-grant projection; "
                     "complete mode replays the unchanged original SELECT * loader. Separate Linux processes, warm SQLite. "
                     "No full group HTTP snapshot, file configuration loading, downstream, concurrency or production SLA.",
            "memory_note": "tracemalloc probes are separate from latency samples; RSS is observed process residency. "
                           "ru_maxrss is cumulative for the whole process including fixture and all profiles, not a request peak."}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, indent=2) + "\n")
        print(json.dumps(output), flush=True)


if __name__ == "__main__":
    main()

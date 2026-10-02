"""D01–D02: real local delivery, configuration changes and artifact versions.

The archive has no dependencies and uses only Python's standard library. All
storage and child processes belong to pytest's temporary directory. No network
endpoint or production credential is used. Run the test under an outer timeout.
"""
from __future__ import annotations

import io
import json
import os
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient


SYNTHETIC_SERVER = '''import json, os, sys
MARKER = os.environ.get("DELIVERY_MARKER", "unset")
for line in sys.stdin:
    message = json.loads(line)
    method = message.get("method")
    if "id" not in message:
        continue
    if method == "server/discover":
        result = {"supportedVersions": ["2026-07-28"], "resultType": "complete",
                  "capabilities": {"tools": {}},
                  "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "synthetic-delivery", "version": "1"}}}
    elif method == "tools/list":
        result = {"tools": [{"name": "snapshot", "description": "Read synthetic process state",
            "inputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}}]}
    elif method == "tools/call":
        result = {"content": [{"type": "text", "text": json.dumps({
            "marker": MARKER, "pid": os.getpid(), "cwd": os.getcwd()})}], "isError": False}
    else:
        result = {}
    print(json.dumps({"jsonrpc": "2.0", "id": message["id"], "result": result}), flush=True)
'''


def test_d01_real_upload_build_deploy_and_configuration_reapply(tmp_path: Path, monkeypatch) -> None:
    for key in tuple(os.environ):
        if key.startswith("LINGSHU_GATE_"):
            monkeypatch.delenv(key)
    for key, value in {
        "DATA_DIR": str(tmp_path), "DB_URL": f"sqlite:///{tmp_path / 'journey.db'}",
        "CONFIG_DIR": str(tmp_path / "mcp.d"), "ALLOWED_ROOT": str(tmp_path),
        "AUTH_ENABLED": "true", "RUNTIME_ROLE": "local",
    }.items():
        monkeypatch.setenv(f"LINGSHU_GATE_{key}", value)
    from lingshu_gate.main import create_app

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("server.py", SYNTHETIC_SERVER)
        bundle.writestr("pyproject.toml", '[project]\nname = "synthetic-delivery"\nversion = "0.0.1"\n')
    with TestClient(create_app(), base_url="https://testserver") as client:
        state = client.app.state
        admin = state.auth_store.list_users()[0]
        state.auth_store.change_password(admin["id"], "Synthetic-delivery-123!")
        login = client.post("/v1/auth/login", json={"username": admin["username"], "password": "Synthetic-delivery-123!"})
        assert login.status_code == 200, login.text
        uploaded = client.post("/v1/projects/upload", files={"file": ("synthetic-delivery.zip", archive.getvalue(), "application/zip")})
        assert uploaded.status_code == 200, uploaded.text
        upload_id = uploaded.json()["id"]
        options = {"upload_id": upload_id, "runtime_override": "python", "run_install": False, "run_build": False}
        planned = client.post("/v1/builds/plan", json=options)
        assert planned.status_code == 200, planned.text
        assert planned.json()["plan"]["steps"] == []  # Packaging only; no install/build scripts.
        created = client.post("/v1/builds", json={**options, "timeout_seconds": 10})
        assert created.status_code == 200, created.text
        build_id = created.json()["id"]
        deadline = time.monotonic() + 20
        while True:
            built = client.get(f"/v1/builds/{build_id}").json()
            if built["status"] in {"success", "failed", "cancelled", "unsupported"}:
                break
            assert time.monotonic() < deadline, f"build did not terminate: {build_id}"
            time.sleep(0.05)
        assert built["status"] == "success", built
        server_id = built["manifest"]["id"]
        patch = {"launch": {"env": {"DELIVERY_MARKER": "synthetic-v1"}},
                 "timeout_seconds": 3, "transport": {"protocol_version": "2026-07-28"}, "restart_policy": {"enabled": False}}
        draft_url = f"/v1/delivery-drafts/{upload_id}"
        draft = client.put(draft_url, json={"expected_revision": 0, "build_id": build_id,
            "server_id": server_id, "manifest_patch": patch, "start": True})
        assert draft.status_code == 200, draft.text
        restored = client.get(draft_url).json()
        assert restored["manifest_patch"] == patch
        assert restored["build_id"] == build_id
        body = {"server_id": server_id, "manifest_patch": restored["manifest_patch"], "start": True}
        deploy_url = f"/v1/builds/{build_id}/deploy"
        preview = client.post(deploy_url + "/preview", json=body)
        assert preview.status_code == 200, preview.text
        confirmation = preview.json()
        body.update({"expected_config_digest": confirmation["config_digest"],
            "expected_previous_config_digest": confirmation["expected_previous_config_digest"],
            "expected_credential_binding_digest": confirmation["expected_credential_binding_digest"]})
        deployed = client.post(deploy_url, json=body)
        assert deployed.status_code == 200, deployed.text
        deployment = deployed.json()
        assert deployment["status"] == "success", deployment
        assert deployment["runtime_started"] is True
        history = state.database.query_one("SELECT manifest_json FROM deployments WHERE id=?", (deployment["id"],))
        assert "synthetic-v1" not in history["manifest_json"]
        server = client.get(f"/v1/mcp/servers/{server_id}").json()
        assert server["status"] == "running", server
        assert server["tool_count"] == 1, server
        tool_id = f"mcp.{server_id}.snapshot"
        assert tool_id in {tool["id"] for tool in client.get("/v1/tools").json()}

        def process_snapshot():
            response = client.post(f"/v1/tools/{tool_id}/invoke", json={"arguments": {}})
            assert response.status_code == 200, response.text
            assert response.json()["ok"], response.text
            return json.loads(response.json()["output"]["content"][0]["text"])

        first = process_snapshot()
        assert first["marker"] == "synthetic-v1"
        assert Path(first["cwd"]) == Path(built["artifact_dir"])
        manifest = client.get(f"/v1/mcp/configs/{server_id}").json()["manifest"]
        manifest["launch"]["env"]["DELIVERY_MARKER"] = "synthetic-v2"
        applied = client.put(f"/v1/mcp/configs/{server_id}", json={"manifest": manifest, "apply": True, "start": True})
        assert applied.status_code == 200, applied.text
        assert applied.json()["server"]["status"] == "running", applied.text
        second = process_snapshot()
        assert second["marker"] == "synthetic-v2"
        assert first["pid"] != second["pid"]
        assert state.mcp_config_store.load_manifest(server_id).launch.env["DELIVERY_MARKER"] == "synthetic-v2"
        saved = client.put(draft_url, json={"expected_revision": restored["revision"],
            "build_id": build_id, "deployment_id": deployment["id"], "server_id": server_id,
            "manifest_patch": patch, "start": True})
        assert saved.status_code == 200, saved.text
        assert client.get(draft_url).json()["deployment_id"] == deployment["id"]
        print(json.dumps({"scenario": "D01", "upload_id": upload_id, "build_id": build_id,
            "deployment_id": deployment["id"], "server_id": server_id, "tool_count": server["tool_count"],
            "before": first, "after": second, "transport": "real stdio", "protocol_version": "2026-07-28", "build_steps": []}))


def test_d02_real_failed_build_preserves_service_then_artifact_replace_and_rollback(tmp_path: Path, monkeypatch) -> None:
    """Two distinct Python artifacts plus one deliberately failing local Node build."""
    for key in tuple(os.environ):
        if key.startswith("LINGSHU_GATE_"):
            monkeypatch.delenv(key)
    for key, value in {
        "DATA_DIR": str(tmp_path), "DB_URL": f"sqlite:///{tmp_path / 'versions.db'}",
        "CONFIG_DIR": str(tmp_path / "mcp.d"), "ALLOWED_ROOT": str(tmp_path),
        "AUTH_ENABLED": "true", "RUNTIME_ROLE": "local",
    }.items():
        monkeypatch.setenv(f"LINGSHU_GATE_{key}", value)
    from lingshu_gate.main import create_app

    with TestClient(create_app(), base_url="https://testserver") as client:
        state = client.app.state
        admin = state.auth_store.list_users()[0]
        state.auth_store.change_password(admin["id"], "Synthetic-version-123!")
        assert client.post("/v1/auth/login", json={"username": admin["username"], "password": "Synthetic-version-123!"}).status_code == 200
        server_id = "synthetic-versioned"
        tool_id = f"mcp.{server_id}.snapshot"

        def build_archive(version: str, *, fail: bool = False):
            archive = io.BytesIO()
            with zipfile.ZipFile(archive, "w") as bundle:
                if fail:
                    bundle.writestr("package.json", json.dumps({"name": "synthetic-failed-version", "version": "0.0.1", "scripts": {"build": "node fail.js"}}))
                    bundle.writestr("index.js", "// This failed artifact is never launched.\n")
                    bundle.writestr("fail.js", "process.stderr.write('synthetic-build-failure\\n'); process.exit(7);\n")
                else:
                    bundle.writestr("server.py", SYNTHETIC_SERVER.replace('"marker": MARKER', f'"artifact_version": "{version}", "marker": MARKER'))
                    bundle.writestr("pyproject.toml", f'[project]\nname = "synthetic-version-{version}"\nversion = "0.0.1"\n')
            uploaded = client.post("/v1/projects/upload", files={"file": (f"synthetic-{version}.zip", archive.getvalue(), "application/zip")})
            assert uploaded.status_code == 200, uploaded.text
            upload_id = uploaded.json()["id"]
            options = {"upload_id": upload_id, "runtime_override": "node" if fail else "python",
                       "run_install": False, "run_build": fail}
            plan = client.post("/v1/builds/plan", json=options)
            assert plan.status_code == 200, plan.text
            phases = [step["phase"] for step in plan.json()["plan"]["steps"]]
            assert phases == (["build"] if fail else [])
            result = client.post("/v1/builds", json={**options, "timeout_seconds": 10})
            assert result.status_code == 200, result.text
            build_id = result.json()["id"]
            deadline = time.monotonic() + 20
            while True:
                built = client.get(f"/v1/builds/{build_id}").json()
                if built["status"] in {"success", "failed", "cancelled", "unsupported"}:
                    break
                assert time.monotonic() < deadline, f"version build did not terminate: {build_id}"
                time.sleep(0.05)
            assert built["status"] == ("failed" if fail else "success"), built
            return built

        def deploy(build, *, overwrite: bool = False):
            url = f"/v1/builds/{build['id']}/deploy"
            body = {"server_id": server_id, "start": True, "overwrite": overwrite,
                "manifest_patch": {"launch": {"env": {"DELIVERY_MARKER": "synthetic-retained-setting"}},
                    "transport": {"protocol_version": "2026-07-28"}, "timeout_seconds": 3,
                    "restart_policy": {"enabled": False}}}
            preview = client.post(url + "/preview", json=body)
            assert preview.status_code == 200, preview.text
            confirmation = preview.json()
            body.update({"expected_config_digest": confirmation["config_digest"],
                "expected_previous_config_digest": confirmation["expected_previous_config_digest"],
                "expected_credential_binding_digest": confirmation["expected_credential_binding_digest"]})
            result = client.post(url, json=body)
            assert result.status_code == 200, result.text
            assert result.json()["status"] == "success", result.text
            assert result.json()["runtime_started"] is True
            return result.json()

        def snapshot():
            running = client.get(f"/v1/mcp/servers/{server_id}").json()
            assert running["status"] == "running" and running["tool_count"] == 1, running
            result = client.post(f"/v1/tools/{tool_id}/invoke", json={"arguments": {}})
            assert result.status_code == 200 and result.json()["ok"], result.text
            return json.loads(result.json()["output"]["content"][0]["text"])

        v1_build = build_archive("v1")
        deploy(v1_build)
        initial = snapshot()
        assert initial["artifact_version"] == "v1"
        old_manifest = state.mcp_config_store.load_manifest(server_id).model_dump(mode="json", exclude={"manifest_path"})
        failed_build = build_archive("broken-v2", fail=True)
        after_failure = snapshot()
        assert after_failure == initial  # Same live process, artifact path and values.
        assert state.mcp_config_store.load_manifest(server_id).model_dump(mode="json", exclude={"manifest_path"}) == old_manifest
        failed_preview = client.post(f"/v1/builds/{failed_build['id']}/deploy/preview", json={"server_id": server_id, "overwrite": True, "start": True})
        assert failed_preview.status_code == 400
        assert len(state.database.query_all("SELECT id FROM deployments")) == 1

        v2_build = build_archive("v2")
        assert v1_build["artifact_dir"] != v2_build["artifact_dir"]
        replacement = deploy(v2_build, overwrite=True)
        updated = snapshot()
        assert updated["artifact_version"] == "v2"
        assert updated["marker"] == initial["marker"] == "synthetic-retained-setting"
        assert updated["pid"] != initial["pid"]
        assert Path(updated["cwd"]) == Path(v2_build["artifact_dir"])
        assert replacement["rollback_available"] is True
        rolled_back = client.post(f"/v1/deployments/{replacement['id']}/rollback", json={"start": True})
        assert rolled_back.status_code == 200, rolled_back.text
        restored = snapshot()
        assert restored["artifact_version"] == "v1"
        assert Path(restored["cwd"]) == Path(v1_build["artifact_dir"])
        assert restored["marker"] == initial["marker"]
        assert restored["pid"] != updated["pid"]
        print(json.dumps({"scenario": "D02", "protocol_version": "2026-07-28",
            "v1_build_id": v1_build["id"], "failed_build_id": failed_build["id"],
            "v2_build_id": v2_build["id"], "replacement_deployment_id": replacement["id"],
            "initial": initial, "after_failed_build": after_failure, "after_replace": updated,
            "after_manual_rollback": restored, "failure_status": failed_build["status"]}))

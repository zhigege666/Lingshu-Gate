"""Console delivery against real temporary SQLite/config/runtime boundaries.

No external process or network connection is started by these scenarios.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from fastapi.testclient import TestClient


def test_console_preview_and_deploy_preserve_config_and_reject_stale_digest(tmp_path: Path, monkeypatch) -> None:
    for key, value in {
        "DATA_DIR": str(tmp_path), "CONFIG_DIR": str(tmp_path / "mcp.d"),
        "ALLOWED_ROOT": str(tmp_path), "AUTH_ENABLED": "false", "RUNTIME_ROLE": "local",
    }.items():
        monkeypatch.setenv(f"LINGSHU_GATE_{key}", value)
    from lingshu_gate.main import create_app
    app = create_app()
    with TestClient(app) as client:
        manifest = {
            "id": "console-synthetic", "enabled": True, "auto_start": False,
            "launch": {"type": "managed_process", "command": "synthetic-not-executed"},
            "transport": {"type": "stdio"},
        }
        app.state.database.execute(
            """INSERT INTO project_uploads (id, filename, status, root_dir, detected_runtime, analysis_json, created_at, updated_at)
            VALUES ('synthetic-upload', 'synthetic.zip', 'analyzed', ?, 'node', '{}', '2026-09-30', '2026-09-30')""", (str(tmp_path),),
        )
        draft_url = "/v1/delivery-drafts/synthetic-upload"
        assert client.get(draft_url).json()["revision"] == 0
        draft = client.put(draft_url, json={"expected_revision": 0, "manifest_patch": {"launch": {"env": {"NODE_ENV": "test"}}}})
        assert draft.status_code == 200, draft.text
        assert draft.json()["revision"] == 1
        assert client.put(draft_url, json={"expected_revision": 0}).status_code == 409
        assert client.get(draft_url).json()["manifest_patch"]["launch"]["env"]["NODE_ENV"] == "test"
        app.state.database.execute(
            """INSERT INTO builds (id, upload_id, status, runtime, source_dir, artifact_dir,
            manifest_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            ("synthetic-build", "synthetic-upload", "success", "node", str(tmp_path), str(tmp_path), json.dumps(manifest), "2026-09-30", "2026-09-30"),
        )
        url = "/v1/builds/synthetic-build/deploy"
        payload = {"manifest_patch": {"launch": {"args": ["--synthetic"]}}}
        preview = client.post(url + "/preview", json=payload)
        assert preview.status_code == 200, preview.text
        assert app.state.database.query_one("SELECT id FROM deployments") is None
        missing_confirmation = client.post(url, json=payload)
        assert missing_confirmation.status_code == 409
        assert missing_confirmation.json()["detail"]["code"] == "config_digest_required"
        assert app.state.database.query_one("SELECT id FROM deployments") is None
        masked = client.post(url + "/preview", json={"manifest_patch": {"launch": {"env": {"MARKER": "***"}}}})
        assert masked.status_code == 400, masked.text
        payload["expected_config_digest"] = preview.json()["config_digest"]
        result = client.post(url, json=payload)
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "success"
        actual = app.state.mcp_config_store.load_manifest("console-synthetic").model_dump(mode="json", exclude={"manifest_path"})
        applied_digest = hashlib.sha256(json.dumps(actual, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        assert applied_digest == preview.json()["config_digest"]
        assert not result.json()["runtime_started"]
        assert not result.json()["rollback_available"]
        assert app.state.mcp_config_store.load_manifest("console-synthetic").launch.args == ["--synthetic"]

        payload["overwrite"] = True
        preview_data = client.post(url + "/preview", json=payload).json()
        payload["expected_previous_config_digest"] = preview_data["expected_previous_config_digest"]
        changed = dict(manifest, name="changed after preview")
        app.state.mcp_config_store.save_config(changed, overwrite=True)
        stale = client.post(url, json=payload)
        assert stale.status_code == 409, stale.text
        assert stale.json()["detail"]["code"] == "previous_config_digest_conflict"
        assert app.state.mcp_config_store.load_manifest("console-synthetic").name == "changed after preview"
        assert len(app.state.database.query_all("SELECT id FROM deployments")) == 1

        preview_data = client.post(url + "/preview", json=payload).json()
        payload["expected_previous_config_digest"] = preview_data["expected_previous_config_digest"]
        replaced = client.post(url, json=payload)
        assert replaced.status_code == 200, replaced.text
        assert replaced.json()["rollback_available"]

        before_failed_rollback = app.state.mcp_config_store.load_manifest("console-synthetic").model_dump(mode="json", exclude={"manifest_path"})
        failed_rollback = client.post(f"/v1/deployments/{replaced.json()['id']}/rollback", json={"start": True})
        assert failed_rollback.status_code == 409, failed_rollback.text
        assert failed_rollback.json()["detail"]["code"] == "rollback_apply_failed"
        assert failed_rollback.json()["detail"]["config_restored"] is True
        assert failed_rollback.json()["detail"]["runtime_restored"] is True
        assert app.state.mcp_config_store.load_manifest("console-synthetic").model_dump(mode="json", exclude={"manifest_path"}) == before_failed_rollback
        assert app.state.mcp_runtime.iter_manifests()["console-synthetic"].model_dump(mode="json", exclude={"manifest_path"}) == before_failed_rollback

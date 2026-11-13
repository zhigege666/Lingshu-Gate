"""Combined saves use real stores and policy with isolated synthetic runtime work."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from lingshu_gate.application.configuration_credentials import ConfigurationCredentialService, ConfigurationCredentialSaveError
from lingshu_gate.application.mcp_configuration import McpConfigurationService
from lingshu_gate.domain.http_mcp_management import McpConfigCredentialSaveRequest
from lingshu_gate.models import McpServerStatusResponse
from lingshu_gate.registry import ToolExecutionError
from test_shared_credentials import SECRET, create, gate as gate, manifest


@pytest.fixture
def workflow(gate):
    runtime = Mock()
    configuration = McpConfigurationService(gate["service"].configs, runtime, Mock(), credentials=gate["service"].credentials)
    return ConfigurationCredentialService(configuration, gate["service"]), runtime


def request(**changes):
    return McpConfigCredentialSaveRequest.model_validate({"manifest": manifest(), "idempotency_key": "synthetic-config-save",
        "credential_write": {"kind": "create", "credential_id": "synthetic-credential", "name": "Synthetic", "value": SECRET,
            "target": {"server_id": "synthetic-http", "origin": "https://mcp.example.test:443"}}, **changes})


def test_final_save_creates_and_binds_once_without_exposing_secret(workflow, gate):
    service, runtime = workflow
    body = request()
    first = service.save(body, gate["principal"])
    second = service.save(body, gate["principal"])
    assert first["config"]["id"] == "synthetic-http" and second["idempotent_replay"]
    assert first["operation_id"] == second["operation_id"]
    assert len(gate["service"].credentials.list_credentials()) == 1
    assert gate["service"].credentials.get_credential("synthetic-credential").http_scopes[0].server_binding
    runtime.apply_manifest.assert_not_called()
    journal = [dict(row) for row in gate["service"].database.query_all("SELECT * FROM mcp_idempotent_operations")]
    assert SECRET not in json.dumps([first, second, journal])
    assert SECRET not in gate["service"].credentials.store_path.read_text()
    with pytest.raises(ConfigurationCredentialSaveError, match="different save"):
        service.save(request(manifest={**manifest(), "name": "Changed"}), gate["principal"])


@pytest.mark.parametrize("invalid", ["target", "other_reference", "config_revision"])
def test_preflight_rejection_changes_no_credential_or_config(workflow, gate, invalid):
    service, _ = workflow
    body = request()
    before = None
    if invalid == "target":
        body.credential_write.target.server_id = "another-service"
    elif invalid == "other_reference":
        body.manifest["transport"]["headers"]["X-Other"] = "${credential:unavailable}"
    else:
        saved = gate["service"].configs.save_config({**manifest(), "transport": {**manifest()["transport"], "headers": {}}})
        before = saved.digest
        body = request(existing_server_id=saved.id, expected_config_digest="0" * 64)
    with pytest.raises(ConfigurationCredentialSaveError) as failure:
        service.save(body, gate["principal"])
    assert failure.value.detail["credential_saved"] is False
    assert failure.value.detail["config_saved"] is False
    assert gate["service"].credentials.list_credentials() == []
    if before:
        assert gate["service"].configs.get_config("synthetic-http").digest == before
    else:
        assert gate["service"].configs.list_configs().configs == []


def test_config_failure_keeps_honest_credential_facts_and_failed_replay_is_read_only(workflow, gate, monkeypatch):
    service, runtime = workflow
    write = Mock(side_effect=OSError("Synthetic disk failure"))
    monkeypatch.setattr(service.configuration, "create", write)
    for _ in range(2):
        with pytest.raises(ConfigurationCredentialSaveError) as failure:
            service.save(request(), gate["principal"])
        assert failure.value.detail["credential_saved"] is True
        assert failure.value.detail["config_saved"] is False
        assert failure.value.detail["requires_reconciliation"] is True
    assert write.call_count == 1
    runtime.apply_manifest.assert_not_called()
    assert gate["service"].credentials.resolve_value("synthetic-credential") == SECRET


def test_unknown_credential_persistence_is_not_reported_as_no_change(workflow, gate, monkeypatch):
    service, _ = workflow
    monkeypatch.setattr(gate["service"], "create", Mock(side_effect=ToolExecutionError("credential_operation_interrupted", "Synthetic interruption",
                        details={"credential_mutated": "unknown", "requires_reconciliation": True})))
    with pytest.raises(ConfigurationCredentialSaveError) as failure:
        service.save(request(), gate["principal"])
    assert failure.value.detail["credential_saved"] == "unknown"
    assert failure.value.detail["requires_reconciliation"] is True


def test_activation_releases_credential_writer_and_successful_retry_never_restarts(workflow, gate):
    service, runtime = workflow
    def activate(manifest, **kwargs):
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            assert executor.submit(gate["service"].credentials.resolve_value, "synthetic-credential").result(timeout=2) == SECRET
        finally:
            executor.shutdown(wait=False)
        return McpServerStatusResponse(id=manifest.id, enabled=True, launch_type="external", transport_type="streamable_http", status="running")
    runtime.apply_manifest.side_effect = activate
    body = request(apply=True, start=True)
    assert service.save(body, gate["principal"])["server"]["status"] == "running"
    assert service.save(body, gate["principal"])["idempotent_replay"]
    assert runtime.apply_manifest.call_count == 1


def test_runtime_failure_is_partial_and_cannot_be_retried_as_another_activation(workflow, gate):
    service, runtime = workflow
    runtime.apply_manifest.return_value = McpServerStatusResponse(id="synthetic-http", enabled=True,
        launch_type="external", transport_type="streamable_http", status="failed", last_error="Synthetic connection failure")
    for _ in range(2):
        with pytest.raises(ConfigurationCredentialSaveError) as failure:
            service.save(request(apply=True, start=True), gate["principal"])
        assert failure.value.detail["credential_saved"] is True
        assert failure.value.detail["config_saved"] is True
        assert failure.value.detail["runtime_state"] == "failed"
    assert runtime.apply_manifest.call_count == 1


def test_audit_failure_after_save_records_partial_completion_without_repeating_writes(workflow, gate, monkeypatch):
    service, _ = workflow
    emit = gate["service"].observability.emit_event
    def fail_combined(event, **kwargs):
        if event == "gate.config.credential_saved":
            raise OSError("Synthetic audit failure")
        return emit(event, **kwargs)
    monkeypatch.setattr(gate["service"].observability, "emit_event", fail_combined)
    for _ in range(2):
        with pytest.raises(ConfigurationCredentialSaveError) as failure:
            service.save(request(), gate["principal"])
        assert failure.value.detail["credential_saved"] is True and failure.value.detail["config_saved"] is True
    assert len(gate["service"].credentials.list_credentials()) == 1


def test_scope_update_uses_both_revisions_and_retains_other_targets(workflow, gate):
    service, _ = workflow
    credential = create(gate, http_scopes=[{"server_id": "other", "origin": "https://other.example.test"}])
    draft = {"kind": "authorize", "credential_id": credential["id"], "expected_revision": credential["updated_at"],
             "expected_http_scopes_revision": "0" * 64, "target": {"server_id": "synthetic-http", "origin": "https://mcp.example.test:443"}}
    with pytest.raises(ConfigurationCredentialSaveError):
        service.save(request(credential_write=draft), gate["principal"])
    assert gate["service"].credentials.get_credential(credential["id"]).http_scopes_revision == credential["http_scopes_revision"]
    result = service.save(request(credential_write={**draft, "expected_http_scopes_revision": credential["http_scopes_revision"]},
                                  idempotency_key="synthetic-current-scopes"), gate["principal"])
    assert result["credential_saved"]
    scopes = gate["service"].credentials.get_credential(credential["id"]).http_scopes
    assert {scope.server_id for scope in scopes} == {"other", "synthetic-http"}
    assert gate["service"].credentials.resolve_value(credential["id"]) == SECRET


def test_revoked_permission_cannot_read_a_previous_successful_receipt(workflow, gate, monkeypatch):
    service, _ = workflow
    service.save(request(), gate["principal"])
    monkeypatch.setattr(gate["service"].access, "has_control_permission", lambda *args, **kwargs: False)
    with pytest.raises(ToolExecutionError, match="permission"):
        service.save(request(), gate["principal"])


def test_http_validates_without_echoing_secret_and_cancelled_draft_has_no_writes(gate):
    with TestClient(gate["app"], base_url="https://console.example.test") as client:
        client.cookies.set(gate["auth"].cookie_name, gate["cookie"])
        # Prechecking and then cancelling does not call the combined save at all.
        checked = client.post("/v1/mcp/configs/validate", json={"manifest": manifest()}, headers={"Origin": "https://console.example.test"})
        assert checked.status_code == 200
        assert gate["service"].credentials.list_credentials() == []
        assert gate["service"].configs.list_configs().configs == []
        body = request().model_dump(mode="json")
        rejected = client.post("/v1/mcp/configs/with-credential", json={**body, "unexpected": SECRET})
        assert rejected.status_code == 422 and SECRET not in rejected.text
        cross_site = client.post("/v1/mcp/configs/with-credential", json=body, headers={"Origin": "https://other.example.test"})
        assert cross_site.status_code == 403
        saved = client.post("/v1/mcp/configs/with-credential", json=body, headers={"Origin": "https://console.example.test"})
        assert saved.status_code == 200, saved.text
        assert saved.headers["cache-control"] == "no-store" and SECRET not in saved.text


@pytest.mark.parametrize("personal_values", [{}, {"synthetic-personal-slot": "Synthetic-personal-secret"}])
def test_http_transport_preserves_shared_rest_and_personal_secret_boundaries(gate, personal_values):
    with TestClient(gate["app"], base_url="http://console.example.test", client=("192.0.2.30", 48000)) as client:
        client.cookies.set(gate["auth"].cookie_name, gate["cookie"])
        body = {**request().model_dump(mode="json"), "user_credential_values": personal_values}
        response = client.post("/v1/mcp/configs/with-credential", json=body, headers={"Origin": "http://console.example.test"})
        assert SECRET not in response.text and "Synthetic-personal-secret" not in response.text
        if personal_values:
            assert response.status_code == 400 and "HTTPS" in response.text
            assert gate["service"].credentials.list_credentials() == []
            assert gate["service"].configs.list_configs().configs == []
            assert gate["service"].database.query_one("SELECT count(*) AS n FROM mcp_idempotent_operations")["n"] == 0
        else:
            assert response.status_code == 200, response.text
            assert response.json()["credential_saved"] is True
            assert response.headers["cache-control"] == "no-store"

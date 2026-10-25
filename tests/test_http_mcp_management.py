"""HTTP management uses one reviewed apply, precise identity and live policy."""

from __future__ import annotations

import json
import threading
import time
from unittest.mock import Mock

import pytest

from lingshu_gate.domain.mcp_groups import McpGroupDraft
from lingshu_gate.endpoint_security import REDACTED_ENDPOINT
from lingshu_gate.mcp_config_store import McpConfigStore
from lingshu_gate.mcp_http_client import StreamableHttpMcpClient
from lingshu_gate.mcp_http_trust import McpHttpTrustUpdate
from lingshu_gate.registry import ToolExecutionError

from test_external_mcp_configuration import apply_arguments, manifest
from test_external_mcp_configuration import gate as gate

SERVER = "synthetic-http"
ENDPOINT = "http://10.23.45.67:8080/mcp"


def draft(**fields):
    return {**manifest(SERVER, ENDPOINT), **fields}


def plan(gate, mode="create", *, data=None, **options):
    service = gate["service"]
    body = {"mode": mode, **options}
    if mode in {"create", "update"}:
        body["manifest"] = data or draft()
    else:
        body["server_id"] = SERVER
    if mode != "create":
        body.setdefault("expected_config_digest", service.configs.get_config(SERVER).digest)
    return service.http_plan(body, gate["context"])


def wait(gate, operation_id):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        result = gate["service"].http_status({"operation_id": operation_id}, gate["context"])
        if result["terminal"]:
            return result
        time.sleep(.01)
    pytest.fail("HTTP management operation did not terminate")


def apply(gate, preview):
    arguments = apply_arguments(preview, "apply-" + preview["plan_id"])
    queued = gate["service"].http_apply(arguments, gate["context"])
    return wait(gate, queued["operation_id"])


def test_offline_plan_and_single_apply_save_exact_permission(gate):
    service = gate["service"]
    preview = plan(gate)
    assert preview["network_contacted"] is False
    assert preview["http_trust"]["change"] == "authorize"
    assert preview["connection_target"] == ENDPOINT
    assert service.configs.http_trust_store.get(SERVER)["revision"] == 0
    assert not service.configs.list_configs().configs and not gate["calls"]
    result = apply(gate, preview)
    assert result["status"] == "success", result
    assert result["config_applied"] and result["trust_applied"]
    assert result["connection_state"] == "not_requested"
    assert result["http_trust"]["origins"] == [{"ip": "10.23.45.67", "port": 8080}]
    assert result["http_trust"]["state"] == "active" and result["http_trust"]["server_binding"]
    assert not gate["calls"]
    status = service.http_status({"server_id": SERVER}, gate["context"])
    assert status["http_trust"] == result["http_trust"]


def test_new_and_legacy_plan_contracts_cannot_be_interchanged(gate):
    service = gate["service"]
    with pytest.raises(ToolExecutionError, match="HTTP trust is invalid"):
        service.plan({"mode": "create", "manifest": draft()}, gate["context"])
    preview = plan(gate)
    with pytest.raises(ToolExecutionError, match="tool that created"):
        service.apply(apply_arguments(preview), gate["context"])
    assert not service.configs.list_configs().configs
    result = apply(gate, preview)
    with pytest.raises(ToolExecutionError, match="entry that owns"):
        service.status({"operation_id": result["operation_id"]}, gate["context"])


def test_connect_discovers_without_publishing_and_replay_has_no_side_effect(gate):
    preview = plan(gate, connect=True, refresh_tools=True)
    result = apply(gate, preview)
    assert result["status"] == "success", result
    assert result["connection_state"] == "connected"
    assert result["classification_state"] == "needs_review"
    assert result["effective_permissions_expanded"] is False
    assert result["counts"]["needs_review"] == 1
    calls = list(gate["calls"])
    replay = gate["service"].http_apply(apply_arguments(preview, "apply-" + preview["plan_id"]), gate["context"])
    assert replay["idempotent_replay"] is True
    assert replay["operation_id"] == result["operation_id"]
    assert gate["calls"] == calls


def test_http_cancel_rechecks_completion_after_the_initial_status_read(gate, monkeypatch):
    service = gate["service"]
    started, release = threading.Event(), threading.Event()
    gate["mode"]["wait"] = (started, release)
    operation = service.http_apply(apply_arguments(plan(gate, connect=True)), gate["context"])
    operation_id = operation["operation_id"]
    worker = service._threads[operation_id]
    original = service.http_status

    def stale_status(arguments, context):
        observed = original(arguments, context)
        assert observed["terminal"] is False
        release.set()
        worker.join(2)
        assert not worker.is_alive()
        return observed

    try:
        assert started.wait(2)
        monkeypatch.setattr(service, "http_status", stale_status)
        cancelled = service.http_cancel({"operation_id": operation_id, "idempotency_key": "synthetic-terminal-race", "confirmed": True}, gate["context"])
        assert cancelled["status"] == "already_terminal" and cancelled["terminal"] is True
        row = service.database.query_one("SELECT status,cancel_requested FROM external_mcp_config_operations WHERE id=?", (operation_id,))
        assert row["status"] == "success" and row["cancel_requested"] == 0
        assert original({"operation_id": operation_id}, gate["context"])["connection_state"] == "connected"
        assert not any(action == "disconnect" for action, _ in gate["calls"])
    finally:
        release.set()


def test_a_later_queued_plan_cannot_interrupt_the_current_reviewed_connect(gate, monkeypatch):
    service = gate["service"]
    first = plan(gate, connect=True, refresh_tools=True)
    second = plan(gate, connect=True, refresh_tools=True)
    entered, release = threading.Event(), threading.Event()
    original = service.runtime.external_connection_guard

    def paused_guard(server_id, operation_id):
        entered.set()
        assert release.wait(3)
        original(server_id, operation_id)

    monkeypatch.setattr(service.runtime, "external_connection_guard", paused_guard)
    first_operation = service.http_apply(apply_arguments(first, "synthetic-first"), gate["context"])
    assert entered.wait(3)
    try:
        second_operation = service.http_apply(apply_arguments(second, "synthetic-second"), gate["context"])
    finally:
        release.set()
    assert wait(gate, first_operation["operation_id"])["status"] == "success"
    second_result = wait(gate, second_operation["operation_id"])
    assert second_result["status"] == "failed" and second_result["error_code"] == "config_digest_conflict"
    assert sum(action == "connect" for action, _ in gate["calls"]) == 1


def test_revocation_survives_metadata_save_reload_and_cached_client(gate):
    service = gate["service"]
    assert apply(gate, plan(gate, connect=True, refresh_tools=True))["status"] == "success"
    saved = service.configs.load_manifest(SERVER)
    cached = StreamableHttpMcpClient(saved, service.settings)
    cached._opener = Mock()
    revoked = apply(gate, plan(gate, "revoke_trust"))
    assert revoked["status"] == "success", revoked
    assert revoked["http_trust"]["revoked"] is True
    assert not service.runtime.has_server(SERVER)
    with pytest.raises(ValueError, match="administrator-approved trust"):
        cached._post({}, 1, expect_response=False, request_id=None, protocol_headers={})
    cached.session_id = "synthetic-session"
    cached.stop()
    cached._opener.open.assert_not_called()
    preview = plan(gate, "update", data=draft(name="Renamed service"))
    assert preview["http_trust"]["change"] == "preserve_denied"
    result = apply(gate, preview)
    assert result["status"] == "success" and result["connection_state"] == "revoked"
    assert result["http_trust"]["revision"] == revoked["http_trust"]["revision"]
    reloaded = McpConfigStore(service.settings.config_dir, http_trust_store=service.configs.http_trust_store)
    assert reloaded.http_trust_store.get(SERVER)["revoked"] is True
    with pytest.raises(ToolExecutionError, match="explicit restore"):
        plan(gate, "update", connect=True)
    restored = apply(gate, plan(gate, "restore_trust", connect=True, refresh_tools=True))
    assert restored["status"] == "success", restored
    assert restored["connection_state"] == "connected"
    assert restored["http_trust"]["revision"] == revoked["http_trust"]["revision"] + 1


@pytest.mark.parametrize("mutation", ["trust", "config", "credential"])
def test_changed_plan_inputs_fail_before_saving(gate, mutation):
    service = gate["service"]
    data = draft()
    if mutation == "credential":
        service.credentials.save_credential(credential_id="synthetic-token", name="Synthetic", value="synthetic-secret",
            http_scopes=[{"server_id": SERVER, "origin": "http://10.23.45.67:8080", "server_binding": None}])
        data["transport"]["headers"] = {"Authorization": "Bearer ${credential:synthetic-token}"}
    preview = plan(gate, data=data)
    if mutation == "trust":
        service.configs.http_trust_store.update(SERVER, McpHttpTrustUpdate(origins=[], expected_revision=0, confirmed=True),
            actor_id=gate["context"].actor_id)
    elif mutation == "credential":
        service.credentials.save_credential(credential_id="synthetic-token", name="Synthetic", value="synthetic-replacement")
    else:
        service.configs.save_config(manifest(SERVER))
    calls = list(gate["calls"])
    result = apply(gate, preview)
    assert result["status"] == "failed", result
    assert result["config_applied"] is False
    assert result["error_code"] == {"trust": "http_trust_conflict", "config": "config_digest_conflict",
                                   "credential": "external_config_credential_changed"}[mutation]
    assert gate["calls"] == calls
    assert service.configs.http_trust_store.get(SERVER)["state"] != "active"


def test_delete_cleans_local_bindings_groups_tools_and_permission_only(gate):
    service = gate["service"]
    assert apply(gate, plan(gate, connect=True, refresh_tools=True))["status"] == "success"
    old_policy = service.configs.http_trust_store.get(SERVER)
    service.credentials.save_credential(credential_id="synthetic-retained", name="Retained", value="synthetic-secret", http_scopes=[])
    gate["app"].state.user_credential_store.save_binding(user_id=gate["context"].actor_id, server_id=SERVER,
                                                       slot_id="synthetic-slot", value="synthetic-personal")
    group_store = service.configuration._group_store
    group = group_store.save(McpGroupDraft(name="Synthetic group", members=[SERVER], default_instance_id=SERVER, confirmed=True),
        group_id=None, expected_revision=None, actor_id=gate["context"].actor_id, authorize=lambda _: None,
        available_instances={SERVER}, request_key="synthetic-group", request_digest="synthetic-digest")
    old_preview = plan(gate, "update", data=draft(name="Stale update"))
    preview = plan(gate, "delete")
    assert preview["impact"] == {"tool_count": 1, "group_count": 1, "personal_credential_bindings": 1,
                                  "shared_credentials_deleted": False, "remote_service_uninstalled": False}
    result = apply(gate, preview)
    assert result["status"] == "success" and result["config_deleted"], result
    assert not service.runtime.has_server(SERVER)
    assert not any(tool.metadata.get("server_id") == SERVER for tool in service.runtime.registry.list_definitions())
    assert not service.database.query_all("SELECT * FROM mcp_group_members WHERE server_id=?", (SERVER,))
    remaining = service.database.query_one("SELECT revision,default_instance_id FROM mcp_groups WHERE id=?", (group["id"],))
    assert remaining["default_instance_id"] is None and remaining["revision"] > group["revision"]
    assert not gate["app"].state.user_credential_store.list_bindings(gate["context"].actor_id)
    assert service.credentials.get_credential("synthetic-retained")
    assert result["http_trust"]["origins"] == [] and result["http_trust"]["server_binding"] is None
    recreated = apply(gate, plan(gate))
    assert recreated["status"] == "success", recreated
    assert recreated["http_trust"]["server_binding"] != old_policy["server_binding"]
    assert apply(gate, old_preview)["status"] == "failed"


def test_partial_write_is_reported_and_requires_explicit_reconciliation(gate, monkeypatch):
    service = gate["service"]
    trust = service.configs.http_trust_store
    original = trust.apply_saved_configuration
    monkeypatch.setattr(trust, "apply_saved_configuration", Mock(side_effect=OSError("synthetic disk failure")))
    result = apply(gate, plan(gate))
    assert result["status"] == "partial" and result["config_applied"] is True, result
    assert result["requires_reconciliation"] is True and service.configs.get_config(SERVER)
    assert not gate["calls"]
    monkeypatch.setattr(trust, "apply_saved_configuration", original)
    service.runtime.load_manifests()
    failed = service.runtime.start_server(SERVER)
    assert failed.status == "failed" and "unfinished" in failed.last_error
    assert not gate["calls"]
    repaired = apply(gate, plan(gate, "update", connect=True, refresh_tools=True))
    assert repaired["status"] == "success" and repaired["connection_state"] == "connected", repaired
    service.runtime.stop_server(SERVER)
    assert service.runtime.start_server(SERVER).status == "running"


def test_restart_journal_recovery_blocks_automatic_connect_until_new_apply(gate):
    service = gate["service"]
    result = apply(gate, plan(gate))
    stored = {**result, "status": "running", "terminal": False}
    service.database.execute("UPDATE external_mcp_config_operations SET status='running',result_json=? WHERE id=?",
                             (json.dumps(stored), result["operation_id"]))
    service._recover_interrupted()
    calls = list(gate["calls"])
    service.runtime.load_manifests()
    assert service.runtime.start_server(SERVER).status == "failed"
    assert gate["calls"] == calls
    repaired = apply(gate, plan(gate, "update"))
    assert repaired["status"] == "success", repaired
    assert service.runtime.start_server(SERVER).status == "running"
    deleted = apply(gate, plan(gate, "delete"))
    assert deleted["status"] == "success"
    recreated = apply(gate, plan(gate, connect=True, refresh_tools=True))
    assert recreated["status"] == "success", recreated


def test_rest_precheck_is_offline_and_save_grants_without_an_extra_request(gate):
    client, service = gate["client"], gate["service"]
    body = {"manifest": draft(), "apply": False, "start": False, "expected_http_trust_revision": 0}
    checked = client.post("/v1/mcp/configs/validate", json=body)
    assert checked.status_code == 200 and checked.json()["ok"], checked.text
    assert any(check["name"] == "transport.http_trust" and check["severity"] == "warning" for check in checked.json()["checks"])
    assert not service.configs.list_configs().configs and not gate["calls"]
    assert service.configs.http_trust_store.get(SERVER)["revision"] == 0
    saved = client.post("/v1/mcp/configs", json=body, headers={"Origin": "http://testserver"})
    assert saved.status_code == 200, saved.text
    assert service.configs.http_trust_store.get(SERVER)["state"] == "active"
    assert not gate["calls"]
    # A separate restore request cannot grant an unsaved replacement target.
    rejected = client.put(f"/v1/mcp/http-trust/{SERVER}", json={"origins": [{"ip": "10.23.45.68", "port": 8080}],
        "expected_revision": 1, "confirmed": True})
    assert rejected.status_code == 400
    replacement = draft()
    replacement["transport"]["endpoint"] = ENDPOINT + "/changed"
    preserved = client.put(f"/v1/mcp/configs/{SERVER}", json={"manifest": replacement, "apply": False, "start": False,
        "http_trust_action": "preserve", "expected_config_digest": service.configs.get_config(SERVER).digest})
    assert preserved.status_code == 400
    assert service.configs.load_manifest(SERVER).transport.endpoint == ENDPOINT
    assert service.configs.http_trust_store.get(SERVER)["state"] == "active"


def test_rest_revocation_requires_explicit_restore_and_revision(gate):
    service, client = gate["service"], gate["client"]
    assert apply(gate, plan(gate))["status"] == "success"
    assert apply(gate, plan(gate, "revoke_trust"))["status"] == "success"
    policy = client.get(f"/v1/mcp/http-trust/{SERVER}").json()
    assert policy["configured_origin"] == {"ip": "10.23.45.67", "port": 8080}
    assert policy["revoked"]
    masked = client.get(f"/v1/mcp/configs/{SERVER}").json()["manifest"]
    assert masked["transport"]["endpoint"] == REDACTED_ENDPOINT
    body = {"manifest": {**masked, "name": "Renamed"}, "apply": False, "start": False,
            "expected_config_digest": service.configs.get_config(SERVER).digest,
            "expected_http_trust_revision": 2}
    saved = client.put(f"/v1/mcp/configs/{SERVER}", json=body)
    assert saved.status_code == 200, saved.text
    assert service.configs.http_trust_store.get(SERVER)["revoked"]
    body.update(expected_config_digest=saved.json()["config"]["digest"], http_trust_action="restore")
    restored = client.put(f"/v1/mcp/configs/{SERVER}", json=body)
    assert restored.status_code == 200, restored.text
    assert service.configs.http_trust_store.get(SERVER)["state"] == "active"
    stale = client.put(f"/v1/mcp/configs/{SERVER}", json=body)
    assert stale.status_code == 409


def test_rest_permission_and_csrf_boundary_remain_on_combined_save(gate):
    client = gate["client"]
    body = {"manifest": draft(), "apply": False, "start": False}
    assert client.post("/v1/mcp/configs", json=body, headers={"Origin": "https://foreign.example.test"}).status_code == 403
    gate["service"].access.set_user_roles(gate["context"].actor_id, ["operator"])
    assert client.post("/v1/mcp/configs", json=body).status_code == 403
    assert not gate["service"].configs.list_configs().configs


def test_rest_partial_credential_binding_failure_does_not_claim_unsaved(gate, monkeypatch):
    service = gate["service"]
    monkeypatch.setattr(service.configuration, "_bind_saved_http_credentials", Mock(side_effect=ValueError("synthetic secret scope conflict")))
    response = gate["client"].post("/v1/mcp/configs", json={"manifest": draft(), "apply": False, "start": False})
    assert response.status_code == 409
    assert response.json()["detail"]["config_applied"] is True
    assert response.json()["detail"]["requires_reconciliation"] is True
    assert service.configs.get_config(SERVER) and not gate["calls"]


def test_https_apply_failure_after_scope_sealing_reports_partial(gate, monkeypatch):
    service = gate["service"]
    data = manifest(SERVER)
    data["transport"]["headers"] = {"Authorization": "Bearer ${credential:synthetic-token}"}
    service.credentials.save_credential(credential_id="synthetic-token", name="Synthetic", value="synthetic-secret",
        http_scopes=[{"server_id": SERVER, "origin": "https://mcp.example.test:443", "server_binding": None}])
    monkeypatch.setattr(service.runtime, "apply_manifest", Mock(side_effect=RuntimeError("synthetic apply failure")))
    response = gate["client"].post("/v1/mcp/configs", json={"manifest": data, "apply": True, "start": False})
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["config_applied"] is True
    assert service.configs.get_config(SERVER)
    assert service.credentials.get_credential("synthetic-token").http_scopes[0].server_binding
    assert not gate["calls"]


def test_restore_can_finish_a_pending_scope_after_partial_configuration_save(gate, monkeypatch):
    service = gate["service"]
    data = draft()
    data["transport"]["headers"] = {"Authorization": "Bearer ${credential:synthetic-token}"}
    service.credentials.save_credential(credential_id="synthetic-token", name="Synthetic", value="synthetic-secret",
        http_scopes=[{"server_id": SERVER, "origin": "http://10.23.45.67:8080", "server_binding": None}])
    trust = service.configs.http_trust_store
    original = trust.apply_saved_configuration
    monkeypatch.setattr(trust, "apply_saved_configuration", Mock(side_effect=OSError("synthetic failure")))
    partial = apply(gate, plan(gate, data=data))
    assert partial["status"] == "partial" and not gate["calls"]
    assert service.credentials.get_credential("synthetic-token").http_scopes[0].server_binding is None
    monkeypatch.setattr(trust, "apply_saved_configuration", original)
    result = apply(gate, plan(gate, "restore_trust", connect=True, refresh_tools=True))
    assert result["status"] == "success" and result["connection_state"] == "connected", result
    assert service.credentials.get_credential("synthetic-token").http_scopes[0].server_binding == result["http_trust"]["server_binding"]


def test_recreate_after_partial_delete_retires_old_published_classifications(gate, monkeypatch):
    service = gate["service"]
    assert apply(gate, plan(gate, connect=True, refresh_tools=True))["status"] == "success"
    tool_id = f"mcp.{SERVER}.synthetic_read"
    service.access.set_classification(server_id=SERVER, tool_id=tool_id, access="read", destructive=False,
                                      idempotent=True, reviewer_id=gate["context"].actor_id)
    service.access.publish_classifications(server_id=SERVER, tool_ids=[tool_id], reviewer_id=gate["context"].actor_id)
    trust = service.configs.http_trust_store
    previous_revision = trust.get(SERVER)["revision"]
    retire = trust.retire_deleted
    monkeypatch.setattr(trust, "retire_deleted", Mock(side_effect=OSError("synthetic permission cleanup failure")))
    deleted = apply(gate, plan(gate, "delete"))
    assert deleted["status"] == "partial" and deleted["config_deleted"] is True
    with pytest.raises(KeyError):
        service.configs.get_config(SERVER)
    assert service.access.list_classifications(server_id=SERVER)[0]["status"] == "published"
    monkeypatch.setattr(trust, "retire_deleted", retire)
    preview = plan(gate)
    assert preview["impact"]["reconcile_prior_delete"] is True
    recreated = apply(gate, preview)
    assert recreated["status"] == "success" and recreated["reconciled_prior_delete"] is True, recreated
    assert trust.get(SERVER)["revision"] == previous_revision
    assert trust.get(SERVER)["state"] == "needs_review"
    retired = service.access.list_classifications(server_id=SERVER)[0]
    assert retired["status"] == "stale" and retired["effective_access"] == "unknown"
    connected = apply(gate, plan(gate, "restore_trust", connect=True, refresh_tools=True))
    assert connected["status"] == "success" and connected["classification_state"] == "needs_review"
    assert connected["counts"]["needs_review"] == 1

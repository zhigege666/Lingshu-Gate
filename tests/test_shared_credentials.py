"""Shared credentials use real policy/stores and synthetic, in-memory peers."""
from __future__ import annotations

import io
import json
import logging
import threading
from dataclasses import replace
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from lingshu_gate.access_control import AccessDeniedError
from lingshu_gate.application.mcp_configuration import McpConfigurationService
from lingshu_gate.application.shared_credentials import SharedCredentialService, credential_context
from lingshu_gate.credential_store import CredentialAlreadyExists, CredentialRevisionConflict, CredentialStore, CredentialUsageDenied
from lingshu_gate.logging import JsonFormatter
from lingshu_gate.mcp_authorization_policy import server_binding
from lingshu_gate.mcp_config_store import McpConfigPartialError, McpConfigStore
from lingshu_gate.mcp_http_client import StreamableHttpMcpClient
from lingshu_gate.mcp_http_trust import McpHttpTrustUpdate
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.models import McpConfigSaveRequest
from lingshu_gate.registry import ToolExecutionError

PASSWORD = "Synthetic-Shared-123!"
SECRET = "synthetic-shared-secret-z7q2"
ROTATED = "synthetic-shared-rotated-r9m4"


@pytest.fixture
def gate(tmp_path, monkeypatch):
    import os
    for name in tuple(os.environ):
        if name.startswith("LINGSHU_GATE_"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("LINGSHU_GATE_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("LINGSHU_GATE_CONFIG_DIR", str(tmp_path / "mcp.d"))
    monkeypatch.setenv("LINGSHU_GATE_DB_URL", f"sqlite:///{tmp_path / 'gate.db'}")
    monkeypatch.setenv("LINGSHU_GATE_ADMIN_USERNAME", "synthetic-admin")
    monkeypatch.setenv("LINGSHU_GATE_ADMIN_PASSWORD", PASSWORD)
    monkeypatch.setenv("LINGSHU_GATE_AUTH_ENABLED", "true")
    from lingshu_gate.main import create_app
    app = create_app()
    auth = app.state.auth_store
    auth.change_password(str(auth.list_users()[0]["id"]), PASSWORD)
    principal, cookie, _ = auth.login(username="synthetic-admin", password=PASSWORD)
    yield {"app": app, "auth": auth, "principal": principal, "cookie": cookie,
           "context": credential_context(principal), "service": app.state.shared_credential_service}
    app.state.external_mcp_configuration_service.shutdown()
    app.state.mcp_runtime.shutdown()


def create(gate, credential_id="synthetic-credential", **changes):
    body = {"credential_id": credential_id, "name": "Synthetic credential", "value": SECRET,
            "idempotency_key": "create-" + credential_id, **changes}
    return gate["service"].create(body, gate["context"])


def update(gate, current, **changes):
    return gate["service"].update({"credential_id": current["id"], "expected_revision": current["updated_at"],
        "idempotency_key": "update-" + current["updated_at"], **changes}, gate["context"])


def manifest(server_id="synthetic-http", endpoint="https://mcp.example.test/mcp"):
    return {"id": server_id, "auto_start": False, "launch": {"type": "external"},
            "transport": {"type": "streamable_http", "endpoint": endpoint,
                          "headers": {"Authorization": "Bearer ${credential:synthetic-credential}"}}}


def saved_http(gate):
    current = create(gate, http_scopes=[{"server_id": "synthetic-http", "origin": "https://mcp.example.test"}])
    service = gate["service"]
    service.configs.save_config(manifest())
    with service.database.session() as connection:
        binding = server_binding(connection, "synthetic-http")
    service.credentials.bind_http_usage([current["id"]], server_id="synthetic-http",
        endpoint="https://mcp.example.test/mcp", server_binding=binding)
    return current, binding


class Response(io.BytesIO):
    status = 202
    headers = {"Content-Type": "application/json"}


def client_for(gate, data=None):
    client = StreamableHttpMcpClient(McpServerManifest.model_validate(data or manifest()), gate["app"].state.settings)
    sent = []
    class Opener:
        def open(self, request, *, timeout):
            sent.append((request.method, request.get_header("Authorization")))
            return Response()
    client._opener = Opener()
    return client, sent


def send(client):
    client._post({"jsonrpc": "2.0", "method": "notifications/ping"}, 2,
                 expect_response=False, request_id=None, protocol_headers={})


def test_create_conflict_cas_rotation_masks_and_idempotency(gate):
    first = create(gate)
    again = create(gate)
    assert again["idempotent_replay"] and again["updated_at"] == first["updated_at"]
    with pytest.raises(ToolExecutionError) as changed_key:
        create(gate, value=ROTATED)
    assert changed_key.value.code == "idempotency_conflict"
    with pytest.raises(ToolExecutionError) as collision:
        create(gate, value=ROTATED, idempotency_key="create-conflict")
    assert collision.value.code == "credential_exists"
    second = update(gate, first, description="Metadata only", value=None)
    assert second["value_saved"] is False and second["updated_at"] != first["updated_at"]
    assert gate["service"].credentials.resolve_value(first["id"]) == SECRET
    with pytest.raises(ToolExecutionError) as stale:
        update(gate, first, value=ROTATED, idempotency_key="stale-update")
    assert stale.value.code == "credential_revision_conflict"
    with pytest.raises(ToolExecutionError) as masked:
        update(gate, second, value="***")
    assert masked.value.code == "credential_request_invalid"
    rotated = update(gate, second, value=ROTATED, idempotency_key="rotate-success")
    assert rotated["value_saved"] is True and not rotated["connection_verified"]
    assert gate["service"].credentials.resolve_value(first["id"]) == ROTATED
    payloads = [first, second, rotated, gate["service"].list({}, gate["context"])]
    journal = [dict(row) for row in gate["service"].database.query_all("SELECT * FROM mcp_idempotent_operations")]
    for secret in (SECRET, ROTATED):
        assert secret not in json.dumps(payloads + journal)
        assert secret not in gate["service"].credentials.store_path.read_text()


def test_store_cas_is_shared_across_instances(tmp_path):
    left, right = CredentialStore(tmp_path), CredentialStore(tmp_path)
    current = left.create_credential(name="Synthetic", value=SECRET, credential_id="synthetic")
    with pytest.raises(CredentialAlreadyExists):
        right.create_credential(name="Synthetic", value=ROTATED, credential_id=current.id)
    changed = right.update_credential(current.id, expected_revision=current.updated_at, value=ROTATED)
    with pytest.raises(CredentialRevisionConflict):
        left.delete_credential(current.id, expected_revision=current.updated_at)
    assert left.resolve_value(current.id) == ROTATED
    left.delete_credential(current.id, expected_revision=changed.updated_at)


def test_pending_origin_scope_is_consumed_once_and_cannot_follow_recreation(gate):
    current = create(gate, http_scopes=[{"server_id": "synthetic-http", "origin": "https://mcp.example.test"}])
    store = gate["service"].credentials
    params = {"server_id": "synthetic-http", "endpoint": "https://mcp.example.test/mcp", "server_binding": None}
    store.assert_http_binding(current["id"], **params, allow_pending=True)
    with pytest.raises(CredentialUsageDenied):
        store.assert_http_binding(current["id"], **params)
    store.bind_http_usage([current["id"]], **{**params, "server_binding": "first-generation"})
    assert store.get_credential(current["id"]).updated_at == current["updated_at"]
    for target in ({**params, "server_binding": "new-generation"}, {**params, "server_id": "other"},
                   {**params, "endpoint": "https://other.example.test/mcp"}):
        with pytest.raises(CredentialUsageDenied):
            store.assert_http_binding(current["id"], **target, allow_pending=True)


def test_single_http_target_preserves_concurrent_seals_and_replay_does_not_reopen_them(gate, monkeypatch):
    current = create(gate, http_scopes=[{"server_id": "first", "origin": "https://first.example.test"}])
    service, store = gate["service"], gate["service"].credentials
    reserve = service._reserve

    def reserve_then_seal_other_target(*args, **kwargs):
        result = reserve(*args, **kwargs)
        if result[1] is None:
            store.bind_http_usage([current["id"]], server_id="first", endpoint="https://first.example.test/mcp",
                                 server_binding="first-generation")
        return result

    # Deterministically interleave a configuration save after request planning
    # but before the update acquires its mutation barriers.
    monkeypatch.setattr(service, "_reserve", reserve_then_seal_other_target)
    target = {"server_id": "second", "origin": "https://second.example.test"}
    result = update(gate, current, authorize_http_target=target, idempotency_key="authorize-second")
    scopes = {scope["server_id"]: scope for scope in result["http_scopes"]}
    assert scopes["first"]["server_binding"] == "first-generation"
    assert scopes["second"]["server_binding"] is None
    assert result["value_saved"] is False and store.resolve_value(current["id"]) == SECRET
    store.bind_http_usage([current["id"]], server_id="second", endpoint="https://second.example.test/mcp",
                         server_binding="second-generation")
    sealed = store.get_credential(current["id"])
    replay = update(gate, current, authorize_http_target=target, idempotency_key="authorize-second")
    assert replay["idempotent_replay"] and store.get_credential(current["id"]) == sealed
    with pytest.raises(ToolExecutionError) as stale:
        update(gate, current, authorize_http_target=target, idempotency_key="stale-target-update")
    assert stale.value.code == "credential_revision_conflict"
    with pytest.raises(ToolExecutionError) as changed_request:
        update(gate, current, authorize_http_target={**target, "server_id": "third"}, idempotency_key="authorize-second")
    assert changed_request.value.code == "idempotency_conflict"


def test_single_http_target_preserves_unrelated_stale_grants_and_only_authorizes_explicit_rebind(gate):
    current, old_binding = saved_http(gate)
    service, store = gate["service"], gate["service"].credentials
    service.configs.delete_config("synthetic-http")
    result = update(gate, current, authorize_http_target={"server_id": "new-http", "origin": "https://new.example.test"})
    old_scope = next(scope for scope in result["http_scopes"] if scope["server_id"] == "synthetic-http")
    assert old_scope["server_binding"] == old_binding
    with pytest.raises(CredentialUsageDenied):
        store.assert_http_binding(current["id"], server_id="synthetic-http", endpoint="https://mcp.example.test/mcp",
                                  server_binding="replacement-generation", allow_pending=True)
    store.bind_http_usage([current["id"]], server_id="new-http", endpoint="https://new.example.test/mcp",
                         server_binding="new-generation")
    renewed = update(gate, result, authorize_http_target={"server_id": "synthetic-http", "origin": "https://mcp.example.test"})
    assert {scope["server_id"]: scope["server_binding"] for scope in renewed["http_scopes"]} == {
        "synthetic-http": old_binding, "new-http": "new-generation"}
    assert {scope["server_id"]: scope["pending_rebind"] for scope in renewed["http_scopes"]} == {
        "synthetic-http": True, "new-http": False}


def test_same_target_seal_conflicts_with_old_scope_digest_and_authorization_keeps_actual_binding(gate):
    selected, binding = saved_http(gate)
    store = gate["service"].credentials
    sealed = store.get_credential(selected["id"])
    assert sealed.updated_at == selected["updated_at"]
    target = {"server_id": "synthetic-http", "origin": "https://mcp.example.test"}
    with pytest.raises(ToolExecutionError) as stale:
        update(gate, selected, authorize_http_target=target,
               expected_http_scopes_revision=selected["http_scopes_revision"], idempotency_key="stale-same-target")
    assert stale.value.code == "credential_revision_conflict"
    assert store.get_credential(selected["id"]) == sealed
    # Compatibility callers without the optional digest also cannot erase a
    # seal that completed after their selection snapshot.
    result = update(gate, selected, authorize_http_target=target, idempotency_key="merge-same-target")
    assert result["http_scopes"][0]["server_binding"] == binding
    assert result["http_scopes"][0]["pending_rebind"] is True
    assert result["http_scopes_revision"] != sealed.http_scopes_revision


def test_pending_rebind_keeps_running_client_when_draft_is_unsaved_or_cancelled(gate):
    current, binding = saved_http(gate)
    service, store = gate["service"], gate["service"].credentials
    client, sent = client_for(gate)
    send(client)
    current = store.get_credential(current["id"]).model_dump(mode="json")
    pending = update(gate, current, authorize_http_target={"server_id": "synthetic-http", "origin": "https://mcp.example.test"},
                     expected_http_scopes_revision=current["http_scopes_revision"])
    send(client)
    configuration = McpConfigurationService(service.configs, Mock(), Mock(), credentials=store)
    draft = McpConfigSaveRequest(manifest=manifest(endpoint="https://mcp.example.test/new-mcp"))
    configuration.prepare_user_credentials(draft, existing_server_id="synthetic-http")
    # Discarding this prepared draft performs no save and consumes no grant.
    assert service.configs.load_manifest("synthetic-http").transport.endpoint == "https://mcp.example.test/mcp"
    send(client)
    assert sent == [("POST", "Bearer " + SECRET)] * 3
    assert store.get_credential(current["id"]).http_scopes[0].server_binding == binding
    assert store.get_credential(current["id"]).http_scopes_revision == pending["http_scopes_revision"]
    with pytest.raises(CredentialUsageDenied):
        store.assert_http_binding(current["id"], server_id="synthetic-http", endpoint=draft.manifest["transport"]["endpoint"],
                                  server_binding="unsealed-generation")


def test_same_origin_path_save_seals_rebind_and_rejects_previous_client_generation(gate):
    current, old_binding = saved_http(gate)
    service, store = gate["service"], gate["service"].credentials
    old_client, old_sent = client_for(gate)
    send(old_client)
    current = store.get_credential(current["id"]).model_dump(mode="json")
    configuration = McpConfigurationService(service.configs, Mock(), Mock(), credentials=store)
    data = manifest(endpoint="https://mcp.example.test/new-mcp")
    request = McpConfigSaveRequest(manifest=data)
    with pytest.raises(CredentialUsageDenied):
        configuration.prepare_user_credentials(request, existing_server_id="synthetic-http")
    pending = update(gate, current, authorize_http_target={"server_id": "synthetic-http", "origin": "https://mcp.example.test"},
                     expected_http_scopes_revision=current["http_scopes_revision"])
    prepared = configuration.prepare_user_credentials(request, existing_server_id="synthetic-http")
    configuration.update("synthetic-http", request, user_id=gate["principal"].id, prepared=prepared)
    with service.database.session() as connection:
        binding = server_binding(connection, "synthetic-http")
    sealed = store.get_credential(current["id"])
    assert binding != old_binding and sealed.http_scopes[0].server_binding == binding
    assert sealed.http_scopes[0].pending_rebind is False
    assert sealed.updated_at == pending["updated_at"]
    assert sealed.http_scopes_revision != pending["http_scopes_revision"]
    with pytest.raises(CredentialUsageDenied):
        send(old_client)
    assert len(old_sent) == 1
    new_client, new_sent = client_for(gate, data)
    send(new_client)
    assert new_sent == [("POST", "Bearer " + SECRET)]


def test_failed_apply_after_rebind_sealing_retains_new_configuration_as_partial(gate):
    current, old_binding = saved_http(gate)
    service, store = gate["service"], gate["service"].credentials
    current = store.get_credential(current["id"]).model_dump(mode="json")
    update(gate, current, authorize_http_target={"server_id": "synthetic-http", "origin": "https://mcp.example.test"},
           expected_http_scopes_revision=current["http_scopes_revision"])
    runtime = Mock()
    runtime.apply_manifest.side_effect = RuntimeError("Synthetic apply failure")
    configuration = McpConfigurationService(service.configs, runtime, Mock(), credentials=store)
    request = McpConfigSaveRequest(manifest=manifest(endpoint="https://mcp.example.test/new-mcp"), apply=True)
    prepared = configuration.prepare_user_credentials(request, existing_server_id="synthetic-http")
    with pytest.raises(McpConfigPartialError):
        configuration.update("synthetic-http", request, user_id=gate["principal"].id, prepared=prepared)
    assert service.configs.load_manifest("synthetic-http").transport.endpoint == "https://mcp.example.test/new-mcp"
    with service.database.session() as connection:
        binding = server_binding(connection, "synthetic-http")
    sealed = store.get_credential(current["id"])
    assert binding != old_binding and sealed.http_scopes[0].server_binding == binding
    assert sealed.http_scopes[0].pending_rebind is False


def test_legacy_update_receipts_remain_replayable_after_optional_scope_fields_are_added(gate):
    current = create(gate)
    service = gate["service"]
    legacy_scopes = [{"server_id": "target", "origin": "https://target.example.test:443", "server_binding": None}]
    legacy_arguments = {"credential_id": current["id"], "expected_revision": current["updated_at"],
        "name": None, "value": None, "description": "Legacy metadata update", "http_scopes": legacy_scopes,
        "idempotency_key": "legacy-update"}
    result = service._run(gate["context"], "gate_credential_update", "credential.update", current["id"],
        legacy_arguments, lambda: service.credentials.update_credential(current["id"],
            expected_revision=current["updated_at"], description="Legacy metadata update", http_scopes=legacy_scopes), value_saved=False)
    replay = update(gate, current, description="Legacy metadata update", http_scopes=legacy_scopes, idempotency_key="legacy-update")
    assert replay["idempotent_replay"] and replay["updated_at"] == result["updated_at"]


def test_legacy_create_receipts_ignore_default_false_pending_rebind_fields(gate):
    service = gate["service"]
    legacy_arguments = {"credential_id": "legacy-created", "name": "Legacy created", "value": SECRET, "description": "",
        "http_scopes": [{"server_id": "target", "origin": "https://target.example.test:443", "server_binding": None}],
        "idempotency_key": "legacy-create"}
    result = service._run(gate["context"], "gate_credential_create", "credential.create", "legacy-created",
        legacy_arguments, lambda: service.credentials.create_credential(credential_id="legacy-created", name="Legacy created",
            value=SECRET, http_scopes=legacy_arguments["http_scopes"]), value_saved=True)
    replay = service.create(legacy_arguments, gate["context"])
    assert replay["idempotent_replay"] and replay["updated_at"] == result["updated_at"]


def test_full_scope_replace_detects_sealing_without_a_value_revision_change(gate):
    current = create(gate, http_scopes=[{"server_id": "first", "origin": "https://first.example.test"}])
    store = gate["service"].credentials
    store.bind_http_usage([current["id"]], server_id="first", endpoint="https://first.example.test/mcp",
                         server_binding="first-generation")
    sealed = store.get_credential(current["id"])
    assert sealed.updated_at == current["updated_at"]
    assert sealed.http_scopes_revision != current["http_scopes_revision"]
    additional = {"server_id": "second", "origin": "https://second.example.test"}
    with pytest.raises(ToolExecutionError) as stale:
        update(gate, current, http_scopes=[*current["http_scopes"], additional],
               expected_http_scopes_revision=current["http_scopes_revision"], idempotency_key="stale-scope-list")
    assert stale.value.code == "credential_revision_conflict"
    assert store.get_credential(current["id"]) == sealed
    with pytest.raises(CredentialRevisionConflict):
        store.update_credential(current["id"], expected_revision=current["updated_at"],
            expected_http_scopes_revision=current["http_scopes_revision"], http_scopes=current["http_scopes"])
    latest = sealed.model_dump(mode="json")
    result = update(gate, latest, http_scopes=[*latest["http_scopes"], additional],
                    expected_http_scopes_revision=latest["http_scopes_revision"], idempotency_key="fresh-scope-list")
    assert result["http_scopes"][0]["server_binding"] == "first-generation"


def test_full_scope_replace_can_retain_an_unchanged_deleted_service_grant(gate):
    current, old_binding = saved_http(gate)
    service = gate["service"]
    service.configs.delete_config("synthetic-http")
    current = service.credentials.get_credential(current["id"]).model_dump(mode="json")
    result = update(gate, current, http_scopes=[*current["http_scopes"],
        {"server_id": "new-http", "origin": "https://new.example.test"}],
        expected_http_scopes_revision=current["http_scopes_revision"])
    assert next(scope for scope in result["http_scopes"] if scope["server_id"] == "synthetic-http")["server_binding"] == old_binding
    with pytest.raises(CredentialUsageDenied):
        service.credentials.assert_http_binding(current["id"], server_id="synthetic-http",
            endpoint="https://mcp.example.test/mcp", server_binding="replacement-generation", allow_pending=True)


def test_full_scope_replace_preserves_explicit_pending_rebind_for_an_unchanged_binding(gate):
    current, binding = saved_http(gate)
    service, store = gate["service"], gate["service"].credentials
    current = store.get_credential(current["id"]).model_dump(mode="json")
    pending = update(gate, current, http_scopes=[{**current["http_scopes"][0], "pending_rebind": True}],
                     expected_http_scopes_revision=current["http_scopes_revision"])
    assert pending["http_scopes"][0]["server_binding"] == binding
    assert pending["http_scopes"][0]["pending_rebind"] is True
    service.configs.delete_config("synthetic-http")
    preserved = update(gate, pending, http_scopes=[*pending["http_scopes"],
        {"server_id": "additional", "origin": "https://additional.example.test"}],
        expected_http_scopes_revision=pending["http_scopes_revision"])
    scope = next(scope for scope in preserved["http_scopes"] if scope["server_id"] == "synthetic-http")
    assert scope["server_binding"] == binding and scope["pending_rebind"] is True


@pytest.mark.parametrize("change", [{"server_binding": "forged-generation"}, {"origin": "https://other.example.test"},
                                    {"server_binding": "forged-generation", "pending_rebind": True}])
def test_full_scope_replace_revalidates_new_or_changed_nonnull_bindings(gate, change):
    current, _ = saved_http(gate)
    store = gate["service"].credentials
    current = store.get_credential(current["id"]).model_dump(mode="json")
    with pytest.raises(ToolExecutionError) as invalid:
        update(gate, current, http_scopes=[{**current["http_scopes"][0], **change}],
               expected_http_scopes_revision=current["http_scopes_revision"])
    assert invalid.value.code == "credential_http_scope_invalid"
    assert store.get_credential(current["id"]).http_scopes_revision == current["http_scopes_revision"]


def test_http_scope_revision_normalizes_order_and_origins_without_hashing_secret_values(tmp_path):
    store = CredentialStore(tmp_path)
    current = store.create_credential(credential_id="synthetic", name="Synthetic", value=SECRET, http_scopes=[
        {"server_id": "first", "origin": "https://FIRST.example.test", "server_binding": None},
        {"server_id": "second", "origin": "https://second.example.test:443", "server_binding": "old-generation"}])
    reordered = store.update_credential(current.id, expected_revision=current.updated_at, value=ROTATED, http_scopes=[
        {"server_id": "second", "origin": "https://SECOND.example.test", "server_binding": "old-generation", "pending_rebind": False},
        {"server_id": "first", "origin": "https://first.example.test:443"}])
    assert len(current.http_scopes_revision) == 64
    assert reordered.http_scopes_revision == current.http_scopes_revision
    store.bind_http_usage([current.id], server_id="first", endpoint="https://first.example.test/mcp",
                         server_binding="first-generation")
    sealed = store.get_credential(current.id)
    assert sealed.updated_at == reordered.updated_at
    assert sealed.http_scopes_revision != reordered.http_scopes_revision
    pending = store.update_credential(current.id, expected_revision=sealed.updated_at, http_scopes=[
        {**scope.model_dump(mode="json"), "pending_rebind": scope.server_id == "first"} for scope in sealed.http_scopes])
    assert pending.http_scopes_revision != sealed.http_scopes_revision
    store.bind_http_usage([current.id], server_id="first", endpoint="https://first.example.test/mcp",
                         server_binding="first-generation")
    consumed = store.get_credential(current.id)
    assert consumed.updated_at == pending.updated_at
    assert consumed.http_scopes_revision == sealed.http_scopes_revision


@pytest.mark.parametrize("changes", [
    {"authorize_http_target": {"server_id": "target", "origin": "https://target.example.test"}, "http_scopes": []},
    {"authorize_http_target": {"server_id": "target", "origin": "https://target.example.test", "server_binding": None}},
    {"authorize_http_target": {"server_id": "target", "origin": "https://target.example.test", "server_binding": "forged"}},
])
def test_single_http_target_rejects_full_replacement_and_caller_supplied_generation(gate, changes):
    current = create(gate)
    with pytest.raises(ToolExecutionError) as invalid:
        update(gate, current, **changes)
    assert invalid.value.code == "credential_request_invalid"
    assert gate["service"].credentials.get_credential(current["id"]).http_scopes == []


def test_single_http_target_enforces_origin_and_scope_count_limits(gate):
    current = create(gate, http_scopes=[{"server_id": f"target-{index}", "origin": "https://target.example.test"}
                                      for index in range(100)])
    for key, target in (("path", {"server_id": "target-0", "origin": "https://target.example.test/path"}),
                        ("limit", {"server_id": "overflow", "origin": "https://target.example.test"})):
        with pytest.raises(ToolExecutionError) as invalid:
            update(gate, current, authorize_http_target=target, idempotency_key="invalid-target-" + key)
        assert invalid.value.code == "credential_http_scope_invalid"
    renewed = update(gate, current, authorize_http_target={"server_id": "target-0", "origin": "https://target.example.test"})
    assert len(renewed["http_scopes"]) == 100


@pytest.mark.parametrize("scopes", [["operations.manage", "tools.invoke"], ["credentials.manage.system"]])
def test_single_http_target_requires_both_current_credential_write_permissions(gate, scopes):
    current = create(gate)
    token = gate["auth"].create_api_token(principal=gate["principal"], name="Synthetic insufficient target grant", scopes=scopes)
    actor = gate["auth"]._principal_from_api_token(token["token"])
    with pytest.raises(ToolExecutionError) as denied:
        gate["service"].update({"credential_id": current["id"], "expected_revision": current["updated_at"],
            "authorize_http_target": {"server_id": "target", "origin": "https://target.example.test"},
            "idempotency_key": "denied-target"}, credential_context(actor))
    assert denied.value.code == "credential_permission_denied"
    assert gate["service"].credentials.get_credential(current["id"]).http_scopes == []


def test_single_http_target_rechecks_revocation_after_operation_reservation(gate, monkeypatch):
    current = create(gate)
    service, auth = gate["service"], gate["auth"]
    token = auth.create_api_token(principal=gate["principal"], name="Synthetic revoked target grant",
                                 scopes=["credentials.manage.system", "tools.invoke"])
    context = credential_context(auth._principal_from_api_token(token["token"]))
    reserve = service._reserve

    def reserve_then_revoke(*args, **kwargs):
        result = reserve(*args, **kwargs)
        auth.revoke_api_token(token["id"], user_id=gate["principal"].id)
        return result

    monkeypatch.setattr(service, "_reserve", reserve_then_revoke)
    with pytest.raises(ToolExecutionError) as denied:
        service.update({"credential_id": current["id"], "expected_revision": current["updated_at"],
            "authorize_http_target": {"server_id": "target", "origin": "https://target.example.test"},
            "idempotency_key": "revoked-target"}, context)
    assert denied.value.code == "credential_permission_denied"
    assert service.credentials.get_credential(current["id"]).http_scopes == []


def test_rest_single_http_target_uses_existing_update_route_and_strict_target_schema(gate):
    current = create(gate)
    target = {"server_id": "target", "origin": "https://target.example.test"}
    with TestClient(gate["app"]) as client:
        client.cookies.set(gate["auth"].cookie_name, gate["cookie"])
        base = {"expected_revision": current["updated_at"], "authorize_http_target": target}
        for extra in ({"http_scopes": []}, {"authorize_http_target": {**target, "server_binding": None}}):
            invalid = client.put("/v1/credentials/" + current["id"], json={**base, **extra})
            assert invalid.status_code == 422
        result = client.put("/v1/credentials/" + current["id"], json={**base, "idempotency_key": "rest-target"})
        assert result.status_code == 200 and SECRET not in result.text
        assert result.json()["http_scopes"] == [{**target, "origin": "https://target.example.test:443", "server_binding": None,
                                                 "pending_rebind": False}]
        assert len(result.json()["http_scopes_revision"]) == 64


def test_http_trust_reports_current_configuration_identity_without_a_policy_binding(gate):
    service = gate["service"]
    data = manifest()
    data["transport"]["headers"] = {}
    service.configs.save_config(data)
    with TestClient(gate["app"]) as client:
        client.cookies.set(gate["auth"].cookie_name, gate["cookie"])
        with service.database.session() as connection:
            binding = server_binding(connection, "synthetic-http")
        response = client.get("/v1/mcp/http-trust/synthetic-http")
        assert response.status_code == 200
        assert response.json().get("server_binding") is None
        assert response.json()["configured_server_binding"] == binding
        assert response.json()["configured_endpoint_origin"] == "https://mcp.example.test:443"
        service.configs.delete_config("synthetic-http")
        deleted = client.get("/v1/mcp/http-trust/synthetic-http")
        assert deleted.status_code == 200
        assert deleted.json()["configured_server_binding"] is None
        assert deleted.json()["configured_endpoint_origin"] is None


def test_http_rotation_refreshes_existing_post_and_session_delete(gate):
    current, _ = saved_http(gate)
    client, sent = client_for(gate)
    send(client)
    result = update(gate, current, value=ROTATED)
    assert result["connections"] == [{"server_id": "synthetic-http", "state": "refresh_on_next_dispatch"}]
    send(client)
    client.session_id = "synthetic-session"
    client.stop()
    assert sent == [("POST", "Bearer " + SECRET), ("POST", "Bearer " + ROTATED), ("DELETE", "Bearer " + ROTATED)]


def test_rotation_waits_for_prior_dispatch_and_no_later_request_uses_old_value(gate):
    current, _ = saved_http(gate)
    client, sent = client_for(gate)
    entered, release, rotated = threading.Event(), threading.Event(), threading.Event()
    original = client._opener.open
    def blocking(request, *, timeout):
        entered.set()
        assert release.wait(3)
        return original(request, timeout=timeout)
    client._opener.open = blocking
    dispatch = threading.Thread(target=send, args=(client,))
    dispatch.start()
    assert entered.wait(2)
    def rotate():
        update(gate, current, value=ROTATED)
        rotated.set()
    rotation = threading.Thread(target=rotate)
    rotation.start()
    assert not rotated.wait(.05)
    release.set()
    dispatch.join(3)
    rotation.join(3)
    assert not dispatch.is_alive() and not rotation.is_alive() and rotated.is_set()
    send(client)
    assert sent[-1] == ("POST", "Bearer " + ROTATED)


def test_existing_client_does_not_adopt_replaced_service_generation(gate):
    _, _binding = saved_http(gate)
    client, sent = client_for(gate)
    send(client)
    service = gate["service"]
    service.configs.delete_config("synthetic-http")
    service.configs.save_config(manifest())
    current = service.credentials.get_credential("synthetic-credential")
    update(gate, current.model_dump(), http_scopes=[{"server_id": "synthetic-http", "origin": "https://mcp.example.test"}])
    with service.database.session() as connection:
        new_binding = server_binding(connection, "synthetic-http")
    service.credentials.bind_http_usage([current.id], server_id="synthetic-http", endpoint="https://mcp.example.test/mcp",
                                        server_binding=new_binding)
    with pytest.raises(CredentialUsageDenied):
        send(client)
    assert len(sent) == 1


def test_private_http_client_without_credentials_cannot_reuse_recreated_service_grant(gate):
    service = gate["service"]
    trust = service.configs.http_trust_store
    data = manifest(endpoint="http://10.23.45.67:4747/mcp")
    data["transport"]["headers"] = {}
    def grant_and_save():
        trust.update("synthetic-http", McpHttpTrustUpdate(origins=[{"ip": "10.23.45.67", "port": 4747}],
            expected_revision=trust.get("synthetic-http")["revision"], confirmed=True), actor_id=gate["context"].actor_id)
        service.configs.save_config(data)
    grant_and_save()
    client, sent = client_for(gate, data)
    send(client)
    service.configs.delete_config("synthetic-http")
    grant_and_save()
    with pytest.raises(ValueError):
        send(client)
    with pytest.raises(ValueError):
        client.start()
    client.session_id = "synthetic-old-session"
    client.stop()
    assert sent == [("POST", None)]
    successor, new_sent = client_for(gate, data)
    send(successor)
    assert new_sent == [("POST", None)]


def test_http_scope_change_fails_before_any_network_or_stale_header_reuse(gate):
    current, _ = saved_http(gate)
    client, sent = client_for(gate)
    send(client)
    update(gate, current, http_scopes=[])
    with pytest.raises(CredentialUsageDenied):
        send(client)
    assert len(sent) == 1 and client._resolved_headers == {}


def test_in_use_delete_and_cas_then_detach_delete_replay(gate):
    current, _ = saved_http(gate)
    body = {"credential_id": current["id"], "expected_revision": current["updated_at"], "idempotency_key": "delete-in-use"}
    with pytest.raises(ToolExecutionError) as used:
        gate["service"].delete(body, gate["context"])
    assert used.value.code == "credential_in_use"
    assert used.value.details["dependencies"]["items"][0]["id"] == "synthetic-http"
    gate["service"].configs.delete_config("synthetic-http")
    body["idempotency_key"] = "delete-detached"
    deleted = gate["service"].delete(body, gate["context"])
    assert deleted["id"] == current["id"]
    assert gate["service"].delete(body, gate["context"])["idempotent_replay"]


def test_legacy_migration_only_current_consumers_and_non_http_resolution_stays_valid(gate):
    service = gate["service"]
    service.credentials.save_credential(name="Legacy", value=SECRET, credential_id="synthetic-credential")
    service.credentials.save_credential(name="Git legacy", value=ROTATED, credential_id="synthetic-git")
    service.configs.save_config(manifest())
    data = json.loads(service.credentials.store_path.read_text())
    for record in data.values():
        record.pop("http_scopes", None)
    service.credentials.store_path.write_text(json.dumps(data))
    service._migrate_legacy()
    assert len(service.credentials.get_credential("synthetic-credential").http_scopes) == 1
    assert not service.credentials.get_credential("synthetic-git").http_scopes
    assert service.credentials.resolve_value("synthetic-git") == ROTATED
    update(gate, service.credentials.get_credential("synthetic-credential").model_dump(), http_scopes=[])
    service._migrate_legacy()
    assert not service.credentials.get_credential("synthetic-credential").http_scopes


def test_legacy_https_credential_does_not_migrate_to_replaced_config_on_restart(gate):
    service = gate["service"]
    service.credentials.save_credential(name="Legacy", value=SECRET, credential_id="synthetic-credential")
    service.configs.save_config(manifest())
    data = json.loads(service.credentials.store_path.read_text())
    data["synthetic-credential"].pop("http_scopes")
    service.credentials.store_path.write_text(json.dumps(data))
    with service.database.session() as connection:
        old_binding = server_binding(connection, "synthetic-http")
        row = connection.execute("SELECT file_path FROM gate_mcp_authorization_identities WHERE server_id='synthetic-http'").fetchone()
    from pathlib import Path
    path = Path(row["file_path"])
    original = path.read_bytes()
    path.unlink()
    path.write_bytes(original)
    service.configs = McpConfigStore(service.configs.config_dir, http_trust_store=service.configs.http_trust_store)
    assert service.configs.invalidated_startup_identities == {"synthetic-http"}
    with service.database.session() as connection:
        assert server_binding(connection, "synthetic-http") != old_binding
    service._migrate_legacy()
    assert service.credentials.get_credential("synthetic-credential").http_scopes == []
    assert service.credentials.resolve_value("synthetic-credential") == SECRET


def test_admin_token_star_is_allowed_but_live_scope_and_role_revocation_win(gate):
    auth, principal, service = gate["auth"], gate["principal"], gate["service"]
    full = auth.create_api_token(principal=principal, name="Synthetic full", scopes=["*"])
    actor = auth._principal_from_api_token(full["token"])
    context = credential_context(actor)
    assert service.create({"name": "Via token", "value": SECRET, "idempotency_key": "token-create"}, context)["id"] == "Via-token"
    limited = auth.create_api_token(principal=principal, name="Synthetic limited", scopes=["operations.manage", "tools.invoke"])
    with pytest.raises(ToolExecutionError) as missing:
        service.list({}, credential_context(auth._principal_from_api_token(limited["token"])))
    assert missing.value.code == "credential_permission_denied"
    auth.revoke_api_token(full["id"], user_id=principal.id)
    with pytest.raises(ToolExecutionError):
        service.list({}, context)
    service.access.set_user_roles(principal.id, ["operator"])
    with pytest.raises(ToolExecutionError):
        service.list({}, gate["context"])


def test_oauth_list_filters_exact_credential_read_actions(gate):
    create(gate, "visible")
    create(gate, "hidden")
    service = gate["service"]
    def authority(context, tool, *, write, target_id, action):
        assert action == "credential.read"
        if target_id == "hidden":
            raise ValueError("target denied")
        return {}
    service.auth.builtin_oauth = Mock(management_authority=authority)
    actor = replace(gate["context"], auth_type="oauth", oauth_builtin=True)
    assert [item["id"] for item in service.list({}, actor)["credentials"]] == ["visible"]
    with pytest.raises(ToolExecutionError):
        service.get({"credential_id": "hidden"}, actor)


@pytest.mark.parametrize("payload_mode", ["metadata_only", "redacted"])
def test_persistence_and_debug_logs_never_contain_secret_value(gate, caplog, payload_mode):
    caplog.set_level(logging.DEBUG)
    service, state = gate["service"], gate["app"].state
    service.database.execute("UPDATE retention_policy SET payload_mode=?", (payload_mode,))
    token = gate["auth"].create_api_token(principal=gate["principal"], name="Synthetic privacy", scopes=["*"])
    principal = gate["auth"]._principal_from_api_token(token["token"])
    result = state.access_store.invoke_tool(state.registry, principal, "gate_credential_create",
        {"credential_id": "synthetic-privacy", "name": "Synthetic privacy", "value": SECRET, "idempotency_key": "privacy-create"})
    assert result.ok
    failed = state.access_store.invoke_tool(state.registry, principal, "gate_credential_update",
        {"credential_id": "synthetic-privacy", "expected_revision": "stale", "value": ROTATED,
         "idempotency_key": "privacy-stale"})
    assert not failed.ok and failed.output["error"]["code"] == "credential_revision_conflict"
    private_rows = [dict(row) for row in service.database.query_all("SELECT * FROM invocation_payloads")]
    assert bool(private_rows) == (payload_mode == "redacted")
    formatter = JsonFormatter()
    exposed = json.dumps(private_rows) + result.model_dump_json() + failed.model_dump_json() + "".join(formatter.format(record) for record in caplog.records)
    for table in ("mcp_idempotent_operations", "events", "logs"):
        exposed += json.dumps([dict(row) for row in service.database.query_all("SELECT * FROM " + table)])
    assert SECRET not in exposed and ROTATED not in exposed


def test_non_http_dependencies_are_preserved_and_block_delete(gate):
    current = create(gate)
    service = gate["service"]
    assert service.credentials.resolve_value(current["id"]) == SECRET
    settings = service.database.query_one("SELECT settings_json FROM delivery_network_settings WHERE id=1")
    values = json.loads(settings["settings_json"]) if settings is not None else {}
    values["npm_credential_ref"] = current["id"]
    service.database.execute("INSERT INTO delivery_network_settings(id,revision,settings_json) VALUES(1,1,?) "
        "ON CONFLICT(id) DO UPDATE SET settings_json=excluded.settings_json", (json.dumps(values),))
    with pytest.raises(ToolExecutionError) as used:
        service.delete({"credential_id": current["id"], "expected_revision": current["updated_at"],
                        "idempotency_key": "network-in-use"}, gate["context"])
    assert used.value.code == "credential_in_use"
    assert used.value.details["dependencies"]["items"] == [{"type": "network_settings", "id": "defaults"}]


def test_token_connection_summary_discloses_only_permitted_consumers(gate):
    current, _ = saved_http(gate)
    service = gate["service"]
    full = gate["auth"].create_api_token(principal=gate["principal"], name="Synthetic full", scopes=["*"])
    principal = gate["auth"]._principal_from_api_token(full["token"])
    first = service.update({"credential_id": current["id"], "expected_revision": current["updated_at"],
        "value": ROTATED, "idempotency_key": "visible-rotation"}, credential_context(principal))
    assert first["affected_connection_count"] == 1 and first["hidden_connection_count"] == 0
    assert first["connections"][0]["server_id"] == "synthetic-http"
    narrow = gate["auth"].create_api_token(principal=gate["principal"], name="Synthetic credentials only",
        scopes=["credentials.manage.system", "tools.invoke"])
    narrow_principal = gate["auth"]._principal_from_api_token(narrow["token"])
    second = service.update({"credential_id": current["id"], "expected_revision": first["updated_at"],
        "value": SECRET, "idempotency_key": "hidden-rotation"}, credential_context(narrow_principal))
    assert second["affected_connection_count"] == second["hidden_connection_count"] == 1
    assert second["connections"] == []


def test_idempotent_results_and_errors_recheck_current_dependency_visibility(gate):
    current, _ = saved_http(gate)
    service = gate["service"]
    token = gate["auth"].create_api_token(principal=gate["principal"], name="Synthetic revocable", scopes=["*"])
    context = credential_context(gate["auth"]._principal_from_api_token(token["token"]))
    arguments = {"credential_id": current["id"], "expected_revision": current["updated_at"],
                 "value": ROTATED, "idempotency_key": "replay-rotation"}
    first = service.update(arguments, context)
    assert first["connections"][0]["server_id"] == "synthetic-http"
    deletion = {"credential_id": current["id"], "expected_revision": first["updated_at"],
                "idempotency_key": "replay-dependency-error"}
    with pytest.raises(ToolExecutionError) as original:
        service.delete(deletion, context)
    assert original.value.details["dependencies"]["items"]
    service.database.execute("UPDATE api_tokens SET scopes_json=? WHERE id=?",
        (json.dumps(["credentials.manage.system", "tools.invoke"]), token["id"]))
    replay = service.update(arguments, context)
    assert replay["idempotent_replay"] and replay["connections"] == []
    assert replay["affected_connection_count"] == replay["hidden_connection_count"] == 1
    with pytest.raises(ToolExecutionError) as repeated:
        service.delete(deletion, context)
    assert repeated.value.details["dependencies"] == {"items": [], "hidden_count": 1}
    assert service.get({"credential_id": current["id"]}, context)["dependencies"] == {"items": [], "hidden_count": 1}


def test_rest_validation_masks_conflicts_and_generic_cookie_entry_is_blocked(gate):
    with TestClient(gate["app"]) as client:
        client.cookies.set(gate["auth"].cookie_name, gate["cookie"])
        invalid = client.post("/v1/credentials", json={"name": "Synthetic", "value": {"secret": SECRET}})
        assert invalid.status_code == 422 and SECRET not in invalid.text
        created = client.post("/v1/credentials", json={"name": "REST synthetic", "value": SECRET, "idempotency_key": "rest-create"})
        assert created.status_code == 200 and SECRET not in created.text
        current = created.json()
        assert created.headers["cache-control"] == "no-store"
        update_response = client.put("/v1/credentials/" + current["id"], json={"value": None, "name": current["name"],
            "description": "Metadata only", "expected_revision": current["updated_at"], "idempotency_key": "rest-update"})
        assert update_response.status_code == 200
        stale = client.delete("/v1/credentials/" + current["id"], params={"expected_revision": current["updated_at"], "idempotency_key": "stale-delete"})
        assert stale.status_code == 409 and stale.json()["detail"]["code"] == "credential_revision_conflict"
        cross_origin = client.post("/v1/credentials", headers={"Origin": "https://other.example.test"}, json={"name": "X", "value": SECRET})
        assert cross_origin.status_code == 403
        result = client.post("/v1/tools/gate_credential_create/invoke", json={"arguments": {"name": "Generic", "value": SECRET, "idempotency_key": "generic"}})
        assert result.status_code == 403 and result.json()["detail"] == "management control permission denied"


def test_unfinished_file_write_is_not_replayed_on_restart(gate):
    service = gate["service"]
    service.database.execute("INSERT INTO mcp_idempotent_operations "
        "(id,actor_id,tool_id,idempotency_key,request_digest,status,resource_type,created_at,updated_at) "
        "VALUES('synthetic-pending',?,'gate_credential_create','pending','digest','pending','shared_credential','now','now')",
        (gate["context"].actor_id,))
    SharedCredentialService(database=service.database, auth=service.auth, access=service.access,
        credentials=service.credentials, configs=service.configs, observability=service.observability)
    row = service.database.query_one("SELECT * FROM mcp_idempotent_operations WHERE id='synthetic-pending'")
    assert row["status"] == "failed" and "credential_operation_interrupted" in row["error_json"]


@pytest.mark.parametrize("failure", ["audit", "receipt", "persistence"])
def test_write_followed_by_audit_or_receipt_failure_reports_reconciliation(gate, monkeypatch, failure):
    service = gate["service"]
    if failure == "audit":
        monkeypatch.setattr(service.observability, "emit_event", Mock(side_effect=ValueError(SECRET)))
    elif failure == "receipt":
        execute = service.database.execute
        def fail_receipt(sql, parameters=()):
            if "UPDATE mcp_idempotent_operations SET status='succeeded'" in sql:
                raise ValueError(SECRET)
            return execute(sql, parameters)
        monkeypatch.setattr(service.database, "execute", fail_receipt)
    else:
        write = service.credentials._write_all
        def ambiguous_write(data):
            write(data)
            raise ValueError(SECRET)
        monkeypatch.setattr(service.credentials, "_write_all", ambiguous_write)
    with pytest.raises(ToolExecutionError) as interrupted:
        create(gate)
    assert interrupted.value.code == "credential_operation_interrupted"
    assert interrupted.value.details["requires_reconciliation"]
    assert interrupted.value.details["credential_mutated"] == ("unknown" if failure == "persistence" else True)
    assert interrupted.value.details["value_saved"] is (None if failure == "persistence" else True)
    assert service.credentials.resolve_value("synthetic-credential") == SECRET
    assert SECRET not in json.dumps(interrupted.value.to_payload())
    with pytest.raises(ToolExecutionError) as replay:
        create(gate)
    assert replay.value.code == "credential_operation_interrupted"
    assert replay.value.details["credential_mutated"] == ("unknown" if failure == "persistence" else True)


@pytest.mark.parametrize("entry", ["invoke", "catalog"])
@pytest.mark.parametrize("operation", ["list", "get", "create", "update", "delete", "http_plan", "http_status"])
def test_minimal_management_token_scopes_match_real_discovery_and_invocation(gate, entry, operation):
    state = gate["app"].state
    current = create(gate)
    http = operation.startswith("http_")
    read_only = operation in {"list", "get", "http_plan", "http_status"}
    scopes = ["operations.manage" if http else "credentials.manage.system"]
    if not read_only:
        scopes.append("tools.invoke")
    token = gate["auth"].create_api_token(principal=gate["principal"], name="Synthetic minimal management", scopes=scopes)
    principal = gate["auth"]._principal_from_api_token(token["token"])
    if http:
        data = manifest("synthetic-http-minimal")
        data["transport"]["headers"] = {}
        tool = "gate_http_mcp_" + operation.removeprefix("http_")
        if operation == "http_status":
            gate["service"].configs.save_config(data)
            arguments = {"server_id": data["id"]}
        else:
            arguments = {"mode": "create", "manifest": data}
    else:
        tool = "gate_credential_" + operation
        arguments = {
            "list": {},
            "get": {"credential_id": current["id"]},
            "create": {"credential_id": "synthetic-created", "name": "Synthetic created", "value": ROTATED,
                       "idempotency_key": "minimal-create"},
            "update": {"credential_id": current["id"], "expected_revision": current["updated_at"],
                       "value": ROTATED, "idempotency_key": "minimal-update"},
            "delete": {"credential_id": current["id"], "expected_revision": current["updated_at"],
                       "idempotency_key": "minimal-delete"},
        }[operation]
    if entry == "invoke":
        response = state.access_store.invoke_tool(state.registry, principal, tool, arguments)
    else:
        catalog = state.tool_catalog
        found = catalog.call("gate_catalog_search", {"query": tool}, principal).output
        assert any(item["tool_ref"] == tool for item in found["tools"]), state.access_store.evaluate(principal, state.registry.get_definition(tool))
        described = catalog.call("gate_tool_describe", {"tool_ref": tool}, principal).output
        response = catalog.call("gate_tool_invoke", {"tool_ref": tool, "schema_revision": described["schema_revision"],
                                "arguments": arguments}, principal)
    assert response.ok, response.output
    if operation == "http_plan":
        assert response.output["status"] == "ready" and response.output["network_contacted"] is False


@pytest.mark.parametrize("scopes,tool", [
    (["credentials.manage.system"], "gate_credential_create"),
    (["tools.invoke"], "gate_credential_create"),
    (["operations.manage"], "gate_http_mcp_apply"),
])
def test_minimal_management_scope_exception_does_not_authorize_writes_without_both_permissions(gate, scopes, tool):
    state = gate["app"].state
    token = gate["auth"].create_api_token(principal=gate["principal"], name="Synthetic missing write permission", scopes=scopes)
    principal = gate["auth"]._principal_from_api_token(token["token"])
    with pytest.raises(AccessDeniedError):
        state.access_store.invoke_tool(state.registry, principal, tool, {})


@pytest.mark.parametrize("tool,revocation,permission", [
    ("gate_credential_list", "role", "credentials.manage.system"),
    ("gate_credential_create", "role", "credentials.manage.system"),
    ("gate_http_mcp_plan", "role", "operations.manage"),
    ("gate_http_mcp_apply", "role", "operations.manage"),
    ("gate_credential_list", "permission", "credentials.manage.system"),
    ("gate_credential_create", "permission", "credentials.manage.system"),
    ("gate_credential_create", "permission", "tools.invoke"),
    ("gate_http_mcp_plan", "permission", "operations.manage"),
    ("gate_http_mcp_apply", "permission", "operations.manage"),
    ("gate_http_mcp_apply", "permission", "tools.invoke"),
])
def test_management_entry_rechecks_live_roles_and_control_permissions(gate, tool, revocation, permission):
    state = gate["app"].state
    token = gate["auth"].create_api_token(principal=gate["principal"], name="Synthetic revocable management", scopes=["*"])
    principal = gate["auth"]._principal_from_api_token(token["token"])
    definition = state.registry.get_definition(tool)
    assert state.access_store.evaluate(principal, definition)["allowed"]
    data = manifest("synthetic-revoked-management")
    data["transport"]["headers"] = {}
    if tool == "gate_credential_list":
        arguments = {}
    elif tool == "gate_credential_create":
        arguments = {"credential_id": "synthetic-revoked-management", "name": "Synthetic denied",
                     "value": SECRET, "idempotency_key": "revoked-create"}
    elif tool == "gate_http_mcp_plan":
        arguments = {"mode": "create", "manifest": data}
    else:
        plan = state.external_mcp_configuration_service.http_plan({"mode": "create", "manifest": data},
                                                                  credential_context(principal))
        arguments = {"plan_id": plan["plan_id"], "plan_digest": plan["plan_digest"], "connect": False,
                     "refresh_tools": False, "confirmed": True, "idempotency_key": "revoked-http-apply"}
    if revocation == "role":
        state.access_store.set_user_roles(principal.id, ["operator"])
    else:
        gate["service"].database.execute("DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM control_permissions WHERE code=?)", (permission,))
    refreshed = gate["auth"]._principal_from_api_token(token["token"])
    assert not state.access_store.evaluate(refreshed, definition)["allowed"]
    found = state.tool_catalog.call("gate_catalog_search", {"query": tool}, refreshed).output["tools"]
    assert all(item["tool_ref"] != tool for item in found)
    with pytest.raises(AccessDeniedError):
        state.access_store.invoke_tool(state.registry, refreshed, tool, arguments)
    # An already queued invocation carrying the pre-revocation principal also
    # fails the shared current_tool_principal guard before reaching the handler.
    stale_result = state.access_store.invoke_tool(state.registry, principal, tool, arguments)
    assert not stale_result.ok and stale_result.output["error"]["code"] == "tool_authorization_changed"
    assert not gate["service"].credentials.list_credentials()
    assert not gate["service"].configs.list_configs().configs
    assert not gate["service"].database.query_all("SELECT id FROM external_mcp_config_operations")


@pytest.mark.parametrize("tool", [
    "gate_credential_list", "gate_credential_get", "gate_credential_create", "gate_credential_update", "gate_credential_delete",
    "gate_http_mcp_plan", "gate_http_mcp_apply", "gate_http_mcp_status", "gate_http_mcp_cancel",
])
def test_console_session_cannot_use_new_management_tools_through_generic_entries(gate, tool):
    state = gate["app"].state
    principal = gate["principal"]
    assert not state.access_store.evaluate(principal, state.registry.get_definition(tool))["allowed"]
    with pytest.raises(AccessDeniedError):
        state.access_store.invoke_tool(state.registry, principal, tool, {})
    found = state.tool_catalog.call("gate_catalog_search", {"query": tool}, principal).output["tools"]
    assert all(item["tool_ref"] != tool for item in found)
    with pytest.raises(ToolExecutionError) as hidden:
        state.tool_catalog.call("gate_tool_describe", {"tool_ref": tool}, principal)
    assert hidden.value.code == "catalog_tool_unavailable"

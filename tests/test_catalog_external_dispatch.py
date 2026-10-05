"""Public catalog dispatch reuses verified external trust after lock waits."""
from contextlib import contextmanager
from threading import Event, Thread

import pytest

from lingshu_gate.domain.mcp_group_routing import logical_service_id
from lingshu_gate.domain.mcp_groups import McpGroupCreate
from lingshu_gate.registry import ToolExecutionError

from test_external_oauth_http import CANONICAL, PASSWORD
from test_mcp_group_external_authority import oauth_http as oauth_http, verified_actor
from test_mcp_groups import draft


@pytest.mark.parametrize("lock_kind", ["config", "runtime"])
@pytest.mark.parametrize("change", ["client", "mapping"])
def test_public_invoke_revoked_during_wait_has_zero_downstream_calls(oauth_http, monkeypatch, lock_kind, change):
    env, state = oauth_http, oauth_http.state
    admin, _, _ = state.auth_store.login(username=env.users["admin"]["username"], password=PASSWORD)
    manifest = state.mcp_runtime._servers["A"].manifest
    state.mcp_config_store.save_config(manifest.model_dump(exclude={"manifest_path"}))
    group = state.mcp_group_service.save(McpGroupCreate(**draft(members=["A"])), admin)
    actor = verified_actor(env)
    state.access_store.save_grant(subject_type="user", subject_id=actor.id, server_id=logical_service_id(group["id"]),
        permission_type_code="read", created_by=admin.id)
    catalog = state.tool_catalog
    page = catalog.call("gate_catalog_search", {"group_id": group["id"], "query": "read"}, actor).output
    described = catalog.call("gate_tool_describe", {"tool_ref": page["tools"][0]["tool_ref"], "instance_id": "A"}, actor).output
    selection = {key: described[key] for key in ("tool_ref", "instance_id", "schema_revision")}
    session = catalog.call("gate_instance_session_open", selection, actor).output
    body = {**selection, "session_id": session["session_id"], "arguments": {}}
    entered, done = Event(), Event()
    results, failures = [], []
    original = state.mcp_runtime.route_instance_guard
    @contextmanager
    def observed(instance):
        entered.set()
        with original(instance) as generation:
            yield generation
    if lock_kind == "runtime":
        monkeypatch.setattr(state.mcp_runtime, "route_instance_guard", observed)
    def worker():
        if lock_kind == "config":
            entered.set()
        try:
            results.append(catalog.call("gate_tool_invoke", body, actor, refresh_principal=lambda: actor))
        except Exception as error:
            failures.append(error)
        finally:
            done.set()
    lock = state.mcp_config_store.mutation_lock if lock_kind == "config" else state.mcp_runtime._servers["A"].lock
    with lock:
        thread = Thread(target=worker)
        thread.start()
        assert entered.wait(2) and not done.wait(.05)
        store = state.external_connection_store
        config = store.config()
        payload = {key: value for key, value in config.items() if key not in {"revision", "updated_at"}}
        if change == "client":
            payload["client_allowlist"] = ["other-synthetic-client"]
        else:
            payload["resource_mappings"] = [[CANONICAL, CANONICAL]]
        store.save_config(payload, config["revision"])
    thread.join(timeout=4)
    assert done.is_set() and not results
    assert len(failures) == 1 and isinstance(failures[0], ToolExecutionError)
    assert failures[0].code == "group_connection_invalid"
    assert not env.calls

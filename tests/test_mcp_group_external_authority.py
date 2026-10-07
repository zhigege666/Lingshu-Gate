"""Verified external claims are rechecked after configuration/runtime lock waits."""
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from threading import Event, Thread

import pytest
from starlette.requests import Request

from lingshu_gate.application.tool_authority import current_tool_principal
from lingshu_gate.domain.mcp_group_routing import GroupToolCall, GroupToolSelection, logical_service_id
from lingshu_gate.domain.mcp_groups import McpGroupCreate, McpGroupError

from test_external_oauth_http import CANONICAL, CLIENT_ID, ISSUER, PASSWORD, TUNNEL
from test_external_oauth_http import oauth_http as oauth_http
from test_mcp_groups import draft


def verified_actor(env, **claims):
    request = Request({"type": "http", "method": "POST", "path": "/mcp", "headers":
        [(b"authorization", ("Bearer " + env.token(claims=claims)).encode())]})
    return env.state.auth_store.authenticate_mcp_request(request)


@pytest.mark.parametrize("change", ["client", "issuer", "jwks", "audience", "canonical", "invalid", "expiry", "proof"])
def test_current_external_trust_rechecks_every_verified_binding(oauth_http, change):
    env = oauth_http
    actor = verified_actor(env)
    assert actor.oauth_audiences == (TUNNEL,) and actor.oauth_resource == CANONICAL
    assert current_tool_principal(env.state.auth_store, actor).id == actor.id
    store = env.state.external_connection_store
    config = store.config()
    payload = {key: value for key, value in config.items() if key not in {"revision", "updated_at"}}
    if change == "client":
        payload["client_allowlist"] = ["other-synthetic-client"]
    elif change == "issuer":
        payload["trusted_issuers"] = ["https://other-issuer.example.test"]
        payload["issuer_jwks"] = [[payload["trusted_issuers"][0], "https://other-issuer.example.test/jwks"]]
    elif change == "jwks":
        payload["issuer_jwks"] = [[ISSUER, ISSUER + "/other-jwks"]]
    elif change == "audience":
        payload["resource_mappings"] = [[CANONICAL, CANONICAL]]
    elif change == "canonical":
        target = "https://other-gate.example.test/mcp"
        payload["endpoint"] = target
        payload["resource_mappings"] = [[TUNNEL, target], [CANONICAL, target]]
    elif change == "invalid":
        payload["endpoint"] = "http://untrusted.example.test/mcp"
    elif change == "expiry":
        actor = replace(actor, external_expires_at="2000-01-01T00:00:00+00:00")
    else:
        actor = replace(actor, oauth_audiences=())
    if change not in {"expiry", "proof"}:
        store.save_config(payload, config["revision"])
    # No configuration write implicitly revoked the active delegation.
    assert store.get_active_grant(actor.id, CLIENT_ID, datetime.now(timezone.utc))["id"] == actor.external_grant_id
    with pytest.raises(McpGroupError, match="revoked"):
        current_tool_principal(env.state.auth_store, actor)
    assert not env.calls


@pytest.mark.parametrize("lock_kind", ["config", "runtime"])
def test_client_removed_during_lock_wait_never_reaches_a_downstream_tool(oauth_http, monkeypatch, lock_kind):
    env, state = oauth_http, oauth_http.state
    admin, _, _ = state.auth_store.login(username=env.users["admin"]["username"], password=PASSWORD)
    manifest = state.mcp_runtime._servers["A"].manifest
    state.mcp_config_store.save_config(manifest.model_dump(exclude={"manifest_path"}))
    group = state.mcp_group_service.save(McpGroupCreate(**draft(members=["A"])), admin)
    actor = verified_actor(env)
    state.access_store.save_grant(subject_type="user", subject_id=actor.id, server_id=logical_service_id(group["id"]),
        permission_type_code="read", created_by=admin.id)
    router = state.mcp_group_router
    page = router.search(actor, group_id=group["id"])
    selected = GroupToolSelection(tool_ref=next(item["tool_ref"] for item in page["tools"] if item["original_tool_name"] == "read"), instance_id="A")
    session = router.open_session(actor, selected)
    call = GroupToolCall(**selected.model_dump(), session_id=session["session_id"])
    entered, done = Event(), Event()
    failures, results = [], []
    original = state.mcp_runtime.route_instance_guard

    @contextmanager
    def observed_guard(instance):
        entered.set()
        with original(instance) as generation:
            yield generation

    if lock_kind == "runtime":
        monkeypatch.setattr(state.mcp_runtime, "route_instance_guard", observed_guard)

    def worker():
        if lock_kind == "config":
            entered.set()
        try:
            with router.dispatch_guard(actor, call) as (current, target):
                results.append(state.access_store.invoke_tool(state.registry, current, target.tool_id, call.arguments,
                    expected_definition_revision=target.definition_fingerprint, allow_read_retry=False))
        except Exception as exc:
            failures.append(exc)
        finally:
            done.set()

    lock = state.mcp_config_store.mutation_lock if lock_kind == "config" else state.mcp_runtime._servers["A"].lock
    with lock:
        thread = Thread(target=worker)
        thread.start()
        assert entered.wait(2) and not done.wait(0.05)
        store = state.external_connection_store
        config = store.config()
        payload = {key: value for key, value in config.items() if key not in {"revision", "updated_at"}}
        payload["client_allowlist"] = ["other-synthetic-client"]
        store.save_config(payload, config["revision"])
        assert not store.configuration().validation_errors()
    thread.join(timeout=3)
    assert done.is_set() and not results
    assert len(failures) == 1 and isinstance(failures[0], McpGroupError)
    assert failures[0].code == "group_connection_invalid"
    assert not env.calls

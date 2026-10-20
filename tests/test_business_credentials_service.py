"""Real Gate identities and authorization with a synthetic native browser peer.

No real account, browser, network endpoint or production credential is used.
The peer returns the official CLI/MCP envelope, including hostile raw output.
"""
from __future__ import annotations

import base64
import copy
import json
import os
from dataclasses import replace
from typing import Any
from urllib.parse import quote

import pytest
from jsonschema import Draft202012Validator

from lingshu_gate.application.business_credential_adapters import ADAPTERS, BROWSER_FIELDS
from lingshu_gate.domain.business_credentials import (
    BusinessCredentialBindingCreate,
    BusinessCredentialBindingUpdate,
    BusinessCredentialCreate,
    BusinessCredentialError,
    BusinessCredentialUpdate,
)
from lingshu_gate.mcp_runtime import McpServerRuntime, McpServerState
from lingshu_gate.registry import ToolDispatchRejectedError, ToolExecutionError
from lingshu_gate.result_budget import ResultCache

GATE_PASSWORD = "Synthetic-Gate-Test-Password!"
BUSINESS_USER = "synthetic-business-account"
BUSINESS_PASSWORD = "Synthetic Business Secret/+测试"
SERVER = "synthetic-browser"
LOGIN_URL = "https://business.example.test/#/login"


def envelope(data: dict[str, Any], *, content: str | None = None, stdout: str = "", stderr: str = "") -> dict[str, Any]:
    return {"content": [{"type": "text", "text": content or json.dumps(data)}], "isError": False,
        "structuredContent": {"exitCode": 0, "stdout": stdout, "stderr": stderr,
            "response": {"success": True, "data": data}}}


def native_tools() -> list[dict[str, Any]]:
    common = {"session": {"type": "string"}, "timeoutMs": {"type": "integer"},
        "extraArgs": {"type": "array", "items": {"type": "string"}}}
    definitions = {
        "auth_save": {key: {"type": "string"} for key in (
            "name", "url", "username", "password", "usernameSelector", "passwordSelector", "submitSelector")},
        "auth_login": {"name": {"type": "string"}, "noNavigate": {"type": "boolean"}},
        "auth_delete": {"name": {"type": "string"}},
        "auth_list": {}, "auth_show": {"name": {"type": "string"}},
        "upload": {"selector": {"type": "string"}, "files": {"type": "array", "items": {"type": "string"}}},
        "eval": {"script": {"type": "string"}},
    }
    for action in ("open", "snapshot", "close", "get_url", "click", "fill", "select"):
        fields = BROWSER_FIELDS[action]
        definitions[action] = {field: {"type": "string"} for field in fields}
    definitions["close"]["all"] = {"type": "boolean"}
    definitions["click"]["newTab"] = {"type": "boolean"}
    definitions["select"]["values"] = {"type": "array", "items": {"type": "string"}}
    required = {"auth_save": ["name", "url", "username", "password"], "auth_login": ["name"],
        "auth_delete": ["name"], "open": ["url"]}
    return [{"name": "agent_browser_" + action, "description": "Synthetic native browser " + action,
        "inputSchema": {"type": "object", "properties": {**common, **fields},
            "required": required.get(action, []), "additionalProperties": False}}
        for action, fields in definitions.items()]


class BrowserPeer:
    pid = None

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.vault: dict[str, dict[str, Any]] = {}
        self.urls: dict[str, str] = {}
        self.results: dict[str, Any] = {}
        self.suppressed = False

    def suppress_payload_logging(self) -> None:
        self.suppressed = True

    def stop(self) -> None:
        pass

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        assert self.suppressed, "Secret-bearing peer calls must suppress raw transport payloads first"
        action = name.removeprefix("agent_browser_")
        self.calls.append((action, copy.deepcopy(arguments)))
        override = self.results.get(action)
        if isinstance(override, BaseException):
            raise override
        if callable(override):
            return override(arguments)
        if override is not None:
            return copy.deepcopy(override)
        if action == "auth_save":
            self.vault[arguments["name"]] = dict(arguments)
            return envelope({"saved": arguments["name"]}, stdout=BUSINESS_PASSWORD, stderr=BUSINESS_USER)
        if action == "auth_delete":
            self.vault.pop(arguments["name"], None)
            return envelope({"deleted": arguments["name"]}, stdout=BUSINESS_PASSWORD)
        if action == "open":
            self.urls[arguments["session"]] = arguments["url"]
            return envelope({"url": arguments["url"]})
        if action == "auth_login":
            assert arguments["name"] in self.vault
            assert arguments["noNavigate"] is True
            return envelope({"loggedIn": True, "name": arguments["name"]}, stdout=BUSINESS_PASSWORD)
        if action == "close":
            self.urls.pop(arguments["session"], None)
            return envelope({"closed": True})
        if action == "get_url":
            return envelope({"url": self.urls[arguments["session"]]})
        return envelope({"snapshot": "Synthetic account page"})


@pytest.fixture
def gate(tmp_path, monkeypatch):
    # These are small, trusted fixture schemas. Keep real JSON Schema checks,
    # while isolating authorization/credential behavior from worker scheduling.
    # The killable untrusted-schema budget has its own regression suite.
    monkeypatch.setattr("lingshu_gate.application.business_credentials.validate_arguments",
        lambda schema, arguments: Draft202012Validator(schema).validate(arguments))
    for name in tuple(os.environ):
        if name.startswith("LINGSHU_GATE_"):
            monkeypatch.delenv(name)
    for key, value in {"DATA_DIR": str(tmp_path), "CONFIG_DIR": str(tmp_path / "mcp.d"),
        "DB_URL": f"sqlite:///{tmp_path / 'gate.db'}", "ADMIN_USERNAME": "synthetic-admin",
        "ADMIN_PASSWORD": GATE_PASSWORD, "AUTH_ENABLED": "true"}.items():
        monkeypatch.setenv("LINGSHU_GATE_" + key, value)
    from lingshu_gate.main import create_app

    app = create_app()
    auth, access = app.state.auth_store, app.state.access_store
    auth.change_password(str(auth.list_users()[0]["id"]), GATE_PASSWORD)
    admin, _, _ = auth.login(username="synthetic-admin", password=GATE_PASSWORD)
    actors = {"admin": admin}
    for name in ("alice", "bob"):
        auth.create_user(username=name, password=GATE_PASSWORD, role="operator")
        actors[name], _, _ = auth.login(username=name, password=GATE_PASSWORD)
    configs, runtime, registry = app.state.mcp_config_store, app.state.mcp_runtime, app.state.registry
    configs.save_config({"id": SERVER, "name": "Synthetic browser", "enabled": True,
        "launch": {"type": "managed_process", "command": "agent-browser", "args": ["mcp", "--tools", "core,state"]},
        "transport": {"type": "stdio", "endpoint": ""}})
    peer = BrowserPeer()
    target = McpServerRuntime(manifest=configs.load_manifest(SERVER), state=McpServerState.RUNNING,
        client=peer, tools=native_tools())
    runtime._servers[SERVER] = target
    runtime._register_mcp_tools(target)
    tools = [tool for tool in registry.list_definitions() if tool.metadata.get("server_id") == SERVER]
    access.synchronize_tools(tools)
    for tool in tools:
        access.set_classification(server_id=SERVER, tool_id=tool.id, access="write", destructive=False,
            idempotent=False, reviewer_id=admin.id)
    access.publish_classifications(reviewer_id=admin.id, server_id=SERVER)
    for actor in (actors["alice"], actors["bob"]):
        access.save_grant(subject_type="user", subject_id=actor.id, server_id=SERVER,
            permission_type_code="write", created_by=admin.id)
    store, service = app.state.business_credential_store, app.state.business_credential_service
    yield {"app": app, "actors": actors, "auth": auth, "access": access, "store": store,
        "service": service, "runtime": runtime, "configs": configs, "registry": registry, "peer": peer, "target": target}
    app.state.external_mcp_configuration_service.shutdown()
    runtime.shutdown()


def create(gate, actor="admin", **options):
    return gate["service"].create(gate["actors"][actor], BusinessCredentialCreate.model_validate({
        "name": "Synthetic account", "environment": "test", "business_role": "physician",
        "login_url": LOGIN_URL, "username": BUSINESS_USER, "password": BUSINESS_PASSWORD, **options}))


def bind(gate, record, actor="admin", **options):
    return gate["service"].bind(gate["actors"][actor], record["id"], BusinessCredentialBindingCreate.model_validate({
        "server_id": SERVER, "confirm_managed_mode": True, **options}), record["version"])


def sync(gate, record, binding, actor="admin", **options):
    return gate["service"].synchronize(gate["actors"][actor], record["id"], binding["id"],
        record["version"], binding["revision"], **options)


def invoke(gate, action, arguments, actor="admin"):
    observed: list[dict[str, Any]] = []
    dispatched = []
    tool = gate["registry"].get_definition(f"mcp.{SERVER}.agent_browser_{action}")
    result = gate["service"].invoke(gate["actors"][actor], tool, arguments,
        arguments_guard=lambda values: observed.append(copy.deepcopy(values)),
        dispatch_started=lambda: dispatched.append(True))
    return result, observed, dispatched


def login(gate, record, actor="admin", session="work"):
    return invoke(gate, "auth_login", {"name": record["credential_ref"], "session": session}, actor)


def ready(gate, **options):
    record = create(gate, **options)
    binding = sync(gate, record, bind(gate, record))
    assert binding["sync_status"] == "synced"
    return record, binding


def update(gate, record, actor="admin", **options):
    values = {key: record[key] for key in ("name", "environment", "business_role", "login_url", "enabled", "allow_http",
        "allowed_user_ids", "allowed_role_ids", "selectors")}
    return gate["service"].update(gate["actors"][actor], record["id"],
        BusinessCredentialUpdate.model_validate({**values, "expected_version": record["version"], **options}))


def assert_denied(code, action):
    with pytest.raises((BusinessCredentialError, ToolExecutionError)) as exc:
        action()
    assert exc.value.code == code


def test_sync_and_login_return_only_references_and_safe_receipts(gate):
    record, binding = ready(gate)
    assert gate["peer"].calls[0] == ("auth_save", {"name": binding["profile_name"], "url": LOGIN_URL,
        "username": BUSINESS_USER, "password": BUSINESS_PASSWORD})
    result, audited, dispatched = login(gate, record)
    public = json.dumps({"credential": record, "binding": binding, "result": result, "audited": audited})
    assert BUSINESS_USER not in public and BUSINESS_PASSWORD not in public
    summary = json.loads(result["content"][0]["text"])
    assert summary == {"status": "login_executed", "credential_ref": record["credential_ref"],
        "session": "work", "authentication_verified": False}
    assert [action for action, _ in gate["peer"].calls] == ["auth_save", "open", "auth_login"]
    assert audited == [{"name": record["credential_ref"], "session": "work"}] * 2
    assert len(dispatched) == 2
    native_session = gate["peer"].calls[-1][1]["session"]
    assert native_session.startswith("gate_") and native_session != "work"
    assert gate["peer"].calls[-2][1]["session"] == native_session


def test_sync_uses_the_real_schema_validation_worker(gate, monkeypatch):
    from lingshu_gate.application import schema_validation

    # Exercise the subprocess boundary once. Its production two-second budget
    # is tested separately; allow shared-CI process startup time in this case.
    monkeypatch.setattr(schema_validation, "VALIDATION_SECONDS", 10.0)
    monkeypatch.setattr("lingshu_gate.application.business_credentials.validate_arguments",
        schema_validation.validate_arguments)
    _, binding = ready(gate)
    assert binding["sync_status"] == "synced"
    assert len(gate["peer"].calls) == 1


def test_personal_account_cannot_be_read_bound_or_used_by_another_user(gate):
    bootstrap = create(gate)
    bind(gate, bootstrap)
    record = create(gate, "alice")
    binding = sync(gate, record, bind(gate, record, "alice"), "alice")
    assert binding["sync_status"] == "synced"
    calls = len(gate["peer"].calls)
    assert_denied("credential_not_found", lambda: gate["service"].detail(record["id"], gate["actors"]["bob"]))
    assert_denied("credential_not_found", lambda: bind(gate, record, "bob"))
    assert_denied("credential_not_found", lambda: login(gate, record, "bob"))
    assert len(gate["peer"].calls) == calls
    assert not gate["service"].list(gate["actors"]["bob"], "personal")["credentials"]


def test_shared_credential_grant_does_not_grant_tools_or_expand_user_scope(gate):
    record, _ = ready(gate, scope="shared", allowed_user_ids=[gate["actors"]["alice"].id])
    assert_denied("credential_not_found", lambda: login(gate, record, "bob"))
    gate["access"].save_grant(subject_type="user", subject_id=gate["actors"]["alice"].id, server_id=SERVER,
        tool_id=f"mcp.{SERVER}.agent_browser_auth_login", permission_type_code="none", created_by=gate["actors"]["admin"].id)
    calls = len(gate["peer"].calls)
    assert_denied("credential_tool_denied", lambda: login(gate, record, "alice"))
    # Navigation may run under its own grant; no password-consuming login may run.
    assert all(action != "auth_login" for action, _ in gate["peer"].calls[calls:])


def test_shared_role_membership_is_checked_again_for_existing_browser_sessions(gate):
    role = gate["access"].save_role(code="synthetic_physicians", name="Synthetic physicians",
        description="Business credential test role", permissions=[])
    alice = gate["actors"]["alice"]
    gate["access"].set_user_roles(alice.id, ["operator", role["code"]])
    record, _ = ready(gate, scope="shared", allowed_role_ids=[role["id"]])
    assert_denied("credential_not_found", lambda: login(gate, record, "bob"))
    login(gate, record, "alice")
    gate["access"].set_user_roles(alice.id, ["operator"])
    calls = len(gate["peer"].calls)
    assert_denied("credential_not_found", lambda: invoke(gate, "snapshot", {"session": "work"}, "alice"))
    assert len(gate["peer"].calls) == calls


def test_same_logical_session_isolated_by_user_and_authorization_connection(gate):
    record, _ = ready(gate, scope="shared", allowed_user_ids=[gate["actors"][name].id for name in ("alice", "bob")])
    login(gate, record, "alice")
    login(gate, record, "bob")
    first = [values["session"] for action, values in gate["peer"].calls if action == "auth_login"]
    assert len(set(first)) == 2
    actor, _, _ = gate["auth"].login(username="alice", password=GATE_PASSWORD)
    gate["actors"]["alice"] = actor
    login(gate, record, "alice")
    sessions = [values["session"] for action, values in gate["peer"].calls if action == "auth_login"]
    assert len(set(sessions)) == 3
    invoke(gate, "snapshot", {"session": "work"}, "alice")
    assert gate["peer"].calls[-1][1]["session"] == sessions[-1]


def test_managed_mode_requires_admin_controls_and_explicit_confirmation(gate):
    personal = create(gate, "alice")
    assert_denied("credential_permission_denied", lambda: bind(gate, personal, "alice"))
    record = create(gate)
    assert_denied("managed_mode_confirmation_required", lambda: bind(gate, record, confirm_managed_mode=False))
    assert not gate["store"].is_managed_server(SERVER)
    assert not gate["peer"].calls


@pytest.mark.parametrize("action,arguments", [
    ("auth_save", {"name": "unmanaged", "url": LOGIN_URL, "username": "not-a-secret", "password": "not-a-secret"}),
    ("auth_list", {}), ("auth_show", {"name": "unmanaged"}), ("auth_delete", {"name": "unmanaged"}),
    ("upload", {"selector": "input", "files": ["/home/example/.agent-browser/auth/profile.json"]}),
    ("eval", {"script": "document.cookie"}),
])
def test_raw_vault_and_host_or_code_tools_are_rejected(gate, action, arguments):
    record, _ = ready(gate)
    login(gate, record)
    calls = len(gate["peer"].calls)
    assert_denied("managed_browser_tool_denied", lambda: invoke(gate, action, {"session": "work", **arguments}))
    assert len(gate["peer"].calls) == calls


@pytest.mark.parametrize("action,arguments", [
    ("snapshot", {"extraArgs": ["--session", "foreign"]}),
    ("snapshot", {"cdp": "http://localhost:9222"}),
    ("snapshot", {"profile": "/home/another-user"}),
    ("snapshot", {"timeoutMs": True}),
    ("close", {"all": True}),
    ("open", {"url": "https://unbound.example.test/"}),
])
def test_process_overrides_global_close_and_unbound_origins_never_dispatch(gate, action, arguments):
    record, _ = ready(gate)
    login(gate, record)
    calls = len(gate["peer"].calls)
    with pytest.raises(ToolDispatchRejectedError):
        invoke(gate, action, {"session": "work", **arguments})
    assert len(gate["peer"].calls) == calls


@pytest.mark.parametrize("action,arguments", [
    ("select", {"selector": "select", "values": ["ok", "--session", "other"]}),
    ("fill", {"selector": "input", "text": "--cdp"}),
    ("click", {"selector": "--profile=/home/another-user"}),
])
def test_native_positional_option_injection_never_dispatches(gate, action, arguments):
    record, _ = ready(gate)
    login(gate, record)
    calls = len(gate["peer"].calls)
    with pytest.raises(ToolDispatchRejectedError):
        invoke(gate, action, {"session": "work", **arguments})
    assert len(gate["peer"].calls) == calls


def test_every_reviewed_browser_field_rejects_options_recursively():
    adapter = ADAPTERS["agent_browser"]
    for action, fields in BROWSER_FIELDS.items():
        for field in fields:
            for value in ("--session", ["ok", "--cdp"], {"nested": ["ok", "--profile"]}):
                with pytest.raises(BusinessCredentialError):
                    adapter.browser_arguments(action, {"session": "work", field: value},
                        native_session="gate_" + "a" * 32, login_url=LOGIN_URL)


@pytest.mark.parametrize("options", [
    {"username": "--session"},
    {"selectors": {"username": "--cdp"}},
    {"selectors": {"password": "--profile"}},
    {"selectors": {"submit": "--session=foreign"}},
])
def test_secret_save_rejects_native_option_values_before_peer_io(gate, options):
    record = create(gate, **options)
    binding = bind(gate, record)
    assert_denied("browser_option_value_denied", lambda: sync(gate, record, binding))
    current = gate["store"].get_binding(binding["id"])
    assert current["sync_status"] == "pending" and not current["remote_copy_possible"]
    assert not gate["peer"].calls


def test_password_stdin_can_contain_a_leading_hyphen(gate):
    record, binding = ready(gate, password="--cdp")
    assert binding["sync_status"] == "synced"
    assert gate["peer"].calls[0][1]["password"] == "--cdp"
    assert "--cdp" not in json.dumps(record)


def test_login_requires_reference_explicit_session_and_synchronized_version(gate):
    record = create(gate)
    binding = bind(gate, record)
    assert_denied("browser_session_required", lambda: invoke(gate, "auth_login", {"name": record["credential_ref"]}))
    assert_denied("credential_reference_required", lambda: invoke(gate, "auth_login", {"name": binding["profile_name"], "session": "work"}))
    assert_denied("credential_reference_required", lambda: invoke(gate, "auth_login", {
        "name": record["credential_ref"], "session": "work", "extraArgs": ["--url", "https://foreign.example.test"]}))
    assert_denied("credential_sync_required", lambda: login(gate, record))
    assert not gate["peer"].calls


def test_open_redirect_to_other_origin_prevents_login_and_keeps_unknown_session(gate):
    record, _ = ready(gate)
    gate["peer"].results["open"] = envelope({"url": "https://foreign.example.test/login"})
    assert_denied("credential_origin_unverified", lambda: login(gate, record))
    assert [action for action, _ in gate["peer"].calls] == ["auth_save", "open"]
    rows = gate["service"].sessions(gate["actors"]["admin"], record["id"])["sessions"]
    assert len(rows) == 1 and rows[0]["status"] == "unknown"


def test_rotation_stales_sessions_and_cleanup_still_works_when_disabled(gate):
    record, binding = ready(gate)
    login(gate, record)
    current = update(gate, record, password="Rotated synthetic password")
    assert_denied("browser_session_stale", lambda: invoke(gate, "snapshot", {"session": "work"}))
    assert_denied("credential_sync_required", lambda: login(gate, current, session="new"))
    disabled = update(gate, current, enabled=False)
    gate["service"].update_binding(gate["actors"]["admin"], disabled["id"], binding["id"],
        BusinessCredentialBindingUpdate(expected_version=disabled["version"],
            expected_revision=gate["store"].get_binding(binding["id"])["revision"], enabled=False))
    invoke(gate, "close", {"session": "work"})
    state = gate["service"].sessions(gate["actors"]["admin"], record["id"])["sessions"][0]
    assert state["status"] == "closed"


def test_raw_stdout_stderr_and_known_secret_echoes_are_not_model_output(gate):
    record, _ = ready(gate)
    login(gate, record)
    echoes = [BUSINESS_PASSWORD, BUSINESS_USER, quote(BUSINESS_PASSWORD, safe=""),
        base64.b64encode(BUSINESS_PASSWORD.encode()).decode(), json.dumps(BUSINESS_PASSWORD, ensure_ascii=True)[1:-1]]
    gate["peer"].results["snapshot"] = envelope({"snapshot": " | ".join(echoes)}, content="untrusted-CLI-envelope",
        stdout="raw-command-secret", stderr="raw-error-secret")
    result, _, _ = invoke(gate, "snapshot", {"session": "work"})
    serialized = json.dumps(result, ensure_ascii=False)
    visible_snapshot = json.loads(result["content"][0]["text"])["snapshot"]
    for echo in echoes:
        assert echo not in serialized
        assert echo not in visible_snapshot
    assert "raw-command-secret" not in serialized and "raw-error-secret" not in serialized
    assert "untrusted-CLI-envelope" not in serialized
    assert "structuredContent" not in result
    assert "[REDACTED]" in serialized


def test_model_output_is_derived_only_from_verified_response_data(gate):
    record, _ = ready(gate)
    login(gate, record)
    safe_data = {"snapshot": "Clean page content", "url": LOGIN_URL}
    gate["peer"].results["snapshot"] = envelope(safe_data,
        content="sensitive CLI framing " + BUSINESS_PASSWORD,
        stdout="sensitive command line " + BUSINESS_USER, stderr="sensitive stderr " + BUSINESS_PASSWORD)
    result, _, _ = invoke(gate, "snapshot", {"session": "work"})
    assert result.keys() == {"content", "isError"} and result["isError"] is False
    assert len(result["content"]) == 1 and result["content"][0]["type"] == "text"
    assert json.loads(result["content"][0]["text"]) == safe_data


def test_reenabled_binding_does_not_revive_older_browser_authority(gate):
    record, binding = ready(gate)
    login(gate, record)
    for enabled in (False, True):
        binding = gate["service"].update_binding(gate["actors"]["admin"], record["id"], binding["id"],
            BusinessCredentialBindingUpdate(expected_version=record["version"],
                expected_revision=binding["revision"], enabled=enabled))
    assert binding["sync_status"] == "synced" and binding["enabled"]
    calls = len(gate["peer"].calls)
    assert_denied("browser_session_stale", lambda: invoke(gate, "snapshot", {"session": "work"}))
    assert len(gate["peer"].calls) == calls
    invoke(gate, "close", {"session": "work"})
    login(gate, record)


def test_ambiguous_or_exceptional_sync_never_claims_success_or_allows_record_deletion(gate):
    record = create(gate)
    binding = bind(gate, record)
    gate["peer"].results["auth_save"] = RuntimeError("remote echo " + BUSINESS_PASSWORD)
    unknown = sync(gate, record, binding)
    assert unknown["sync_status"] == "unknown" and unknown["remote_copy_possible"]
    assert unknown["last_error_code"] == "downstream_unknown"
    assert BUSINESS_PASSWORD not in json.dumps(unknown, ensure_ascii=False)
    assert_denied("remote_copy_cleanup_required", lambda: gate["service"].delete(
        gate["actors"]["admin"], record["id"], record["version"]))
    gate["peer"].results["auth_delete"] = envelope({"deleted": "some-other-profile"})
    still_unknown = sync(gate, record, unknown, delete_remote=True)
    assert still_unknown["remote_copy_possible"] and still_unknown["sync_status"] == "unknown"


def test_deleting_vault_copy_does_not_report_closed_browser_or_website_logout(gate):
    record, binding = ready(gate)
    login(gate, record)
    removed = sync(gate, record, binding, delete_remote=True)
    assert removed["sync_status"] == "deleted"
    assert gate["service"].sessions(gate["actors"]["admin"], record["id"])["sessions"][0]["status"] == "active"
    assert_denied("browser_session_cleanup_required", lambda: gate["service"].delete(
        gate["actors"]["admin"], record["id"], record["version"]))
    session = gate["service"].sessions(gate["actors"]["admin"], record["id"])["sessions"][0]
    closed = gate["service"].close_session(gate["actors"]["admin"], record["id"], session["id"])
    assert closed == {"status": "closed", "website_logout_verified": False}
    gate["service"].delete(gate["actors"]["admin"], record["id"], record["version"])
    assert gate["store"].is_managed_server(SERVER)


def test_interrupted_close_records_uncertainty_without_echoing_transport_errors(gate):
    record, _ = ready(gate)
    login(gate, record)
    gate["peer"].results["close"] = RuntimeError("remote close echo " + BUSINESS_PASSWORD)
    with pytest.raises(ToolExecutionError) as exc:
        invoke(gate, "close", {"session": "work"})
    assert BUSINESS_PASSWORD not in str(exc.value)
    state = gate["service"].sessions(gate["actors"]["admin"], record["id"])["sessions"][0]
    assert state["status"] == "unknown"
    # An uncertain close remains safely retryable through the cleanup path.
    gate["peer"].results.pop("close")
    result = gate["service"].close_session(gate["actors"]["admin"], record["id"], state["id"])
    assert result == {"status": "closed", "website_logout_verified": False}


def test_changed_tool_contract_stops_password_transfer(gate):
    record = create(gate)
    binding = bind(gate, record)
    tool = gate["registry"].get_definition(f"mcp.{SERVER}.agent_browser_auth_save")
    gate["registry"].update_definition(tool.model_copy(update={"description": "Changed downstream contract"}))
    assert_denied("credential_contract_changed", lambda: sync(gate, record, binding))
    assert not gate["peer"].calls


def test_revoked_connection_cannot_use_previously_allowed_credential(gate):
    record, _ = ready(gate)
    admin = gate["actors"]["admin"]
    gate["app"].state.database.execute("DELETE FROM auth_sessions WHERE id=?", (admin.session_id,))
    assert_denied("credential_authority_changed", lambda: login(gate, record))
    assert [action for action, _ in gate["peer"].calls] == ["auth_save"]


def test_identity_or_target_scope_never_comes_from_tool_arguments(gate):
    record, _ = ready(gate)
    assert_denied("credential_reference_required", lambda: invoke(gate, "auth_login", {
        "name": record["credential_ref"], "session": "work", "owner_id": gate["actors"]["admin"].id}, "bob"))
    denied_actor = replace(gate["actors"]["admin"], delegated_scopes=("tools.read",))
    gate["actors"]["admin"] = denied_actor
    assert_denied("credential_tool_denied", lambda: login(gate, record))


def test_managed_browser_results_cannot_create_or_reuse_generic_result_cache(gate):
    cache = ResultCache(gate["registry"], gate["access"], None)
    actor = gate["actors"]["admin"]
    tool_id = f"mcp.{SERVER}.agent_browser_snapshot"
    target = cache.capture(actor, tool_id)
    assert target is not None and cache.validate_target(actor, target)
    record = create(gate)
    bind(gate, record)
    assert cache.capture(actor, tool_id) is None
    assert not cache.validate_target(actor, target)


def test_business_bindings_reject_http_targets_with_per_user_transport_routes(gate):
    manifest = gate["target"].manifest.model_dump(mode="json", exclude={"manifest_path"})
    manifest.update(launch={"type": "external"},
        transport={"type": "streamable_http", "endpoint": "https://browser.example.test/mcp"},
        user_credentials=[{"id": "routing-key", "name": "Synthetic user-specific routing", "required": True,
            "injection": {"type": "http_header", "name": "X-User-Route", "template": "{value}"}}])
    gate["configs"].save_config(manifest, overwrite=True)
    gate["target"].manifest = gate["configs"].load_manifest(SERVER)
    record = create(gate)
    assert_denied("credential_target_user_routing", lambda: bind(gate, record))
    assert not gate["store"].is_managed_server(SERVER)
    assert not gate["peer"].calls


def test_final_dispatch_cannot_bypass_a_newly_enabled_managed_target(gate):
    record = create(gate)
    activated = []
    # Permit the ordinary peer path so a missing final guard really reaches it;
    # a fake transport logging assertion must not mask an authorization bug.
    gate["peer"].suppressed = True

    def activate_at_final_guard():
        if not activated:
            activated.append(bind(gate, record))

    response = gate["access"].invoke_tool(gate["registry"], gate["actors"]["admin"],
        f"mcp.{SERVER}.agent_browser_auth_show", {"name": "preexisting-profile", "session": "work"},
        dispatch_guard=activate_at_final_guard)
    assert activated and gate["store"].is_managed_server(SERVER)
    assert response.ok is False
    assert response.output["error"]["code"] == "credential_target_changed"
    assert not gate["peer"].calls

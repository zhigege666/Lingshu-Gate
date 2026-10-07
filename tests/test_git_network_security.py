"""Offline policy/contract tests. No real Git, proxy, dependency or SSH operation."""

from __future__ import annotations

import io
import json
import stat
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import zipfile

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.build_deploy import LocalExecutionBlocked
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.credential_store import CredentialStore
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.git_import_mcp import GitImportService, ProxyTest
from lingshu_gate.git_source import GitSourceInput, repository_rule, snapshot_inventory, validate_resolved_addresses, verify_git_snapshot
from lingshu_gate.interfaces.control_api.network_routes import register_network_routes
from lingshu_gate.network_settings import NetworkDefaults, NetworkSelection, NetworkSettingsStore, ProfileWrite
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.ports.safe_network_executor import REQUIRED_CAPABILITIES, SafeExecutionCancelled, require_proxy_support, require_safe_executor
from lingshu_gate.project_delivery_mcp import ProjectDeliveryMcpService
from lingshu_gate.project_uploads import ProjectUploadStore
from lingshu_gate.registry import ToolExecutionError, ToolInvocationContext

SHA = "a" * 40
URL = "https://github.com/example/repository.git"


def archive(entries: dict[str, bytes]) -> bytes:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w", compression=zipfile.ZIP_DEFLATED) as zipped:
        for name, data in entries.items():
            zipped.writestr(name, data)
    return content.getvalue()


class Queue:
    def __init__(self):
        self.jobs = []

    def submit(self, action, *args):
        self.jobs.append((action, args))

    def run(self):
        action, args = self.jobs.pop(0)
        action(*args)


class FakeExecutor:
    capabilities = REQUIRED_CAPABILITIES
    proxy_schemes = {"git": frozenset({"http", "https", "socks5", "socks5h"}), "npm": frozenset({"http", "https"}), "python": frozenset({"http", "https"})}

    def __init__(self):
        self.export_error = None
        self.resolve_error = None
        self.commit = SHA
        self.exports = []
        self.probes = []
        self.content = archive({"package.json": b'{"name":"example","bin":{"example":"bin/ssh-mcp.mjs"}}', "bin/ssh-mcp.mjs": b"export {};"})

    def resolve_commit(self, request, **kwargs):
        if self.resolve_error:
            raise self.resolve_error
        return self.commit

    def export_snapshot(self, request, **kwargs):
        self.exports.append(json.loads(json.dumps(request)))
        if self.export_error:
            raise self.export_error
        return self.content

    def probe(self, target, **kwargs):
        self.probes.append((target, kwargs))
        return {"ok": True, "body": "must not be returned", "headers": {"token": "must not be returned"}}


@pytest.fixture
def services(tmp_path):
    database = SQLiteDatabase("", tmp_path)
    audit = ObservabilityStore(database)
    credentials = CredentialStore(tmp_path)
    network = NetworkSettingsStore(database, tmp_path, credentials, audit)
    uploads = ProjectUploadStore(database, tmp_path)
    queue = Queue()
    delivery = ProjectDeliveryMcpService(database, tmp_path, uploads, SimpleNamespace(executor=queue, _require_local_execution=lambda operation: None), None, None, audit)
    executor = FakeExecutor()
    imports = GitImportService(delivery, network, executor=executor)
    context = ToolInvocationContext(actor_id="actor-one", username="operator", auth_type="session", token_id=None, correlation_id="correlation", permissions=("operations.manage", "network.use", "tools.invoke"))
    return SimpleNamespace(database=database, network=network, credentials=credentials, audit=audit, uploads=uploads, queue=queue, delivery=delivery, executor=executor, imports=imports, context=context, root=tmp_path)


@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "git://github.com/example/repo", "ext::sh -c whoami", "git@github.com:example/repo",
    "ssh://git@github.com/example/repo", "https://user:password@github.com/example/repo", "https://github.com/example/repo?token=x",
    "https://github.com/example/repo#token=x", "https://github.com/example/%2e%2e/repo", "https://github.com/example/../repo",
    "https://github.com/example\\repo", "https://github.com/example/repo\n--config=x", "https://github.com/",
])
def test_git_protocol_url_and_credential_injection_rejected(url):
    with pytest.raises(ValidationError):
        GitSourceInput(repository_url=url)


@pytest.mark.parametrize("ref", ["--upload-pack=sh", "HEAD~1", "branch..bad", "a:b", "a@{1}", "a//b", "x.lock", ".hidden", "a/.hidden", "a\nb"])
def test_git_ref_injection_rejected(ref):
    with pytest.raises(ValidationError):
        GitSourceInput(repository_url=URL, ref=ref)


@pytest.mark.parametrize("root", ["../secret", "/etc", "C:/users", "a/../../b", "a\\b", "a//b", ".git/hooks"])
def test_project_subdirectory_escape_rejected(root):
    with pytest.raises(ValidationError):
        GitSourceInput(repository_url=URL, project_root=root)


@pytest.mark.parametrize("value", ["a" * 7, "A" * 40, "-" + SHA, SHA + "^{commit}"])
def test_commit_must_be_exact_full_sha(value):
    with pytest.raises(ValidationError):
        GitSourceInput(repository_url=URL, ref_type="commit", ref=value)


def test_core_role_blocks_git_resolution_import_and_probe_even_with_fake_executor(services):
    def deny(operation):
        raise LocalExecutionBlocked(operation, "core")
    services.delivery.builds._require_local_execution = deny
    response = services.imports.plan({"repository_url": URL}, services.context)
    assert response["status"] == "blocked"
    assert services.executor.exports == []
    assert not services.queue.jobs


def test_explicit_host_policy_and_private_dns_are_required():
    with pytest.raises(ToolExecutionError, match="host/port"):
        repository_rule("https://git.example.invalid/project/repository", NetworkDefaults().model_dump()["git_hosts"])
    rule = {"host": "git.example.invalid", "port": 443, "private_cidrs": ["10.20.0.0/16"]}
    validate_resolved_addresses(rule, ["10.20.1.4"])
    for addresses in (["10.21.1.4"], ["127.0.0.1"], ["169.254.169.254"], ["::ffff:127.0.0.1"], ["100.100.100.200"], ["93.184.216.34", "10.21.1.4"]):
        with pytest.raises(ValueError):
            validate_resolved_addresses(rule, addresses)


@pytest.mark.parametrize("entry", ["../file", "/file", ".env", ".ssh/id_ed25519", ".npmrc", "source/secret.pem"])
def test_snapshot_path_and_sensitive_file_rejection(entry):
    with pytest.raises(ValueError):
        snapshot_inventory(archive({entry: b"secret"}), ".")


def test_snapshot_links_submodules_lfs_and_possible_tokens_rejected():
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as zipped:
        link = zipfile.ZipInfo("link")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        zipped.writestr(link, "../../secret")
    with pytest.raises(ValueError):
        snapshot_inventory(stream.getvalue(), ".")
    for name, data in [(".gitmodules", b"[submodule]"), ("pointer", b"version https://git-lfs.github.com/spec/v1\n"), ("secret", b"-----BEGIN PRIVATE KEY-----")]:
        with pytest.raises(ValueError):
            snapshot_inventory(archive({name: data}), ".")


def test_compressed_network_material_and_resource_limits_rejected():
    with pytest.raises(ValueError, match="network material"):
        snapshot_inventory(archive({"file": b"http://proxy.example.invalid:8080"}), ".", forbidden_values=["http://proxy.example.invalid:8080"])
    content = archive({"a": b"a", "b": b"b"})
    with patch("lingshu_gate.git_source.MAX_FILES", 1), pytest.raises(ValueError, match="file count"):
        snapshot_inventory(content, ".")
    with patch("lingshu_gate.git_source.MAX_EXTRACTED_BYTES", 1), pytest.raises(ValueError, match="expanded"):
        snapshot_inventory(content, ".")
    with patch("lingshu_gate.git_source.MAX_ZIP_BYTES", 1), pytest.raises(ValueError, match="compressed"):
        snapshot_inventory(content, ".")


def profile(services, scheme="http"):
    return services.network.save_profile(ProfileWrite(name="Example network", endpoint=f"{scheme}://proxy.example.invalid:8080"), "admin")


def test_profile_values_encrypted_redacted_audited_and_cas_protected(services):
    saved = profile(services)
    response = json.dumps(services.network.profiles())
    assert "proxy.example.invalid" not in response
    assert '"endpoint_masked": "***"' in response
    raw = (services.root / "private-network-profiles" / "credentials.json").read_text()
    assert "proxy.example.invalid" not in raw
    assert "proxy.example.invalid" not in json.dumps([dict(row) for row in services.database.query_all("SELECT * FROM events")])
    with pytest.raises(ToolExecutionError) as error:
        services.network.save_profile(ProfileWrite(name="Other", endpoint="http://other.example.invalid:8080", expected_version=0), "admin", saved["id"])
    assert error.value.code == "network_version_conflict"
    assert services.network.profiles()[0]["version"] == 1


def test_inherit_direct_profile_and_pinned_revision_semantics(services):
    saved = profile(services)
    pick = NetworkSelection(mode="profile", profile_id=saved["id"], version=1)
    services.network.save_defaults(NetworkDefaults(git=pick), 0, "admin")
    frozen = services.network.freeze(NetworkSelection(), NetworkSelection())
    assert frozen["git"]["version"] == 1 and frozen["install"]["mode"] == "direct"
    assert services.network.resolve({"mode": "direct"}, "git")["mode"] == "direct"
    services.network.retain(frozen, "queued", "task")
    services.network.save_profile(ProfileWrite(name="Changed", endpoint="https://other.example.invalid:443", enabled=False, expected_version=1), "admin", saved["id"])
    services.network.validate_frozen(frozen)
    assert services.network.execution_material(frozen, "git")["proxy"] == "http://proxy.example.invalid:8080"
    with pytest.raises(ToolExecutionError) as blocked:
        services.network.resolve({"mode": "inherit"}, "git")
    assert blocked.value.code == "network_profile_disabled"
    with pytest.raises(ToolExecutionError) as blocked:
        services.network.delete_profile(saved["id"], 2, "admin")
    assert blocked.value.code == "network_profile_in_use"


def test_registry_index_separate_from_proxy_and_defaults_cas(services):
    saved = profile(services)
    body = NetworkDefaults(install=NetworkSelection(mode="profile", profile_id=saved["id"]), npm_registry="https://registry.example.invalid/", python_index="https://index.example.invalid/simple/")
    configured = services.network.save_defaults(body, 0, "admin")
    assert configured["defaults"]["install"]["profile_id"] == saved["id"]
    assert configured["defaults"]["npm_registry"] == body.npm_registry
    with pytest.raises(ToolExecutionError) as error:
        services.network.save_defaults(NetworkDefaults(), 0, "admin")
    assert error.value.code == "network_version_conflict"


def test_changed_credential_reference_fails_closed(services):
    services.credentials.save_credential(name="Repository", value="first-value", credential_id="repo")
    prepared = services.imports.plan({"repository_url": URL, "credential_ref": "repo"}, services.context)
    services.credentials.save_credential(name="Repository", value="second-value", credential_id="repo")
    with pytest.raises(ToolExecutionError) as error:
        services.imports.create({"plan_id": prepared["plan_id"], "plan_digest": prepared["plan_digest"], "idempotency_key": "changed-credential-001", "confirmed": True}, services.context)
    assert error.value.code == "git_credential_changed"
    assert not services.queue.jobs


def test_missing_safe_executor_does_not_call_host_git_or_queue(services):
    services.imports.executor = None
    with patch("subprocess.Popen") as process, patch("subprocess.run") as run:
        planned = services.imports.plan({"repository_url": URL}, services.context)
    assert planned["status"] == "blocked" and planned["commit_sha"] is None
    assert planned["error"]["code"] == "safe_executor_unavailable"
    process.assert_not_called()
    run.assert_not_called()
    assert not services.queue.jobs
    with pytest.raises(ToolExecutionError):
        require_safe_executor(SimpleNamespace(capabilities=frozenset()))


def test_exact_commit_plan_snapshot_and_reanalysis_preserve_provenance(services):
    planned = services.imports.plan({"repository_url": URL}, services.context)
    body = {"plan_id": planned["plan_id"], "plan_digest": planned["plan_digest"], "idempotency_key": "git-source-import-001", "confirmed": True}
    created = services.imports.create(body, services.context)
    replay = services.imports.create(body, services.context)
    assert replay["import_id"] == created["import_id"] and len(services.queue.jobs) == 1
    services.executor.commit = "b" * 40  # Moving ref cannot change the acquired plan.
    services.queue.run()
    result = services.imports.status({"import_id": created["import_id"]}, services.context)
    assert result["status"] == "success"
    assert services.executor.exports[0]["commit_sha"] == SHA
    analysis = services.uploads.get_upload(result["upload_id"])["analysis"]
    assert analysis["git_source"]["commit_sha"] == SHA
    assert len(analysis["source_sha256"]) == len(analysis["file_list_sha256"]) == 64
    assert services.uploads.analyze_upload(result["upload_id"])["analysis"]["delivery_network"] == analysis["delivery_network"]
    owner = services.database.query_one("SELECT owner_id FROM project_delivery_resource_owners WHERE resource_id=?", (result["upload_id"],))
    assert owner[0] == services.context.actor_id


@pytest.mark.parametrize("selected_root", [".", "repository", "repository/nested"])
def test_git_reanalysis_keeps_explicit_inventory_root_and_detects_real_changes(services, selected_root):
    services.executor.content = archive({
        "README.md": b"Repository overview",
        "repository/nested/package.json": b'{"name":"example","bin":{"example":"bin/server.mjs"}}',
        "repository/nested/bin/server.mjs": b"export {};",
    })
    planned = services.imports.plan({"repository_url": URL, "project_root": selected_root}, services.context)
    created = services.imports.create({"plan_id": planned["plan_id"], "plan_digest": planned["plan_digest"], "idempotency_key": "nested-root-import-001", "confirmed": True}, services.context)
    services.queue.run()
    result = services.imports.status({"import_id": created["import_id"]}, services.context)
    assert result["status"] == "success"
    before = services.uploads.get_upload(result["upload_id"])
    verify_git_snapshot(before)
    after = services.uploads.analyze_upload(result["upload_id"])
    assert after["root_dir"] == before["root_dir"]
    assert after["analysis"]["project_root_dir"] == before["root_dir"]
    for field in ("git_source", "included_files", "file_list_sha256", "source_sha256", "delivery_network"):
        assert after["analysis"][field] == before["analysis"][field]
    verify_git_snapshot(after)
    entrypoint = next(Path(after["root_dir"]).rglob("server.mjs"))
    entrypoint.write_text("export const changed = true;")
    with pytest.raises(ToolExecutionError) as error:
        verify_git_snapshot(services.uploads.analyze_upload(result["upload_id"]))
    assert error.value.code == "git_snapshot_changed"
    # The default ZIP analyzer still unwraps nested projects.
    zipped = services.uploads.save_zip(filename="nested.zip", content=services.executor.content)
    assert zipped["root_dir"].endswith("repository/nested")


def test_http_successful_git_plan_has_secret_safe_actor_digest_audit(services):
    saved = profile(services)
    app = FastAPI()
    principal = AuthPrincipal(id=services.context.actor_id, username="operator", role="operator", permissions=services.context.permissions)
    register_network_routes(app, network=services.network, imports=services.imports, auth=SimpleNamespace(authenticate_request=lambda request: principal), access=AccessControlStore(services.database))
    response = TestClient(app).post("/v1/projects/git/plan", json={"repository_url": URL, "git_network": {"mode": "profile", "profile_id": saved["id"], "version": 1}})
    assert response.status_code == 200
    planned = response.json()
    event = dict(services.database.query_one("SELECT * FROM events WHERE type='gate.git.plan_created'"))
    assert event["subject_type"] == "git_plan" and event["subject_id"] == planned["plan_id"]
    assert json.loads(event["payload_json"]) == {"actor_id": principal.id, "plan_digest": planned["plan_digest"]}
    assert URL not in json.dumps(event) and "proxy.example.invalid" not in json.dumps(event)
    assert services.database.query_one("SELECT digest FROM git_import_plans WHERE id=?", (planned["plan_id"],))[0] == planned["plan_digest"]


def test_import_confirmation_digest_owner_and_idempotency_boundaries(services):
    planned = services.imports.plan({"repository_url": URL}, services.context)
    body = {"plan_id": planned["plan_id"], "plan_digest": planned["plan_digest"], "idempotency_key": "git-source-confirm-001", "confirmed": True}
    with pytest.raises(ToolExecutionError):
        services.imports.create({**body, "confirmed": False}, services.context)
    with pytest.raises(ToolExecutionError) as error:
        services.imports.create({**body, "plan_digest": "b" * 64, "idempotency_key": "wrong-plan-digest-001"}, services.context)
    assert error.value.code == "git_plan_conflict"
    created = services.imports.create(body, services.context)
    with pytest.raises(ToolExecutionError) as error:
        services.imports.create({**body, "plan_digest": "b" * 64}, services.context)
    assert error.value.code == "idempotency_conflict"
    with pytest.raises(ToolExecutionError):
        services.imports.status({"import_id": created["import_id"]}, replace(services.context, actor_id="actor-two"))


@pytest.mark.parametrize("failure, expected", [(TimeoutError("secret-value"), "git_import_timeout"), (RuntimeError("secret-value"), "git_import_failed")])
def test_import_timeout_failure_redaction_and_old_deployment_unchanged(services, failure, expected):
    old = services.root / "old-artifact"
    old.mkdir()
    (old / "running.mjs").write_text("old-running-version")
    services.database.execute("INSERT INTO deployments(id,build_id,server_id,status,manifest_json,created_at,updated_at) VALUES('old','old-build','server','success','{}','now','now')")
    before = dict(services.database.query_one("SELECT * FROM deployments WHERE id='old'"))
    planned = services.imports.plan({"repository_url": URL}, services.context)
    task = services.imports.create({"plan_id": planned["plan_id"], "plan_digest": planned["plan_digest"], "idempotency_key": "git-failure-import-001", "confirmed": True}, services.context)
    services.executor.export_error = failure
    services.queue.run()
    current = services.imports.status({"import_id": task["import_id"]}, services.context)
    assert current["status"] == "failed" and current["error_code"] == expected
    assert not services.uploads.list_uploads()
    assert "secret-value" not in json.dumps(current)
    assert dict(services.database.query_one("SELECT * FROM deployments WHERE id='old'")) == before
    assert (old / "running.mjs").read_text() == "old-running-version"


def test_cancel_is_independent_confirmed_and_not_blindly_replayed(services):
    planned = services.imports.plan({"repository_url": URL}, services.context)
    task = services.imports.create({"plan_id": planned["plan_id"], "plan_digest": planned["plan_digest"], "idempotency_key": "git-cancel-import-001", "confirmed": True}, services.context)
    body = {"import_id": task["import_id"], "idempotency_key": "git-cancel-request-001", "confirmed": True}
    with pytest.raises(ToolExecutionError):
        services.imports.cancel({**body, "confirmed": False}, services.context)
    assert services.imports.cancel(body, services.context)["status"] == "cancel_requested"
    services.queue.run()
    assert services.imports.status({"import_id": task["import_id"]}, services.context)["status"] == "cancelled"
    assert not services.executor.exports
    assert not services.uploads.list_uploads()


def test_test_targets_methods_limits_rate_and_scheme_support(services):
    saved = profile(services)
    body = ProxyTest(profile_id=saved["id"], version=1, target_id="github", confirmed=True)
    result = services.imports.test_proxy(body, services.context)
    target, kwargs = services.executor.probes[0]
    assert target == "https://github.com/"
    assert kwargs["method"] == "HEAD" and kwargs["timeout_seconds"] == 5 and kwargs["max_response_bytes"] == 4096
    assert "body" not in result and "headers" not in result
    with pytest.raises(ToolExecutionError) as error:
        services.imports.test_proxy(body, services.context)
    assert error.value.code == "network_test_rate_limited"
    with pytest.raises(ValidationError):
        ProxyTest(profile_id=saved["id"], version=1, target_id="http://169.254.169.254/", confirmed=True)
    with pytest.raises(ToolExecutionError) as error:
        require_proxy_support(services.executor, "npm", "socks5")
    assert error.value.code == "proxy_scheme_unsupported"


def test_settings_and_network_use_permissions_are_independent_and_scoped(services):
    app = FastAPI()
    principal = AuthPrincipal(id="manager", username="manager", role="operator", permissions=("system_settings.manage",))
    auth = SimpleNamespace(authenticate_request=lambda request: principal)
    access = AccessControlStore(services.database)
    register_network_routes(app, network=services.network, imports=services.imports, auth=auth, access=access)
    client = TestClient(app)
    assert client.get("/v1/system-settings/network").status_code == 200
    assert client.post("/v1/projects/git/plan", json={"repository_url": URL}).status_code == 403
    principal = replace(principal, permissions=("operations.manage", "network.use"))
    assert client.get("/v1/system-settings/network").status_code == 403
    assert client.get("/v1/network/options").status_code == 200
    principal = replace(principal, role="admin", auth_type="token", permissions=("*",), scopes=("operations.manage",))
    assert client.get("/v1/system-settings/network").status_code == 403
    assert client.post("/v1/projects/git/plan", json={"repository_url": URL}).status_code == 403


def test_invalid_endpoint_validation_does_not_echo_secret_inputs(services):
    app = FastAPI()
    principal = AuthPrincipal(id="manager", username="manager", role="operator", permissions=("system_settings.manage",))
    auth = SimpleNamespace(authenticate_request=lambda request: principal)
    register_network_routes(app, network=services.network, imports=services.imports, auth=auth, access=AccessControlStore(services.database))
    response = TestClient(app).post("/v1/system-settings/network/profiles", json={"name": "Example", "endpoint": "http://alice:secret-value@proxy.example.invalid:8080"})
    assert response.status_code == 409
    assert "secret-value" not in response.text and "alice" not in response.text and "proxy.example.invalid" not in response.text


def test_confirmed_import_inserts_nine_named_columns_and_queues_once(services):
    planned = services.imports.plan({"repository_url": URL}, services.context)
    body = {"plan_id": planned["plan_id"], "plan_digest": planned["plan_digest"], "idempotency_key": "nine-column-import-001", "confirmed": True}
    created = services.imports.create(body, services.context)
    row = services.database.query_one("SELECT * FROM git_imports WHERE id=?", (created["import_id"],))
    assert len(row.keys()) == 9
    assert row["plan_id"] == planned["plan_id"] and row["actor_id"] == services.context.actor_id
    assert row["status"] == "queued" and row["created_at"] and row["updated_at"]
    assert row["upload_id"] is None and row["error_code"] is None
    assert len(services.queue.jobs) == 1


def test_restart_persists_interruption_and_releases_all_four_coordinator_slots(services):
    planned = services.imports.plan({"repository_url": URL}, services.context)
    body = {"plan_id": planned["plan_id"], "plan_digest": planned["plan_digest"], "confirmed": True}
    created = [services.imports.create({**body, "idempotency_key": f"restart-import-{index:03d}"}, services.context) for index in range(4)]
    for item, status in zip(created, ("queued", "running", "cancel_requested", "running")):
        services.database.execute("UPDATE git_imports SET status=? WHERE id=?", (status, item["import_id"]))
    with pytest.raises(ToolExecutionError) as full:
        services.imports.create({**body, "idempotency_key": "before-restart-full-001"}, services.context)
    assert full.value.code == "git_queue_full"
    restarted = GitImportService(services.delivery, services.network, executor=services.executor)
    assert services.database.query_one("SELECT count(*) FROM git_imports WHERE status IN ('queued','running','cancel_requested')")[0] == 0
    assert services.database.query_one("SELECT count(*) FROM git_imports WHERE status='interrupted'")[0] == 4
    for item in created:
        result = restarted.status({"import_id": item["import_id"]}, services.context)
        assert result["terminal"] and result["status"] == "interrupted"
        assert result["execution_state"] == "unknown" and result["requires_reconciliation"]
        assert not result["execution_terminated"]
        assert result["progress"][-1]["phase"] == "reconcile"
    fresh = restarted.create({**body, "idempotency_key": "after-restart-new-001"}, services.context)
    assert fresh["status"] == "queued"
    before = dict(services.database.query_one("SELECT * FROM git_imports WHERE id=?", (created[0]["import_id"],)))
    restarted.status({"import_id": created[0]["import_id"]}, services.context)
    assert dict(services.database.query_one("SELECT * FROM git_imports WHERE id=?", (created[0]["import_id"],))) == before


def test_lost_handle_status_recovery_is_durable_without_interrupting_live_handles(services):
    planned = services.imports.plan({"repository_url": URL}, services.context)
    created = services.imports.create({"plan_id": planned["plan_id"], "plan_digest": planned["plan_digest"], "idempotency_key": "lost-handle-import-001", "confirmed": True}, services.context)
    assert services.imports.status({"import_id": created["import_id"]}, services.context)["status"] == "queued"
    services.imports._cancels.pop(created["import_id"])
    assert services.imports.status({"import_id": created["import_id"]}, services.context)["status"] == "interrupted"
    assert services.database.query_one("SELECT status FROM git_imports WHERE id=?", (created["import_id"],))[0] == "interrupted"


def test_restart_replay_and_late_callback_never_resubmit_or_report_cancelled(services):
    planned = services.imports.plan({"repository_url": URL}, services.context)
    body = {"plan_id": planned["plan_id"], "plan_digest": planned["plan_digest"], "idempotency_key": "restart-replay-import-001", "confirmed": True}
    created = services.imports.create(body, services.context)
    restarted = GitImportService(services.delivery, services.network, executor=services.executor)
    replay = restarted.create(body, services.context)
    assert replay["import_id"] == created["import_id"] and replay["status"] == "interrupted"
    assert len(services.queue.jobs) == 1
    services.queue.run()  # Callback from the old synthetic coordinator is fenced.
    assert not services.executor.exports and not services.uploads.list_uploads()
    with pytest.raises(ToolExecutionError) as error:
        restarted.cancel({"import_id": created["import_id"], "idempotency_key": "restart-cancel-unknown-001", "confirmed": True}, services.context)
    assert error.value.code == "operation_interrupted"
    assert restarted.status({"import_id": created["import_id"]}, services.context)["execution_state"] == "unknown"
    assert services.database.query_one("SELECT status FROM git_imports WHERE id=?", (created["import_id"],))[0] == "interrupted"
    assert not services.database.query_one("SELECT 1 FROM events WHERE type='gate.git.cancel_requested'")


def test_expired_unused_plan_is_pruned_without_removing_digest_audit(services):
    saved = profile(services)
    planned = services.imports.plan({"repository_url": URL, "git_network": {"mode": "profile", "profile_id": saved["id"], "version": 1}}, services.context)
    with pytest.raises(ToolExecutionError) as protected:
        services.network.delete_profile(saved["id"], 1, "admin")
    assert protected.value.code == "network_profile_in_use"
    services.database.execute("UPDATE git_import_plans SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (planned["plan_id"],))
    assert services.network.delete_profile(saved["id"], 1, "admin")["deleted"]
    assert services.database.query_one("SELECT 1 FROM git_import_plans WHERE id=?", (planned["plan_id"],)) is None
    audit = services.database.query_one("SELECT payload_json FROM events WHERE type='gate.git.plan_created' AND subject_id=?", (planned["plan_id"],))
    assert json.loads(audit[0])["plan_digest"] == planned["plan_digest"]
    assert services.database.query_one("SELECT count(*) FROM network_profile_references WHERE profile_id=?", (saved["id"],))[0] == 0


def test_expired_unused_plan_sweep_is_bounded_and_keeps_live_plans(services):
    saved = profile(services)
    live = services.imports.plan({"repository_url": URL}, services.context)
    with services.database.session() as connection:
        connection.executemany("INSERT INTO git_import_plans VALUES(?,?,?,?,?,?)", [(f"expired-{index:04d}", "other-actor", "a" * 64, "{}", "2000-01-01T00:00:00+00:00", "2000-01-01T00:00:00+00:00") for index in range(101)])
    services.network.references(saved["id"])
    assert services.database.query_one("SELECT count(*) FROM git_import_plans WHERE id LIKE 'expired-%'")[0] == 1
    assert services.database.query_one("SELECT 1 FROM git_import_plans WHERE id=?", (live["plan_id"],))
    services.network.references(saved["id"])
    assert services.database.query_one("SELECT count(*) FROM git_import_plans WHERE id LIKE 'expired-%'")[0] == 0


@pytest.mark.parametrize("status", ["queued", "running", "cancel_requested", "interrupted", "unknown", "success", "failed", "cancelled"])
def test_expired_import_referenced_plan_is_retained_for_provenance(services, status):
    saved = profile(services)
    planned = services.imports.plan({"repository_url": URL}, services.context)
    created = services.imports.create({"plan_id": planned["plan_id"], "plan_digest": planned["plan_digest"], "idempotency_key": "retained-provenance-001", "confirmed": True}, services.context)
    services.database.execute("UPDATE git_imports SET status=? WHERE id=?", (status, created["import_id"]))
    services.database.execute("UPDATE git_import_plans SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (planned["plan_id"],))
    services.network.references(saved["id"])
    row = services.database.query_one("SELECT digest,plan_json FROM git_import_plans WHERE id=?", (planned["plan_id"],))
    assert row["digest"] == planned["plan_digest"] and json.loads(row["plan_json"])["commit_sha"] == SHA


def test_unused_plan_capacity_is_per_actor_and_global_with_expiry_recovery(services):
    other = replace(services.context, actor_id="actor-two")
    with patch("lingshu_gate.git_import_mcp.MAX_UNUSED_PLANS_PER_ACTOR", 2), patch("lingshu_gate.git_import_mcp.MAX_UNUSED_PLANS", 3):
        first = services.imports.plan({"repository_url": URL}, services.context)
        services.imports.plan({"repository_url": URL}, services.context)
        with pytest.raises(ToolExecutionError) as per_actor:
            services.imports.plan({"repository_url": URL}, services.context)
        assert per_actor.value.code == "git_plan_capacity"
        services.imports.plan({"repository_url": URL}, other)
        with pytest.raises(ToolExecutionError) as global_limit:
            services.imports.plan({"repository_url": URL}, other)
        assert global_limit.value.code == "git_plan_capacity"
        services.database.execute("UPDATE git_import_plans SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (first["plan_id"],))
        assert services.imports.plan({"repository_url": URL}, other)["status"] == "ready"
    assert services.database.query_one("SELECT count(*) FROM git_import_plans")[0] == 3


def test_active_and_unknown_imports_protect_profile_after_plan_expiry(services):
    saved = profile(services)
    planned = services.imports.plan({"repository_url": URL, "git_network": {"mode": "profile", "profile_id": saved["id"], "version": 1}}, services.context)
    created = services.imports.create({"plan_id": planned["plan_id"], "plan_digest": planned["plan_digest"], "idempotency_key": "profile-live-import-001", "confirmed": True}, services.context)
    services.database.execute("UPDATE git_import_plans SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (planned["plan_id"],))
    assert [row["resource_type"] for row in services.network.references(saved["id"])] == ["git_import"]
    with pytest.raises(ToolExecutionError):
        services.network.delete_profile(saved["id"], 1, "admin")
    restarted = GitImportService(services.delivery, services.network, executor=services.executor)
    assert restarted.status({"import_id": created["import_id"]}, services.context)["execution_state"] == "unknown"
    assert services.network.references(saved["id"])[0]["resource_id"] == created["import_id"]
    with pytest.raises(ToolExecutionError) as protected:
        services.network.delete_profile(saved["id"], 1, "admin")
    assert protected.value.code == "network_profile_in_use"


def test_successful_import_transfers_guard_to_upload_and_delete_releases_it(services):
    saved = profile(services)
    planned = services.imports.plan({"repository_url": URL, "git_network": {"mode": "profile", "profile_id": saved["id"], "version": 1}}, services.context)
    created = services.imports.create({"plan_id": planned["plan_id"], "plan_digest": planned["plan_digest"], "idempotency_key": "profile-upload-import-001", "confirmed": True}, services.context)
    services.queue.run()
    result = services.imports.status({"import_id": created["import_id"]}, services.context)
    assert result["status"] == "success"
    assert services.database.query_one("SELECT count(*) FROM network_profile_references WHERE resource_type='git_import' AND resource_id=?", (created["import_id"],))[0] == 0
    services.database.execute("UPDATE git_import_plans SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (planned["plan_id"],))
    assert [row["resource_type"] for row in services.network.references(saved["id"])] == ["upload"]
    with pytest.raises(ToolExecutionError):
        services.network.delete_profile(saved["id"], 1, "admin")
    services.uploads.delete_upload(result["upload_id"])
    assert services.database.query_one("SELECT count(*) FROM network_profile_references WHERE resource_type='upload' AND resource_id=?", (result["upload_id"],))[0] == 0
    assert services.network.delete_profile(saved["id"], 1, "admin")["deleted"]


@pytest.mark.parametrize("signal,expected,terminated", [(InterruptedError("uncertain"), "interrupted", False), (SafeExecutionCancelled(), "cancelled", True)])
def test_executor_interruption_requires_evidence_before_reporting_termination(services, signal, expected, terminated):
    saved = profile(services)
    planned = services.imports.plan({"repository_url": URL, "git_network": {"mode": "profile", "profile_id": saved["id"], "version": 1}}, services.context)
    created = services.imports.create({"plan_id": planned["plan_id"], "plan_digest": planned["plan_digest"], "idempotency_key": "executor-outcome-import-001", "confirmed": True}, services.context)
    services.executor.export_error = signal
    services.queue.run()
    result = services.imports.status({"import_id": created["import_id"]}, services.context)
    assert result["status"] == expected and result["execution_terminated"] is terminated
    assert result["requires_reconciliation"] is (not terminated)
    assert services.database.query_one("SELECT count(*) FROM git_imports WHERE status IN ('queued','running','cancel_requested')")[0] == 0
    references = services.network.references(saved["id"])
    assert any(row["resource_type"] == "git_import" for row in references) is (not terminated)

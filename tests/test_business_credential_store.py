"""Business credentials never expose plaintext and never forget remote state."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from lingshu_gate.business_credential_store import BusinessCredentialStore
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.domain.business_credentials import (
    BusinessCredentialBindingCreate,
    BusinessCredentialBindingUpdate,
    BusinessCredentialCreate,
    BusinessCredentialError,
    BusinessCredentialUpdate,
)
from lingshu_gate.persistence.business_credentials_migration import BUSINESS_CREDENTIALS_MIGRATION_ID

USERNAME = "private-test-username"
PASSWORD = "private-test-password"
CONTRACT = {"save": "a" * 64, "login": "b" * 64, "delete": "c" * 64, "open": "d" * 64}


@pytest.fixture
def store(tmp_path: Path) -> BusinessCredentialStore:
    database = SQLiteDatabase("", tmp_path)
    for user_id in ("user-a", "user-b"):
        database.execute("INSERT INTO users(id,username,password_hash,created_at,updated_at) VALUES (?,?,?,? ,?)",
            (user_id, user_id, "unused", "2026-10-20", "2026-10-20"))
    return BusinessCredentialStore(database, tmp_path)


def create(store: BusinessCredentialStore, **changes):
    return store.create_credential("user-a", BusinessCredentialCreate.model_validate({
        "name": "Test physician", "environment": "test", "business_role": "physician",
        "login_url": "https://app.example.test/login", "username": USERNAME, "password": PASSWORD, **changes}))


def update_request(record, **changes):
    return BusinessCredentialUpdate.model_validate({key: record[key] for key in (
        "name", "environment", "business_role", "login_url", "enabled", "allow_http", "allowed_user_ids",
        "allowed_role_ids", "selectors")} | {"expected_version": record["version"], **changes})


def bind(store, credential, **changes):
    return store.create_binding(credential["id"], BusinessCredentialBindingCreate.model_validate({
        "server_id": "browser-one", "confirm_managed_mode": True, **changes}),
        manifest_digest="e" * 64, tool_revisions=CONTRACT)


def receipt(store, binding, credential, status, **changes):
    return store.mark_sync(binding["id"], expected_revision=binding["revision"],
        expected_version=credential["version"], status=status, **changes)


def test_encrypted_at_rest_and_metadata_never_resolves_secrets(store, tmp_path, caplog):
    record = create(store)
    assert record["credential_ref"] == f'gate:{record["id"]}'
    assert record["username_masked"] == "***" and record["password_configured"] is True
    assert not {"username", "password", "encrypted_secret"} & set(record)
    public = json.dumps(store.list_credentials())
    assert USERNAME not in public and PASSWORD not in public
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert USERNAME.encode() not in path.read_bytes()
            assert PASSWORD.encode() not in path.read_bytes()
    assert USERNAME not in caplog.text and PASSWORD not in caplog.text
    assert store.resolve_secret(record["id"], expected_version=1) == {"username": USERNAME, "password": PASSWORD}
    assert (tmp_path / "business-credentials" / "credential.key").exists()
    assert not (tmp_path / "credential.key").exists()


def test_missing_edit_values_preserve_secrets_and_scope_owner_are_immutable(store):
    record = create(store)
    updated = store.update_credential(record["id"], update_request(record, name="Changed metadata"))
    assert updated["version"] == 2
    assert store.resolve_secret(record["id"], expected_version=2) == {"username": USERNAME, "password": PASSWORD}
    updated = store.update_credential(record["id"], update_request(updated, password="replacement-password"))
    assert store.resolve_secret(record["id"], expected_version=3) == {
        "username": USERNAME, "password": "replacement-password"}
    for field, value in (("owner_id", "user-b"), ("scope", "shared")):
        with pytest.raises(ValidationError):
            update_request(updated, **{field: value})


def test_lost_update_and_stale_secret_read_fail_closed(store):
    record = create(store)
    other = BusinessCredentialStore(store.database, store.database.path.parent)
    store.update_credential(record["id"], update_request(record, name="Current"))
    with pytest.raises(BusinessCredentialError, match="changed") as exc:
        other.update_credential(record["id"], update_request(record, name="Stale"))
    assert exc.value.status == 409
    with pytest.raises(BusinessCredentialError):
        other.resolve_secret(record["id"], expected_version=1)
    assert store.get_credential(record["id"])["name"] == "Current"


def test_credential_update_invalidates_old_sync_receipt_and_preserves_remote_copy(store):
    record = create(store)
    binding = receipt(store, bind(store, record), record, "synced")
    assert binding["synced_version"] == 1
    current = store.update_credential(record["id"], update_request(record, password="rotated-password"))
    pending = store.get_binding(binding["id"])
    assert pending["sync_status"] == "pending"
    assert pending["remote_copy_possible"] and pending["synced_version"] == 1
    assert pending["revision"] == binding["revision"] + 1
    with pytest.raises(BusinessCredentialError):
        receipt(store, binding, record, "synced")
    with pytest.raises(BusinessCredentialError):
        receipt(store, pending, record, "synced")
    current_binding = receipt(store, pending, current, "synced")
    assert current_binding["synced_version"] == 2


def test_unknown_dispatch_is_durable_and_failed_cleanup_cannot_drop_remote_state(store):
    record = create(store)
    binding = receipt(store, bind(store, record), record, "unknown")
    reopened = BusinessCredentialStore(store.database, store.database.path.parent)
    assert reopened.get_binding(binding["id"])["remote_copy_possible"]
    failed = receipt(store, binding, record, "failed", error_code="downstream_failed")
    with pytest.raises(BusinessCredentialError) as exc:
        store.delete_binding(failed["id"], expected_revision=failed["revision"])
    assert exc.value.code == "remote_copy_cleanup_required"
    with pytest.raises(BusinessCredentialError):
        store.delete_credential(record["id"], expected_version=record["version"])
    removed = receipt(store, failed, record, "deleted")
    assert not removed["remote_copy_possible"] and removed["synced_version"] is None
    store.delete_binding(removed["id"], expected_revision=removed["revision"])
    store.delete_credential(record["id"], expected_version=record["version"])
    assert reopened.is_managed_server("browser-one")
    assert reopened.list_managed_servers()[0]["tool_prefix"] == "agent_browser_"


def test_internal_profiles_do_not_collide_for_same_name_or_different_users(store):
    first = create(store)
    second = store.create_credential("user-b", BusinessCredentialCreate.model_validate({
        "name": first["name"], "login_url": first["login_url"], "username": USERNAME, "password": PASSWORD}))
    first_binding, second_binding = bind(store, first), bind(store, second)
    assert first_binding["profile_name"] != second_binding["profile_name"]
    assert first_binding["profile_name"].startswith("gate_")
    assert first["credential_ref"] != second["credential_ref"]
    with pytest.raises(BusinessCredentialError) as exc:
        bind(store, first)
    assert exc.value.code == "binding_exists"


def test_disabled_account_does_not_decrypt_or_report_new_sync_success(store):
    record = create(store)
    binding = bind(store, record)
    disabled = store.update_credential(record["id"], update_request(record, enabled=False))
    with pytest.raises(BusinessCredentialError) as exc:
        store.resolve_secret(record["id"], expected_version=disabled["version"])
    assert exc.value.code == "credential_disabled"
    with pytest.raises(BusinessCredentialError):
        receipt(store, store.get_binding(binding["id"]), disabled, "synced")


def test_binding_repin_requires_remote_cleanup_and_current_credential_version(store):
    record = create(store)
    binding = receipt(store, bind(store, record), record, "synced")
    change = BusinessCredentialBindingUpdate(expected_revision=binding["revision"], expected_version=1, enabled=False)
    with pytest.raises(BusinessCredentialError) as exc:
        store.update_binding(binding["id"], change, manifest_digest="f" * 64, tool_revisions=CONTRACT)
    assert exc.value.code == "remote_copy_cleanup_required"
    disabled = store.update_binding(binding["id"], change, manifest_digest="e" * 64, tool_revisions=CONTRACT)
    assert not disabled["enabled"] and disabled["remote_copy_possible"]


def test_active_or_unknown_sessions_prevent_forgetting_cleanup_information(store):
    record = create(store)
    binding = bind(store, record)
    store.database.execute("INSERT INTO business_credential_sessions "
        "(id,connection_key,owner_id,server_id,logical_session,credential_id,binding_id,credential_version,"
        "binding_revision,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,'unknown',?,?)",
        ("gate_session", "proof", "user-a", "browser-one", "test-session", record["id"], binding["id"], 1, 1, "now", "now"))
    for remove in (lambda: store.delete_binding(binding["id"], expected_revision=1),
                   lambda: store.delete_credential(record["id"], expected_version=1)):
        with pytest.raises(BusinessCredentialError) as exc:
            remove()
        assert exc.value.code == "browser_session_cleanup_required"
    store.database.execute("UPDATE business_credential_sessions SET status='closed'")
    store.delete_credential(record["id"], expected_version=1)
    assert store.database.query_one("SELECT id FROM business_credential_sessions") is not None
    assert store.is_managed_server("browser-one")


@pytest.mark.parametrize("url", ["http://app.example.test/login", "https://name:password@app.example.test/login",
    "https://app.example.test/login?token=secret", "https://app.example.test/#secret", "javascript:alert(1)",
    "https://app.example.test:bad/login", "https://app.example.test/\nlogin",
    "https://app.example.test/#/login?token=secret", "https://app.example.test/#/login=secret"])
def test_unsafe_or_unacknowledged_login_destinations_rejected(store, url):
    with pytest.raises(ValidationError):
        create(store, login_url=url)


def test_http_requires_explicit_acknowledgement_and_personal_acl_stays_private(store):
    assert create(store, login_url="http://internal.example.test/login", allow_http=True)["allow_http"]
    assert create(store, login_url="https://app.example.test/#/login")["login_url"].endswith("#/login")
    with pytest.raises(ValidationError):
        create(store, allowed_user_ids=["user-b"])
    personal = create(store)
    with pytest.raises(BusinessCredentialError):
        store.update_credential(personal["id"], update_request(personal, allowed_role_ids=["role-admin"]))
    shared = create(store, scope="shared", allowed_user_ids=["user-b", "user-b"], allowed_role_ids=["role-admin"])
    assert shared["allowed_user_ids"] == ["user-b"]


@pytest.mark.parametrize("field,value", [("password", "***"), ("username", "***"), ("password", ""),
    ("password", " \t"), ("username", "bad\nname"), ("password", "bad\x00secret")])
def test_secret_validation_is_masked_and_not_a_preserve_value_sentinel(store, field, value):
    with pytest.raises(ValidationError) as exc:
        create(store, **{field: value})
    assert "input_value=" not in str(exc.value)


def test_corrupt_ciphertext_is_a_safe_error_and_cannot_be_edited_with_new_secret(store):
    record = create(store)
    store.database.execute("UPDATE business_credentials SET encrypted_secret='invalid-sensitive-envelope'")
    with pytest.raises(BusinessCredentialError) as exc:
        store.resolve_secret(record["id"], expected_version=1)
    assert "invalid-sensitive-envelope" not in str(exc.value)
    assert exc.value.code == "credential_unavailable"
    with pytest.raises(BusinessCredentialError):
        store.update_credential(record["id"], update_request(record, password="new-password"))
    assert store.get_credential(record["id"])["version"] == 1


def test_sync_error_details_never_accept_downstream_message_or_secret(store):
    record = create(store)
    binding = bind(store, record)
    with pytest.raises(BusinessCredentialError) as exc:
        receipt(store, binding, record, "failed", error_code=f"Failed: {PASSWORD}")
    assert PASSWORD not in str(exc.value)
    assert store.get_binding(binding["id"])["last_error_code"] is None


def test_reading_ciphertext_without_its_key_does_not_generate_a_replacement(store, tmp_path):
    record = create(store)
    key_path = tmp_path / "business-credentials" / "credential.key"
    key_path.unlink()
    with pytest.raises(BusinessCredentialError) as exc:
        store.resolve_secret(record["id"], expected_version=1)
    assert exc.value.code == "credential_unavailable"
    assert not key_path.exists()
    with pytest.raises(BusinessCredentialError):
        create(store, name="Another account")
    assert not key_path.exists()
    assert len(store.list_credentials()) == 1


def test_migration_is_idempotent_and_keeps_shared_credentials_separate(store):
    record = create(store)
    store.database.initialize()
    rows = store.database.query_all("SELECT id FROM schema_migrations WHERE id=?", (BUSINESS_CREDENTIALS_MIGRATION_ID,))
    assert len(rows) == 1
    assert store.get_credential(record["id"])["version"] == 1
    assert store.database.query_all("SELECT id FROM user_downstream_credentials") == []

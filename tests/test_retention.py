"""RET-01..10: isolated SQLite retention, real auth/API and worker lifecycle."""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lingshu_gate.access_control import AccessControlStore
from lingshu_gate.auth import AuthStore
from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.interfaces.control_api.auth_routes import register_auth_routes
from lingshu_gate.interfaces.control_api.retention_routes import register_retention_routes
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.retention_store import RetentionConflict, RetentionStore
from lingshu_gate.retention_worker import RetentionWorker

NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path):
    return RetentionStore(SQLiteDatabase(f"sqlite:///{tmp_path / 'synthetic.db'}", tmp_path))


def seed(store, stamp, suffix="old"):
    db = store.database
    db.execute("INSERT INTO logs(id,level,source,message,created_at) VALUES (?,'info','synthetic','safe',?)", (suffix, stamp))
    db.execute("INSERT INTO events(id,type,source,created_at) VALUES (?,'gate.synthetic','synthetic',?)", (suffix, stamp))
    db.execute("INSERT INTO invocation_audits(id,correlation_id,user_id,username,auth_type,server_id,tool_id,"
               "tool_access,required_access,granted_access,decision,reason,outcome,created_at) "
               "VALUES (?,?,'synthetic-user','synthetic','session','A','A.read','read','read','read','allow','allowed','success',?)", (suffix, suffix, stamp))
    db.execute("INSERT INTO invocation_payloads VALUES (?,'synthetic-user','{}','{}')", (suffix,))


def enqueue(store):
    preview = store.preview(now=NOW)
    return store.enqueue(preview["preview_id"], preview["revision"], "synthetic-admin", now=NOW)


def test_defaults_cas_and_preview_never_delete(store):
    seed(store, "2026-01-01T00:00:00+00:00")
    assert store.policy() == dict(revision=1, logs_days=7, events_days=7, invocation_audits_days=7, payload_mode="metadata_only")
    before = store.database.query_one("SELECT COUNT(*) AS n FROM events")["n"]
    values = dict(logs_days=1, events_days=3, invocation_audits_days=7, payload_mode="metadata_only")
    preview = store.preview(values, now=NOW)
    assert preview["shortened"] == ["logs", "events"]
    assert store.database.query_one("SELECT COUNT(*) AS n FROM events")["n"] == before
    assert store.database.query_one("SELECT COUNT(*) AS n FROM retention_jobs")["n"] == 0
    with pytest.raises(RetentionConflict):
        store.save_policy(1, values)
    fresh = store.preview(values)
    assert store.save_policy(1, values, preview_id=fresh["preview_id"], confirmed=True)["revision"] == 2
    with pytest.raises(RetentionConflict):
        store.save_policy(1, values)
    with pytest.raises(RetentionConflict):
        store.enqueue(preview["preview_id"], 1, "synthetic", now=NOW)


def test_utc_cutoff_index_strict_boundary_and_payload_cascade(store):
    seed(store, "2026-09-24T11:59:59+00:00", "before")
    seed(store, "2026-09-24T15:00:00+03:00", "equal")
    seed(store, "2026-09-24T12:00:01+00:00", "after")
    assert store.preview(now=NOW)["counts"] == dict(logs=1, events=1, invocation_audits=1)
    plan = store.database.query_all("EXPLAIN QUERY PLAN SELECT id FROM logs WHERE julianday(created_at)<julianday(?) ORDER BY julianday(created_at),id LIMIT 200", (NOW.isoformat(),))
    assert any("idx_logs_retention_utc" in row["detail"] for row in plan)
    job = enqueue(store)
    for _ in range(4):
        store.run_batch("owner", batch_size=1, now=NOW)
    assert store.job(job["id"])["state"] == "succeeded"
    assert store.job(job["id"])["counts"] == dict(logs=1, events=1, invocation_audits=1)
    assert store.database.query_one("SELECT audit_id FROM invocation_payloads WHERE audit_id='before'") is None
    assert store.database.query_one("SELECT COUNT(*) AS n FROM invocation_payloads")["n"] == 2


def test_leases_bound_batches_takeover_and_cancel(store):
    for i in range(5):
        seed(store, "2026-01-01T00:00:00Z", str(i))
    job = enqueue(store)
    store.run_batch("owner-a", batch_size=2, now=NOW)
    assert store.job(job["id"])["counts"]["logs"] == 2
    assert store.run_batch("owner-b", now=NOW) is None
    store.run_batch("owner-b", batch_size=2, now=NOW+timedelta(seconds=31))
    assert store.job(job["id"])["counts"]["logs"] == 4
    store.cancel(job["id"])
    store.run_batch("owner-b", now=NOW+timedelta(seconds=32))
    assert store.job(job["id"])["state"] == "cancelled"
    assert store.database.query_one("SELECT COUNT(*) AS n FROM events")["n"] == 5


def test_policy_revision_change_stops_old_job(store):
    seed(store, "2026-01-01T00:00:00Z")
    job = enqueue(store)
    store.save_policy(1, dict(logs_days=30, events_days=30, invocation_audits_days=30, payload_mode="metadata_only"))
    store.run_batch("owner", now=NOW)
    assert store.job(job["id"])["state"] == "cancelled"
    assert store.database.query_one("SELECT COUNT(*) AS n FROM logs")["n"] == 1


def test_retry_bounded_and_expired_preview(store):
    job = enqueue(store)
    for i in range(3):
        store.retry_failure("owner", now=NOW+timedelta(seconds=6*i))
    assert store.job(job["id"])["state"] == "failed"
    assert store.job(job["id"])["attempts"] == 3
    preview = store.preview(now=NOW)
    with pytest.raises(RetentionConflict):
        store.enqueue(preview["preview_id"], preview["revision"], "synthetic", now=NOW+timedelta(minutes=6))


def test_preview_return_cannot_mutate_confirmation(store):
    preview = store.preview(now=NOW)
    preview["cutoffs"]["logs"] = "9999-01-01"
    job = store.enqueue(preview["preview_id"], 1, "synthetic", now=NOW)
    assert job["cutoffs"]["logs"].startswith("2026-09-24")


@pytest.fixture(params=[False, True])
def api(store, tmp_path, monkeypatch, request):
    monkeypatch.setenv("LINGSHU_GATE_ADMIN_USERNAME", "synthetic-admin")
    monkeypatch.setenv("LINGSHU_GATE_ADMIN_PASSWORD", "Synthetic-Only-123!")
    monkeypatch.delenv("LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE", raising=False)
    settings = Settings(data_dir=tmp_path, db_url=f"sqlite:///{tmp_path / 'synthetic.db'}")
    access = AccessControlStore(store.database)
    auth = AuthStore(settings, store.database)
    admin = auth.list_users()[0]
    auth.change_password(admin["id"], "Synthetic-Only-123!")
    auth.create_user(username="operator", password="Synthetic-Only-123!", role="operator")
    observability = ObservabilityStore(store.database)
    app = FastAPI()
    register_auth_routes(app, settings=settings, auth_store=auth, observability_store=observability, require_viewer=auth.authenticate_request)
    register_retention_routes(app, store=store, auth_store=auth, access_store=access, observability_store=observability, worker_enabled=request.param)
    with TestClient(app) as client:
        def login(name):
            client.cookies.clear()
            assert client.post("/v1/auth/login", json={"username":name,"password":"Synthetic-Only-123!"}).status_code == 200
        yield client, login, request.param


def test_real_http_save_preview_confirm_cancel_and_nonadmin(api, store):
    client, login, enabled = api
    login("operator")
    assert client.get("/v1/retention/policy").status_code == 403
    assert client.post("/v1/retention/preview").status_code == 403
    login("synthetic-admin")
    policy = client.get("/v1/retention/policy").json()
    assert client.put("/v1/retention/policy", json={"payload_mode":"redacted","expected_revision":policy["revision"]}).status_code == 422
    assert store.policy()["revision"] == policy["revision"]
    assert policy["worker_enabled"] is enabled
    body = dict(runtime_logs_retention_days=3, events_retention_days=7, call_records_retention_days=9, payload_mode="redacted", expected_revision=policy["revision"])
    assert client.put("/v1/retention/policy", json=body).status_code == 409
    change_preview = client.post("/v1/retention/preview", json={key:value for key,value in body.items() if key != "expected_revision"}).json()
    body.update(preview_id=change_preview["preview_id"], confirmed=True)
    response = client.put("/v1/retention/policy", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 2
    assert client.put("/v1/retention/policy", json=body).status_code == 409
    assert store.database.query_one("SELECT COUNT(*) AS n FROM retention_jobs")["n"] == 0
    preview = client.post("/v1/retention/preview").json()
    payload = {"preview_id":preview["preview_id"],"expected_revision":2,"confirmed":False}
    assert client.post("/v1/retention/jobs",json=payload).status_code == (422 if enabled else 409)
    assert store.database.query_one("SELECT COUNT(*) AS n FROM retention_jobs")["n"] == 0
    payload["confirmed"] = True
    response = client.post("/v1/retention/jobs",json=payload)
    if not enabled:
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "retention_worker_disabled"
        return
    assert response.status_code == 202, response.text
    job_id = response.json()["id"]
    assert client.get(f"/v1/retention/jobs/{job_id}").json()["state"] == "queued"
    assert client.post(f"/v1/retention/jobs/{job_id}/cancel").json()["state"] == "cancelled"
    assert client.get("/v1/retention/jobs/missing").status_code == 404


def test_worker_default_disabled_and_explicit_isolated_run(store):
    async def scenario():
        disabled = RetentionWorker(store)
        disabled.start()
        assert disabled._task is None
        await disabled.stop()
        seed(store, "2026-01-01T00:00:00Z")
        job = enqueue(store)
        enabled = RetentionWorker(store, enabled=True)
        enabled.start()
        # Only the already confirmed temporary-DB job runs; no startup auto sweep.
        for _ in range(60):
            if store.job(job["id"])["state"] == "succeeded":
                break
            await asyncio.sleep(.1)
        await enabled.stop()
        assert store.job(job["id"])["state"] == "succeeded"
    asyncio.run(scenario())


@pytest.mark.parametrize("enabled", [False, True])
def test_app_lifespan_owns_worker_only_in_isolated_environment(tmp_path, monkeypatch, enabled):
    import importlib
    import os
    for name in tuple(os.environ):
        if name.startswith("LINGSHU_GATE_"):
            monkeypatch.delenv(name)
    for name, value in {
        "DATA_DIR": str(tmp_path), "DB_URL": f"sqlite:///{tmp_path / 'lifespan.db'}",
        "CONFIG_DIR": str(tmp_path / "mcp"), "ALLOWED_ROOT": str(tmp_path / "workspace"),
        "ADMIN_USERNAME": "synthetic-admin", "ADMIN_PASSWORD": "Synthetic-Only-123!",
        "RUNTIME_ROLE": "core", "SYSTEM_DEBUG_MCP_ENABLED": "false",
        "RETENTION_WORKER_ENABLED": str(enabled).lower(), "RETENTION_INTERVAL_SECONDS": "86400",
    }.items():
        monkeypatch.setenv(f"LINGSHU_GATE_{name}", value)
    module = importlib.import_module("lingshu_gate.main")
    app = module.create_app()
    worker = app.state.retention_worker
    assert worker.enabled is enabled
    with TestClient(app):
        assert (worker._task is not None) is enabled
        assert app.state.retention_store.database.path.parent == tmp_path
        assert app.state.retention_store.database.query_one("SELECT COUNT(*) AS n FROM retention_jobs")["n"] == 0
    assert worker._task is None

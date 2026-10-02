"""Indexed log history windows retain all server records and remain authorized."""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.build_deploy import BuildDeployStore
from lingshu_gate.build_deploy_routes import register_build_deploy_routes


def make_store(root: Path) -> BuildDeployStore:
    database = SQLiteDatabase('', root)
    database.execute("INSERT INTO builds(id,upload_id,status,source_dir,artifact_dir,created_at,updated_at) "
                     "VALUES('build','upload','success','','','now','now')")
    with database.session() as connection:
        connection.executemany(
            "INSERT INTO build_logs(id,build_id,sequence,phase,started_at,created_at) VALUES(?,'build',?,'command','now','now')",
            ((str(index), index) for index in range(2501)),
        )
    # These persistence methods use only the database; no runtime/executor is started.
    store = object.__new__(BuildDeployStore)
    store.database = database
    return store


def test_window_navigation_is_complete_and_bounds_are_exact(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    app = FastAPI()
    register_build_deploy_routes(app, store, lambda: None)
    with TestClient(app) as client:
        latest = client.get('/v1/builds/build/logs?tail=true&limit=200').json()
        assert [row['sequence'] for row in latest['logs']] == list(range(2301, 2501))
        assert latest['has_earlier'] is True and latest['has_later'] is False
        older = client.get('/v1/builds/build/logs?before_sequence=2301&limit=200').json()
        assert [row['sequence'] for row in older['logs']] == list(range(2101, 2301))
        assert older['has_earlier'] and older['has_later']
        newer = client.get('/v1/builds/build/logs?after_sequence=2300&limit=200').json()
        assert newer == latest
        first = client.get('/v1/builds/build/logs?limit=200').json()
        assert first['logs'][0]['sequence'] == 0
        assert first['has_earlier'] is False
        assert client.get('/v1/builds/build/logs?tail=true&before_sequence=2301').status_code == 422
        assert client.get('/v1/builds/missing/logs?tail=true').status_code == 404
        stream = client.get('/v1/builds/build/logs/stream?tail=true').text
        assert stream.count('event: log\n') == 200
        assert '"sequence": 2500' in stream
    assert store.database.query_one('SELECT COUNT(*) AS count FROM build_logs')['count'] == 2501


def test_log_windows_do_not_bypass_operations_permission(tmp_path: Path) -> None:
    def denied() -> None:
        raise HTTPException(403, 'not allowed')
    app = FastAPI()
    register_build_deploy_routes(app, make_store(tmp_path), denied)
    with TestClient(app) as client:
        for path in ('/v1/builds/build/logs?tail=true', '/v1/builds/build/logs?before_sequence=200', '/v1/builds/build/logs/stream?tail=true'):
            assert client.get(path).status_code == 403

"""Incremental build streams stay off the event loop and drain terminal pages."""
import asyncio
import json
import threading
from typing import Any, cast
from unittest.mock import Mock

from fastapi import FastAPI
from starlette.routing import Route

from lingshu_gate.build_deploy import BuildDeployStore
from lingshu_gate.build_deploy_routes import register_build_deploy_routes


def test_stream_drains_more_than_one_page_without_reloading_old_rows() -> None:
    main_thread = threading.get_ident()
    cursors: list[int] = []
    worker_threads: list[int] = []
    store = Mock(spec=BuildDeployStore)
    store.get_build.return_value = {'status': 'success', 'updated_at': 'now'}

    def read_logs(build_id: str, *, limit: int, after_sequence: int) -> list[dict[str, Any]]:
        assert build_id == 'build'
        worker_threads.append(threading.get_ident())
        cursors.append(after_sequence)
        return [{'id': str(i), 'sequence': i} for i in range(after_sequence + 1, min(after_sequence + 1 + limit, 2501))]

    store.list_build_logs.side_effect = read_logs
    app = FastAPI()
    register_build_deploy_routes(app, cast(BuildDeployStore, store), lambda: None)
    endpoint = next(cast(Route, route).endpoint for route in app.routes if getattr(route, 'path', '') == '/v1/builds/{build_id}/logs/stream')
    response = endpoint('build', interval_seconds=0.5)

    async def consume() -> list[str]:
        return [part async for part in response.body_iterator]

    chunks = asyncio.run(consume())
    logs = [json.loads(chunk.split('data: ', 1)[1]) for chunk in chunks if chunk.startswith('event: log\n')]
    assert [log['sequence'] for log in logs] == list(range(2501))
    assert cursors == [-1, 999, 1999]
    assert all(identity != main_thread for identity in worker_threads)
    assert chunks[-1].startswith('event: status\n')
    assert json.loads(chunks[-1].split('data: ', 1)[1])['log_count'] == 2501

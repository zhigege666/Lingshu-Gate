"""Observe late responses without replaying or terminating downstream work."""
from __future__ import annotations

import io
import json
import queue
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from lingshu_gate.config import Settings
from lingshu_gate.domain.mcp_request_outcome import (
    MAX_REQUEST_OUTCOME_NODES,
    McpRequestTimeout,
    RequestOutcomeStore,
    find_request_timeout,
)
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_stdio_client import StdioMcpClient
from lingshu_gate.protocol.version import MCP_PROTOCOL_VERSION


PEER = r'''
import json
import sys
import time
from pathlib import Path

root = Path(sys.argv[1])
for line in sys.stdin:
    request = json.loads(line)
    method = request['method']
    with (root / 'received-methods').open('a') as trace:
        trace.write(method + '\n')
    if method == 'server/discover':
        response = {'result': {'supportedVersions': [sys.argv[2]], 'capabilities': {'tools': {}}}}
    elif method == 'tools/call':
        arguments = request['params']['arguments']
        if request['params']['name'] == 'delayed':
            (root / 'started').write_text('started')
            while not (root / 'release').exists():
                time.sleep(0.002)
        response = arguments.get('response', {'result': {'content': [], 'structuredContent': {'exit_code': 0}}})
    elif method == 'notifications/initialized':
        continue
    else:
        response = {'error': {'code': -32601, 'message': 'Method not found'}}
    print(json.dumps({'jsonrpc': '2.0', 'id': request['id'], **response}), flush=True)
'''


def _client(root: Path, log_sink=None) -> StdioMcpClient:
    peer = root / 'peer.py'
    peer.write_text(PEER, encoding='utf-8')
    manifest = McpServerManifest.model_validate({
        'id': 'request-outcome-peer',
        'launch': {'type': 'managed_process', 'command': sys.executable,
                   'args': [str(peer), str(root), MCP_PROTOCOL_VERSION]},
        'transport': {'type': 'stdio'},
        'timeout_seconds': 3,
    })
    return StdioMcpClient(manifest, Settings(data_dir=root / 'data', allowed_root=root), log_sink=log_sink)


def _completed(client: StdioMcpClient, handle: str) -> dict:
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        result = client.get_request_outcome(handle)
        if result and result['state'] != 'waiting':
            return result
        time.sleep(0.005)
    pytest.fail('The controlled peer did not deliver its released response')


@pytest.mark.parametrize('reply', [
    {'result': {'content': [], 'structuredContent': {'exit_code': 0, 'stdout': 'done'}}},
    {'result': {'content': [{'type': 'text', 'text': 'command failed'}], 'isError': True}},
    {'error': {'code': -32000, 'message': 'cancelled by execution service'}},
])
def test_timeout_retains_late_original_response_without_replay_or_cancel(tmp_path, reply):
    logs: list[tuple] = []
    client = _client(tmp_path, log_sink=lambda *args: logs.append(args))
    try:
        client.start()
        client.last_stdout.append('stdout-private-canary')
        client.last_stderr.append('stderr-private-canary')
        with pytest.raises(McpRequestTimeout) as caught:
            client.request('tools/call', {'name': 'delayed', 'arguments': {
                'password': 'argument-private-canary', 'response': reply,
            }}, timeout=0.03)
        failure = caught.value
        assert isinstance(failure, TimeoutError)
        assert failure.code == 'mcp_request_timeout'
        assert failure.details['dispatch_state'] == 'sent'
        assert failure.details['execution_state'] == 'unknown'
        assert failure.details['execution_terminated'] is False
        assert failure.details['recovery_scope'] == 'current_process'
        assert failure.request_handle and failure.connection_generation
        assert callable(failure.outcome_reader)
        assert 'outcome_reader' not in failure.details
        assert failure.outcome_reader()['state'] == 'waiting'
        for secret in ['argument-private-canary', 'stdout-private-canary', 'stderr-private-canary']:
            assert secret not in str(failure)
            assert secret not in repr(failure.details)
            assert secret not in repr(logs)
        assert client.process is not None and client.process.poll() is None
        (tmp_path / 'release').write_text('release', encoding='utf-8')
        outcome = _completed(client, failure.request_handle)
        assert outcome['state'] == 'completed'
        assert {key: outcome['response'][key] for key in reply} == reply
        assert outcome['connection_generation'] == failure.connection_generation
        # A caller cannot mutate the retained result used by a later query.
        outcome['response'].clear()
        assert client.get_request_outcome(failure.request_handle)['response']
        assert (tmp_path / 'received-methods').read_text().splitlines().count('tools/call') == 1
        assert 'notifications/cancelled' not in (tmp_path / 'received-methods').read_text()
        assert client.call_tool('immediate', {})['structuredContent']['exit_code'] == 0
    finally:
        client.stop()


def test_protocol_timeout_does_not_claim_business_dispatch():
    failure = McpRequestTimeout(method='server/discover', timeout_seconds=3,
                                transport='streamable_http', recovery_supported=False,
                                dispatch_state='unknown', phase='connect')
    assert failure.details['business_request'] is False
    assert failure.details['execution_state'] == 'not_started'
    assert failure.details['recovery_scope'] == 'none'
    before_dispatch = McpRequestTimeout(method='tools/call', timeout_seconds=3,
                                        dispatch_state='not_dispatched', recovery_supported=False)
    assert before_dispatch.details['execution_state'] == 'not_started'


def test_timeout_lookup_uses_only_explicit_cycle_safe_causes():
    failure = McpRequestTimeout(method='tools/call', timeout_seconds=3)
    wrapped = RuntimeError('protocol wrapper')
    wrapped.__cause__ = failure
    assert find_request_timeout(wrapped) is failure
    hidden = RuntimeError('MCP request timed out')
    hidden.__context__ = failure
    assert find_request_timeout(hidden) is None
    first, second = RuntimeError('first'), RuntimeError('second')
    first.__cause__, second.__cause__ = second, first
    assert find_request_timeout(first) is None


class _Process:
    def __init__(self, output: str = '') -> None:
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(output)
        self.returncode = None

    def poll(self):
        return self.returncode


def test_response_at_wait_deadline_is_returned_instead_of_lost(tmp_path):
    client = _client(tmp_path)
    process = _Process()
    client.process = process
    reply = {'content': [], 'structuredContent': {'exit_code': 7}}

    def write_and_receive(message, **_kwargs):
        process.stdout = io.StringIO(json.dumps({'jsonrpc': '2.0', 'id': message['id'], 'result': reply}) + '\n')
        client._read_stdout()

    # The response is delivered before the expired-deadline branch gets the
    # shared response lock. This exact ordering previously discarded the queue.
    with patch.object(client, '_write_message', side_effect=write_and_receive), \
            patch('lingshu_gate.mcp_stdio_client.time.monotonic', side_effect=[0, 2]):
        assert client.request('tools/call', {'name': 'immediate', 'arguments': {}}, timeout=1) == reply


def test_restart_marks_unknown_receipt_and_old_reader_cannot_complete_new_call(tmp_path):
    client = _client(tmp_path)
    try:
        client.start()
        with pytest.raises(McpRequestTimeout) as caught:
            client.request('tools/call', {'name': 'delayed', 'arguments': {}}, timeout=0.03)
        failure = caught.value
        old_generation = failure.connection_generation
        client.stop()
        assert client.get_request_outcome(failure.request_handle)['state'] == 'interrupted'
        client.start()
        assert client._connection_generation != old_generation
        # Even an identical request ID from an old reader cannot reach a
        # current-generation waiter or change its receipt.
        current_response = queue.Queue()
        client._responses[99] = current_response
        old_process = _Process(json.dumps({'jsonrpc': '2.0', 'id': 99, 'result': {'old': True}}) + '\n')
        client._read_stdout(old_process, old_generation)
        assert current_response.empty()
        assert client._responses.pop(99) is current_response
        assert client.get_request_outcome(failure.request_handle)['state'] == 'interrupted'
        assert client.call_tool('immediate', {})['structuredContent']['exit_code'] == 0
    finally:
        client.stop()


def test_receipt_count_ttl_and_byte_limits_are_explicit_and_release_capacity():
    tick = [1.0]
    first_response = {'jsonrpc': '2.0', 'id': 1, 'result': {'text': '中文'}}
    size = len(json.dumps(first_response, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
    store = RequestOutcomeStore(max_entries=2, max_response_bytes=size, ttl_seconds=5, clock=lambda: tick[0])
    store.retain('first', 'generation', 1, 'tools/call')
    assert store.complete('generation', 1, first_response)
    first_response['result']['text'] = 'changed after delivery'
    assert store.get('first')['response']['result']['text'] == '中文'
    store.retain('second', 'generation', 2, 'tools/call')
    assert store.complete('generation', 2, {'jsonrpc': '2.0', 'id': 2, 'result': {}})
    assert store.get('second')['state'] == 'unavailable'
    assert store.get('second')['unavailable_reason'] == 'response_byte_limit'
    assert store.get('second')['response'] is None
    store.retain('third', 'generation', 3, 'tools/call')
    assert store.get('first') is None  # Count eviction also releases result bytes.
    assert store.complete('generation', 3, {'jsonrpc': '2.0', 'id': 3, 'result': {}})
    assert store.get('third')['state'] == 'completed'
    tick[0] = 7
    assert store.get('second') is None and store.get('third') is None
    assert not store.complete('generation', 2, {'result': {}})


def test_connection_generation_is_part_of_late_response_identity():
    store = RequestOutcomeStore()
    store.retain('old', 'old-generation', 1, 'tools/call')
    store.interrupt_generation('old-generation')
    store.retain('new', 'new-generation', 1, 'tools/call')
    assert not store.complete('old-generation', 1, {'result': {'wrong': True}})
    assert store.get('old')['state'] == 'interrupted'
    assert store.get('new')['state'] == 'waiting'
    assert store.complete('new-generation', 1, {'result': {'correct': True}})
    assert store.get('new')['response'] == {'result': {'correct': True}}


@pytest.mark.parametrize(('payload', 'reason'), [
    ('[' * 600 + '0' + ']' * 600, 'response_complexity_limit'),
    ('"\\ud800"', 'response_invalid_json'),
    ('[' + ','.join(['0'] * MAX_REQUEST_OUTCOME_NODES) + ']', 'response_complexity_limit'),
    ('NaN', 'response_invalid_json'),
], ids=['deep-json', 'invalid-unicode', 'node-limit', 'non-finite-number'])
def test_unrecoverable_response_does_not_break_later_stdout_delivery(tmp_path, payload, reason):
    client = _client(tmp_path)
    generation = client._connection_generation
    client._request_outcomes.retain('invalid', generation, 1, 'tools/call')
    client._request_outcomes.retain('valid', generation, 2, 'tools/call')
    normal = {'jsonrpc': '2.0', 'id': 2, 'result': {'content': [], 'structuredContent': {'exit_code': 0}}}
    # Both responses traverse the actual reader. A failed retention must allow
    # the next frame through, even for small but deeply nested legal JSON.
    client.process = _Process('{"jsonrpc":"2.0","id":1,"result":' + payload + '}\n'
                              + json.dumps(normal) + '\n')
    client._read_stdout()
    unavailable = client.get_request_outcome('invalid')
    assert unavailable['state'] == 'unavailable'
    assert unavailable['unavailable_reason'] == reason
    assert unavailable['response'] is None
    completed = client.get_request_outcome('valid')
    assert completed['state'] == 'completed'
    assert completed['response'] == normal
    # This is the same safe boundary used to serialize a status response.
    json.dumps(unavailable, ensure_ascii=False, allow_nan=False).encode('utf-8')
    json.dumps(completed, ensure_ascii=False, allow_nan=False).encode('utf-8')

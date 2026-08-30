"""Hard resource-boundary tests for downstream protocol and build processes."""

from __future__ import annotations

import io
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from lingshu_gate.build_deploy import MAX_CAPTURE_CHARS, _run_command
from lingshu_gate.config import Settings
from lingshu_gate.mcp_http_client import StreamableHttpMcpClient
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_stdio_client import McpProtocolError, StdioMcpClient


class _MemoryResponse:
    def __init__(
        self,
        body: bytes,
        *,
        content_type: str = "application/json",
        content_length: int | None = None,
    ) -> None:
        self.status = 200
        self.headers = {"Content-Type": content_type}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)
        self._stream = io.BytesIO(body)

    def __enter__(self) -> _MemoryResponse:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def read1(self, size: int = -1) -> bytes:
        return self._stream.read(size)


class _FakeStdioProcess:
    def __init__(self, stdout: str = "") -> None:
        self.pid = 1234
        self.returncode: int | None = None
        self.stdin = io.StringIO()
        self.stdout = io.StringIO(stdout)
        self.stderr = io.StringIO()
        self.terminated = False

    def poll(self) -> int | None:
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True
        self.returncode = -15


def _manifest(transport_type: str) -> McpServerManifest:
    if transport_type == "stdio":
        return McpServerManifest.model_validate(
            {
                "id": "bounded-stdio",
                "launch": {"type": "managed_process", "command": "server"},
                "transport": {"type": "stdio"},
            }
        )
    return McpServerManifest.model_validate(
        {
            "id": "bounded-http",
            "launch": {"type": "external"},
            "transport": {
                "type": "streamable_http",
                "endpoint": "https://mcp.example.test/mcp",
            },
        }
    )


def _http_client(root: Path) -> StreamableHttpMcpClient:
    return StreamableHttpMcpClient(_manifest("streamable_http"), Settings(data_dir=root))


def _stdio_client(root: Path) -> StdioMcpClient:
    return StdioMcpClient(_manifest("stdio"), Settings(data_dir=root))


def test_http_rejects_declared_and_streamed_oversized_responses() -> None:
    with tempfile.TemporaryDirectory() as directory:
        client = _http_client(Path(directory))
        with (
            patch("lingshu_gate.mcp_http_client.MAX_HTTP_RESPONSE_BYTES", 32),
            patch.object(
                client._opener,
                "open",
                return_value=_MemoryResponse(b"{}", content_length=33),
            ),
            pytest.raises(McpProtocolError, match="byte limit"),
        ):
            client.request("tools/list")

        with (
            patch("lingshu_gate.mcp_http_client.MAX_HTTP_RESPONSE_BYTES", 32),
            patch.object(
                client._opener,
                "open",
                return_value=_MemoryResponse(b"{" + b"x" * 64 + b"}"),
            ),
            pytest.raises(McpProtocolError, match="byte limit"),
        ):
            client.request("tools/list")


def test_http_sse_enforces_event_count_event_size_and_absolute_deadline() -> None:
    with tempfile.TemporaryDirectory() as directory:
        client = _http_client(Path(directory))
        events = b"".join(
            f'data: {{"jsonrpc":"2.0","id":{identifier}}}\n\n'.encode()
            for identifier in (11, 12, 13)
        )
        with (
            patch("lingshu_gate.mcp_http_client.MAX_SSE_EVENTS", 2),
            pytest.raises(McpProtocolError, match="event limit"),
        ):
            client._read_sse_response(
                _MemoryResponse(events, content_type="text/event-stream"),
                request_id=99,
                deadline=time.monotonic() + 5,
            )

        oversized_event = b"data: " + b"x" * 33 + b"\n\n"
        with (
            patch("lingshu_gate.mcp_http_client.MAX_SSE_EVENT_BYTES", 32),
            pytest.raises(McpProtocolError, match="event exceeded"),
        ):
            client._read_sse_response(
                _MemoryResponse(oversized_event, content_type="text/event-stream"),
                request_id=1,
                deadline=time.monotonic() + 5,
            )

        with pytest.raises(TimeoutError, match="deadline expired"):
            client._read_sse_response(
                _MemoryResponse(b": keepalive\n\n", content_type="text/event-stream"),
                request_id=1,
                deadline=time.monotonic() - 1,
            )


@pytest.mark.parametrize("transport_type", ["streamable_http", "stdio"])
def test_tool_pagination_rejects_repeated_cursor_and_tool_overflow(
    transport_type: str,
) -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        client = (
            _http_client(root)
            if transport_type == "streamable_http"
            else _stdio_client(root)
        )
        client.request = Mock(
            side_effect=[
                {"tools": [{"name": "first"}], "nextCursor": "again"},
                {"tools": [{"name": "second"}], "nextCursor": "again"},
            ]
        )
        with pytest.raises(McpProtocolError, match="repeated cursor"):
            client.list_tools()

        client.request = Mock(return_value={"tools": [{"name": "a"}, {"name": "b"}]})
        module = (
            "lingshu_gate.mcp_http_client.MAX_DISCOVERED_TOOLS"
            if transport_type == "streamable_http"
            else "lingshu_gate.mcp_stdio_client.MAX_DISCOVERED_TOOLS"
        )
        with patch(module, 1), pytest.raises(McpProtocolError, match="tool limit"):
            client.list_tools()


def test_tool_pagination_has_a_hard_page_limit() -> None:
    with tempfile.TemporaryDirectory() as directory:
        client = _http_client(Path(directory))
        client.request = Mock(
            side_effect=lambda _method, params: {
                "tools": [],
                "nextCursor": f"cursor-{len(client.request.call_args_list)}-{params}",
            }
        )
        with (
            patch("lingshu_gate.mcp_http_client.MAX_TOOL_LIST_PAGES", 2),
            pytest.raises(McpProtocolError, match="page limit"),
        ):
            client.list_tools()
        assert client.request.call_count == 2


def test_stdio_rejects_oversized_outbound_and_inbound_messages() -> None:
    with tempfile.TemporaryDirectory() as directory:
        client = _stdio_client(Path(directory))
        process = _FakeStdioProcess()
        client.process = process  # type: ignore[assignment]
        with (
            patch("lingshu_gate.mcp_stdio_client.MAX_STDIO_MESSAGE_BYTES", 32),
            pytest.raises(McpProtocolError, match="byte limit"),
        ):
            client._write_message({"value": "x" * 64})
        assert process.stdin.getvalue() == ""

        process = _FakeStdioProcess("x" * 33 + "\n")
        client.process = process  # type: ignore[assignment]
        with patch("lingshu_gate.mcp_stdio_client.MAX_STDIO_MESSAGE_BYTES", 32):
            client._read_stdout()
        assert client._fatal_protocol_error is not None
        assert process.terminated
        assert "x" * 8 not in repr(client.last_stdout)


def test_build_output_is_streamed_into_bounded_tail_buffers() -> None:
    payload_size = MAX_CAPTURE_CHARS * 10
    script = (
        "import sys; "
        f"sys.stdout.write('a'*{payload_size}+'stdout-tail'); "
        f"sys.stderr.write('b'*{payload_size}+'stderr-tail')"
    )
    with tempfile.TemporaryDirectory() as directory:
        result = _run_command(
            [sys.executable, "-c", script],
            Path(directory),
            10,
            dict(os.environ),
        )

    assert result["returncode"] == 0
    assert len(result["stdout"]) <= MAX_CAPTURE_CHARS
    assert len(result["stderr"]) <= MAX_CAPTURE_CHARS
    assert result["stdout"].endswith("stdout-tail")
    assert result["stderr"].endswith("stderr-tail")


def test_build_timeout_and_cancellation_stop_the_running_group() -> None:
    with tempfile.TemporaryDirectory() as directory:
        timeout_result = _run_command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            Path(directory),
            1,
            dict(os.environ),
        )
        cancel_started = time.monotonic()
        cancel_result = _run_command(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            Path(directory),
            10,
            dict(os.environ),
            cancel_requested=lambda: time.monotonic() - cancel_started > 0.2,
        )

    assert timeout_result["returncode"] == 124
    assert "timed out" in timeout_result["stderr"]
    assert cancel_result["returncode"] == 130
    assert cancel_result["cancelled"] is True
    assert "cancelled" in cancel_result["stderr"]
    assert time.monotonic() - cancel_started < 3


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group regression")
def test_build_timeout_terminates_descendants_in_the_process_group() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        marker = root / "escaped-child.txt"
        child_script = (
            "import time; from pathlib import Path; "
            f"time.sleep(1.5); Path({str(marker)!r}).write_text('escaped')"
        )
        parent_script = (
            "import subprocess, sys, time; "
            f"subprocess.Popen([sys.executable, '-c', {child_script!r}]); "
            "time.sleep(30)"
        )
        result = _run_command(
            [sys.executable, "-c", parent_script],
            root,
            1,
            dict(os.environ),
        )
        time.sleep(1)

        assert result["returncode"] == 124
        assert not marker.exists()

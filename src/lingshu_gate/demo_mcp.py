"""An explicitly started, bounded in-memory MCP server for the first call."""
from __future__ import annotations

from threading import Lock
from typing import Annotated, Any

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.applications import Starlette

from lingshu_gate import __version__

DemoText = Annotated[str, Field(max_length=4096, strict=True)]


def create_demo_app() -> Starlette:
    """Create a fresh note; no files, credentials, commands or external I/O."""
    server = MCPServer("Lingshu Gate demo", version=__version__)
    lock = Lock()
    note: dict[str, Any] = {"text": "Hello from the Gate demo", "revision": 0, "write_count": 0}

    @server.tool(annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False),
                 structured_output=False)
    def gate_demo_echo(message: DemoText) -> str:
        """Return a message of at most 4096 characters without changing anything."""
        return message

    @server.tool(annotations=ToolAnnotations(read_only_hint=True, idempotent_hint=True, open_world_hint=False))
    def gate_demo_note_read() -> dict[str, Any]:
        """Read the demo's in-memory note and write counter. Restarting clears it."""
        with lock:
            return dict(note)

    @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                            idempotent_hint=False, open_world_hint=False))
    def gate_demo_note_write(text: DemoText) -> dict[str, Any]:
        """Replace only this demo process's in-memory note and increment its counter."""
        with lock:
            note.update(text=text, revision=note["revision"] + 1, write_count=note["write_count"] + 1)
            return dict(note)

    return server.streamable_http_app(streamable_http_path="/mcp", json_response=True,
                                      stateless_http=True, max_request_body_size=65_536)

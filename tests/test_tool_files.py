"""Gate 通用 fileRef 存储与 MCP 工具测试。"""

from __future__ import annotations

import base64
import hashlib
import tempfile
import unittest
from pathlib import Path

from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.registry import ToolInvocationContext
from lingshu_gate.tool_file_mcp import TOOL_FILE_DEFINITIONS, ToolFileMcpService
from lingshu_gate.tool_files import ToolFileError, ToolFileStore


class ToolFileTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp_dir.name)
        self.database = SQLiteDatabase(f"sqlite:///{self.root / 'gate.db'}", self.root)
        self.store = ToolFileStore(self.database, self.root)
        self.context = ToolInvocationContext(
            actor_id="user-a",
            username="tester",
            auth_type="session",
            token_id=None,
            correlation_id="test-correlation",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_definitions_include_four_contextual_upload_steps(self) -> None:
        self.assertEqual(
            {definition.id for definition in TOOL_FILE_DEFINITIONS},
            {
                "gate_file_upload_begin",
                "gate_file_upload_chunk",
                "gate_file_upload_commit",
                "gate_file_upload_abort",
            },
        )
        chunk = next(item for item in TOOL_FILE_DEFINITIONS if item.id.endswith("_chunk"))
        self.assertEqual(chunk.metadata["sensitive_input_fields"], ["data_base64"])

    def test_upload_commit_and_resolve_are_owner_bound(self) -> None:
        content = "自测报告".encode()
        digest = hashlib.sha256(content).hexdigest()
        transfer = self.store.begin(
            actor_id="user-a",
            filename="自测报告.md",
            size_bytes=len(content),
            sha256=digest,
            idempotency_key="begin-test-0001",
        )
        first = self.store.append_chunk(
            actor_id="user-a",
            transfer_id=str(transfer["transfer_id"]),
            offset=0,
            data=content,
            chunk_sha256=digest,
            idempotency_key="chunk-test-0001",
        )
        repeated = self.store.append_chunk(
            actor_id="user-a",
            transfer_id=str(transfer["transfer_id"]),
            offset=0,
            data=content,
            chunk_sha256=digest,
            idempotency_key="chunk-test-0001",
        )
        self.assertEqual(first["received_bytes"], repeated["received_bytes"])
        committed = self.store.commit(
            actor_id="user-a",
            transfer_id=str(transfer["transfer_id"]),
            idempotency_key="commit-test-001",
        )
        resolved = self.store.resolve(actor_id="user-a", file_ref=str(committed["fileRef"]))
        self.assertEqual(resolved.read_bytes(), content)
        with self.assertRaisesRegex(ToolFileError, "不属于当前用户"):
            self.store.resolve(actor_id="user-b", file_ref=str(committed["fileRef"]))

    def test_prepare_arguments_replaces_only_top_level_file_ref(self) -> None:
        content = b"hello"
        digest = hashlib.sha256(content).hexdigest()
        transfer = self.store.begin(
            actor_id="user-a",
            filename="hello.txt",
            size_bytes=len(content),
            sha256=digest,
            idempotency_key="begin-test-0002",
        )
        self.store.append_chunk(
            actor_id="user-a",
            transfer_id=str(transfer["transfer_id"]),
            offset=0,
            data=content,
            chunk_sha256=digest,
            idempotency_key="chunk-test-0002",
        )
        committed = self.store.commit(
            actor_id="user-a",
            transfer_id=str(transfer["transfer_id"]),
            idempotency_key="commit-test-002",
        )
        prepared = self.store.prepare_tool_arguments(
            actor_id="user-a",
            arguments={"id": 1728873, "fileRef": committed["fileRef"]},
        )
        self.assertNotIn("fileRef", prepared)
        self.assertTrue(Path(str(prepared["filePath"])).is_file())
        with self.assertRaisesRegex(ToolFileError, "不能同时传入"):
            self.store.prepare_tool_arguments(
                actor_id="user-a",
                arguments={"fileRef": committed["fileRef"], "filePath": "x"},
            )

    def test_mcp_service_decodes_chunk_and_returns_file_ref(self) -> None:
        service = ToolFileMcpService(self.store)
        content = b"mcp"
        digest = hashlib.sha256(content).hexdigest()
        transfer = service.begin(
            {
                "filename": "mcp.txt",
                "size_bytes": len(content),
                "sha256": digest,
                "idempotency_key": "begin-test-0003",
                "confirmed": True,
            },
            self.context,
        )
        service.chunk(
            {
                "transfer_id": transfer["transfer_id"],
                "offset": 0,
                "data_base64": base64.b64encode(content).decode(),
                "chunk_sha256": digest,
                "idempotency_key": "chunk-test-0003",
            },
            self.context,
        )
        result = service.commit(
            {"transfer_id": transfer["transfer_id"], "idempotency_key": "commit-test-003"},
            self.context,
        )
        self.assertTrue(str(result["fileRef"]).startswith("gate_file_"))


if __name__ == "__main__":
    unittest.main()

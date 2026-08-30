"""项目交付 MCP 工具的轻量契约与上传链路测试。"""

from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.project_delivery_mcp import (
    PROJECT_DELIVERY_TOOL_DEFINITIONS,
    ProjectDeliveryMcpService,
)
from lingshu_gate.mcp_runtime import McpManifestDigestConflict
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.models import ToolDefinition
from lingshu_gate.project_uploads import ProjectUploadStore
from lingshu_gate.registry import (
    ToolExecutionError,
    ToolInvocationContext,
    ToolRegistry,
)


EXPECTED_TOOL_IDS = {
    "gate_project_upload_begin",
    "gate_project_upload_chunk",
    "gate_project_upload_commit",
    "gate_project_upload_abort",
    "gate_build_preflight",
    "gate_build_plan",
    "gate_build_create",
    "gate_build_status",
    "gate_build_cancel",
    "gate_deploy_build",
    "gate_deployment_status",
    "gate_server_start",
    "gate_server_status",
    "gate_server_refresh_tools",
}

CONFIRMED_TOOL_IDS = {
    "gate_project_upload_begin",
    "gate_project_upload_abort",
    "gate_build_create",
    "gate_build_cancel",
    "gate_deploy_build",
    "gate_server_start",
    "gate_server_refresh_tools",
}


def assert_json_schema_instance(
    testcase: unittest.TestCase,
    instance: object,
    schema: dict[str, object],
    *,
    path: str = "$",
) -> None:
    """覆盖当前 MCP outputSchema 使用面的严格 JSON Schema 实例校验。"""

    type_names = schema.get("type")
    if isinstance(type_names, str):
        type_names = [type_names]
    if isinstance(type_names, list):
        matches_type = {
            "object": lambda value: isinstance(value, dict),
            "array": lambda value: isinstance(value, list),
            "string": lambda value: isinstance(value, str),
            "boolean": lambda value: isinstance(value, bool),
            "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
            "number": lambda value: isinstance(value, (int, float)) and not isinstance(value, bool),
            "null": lambda value: value is None,
        }
        testcase.assertTrue(
            any(
                isinstance(type_name, str)
                and type_name in matches_type
                and matches_type[type_name](instance)
                for type_name in type_names
            ),
            f"{path} 不匹配 JSON Schema type={type_names!r}: {instance!r}",
        )

    required = schema.get("required")
    if isinstance(required, list):
        testcase.assertIsInstance(instance, dict, f"{path} 必须是对象")
        for key in required:
            testcase.assertIn(key, instance, f"{path} 缺少必填字段 {key}")

    if isinstance(instance, dict):
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for key, value in instance.items():
                property_schema = properties.get(key)
                if isinstance(property_schema, dict):
                    assert_json_schema_instance(
                        testcase,
                        value,
                        property_schema,
                        path=f"{path}.{key}",
                    )
                elif schema.get("additionalProperties") is False:
                    testcase.fail(f"{path} 不允许额外字段 {key}")

    variants = schema.get("oneOf")
    if isinstance(variants, list):
        matched = 0
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            try:
                assert_json_schema_instance(testcase, instance, variant, path=path)
            except AssertionError:
                continue
            matched += 1
        testcase.assertEqual(matched, 1, f"{path} 必须且只能匹配一个 oneOf 分支")


class FakeObservability:
    def __init__(self) -> None:
        self.events: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def emit_event(self, *args: object, **kwargs: object) -> None:
        self.events.append((args, kwargs))


class FakeManifest:
    def __init__(self, payload: dict[str, object]) -> None:
        self.manifest = McpServerManifest.model_validate(payload)
        self.payload = self.manifest.model_dump(mode="json", exclude={"manifest_path"})

    def model_dump(self, **kwargs: object) -> dict[str, object]:
        return self.manifest.model_dump(**kwargs)

    def __getattr__(self, name: str) -> object:
        return getattr(self.manifest, name)


class FakeConfigStore:
    def __init__(self) -> None:
        self.manifests: dict[str, FakeManifest] = {}

    def load_manifest(self, server_id: str) -> FakeManifest:
        try:
            return self.manifests[server_id]
        except KeyError as exc:
            raise KeyError(server_id) from exc


class FakeRuntime:
    def __init__(self) -> None:
        self.servers: dict[str, SimpleNamespace] = {}
        self.manifest_digests: dict[str, str] = {}
        self.start_requests: list[tuple[str, str]] = []
        self.refresh_requests: list[str] = []

    def get_server(self, server_id: str) -> SimpleNamespace:
        try:
            return self.servers[server_id]
        except KeyError as exc:
            raise KeyError(server_id) from exc

    def has_server(self, server_id: str) -> bool:
        return server_id in self.servers

    def add_server(
        self,
        server_id: str,
        *,
        status: str = "stopped",
        manifest_digest: str | None = None,
    ) -> None:
        self.servers[server_id] = SimpleNamespace(
            id=server_id,
            status=status,
            desired_state="running" if status == "running" else "stopped",
            effective_should_run=status == "running",
            tool_count=2 if status == "running" else 0,
            health_status="healthy" if status == "running" else "unknown",
            last_error=None,
            pid=1234 if status == "running" else None,
            desired_state_updated_at="2026-08-12T00:00:00+00:00",
        )
        if manifest_digest is not None:
            self.manifest_digests[server_id] = manifest_digest

    def get_manifest_digest(self, server_id: str) -> str:
        self.get_server(server_id)
        return self.manifest_digests[server_id]

    def request_start_if_manifest_digest(
        self,
        server_id: str,
        expected_manifest_digest: str,
    ) -> SimpleNamespace:
        self.start_requests.append((server_id, expected_manifest_digest))
        actual = self.get_manifest_digest(server_id)
        if actual != expected_manifest_digest.lower():
            raise McpManifestDigestConflict(server_id, expected_manifest_digest, actual)
        server = self.get_server(server_id)
        server.status = "running"
        server.desired_state = "running"
        server.effective_should_run = True
        server.tool_count = 2
        server.health_status = "healthy"
        server.pid = 1234
        return server

    def refresh_server_tools(
        self,
        server_id: str,
        *,
        before_replace: object | None = None,
    ) -> dict[str, object]:
        self.get_server(server_id)
        self.refresh_requests.append(server_id)
        definitions = [
            ToolDefinition(
                id=f"mcp:{server_id}:read_file",
                server_id=server_id,
                name="read_file",
                description="读取文件",
                input_schema={"type": "object"},
                source="mcp",
            )
        ]
        if callable(before_replace):
            before_replace(definitions)
        return {
            "server_id": server_id,
            "tool_count": 1,
            "removed_count": 0,
            "registered_count": 1,
            "tool_snapshot_digest": "d" * 64,
            "definitions": definitions,
        }


class FakeBuildStore:
    """只返回受控记录，不创建构建线程，也不执行计划命令。"""

    def __init__(
        self,
        database: SQLiteDatabase,
        configs: FakeConfigStore,
        runtime: FakeRuntime,
    ) -> None:
        self.database = database
        self.configs = configs
        self.runtime = runtime
        self.records: dict[str, dict[str, object]] = {}
        self.deployments: dict[str, dict[str, object]] = {}
        self.logs: dict[str, list[dict[str, object]]] = {}
        self.build_upload_calls: list[dict[str, object]] = []
        self.deploy_calls: list[dict[str, object]] = []

    def plan_upload(self, upload_id: str, **_: object) -> dict[str, object]:
        return {
            "preflight": {
                "status": "ok",
                "runtime": "node",
                "project_root_dir": "project",
            },
            "plan": {
                "ir_version": 1,
                "runtime": "node",
                "buildable": True,
                "project_root_dir": "project",
                "steps": [
                    {
                        "id": "node-install",
                        "phase": "install",
                        "command": ["npm", "ci"],
                        "depends_on": [],
                    }
                ],
                "artifact": {"strategy": "copy_tree", "ignore": []},
                "manifest": {
                    "launch_type": "managed_process",
                    "transport": "stdio",
                    "runtime": "node",
                },
                "warnings": [],
                "notes": [f"fake plan for {upload_id}; never executed"],
            },
            "validation": {"ok": True, "errors": []},
        }

    def build_upload(self, upload_id: str, **kwargs: object) -> dict[str, object]:
        self.build_upload_calls.append(dict(kwargs))
        build_id = f"build-fake-{len(self.build_upload_calls):06d}"
        now = "2026-08-12T00:00:00+00:00"
        self.database.execute(
            """
            INSERT INTO builds (
                id, upload_id, status, runtime, source_dir, artifact_dir,
                command_json, logs_json, manifest_json, plan_json, steps_json,
                created_at, updated_at
            ) VALUES (?, ?, 'queued', 'node', ?, ?, '[]', '[]', '{}', '{}', '[]', ?, ?)
            """,
            (build_id, upload_id, "fake-source", "fake-artifact", now, now),
        )
        record: dict[str, object] = {
            "id": build_id,
            "upload_id": upload_id,
            "status": "queued",
            "runtime": "node",
            "source_sha256": "",
            "plan_fingerprint": "",
            "steps": [],
            "manifest": {},
            "created_at": now,
            "updated_at": now,
        }
        self.records[build_id] = record
        return copy.deepcopy(record)

    def get_build(self, build_id: str) -> dict[str, object]:
        try:
            result = copy.deepcopy(self.records[build_id])
        except KeyError as exc:
            raise KeyError(build_id) from exc
        row = self.database.query_one(
            "SELECT source_sha256, plan_fingerprint FROM builds WHERE id = ?",
            (build_id,),
        )
        if row is not None:
            result["source_sha256"] = str(row["source_sha256"])
            result["plan_fingerprint"] = str(row["plan_fingerprint"])
        return result

    def list_build_logs(
        self,
        build_id: str,
        *,
        limit: int,
        after_sequence: int,
    ) -> list[dict[str, object]]:
        return [
            copy.deepcopy(row)
            for row in self.logs.get(build_id, [])
            if int(row.get("sequence") or 0) > after_sequence
        ][:limit]

    def deploy_build(
        self,
        build_id: str,
        *,
        server_id: str,
        start: bool,
        overwrite: bool,
        owner_id: str | None = None,
        manifest_override: dict[str, object] | None = None,
    ) -> dict[str, object]:
        self.deploy_calls.append(
            {
                "build_id": build_id,
                "server_id": server_id,
                "start": start,
                "overwrite": overwrite,
                "owner_id": owner_id,
                "manifest_override": copy.deepcopy(manifest_override),
            }
        )
        self.configs.manifests[server_id] = FakeManifest(
            manifest_override or {
                "id": server_id,
                "name": "Fake deployed server",
                "enabled": True,
                "launch": {
                    "type": "managed_process",
                    "command": "node",
                    "args": ["index.js"],
                },
                "transport": {"type": "stdio"},
            }
        )
        self.runtime.add_server(server_id, status="running" if start else "stopped")
        deployment = {
            "id": f"deployment-fake-{len(self.deploy_calls):06d}",
            "build_id": build_id,
            "server_id": server_id,
            "status": "success",
            "started": start,
            "config_applied": True,
            "runtime_started": start,
            "rollback_attempted": False,
            "rollback_succeeded": None,
            "rollback_error": None,
        }
        self.deployments[str(deployment["id"])] = copy.deepcopy(deployment)
        return deployment

    def get_deployment(self, deployment_id: str) -> dict[str, object]:
        try:
            return copy.deepcopy(self.deployments[deployment_id])
        except KeyError as exc:
            raise KeyError(deployment_id) from exc


def create_project_zip() -> bytes:
    """生成只用于安全解压和分析的最小 Node 项目，不执行其中代码。"""

    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "package.json",
            '{"name":"delivery-test","version":"1.0.0","scripts":{"start":"node index.js"}}',
        )
        archive.writestr("index.js", "console.log('delivery-test');\n")
    return stream.getvalue()


class ProjectDeliveryToolContractTest(unittest.TestCase):
    def test_all_fourteen_tools_publish_schema_annotations_and_permissions(self) -> None:
        definitions = {item.id: item for item in PROJECT_DELIVERY_TOOL_DEFINITIONS}

        self.assertEqual(set(definitions), EXPECTED_TOOL_IDS)
        self.assertEqual(len(definitions), 14)
        for definition in definitions.values():
            with self.subTest(tool_id=definition.id):
                self.assertEqual(definition.source, "builtin")
                self.assertEqual(definition.input_schema.get("type"), "object")
                self.assertIsInstance(definition.input_schema.get("properties"), dict)
                self.assertEqual(
                    definition.metadata.get("required_control_permission"),
                    "operations.manage",
                )
                output_schema = definition.metadata.get("outputSchema")
                self.assertIsInstance(output_schema, dict)
                self.assertEqual(output_schema.get("type"), "object")
                variants = output_schema.get("oneOf", [])
                self.assertIn({"required": ["status"]}, variants)
                self.assertIn({"required": ["error"]}, variants)
                annotations = definition.metadata.get("annotations")
                self.assertEqual(
                    set(annotations or {}),
                    {
                        "readOnlyHint",
                        "destructiveHint",
                        "idempotentHint",
                        "openWorldHint",
                    },
                )
                self.assertTrue(annotations["idempotentHint"])

        chunk = definitions["gate_project_upload_chunk"]
        self.assertEqual(chunk.metadata.get("sensitive_input_fields"), ["data_base64"])
        build_status = definitions["gate_build_status"]
        self.assertEqual(build_status.metadata.get("sensitive_output_fields"), ["logs"])

        for tool_id in CONFIRMED_TOOL_IDS:
            with self.subTest(confirmed_tool_id=tool_id):
                schema = definitions[tool_id].input_schema
                self.assertIn("confirmed", schema.get("required", []))
                self.assertIs(schema["properties"]["confirmed"].get("const"), True)

    def test_output_schema_strictly_separates_success_and_structured_error(self) -> None:
        schema = next(
            item
            for item in PROJECT_DELIVERY_TOOL_DEFINITIONS
            if item.id == "gate_build_status"
        ).metadata["outputSchema"]
        assert_json_schema_instance(
            self,
            {"status": "failed", "failure_message": "build failed"},
            schema,
        )
        assert_json_schema_instance(
            self,
            ToolExecutionError(
                "build_not_found",
                "找不到指定构建",
                next_action="确认 build_id。",
            ).to_payload(),
            schema,
        )
        with self.assertRaises(AssertionError):
            assert_json_schema_instance(
                self,
                {"status": "failed", "error": "unstructured error"},
                schema,
            )

    def test_registry_redacts_chunk_base64_before_logging(self) -> None:
        definition = next(
            item
            for item in PROJECT_DELIVERY_TOOL_DEFINITIONS
            if item.id == "gate_project_upload_chunk"
        )
        registry = ToolRegistry()
        secret_chunk = "VEhJU19NVVNUX05PVF9BUFBFQVJfSU5fTE9HUw=="

        with patch("lingshu_gate.registry.log_event") as log_event:
            registry.register(definition, lambda _: {"status": "accepted"})
            response = registry.invoke(
                definition.id,
                {"data_base64": secret_chunk, "offset": 0},
            )

        self.assertTrue(response.ok)
        start_call = next(
            item for item in log_event.call_args_list if item.args[2] == "gate.tool.invoke_started"
        )
        self.assertEqual(start_call.kwargs["arguments"]["data_base64"], "[REDACTED]")
        self.assertNotIn(secret_chunk, repr(log_event.call_args_list))

    def test_registry_does_not_copy_build_logs_into_info_output(self) -> None:
        definition = next(
            item
            for item in PROJECT_DELIVERY_TOOL_DEFINITIONS
            if item.id == "gate_build_status"
        )
        registry = ToolRegistry()
        secret_output = "BUILD_OUTPUT_SECRET_MUST_NOT_REACH_REGISTRY_LOG"

        with patch("lingshu_gate.registry.log_event") as log_event:
            registry.register(
                definition,
                lambda _: {
                    "status": "running",
                    "logs": [{"stdout": secret_output}],
                    "next_sequence": 1,
                },
            )
            response = registry.invoke(definition.id, {"build_id": "build-fake-000001"})

        self.assertTrue(response.ok)
        self.assertEqual(response.output["logs"][0]["stdout"], secret_output)
        self.assertNotIn(secret_output, repr(log_event.call_args_list))
        self.assertIn("[REDACTED]", repr(log_event.call_args_list))


class ProjectDeliveryUploadTest(unittest.TestCase):
    def setUp(self) -> None:
        # SQLite 的短连接在 Windows 上可能延迟释放文件句柄；清理失败不应掩盖契约断言。
        self.temp_dir_context = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.data_dir = Path(self.temp_dir_context.name)
        self.database = SQLiteDatabase("", self.data_dir)
        self.uploads = ProjectUploadStore(self.database, self.data_dir)
        self.observability = FakeObservability()
        self.service = ProjectDeliveryMcpService(
            self.database,
            self.data_dir,
            self.uploads,
            Mock(name="builds"),
            Mock(name="configs"),
            Mock(name="runtime"),
            self.observability,  # type: ignore[arg-type]
        )
        self.context = ToolInvocationContext(
            actor_id="actor-1",
            username="operator",
            auth_type="session",
            token_id=None,
            correlation_id="correlation-1",
        )
        self.archive = create_project_zip()
        self.archive_sha256 = hashlib.sha256(self.archive).hexdigest()

    def tearDown(self) -> None:
        self.temp_dir_context.cleanup()

    def begin_upload(self, *, key: str = "begin-upload-0001") -> dict[str, object]:
        return self.service.project_upload_begin(
            {
                "filename": "project.zip",
                "size_bytes": len(self.archive),
                "sha256": self.archive_sha256,
                "idempotency_key": key,
                "confirmed": True,
            },
            self.context,
        )

    def upload_all(
        self,
        begin: dict[str, object],
        *,
        content: bytes | None = None,
        key: str = "upload-all-0001",
        context: ToolInvocationContext | None = None,
    ) -> dict[str, object]:
        payload = content if content is not None else self.archive
        return self.service.project_upload_chunk(
            {
                "transfer_id": begin["transfer_id"],
                "offset": 0,
                "data_base64": base64.b64encode(payload).decode("ascii"),
                "chunk_sha256": hashlib.sha256(payload).hexdigest(),
                "idempotency_key": key,
            },
            context or self.context,
        )

    def test_container_project_draft_requires_operator_supplied_digest(self) -> None:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("Dockerfile", "FROM scratch\n")

        record = self.uploads.save_zip(
            filename="container-project.zip",
            content=buffer.getvalue(),
        )
        draft = self.uploads.draft_manifest(str(record["id"]))

        self.assertEqual(draft["launch"]["type"], "managed_container")
        self.assertIsNone(draft["launch"]["image"])
        self.assertTrue(draft["analysis"]["requires_digest_pinned_image"])

    def test_begin_chunk_commit_are_idempotent_and_return_source_digest(self) -> None:
        begin_arguments = {
            "filename": "project.zip",
            "size_bytes": len(self.archive),
            "sha256": self.archive_sha256,
            "idempotency_key": "begin-upload-0001",
            "confirmed": True,
        }
        begin = self.service.project_upload_begin(begin_arguments, self.context)
        begin_replay = self.service.project_upload_begin(begin_arguments, self.context)

        self.assertEqual(begin["transfer_id"], begin_replay["transfer_id"])
        self.assertEqual(begin["operation_id"], begin_replay["operation_id"])
        self.assertTrue(begin_replay["idempotent_replay"])

        with self.assertRaises(ToolExecutionError) as begin_conflict:
            self.service.project_upload_begin(
                {**begin_arguments, "filename": "different.zip"},
                self.context,
            )
        self.assertEqual(begin_conflict.exception.code, "idempotency_conflict")

        encoded = base64.b64encode(self.archive).decode("ascii")
        chunk_arguments = {
            "transfer_id": begin["transfer_id"],
            "offset": 0,
            "data_base64": encoded,
            "chunk_sha256": self.archive_sha256,
            "idempotency_key": "upload-chunk-0001",
        }
        chunk = self.service.project_upload_chunk(chunk_arguments, self.context)
        chunk_replay = self.service.project_upload_chunk(chunk_arguments, self.context)
        self.assertEqual(chunk["operation_id"], chunk_replay["operation_id"])
        self.assertEqual(chunk["next_offset"], len(self.archive))
        self.assertTrue(chunk["complete"])
        self.assertTrue(chunk_replay["idempotent_replay"])

        cursor_replay = self.service.project_upload_chunk(
            {**chunk_arguments, "idempotency_key": "upload-chunk-0002"},
            self.context,
        )
        self.assertTrue(cursor_replay["chunk_replayed"])
        self.assertEqual(cursor_replay["accepted_bytes"], 0)
        self.assertEqual(cursor_replay["next_offset"], len(self.archive))

        commit_arguments = {
            "transfer_id": begin["transfer_id"],
            "idempotency_key": "commit-upload-0001",
        }
        committed = self.service.project_upload_commit(commit_arguments, self.context)
        committed_replay = self.service.project_upload_commit(commit_arguments, self.context)

        self.assertEqual(committed["status"], "committed")
        self.assertEqual(committed["source_sha256"], self.archive_sha256)
        self.assertEqual(committed["source_size_bytes"], len(self.archive))
        self.assertEqual(
            committed["upload"]["analysis"]["source_sha256"],
            self.archive_sha256,
        )
        self.assertEqual(
            committed["upload"]["id"],
            committed_replay["upload"]["id"],
        )
        self.assertEqual(committed["operation_id"], committed_replay["operation_id"])
        self.assertTrue(committed_replay["idempotent_replay"])

    def test_chunk_rejects_out_of_order_and_conflicting_content(self) -> None:
        begin = self.begin_upload(key="begin-conflict-0001")
        first_chunk = self.archive[: max(4, len(self.archive) // 2)]
        first_sha256 = hashlib.sha256(first_chunk).hexdigest()

        with self.assertRaises(ToolExecutionError) as out_of_order:
            self.service.project_upload_chunk(
                {
                    "transfer_id": begin["transfer_id"],
                    "offset": 1,
                    "data_base64": base64.b64encode(first_chunk).decode("ascii"),
                    "chunk_sha256": first_sha256,
                    "idempotency_key": "chunk-out-of-order-0001",
                },
                self.context,
            )
        self.assertEqual(out_of_order.exception.code, "chunk_out_of_order")
        self.assertEqual(out_of_order.exception.details["next_offset"], 0)

        self.service.project_upload_chunk(
            {
                "transfer_id": begin["transfer_id"],
                "offset": 0,
                "data_base64": base64.b64encode(first_chunk).decode("ascii"),
                "chunk_sha256": first_sha256,
                "idempotency_key": "chunk-first-valid-0001",
            },
            self.context,
        )
        conflicting_chunk = bytes(value ^ 0x01 for value in first_chunk)
        with self.assertRaises(ToolExecutionError) as conflict:
            self.service.project_upload_chunk(
                {
                    "transfer_id": begin["transfer_id"],
                    "offset": 0,
                    "data_base64": base64.b64encode(conflicting_chunk).decode("ascii"),
                    "chunk_sha256": hashlib.sha256(conflicting_chunk).hexdigest(),
                    "idempotency_key": "chunk-conflicting-0001",
                },
                self.context,
            )
        self.assertEqual(conflict.exception.code, "chunk_offset_conflict")
        self.assertEqual(conflict.exception.details["next_offset"], len(first_chunk))

    def test_transfer_is_not_visible_to_another_actor_for_chunk_or_commit(self) -> None:
        begin = self.begin_upload(key="begin-owner-boundary-0001")
        other_context = ToolInvocationContext(
            actor_id="actor-2",
            username="other-operator",
            auth_type="session",
            token_id=None,
            correlation_id="correlation-2",
        )

        with self.assertRaises(ToolExecutionError) as chunk_denied:
            self.upload_all(
                begin,
                key="chunk-other-actor-0001",
                context=other_context,
            )
        self.assertEqual(chunk_denied.exception.code, "upload_transfer_not_found")

        with self.assertRaises(ToolExecutionError) as commit_denied:
            self.service.project_upload_commit(
                {
                    "transfer_id": begin["transfer_id"],
                    "idempotency_key": "commit-other-actor-0001",
                },
                other_context,
            )
        self.assertEqual(commit_denied.exception.code, "upload_transfer_not_found")

        transfer = self.database.query_one(
            "SELECT status, received_size_bytes FROM project_upload_transfers WHERE id = ?",
            (begin["transfer_id"],),
        )
        self.assertEqual(str(transfer["status"]), "open")
        self.assertEqual(int(transfer["received_size_bytes"]), 0)

    def test_invalid_archive_commit_releases_claim_and_leaves_no_orphan_upload(self) -> None:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("../escape.txt", "must not be extracted")
        unsafe_archive = stream.getvalue()
        unsafe_sha256 = hashlib.sha256(unsafe_archive).hexdigest()
        begin = self.service.project_upload_begin(
            {
                "filename": "unsafe.zip",
                "size_bytes": len(unsafe_archive),
                "sha256": unsafe_sha256,
                "idempotency_key": "begin-invalid-archive-0001",
                "confirmed": True,
            },
            self.context,
        )
        self.upload_all(
            begin,
            content=unsafe_archive,
            key="chunk-invalid-archive-0001",
        )

        with self.assertRaises(ToolExecutionError) as invalid:
            self.service.project_upload_commit(
                {
                    "transfer_id": begin["transfer_id"],
                    "idempotency_key": "commit-invalid-archive-0001",
                },
                self.context,
            )

        self.assertEqual(invalid.exception.code, "invalid_archive")
        transfer = self.database.query_one(
            "SELECT status FROM project_upload_transfers WHERE id = ?",
            (begin["transfer_id"],),
        )
        self.assertEqual(str(transfer["status"]), "open")
        upload_count = self.database.query_one(
            "SELECT COUNT(*) AS count FROM project_uploads"
        )
        self.assertEqual(int(upload_count["count"]), 0)
        uploads_dir = self.data_dir / "uploads"
        self.assertEqual(list(uploads_dir.iterdir()) if uploads_dir.exists() else [], [])

    def test_cleanup_does_not_delete_staging_when_expiry_claim_loses_race(self) -> None:
        begin = self.begin_upload(key="begin-cleanup-race-0001")
        transfer_id = str(begin["transfer_id"])
        staging_path = self.service._transfer_path(transfer_id)
        self.database.execute(
            "UPDATE project_upload_transfers SET expires_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", transfer_id),
        )
        original_query_all = self.database.query_all

        def advance_after_expired_selection(
            sql: str,
            parameters: tuple[object, ...] = (),
        ) -> list[object]:
            rows = original_query_all(sql, parameters)
            if "FROM project_upload_transfers" in sql and "expires_at <" in sql:
                self.database.execute(
                    "UPDATE project_upload_transfers SET status = 'committing' WHERE id = ?",
                    (transfer_id,),
                )
            return rows  # type: ignore[return-value]

        with patch.object(self.database, "query_all", side_effect=advance_after_expired_selection):
            self.service._cleanup_expired_transfers()

        transfer = self.database.query_one(
            "SELECT status FROM project_upload_transfers WHERE id = ?",
            (transfer_id,),
        )
        self.assertEqual(str(transfer["status"]), "committing")
        self.assertTrue(staging_path.exists())

    def test_chunk_cursor_claim_failure_rolls_back_chunk_and_staging(self) -> None:
        begin = self.begin_upload(key="begin-chunk-cas-0001")
        transfer_id = str(begin["transfer_id"])
        staging_path = self.service._transfer_path(transfer_id)
        original_connect = self.database.connect

        class ConnectionProxy:
            def __init__(self) -> None:
                self.connection = original_connect()

            def __enter__(self) -> "ConnectionProxy":
                self.connection.__enter__()
                return self

            def __exit__(self, *args: object) -> object:
                return self.connection.__exit__(*args)

            def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> object:
                if "SET received_size_bytes" in sql:
                    return SimpleNamespace(rowcount=0)
                return self.connection.execute(sql, parameters)

            def __getattr__(self, name: str) -> object:
                return getattr(self.connection, name)

        with patch.object(self.database, "connect", side_effect=ConnectionProxy):
            with self.assertRaises(ToolExecutionError) as conflict:
                self.upload_all(begin, key="chunk-cas-failure-0001")

        self.assertEqual(conflict.exception.code, "upload_transfer_state_conflict")
        transfer = self.database.query_one(
            "SELECT received_size_bytes, status FROM project_upload_transfers WHERE id = ?",
            (transfer_id,),
        )
        self.assertEqual(int(transfer["received_size_bytes"]), 0)
        self.assertEqual(str(transfer["status"]), "open")
        chunk_count = self.database.query_one(
            "SELECT COUNT(*) AS count FROM project_upload_transfer_chunks WHERE transfer_id = ?",
            (transfer_id,),
        )
        self.assertEqual(int(chunk_count["count"]), 0)
        self.assertEqual(staging_path.stat().st_size, 0)

    def test_commit_claim_failure_keeps_open_transfer_and_staging(self) -> None:
        begin = self.begin_upload(key="begin-commit-cas-0001")
        self.upload_all(begin, key="chunk-before-commit-cas-0001")
        transfer_id = str(begin["transfer_id"])
        staging_path = self.service._transfer_path(transfer_id)
        original_connect = self.database.connect

        class ConnectionProxy:
            def __init__(self) -> None:
                self.connection = original_connect()

            def __enter__(self) -> "ConnectionProxy":
                self.connection.__enter__()
                return self

            def __exit__(self, *args: object) -> object:
                return self.connection.__exit__(*args)

            def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> object:
                if "SET status = 'committing'" in sql:
                    return SimpleNamespace(rowcount=0)
                return self.connection.execute(sql, parameters)

            def __getattr__(self, name: str) -> object:
                return getattr(self.connection, name)

        with patch.object(self.database, "connect", side_effect=ConnectionProxy):
            with self.assertRaises(ToolExecutionError) as conflict:
                self.service.project_upload_commit(
                    {
                        "transfer_id": transfer_id,
                        "idempotency_key": "commit-cas-failure-0001",
                    },
                    self.context,
                )

        self.assertEqual(conflict.exception.code, "upload_transfer_state_conflict")
        transfer = self.database.query_one(
            "SELECT status, upload_id FROM project_upload_transfers WHERE id = ?",
            (transfer_id,),
        )
        self.assertEqual(str(transfer["status"]), "open")
        self.assertIsNone(transfer["upload_id"])
        self.assertTrue(staging_path.exists())
        self.assertEqual(staging_path.stat().st_size, len(self.archive))
        upload_count = self.database.query_one(
            "SELECT COUNT(*) AS count FROM project_uploads"
        )
        self.assertEqual(int(upload_count["count"]), 0)

    def test_stale_writing_lease_truncates_unconfirmed_bytes_before_resume(self) -> None:
        begin = self.begin_upload(key="begin-writing-recovery-0001")
        transfer_id = str(begin["transfer_id"])
        split_at = max(4, len(self.archive) // 2)
        first_chunk = self.archive[:split_at]
        second_chunk = self.archive[split_at:]
        self.service.project_upload_chunk(
            {
                "transfer_id": transfer_id,
                "offset": 0,
                "data_base64": base64.b64encode(first_chunk).decode("ascii"),
                "chunk_sha256": hashlib.sha256(first_chunk).hexdigest(),
                "idempotency_key": "writing-recovery-first-0001",
            },
            self.context,
        )
        staging_path = self.service._transfer_path(transfer_id)
        with staging_path.open("ab") as stream:
            stream.write(b"unconfirmed-crash-bytes")
        self.database.execute(
            """
            UPDATE project_upload_transfers
            SET status = 'writing', updated_at = ?
            WHERE id = ?
            """,
            ("2000-01-01T00:00:00+00:00", transfer_id),
        )

        resumed = self.service.project_upload_chunk(
            {
                "transfer_id": transfer_id,
                "offset": split_at,
                "data_base64": base64.b64encode(second_chunk).decode("ascii"),
                "chunk_sha256": hashlib.sha256(second_chunk).hexdigest(),
                "idempotency_key": "writing-recovery-second-0001",
            },
            self.context,
        )

        self.assertTrue(resumed["complete"])
        self.assertEqual(staging_path.read_bytes(), self.archive)
        transfer = self.database.query_one(
            "SELECT status, received_size_bytes FROM project_upload_transfers WHERE id = ?",
            (transfer_id,),
        )
        self.assertEqual(str(transfer["status"]), "open")
        self.assertEqual(int(transfer["received_size_bytes"]), len(self.archive))

    def test_commit_finalize_failure_recovers_candidate_without_second_save_zip(self) -> None:
        begin = self.begin_upload(key="begin-finalize-recovery-0001")
        self.upload_all(begin, key="chunk-finalize-recovery-0001")
        transfer_id = str(begin["transfer_id"])
        staging_path = self.service._transfer_path(transfer_id)
        original_connect = self.database.connect

        class ConnectionProxy:
            def __init__(self) -> None:
                self.connection = original_connect()

            def __enter__(self) -> "ConnectionProxy":
                self.connection.__enter__()
                return self

            def __exit__(self, *args: object) -> object:
                return self.connection.__exit__(*args)

            def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> object:
                if "SET status = 'committed'" in sql:
                    return SimpleNamespace(rowcount=0)
                return self.connection.execute(sql, parameters)

            def __getattr__(self, name: str) -> object:
                return getattr(self.connection, name)

        with patch.object(self.database, "connect", side_effect=ConnectionProxy):
            with self.assertRaises(ToolExecutionError) as finalize_conflict:
                self.service.project_upload_commit(
                    {
                        "transfer_id": transfer_id,
                        "idempotency_key": "commit-finalize-failure-0001",
                    },
                    self.context,
                )

        self.assertEqual(finalize_conflict.exception.code, "upload_transfer_state_conflict")
        transfer = self.database.query_one(
            "SELECT status, upload_id FROM project_upload_transfers WHERE id = ?",
            (transfer_id,),
        )
        self.assertEqual(str(transfer["status"]), "committing")
        self.assertIsNone(transfer["upload_id"])
        candidate = self.database.query_one(
            "SELECT id, filename FROM project_uploads"
        )
        self.assertTrue(str(candidate["filename"]).startswith(".gate-transfer-"))
        owner_count = self.database.query_one(
            "SELECT COUNT(*) AS count FROM project_delivery_resource_owners WHERE resource_type = 'upload'"
        )
        self.assertEqual(int(owner_count["count"]), 0)

        self.database.execute(
            "UPDATE project_upload_transfers SET updated_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", transfer_id),
        )
        with patch.object(self.uploads, "save_zip", wraps=self.uploads.save_zip) as save_zip:
            recovered = self.service.project_upload_commit(
                {
                    "transfer_id": transfer_id,
                    "idempotency_key": "commit-finalize-recovery-0002",
                },
                self.context,
            )
        save_zip.assert_not_called()

        self.assertEqual(recovered["upload"]["id"], str(candidate["id"]))
        self.assertEqual(recovered["source_sha256"], self.archive_sha256)
        transfer = self.database.query_one(
            "SELECT status, upload_id FROM project_upload_transfers WHERE id = ?",
            (transfer_id,),
        )
        self.assertEqual(str(transfer["status"]), "committed")
        self.assertEqual(str(transfer["upload_id"]), str(candidate["id"]))
        owner = self.database.query_one(
            """
            SELECT owner_id FROM project_delivery_resource_owners
            WHERE resource_type = 'upload' AND resource_id = ?
            """,
            (str(candidate["id"]),),
        )
        self.assertEqual(str(owner["owner_id"]), self.context.actor_id)
        self.assertFalse(staging_path.exists())
        upload_count = self.database.query_one(
            "SELECT COUNT(*) AS count FROM project_uploads"
        )
        self.assertEqual(int(upload_count["count"]), 1)

    def test_stale_pending_idempotency_is_failed_without_replaying_action(self) -> None:
        arguments = {
            "filename": "project.zip",
            "size_bytes": len(self.archive),
            "sha256": self.archive_sha256,
            "idempotency_key": "stale-pending-operation-0001",
            "confirmed": True,
        }
        operation_id, replay = self.service._reserve_operation(
            self.context,
            "gate_project_upload_begin",
            arguments["idempotency_key"],
            arguments,
        )
        self.assertIsNone(replay)
        self.database.execute(
            "UPDATE mcp_idempotent_operations SET updated_at = ? WHERE id = ?",
            ("2000-01-01T00:00:00+00:00", operation_id),
        )

        for _ in range(2):
            with self.assertRaises(ToolExecutionError) as interrupted:
                self.service.project_upload_begin(arguments, self.context)
            self.assertEqual(interrupted.exception.code, "operation_interrupted")
            self.assertFalse(interrupted.exception.retryable)
            self.assertEqual(
                interrupted.exception.details["completion_state"],
                "unknown",
            )
            self.assertEqual(interrupted.exception.details["operation_id"], operation_id)

        operation = self.database.query_one(
            "SELECT status, error_json FROM mcp_idempotent_operations WHERE id = ?",
            (operation_id,),
        )
        self.assertEqual(str(operation["status"]), "failed")
        self.assertIn("operation_interrupted", str(operation["error_json"]))
        transfer_count = self.database.query_one(
            "SELECT COUNT(*) AS count FROM project_upload_transfers"
        )
        self.assertEqual(int(transfer_count["count"]), 0)

    def test_confirmed_is_required_before_upload_session_is_created(self) -> None:
        with self.assertRaises(ToolExecutionError) as missing_confirmation:
            self.service.project_upload_begin(
                {
                    "filename": "project.zip",
                    "size_bytes": len(self.archive),
                    "sha256": self.archive_sha256,
                    "idempotency_key": "begin-unconfirmed-0001",
                },
                self.context,
            )

        self.assertEqual(missing_confirmation.exception.code, "invalid_arguments")
        fields = {
            item["field"]
            for item in missing_confirmation.exception.details.get("violations", [])
        }
        self.assertIn("confirmed", fields)
        transfer_count = self.database.query_one(
            "SELECT COUNT(*) AS count FROM project_upload_transfers"
        )
        self.assertEqual(int(transfer_count["count"]), 0)


class ProjectDeliveryFakePipelineTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir_context = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.data_dir = Path(self.temp_dir_context.name)
        self.database = SQLiteDatabase("", self.data_dir)
        self.uploads = ProjectUploadStore(self.database, self.data_dir)
        self.configs = FakeConfigStore()
        self.runtime = FakeRuntime()
        self.builds = FakeBuildStore(self.database, self.configs, self.runtime)
        self.observability = FakeObservability()
        self.reconciliations: list[tuple[str, list[str], str]] = []

        def reconcile(
            server_id: str,
            definitions: list[ToolDefinition],
            reviewer_id: str,
        ) -> dict[str, object]:
            self.reconciliations.append(
                (server_id, [item.id for item in definitions], reviewer_id)
            )
            return {
                "counts": {
                    "new": len(definitions),
                    "changed": 0,
                    "reappeared": 0,
                    "retired": 0,
                    "unchanged": 0,
                    "needs_review": len(definitions),
                },
                "effective_permissions_expanded": False,
            }

        self.service = ProjectDeliveryMcpService(
            self.database,
            self.data_dir,
            self.uploads,
            self.builds,  # type: ignore[arg-type]
            self.configs,  # type: ignore[arg-type]
            self.runtime,  # type: ignore[arg-type]
            self.observability,  # type: ignore[arg-type]
            tool_classification_reconciler=reconcile,
        )
        self.context = ToolInvocationContext(
            actor_id="actor-pipeline",
            username="operator",
            auth_type="session",
            token_id=None,
            correlation_id="correlation-pipeline",
        )
        self.upload_id = "upload-fake-000001"
        self.source_sha256 = "a" * 64
        now = "2026-08-12T00:00:00+00:00"
        self.database.execute(
            """
            INSERT INTO project_uploads (
                id, filename, status, root_dir, detected_runtime,
                analysis_json, created_at, updated_at
            ) VALUES (?, 'project.zip', 'analyzed', ?, 'node', ?, ?, ?)
            """,
            (
                self.upload_id,
                str(self.data_dir / "fake-project"),
                json.dumps(
                    {
                        "source_sha256": self.source_sha256,
                        "detected_runtime": "node",
                    }
                ),
                now,
                now,
            ),
        )
        self.service._claim_owner("upload", self.upload_id, self.context)

    def tearDown(self) -> None:
        self.temp_dir_context.cleanup()

    def add_build(
        self,
        build_id: str,
        *,
        status: str,
        source_sha256: str | None = None,
        plan_fingerprint: str | None = None,
        server_id: str = "fake-server",
        error: str | None = None,
    ) -> None:
        self.builds.records[build_id] = {
            "id": build_id,
            "upload_id": self.upload_id,
            "status": status,
            "runtime": "node",
            "source_sha256": source_sha256 or self.source_sha256,
            "plan_fingerprint": plan_fingerprint or ("b" * 64),
            "steps": [],
            "manifest": {
                "id": server_id,
                "name": "Fake deployed server",
                "enabled": True,
                "launch": {
                    "type": "managed_process",
                    "command": "node",
                    "args": ["index.js"],
                },
                "transport": {"type": "stdio"},
            },
            "error": error,
            "created_at": "2026-08-12T00:00:00+00:00",
            "updated_at": "2026-08-12T00:00:00+00:00",
        }
        self.service._claim_owner("build", build_id, self.context)

    def test_build_plan_is_stable_and_build_create_is_idempotent(self) -> None:
        plan_arguments = {"upload_id": self.upload_id}
        first_plan = self.service.build_plan(plan_arguments, self.context)
        second_plan = self.service.build_plan(plan_arguments, self.context)

        self.assertEqual(first_plan["status"], "planned")
        self.assertEqual(first_plan["source_sha256"], self.source_sha256)
        self.assertEqual(first_plan["plan_fingerprint"], second_plan["plan_fingerprint"])
        self.assertEqual(len(first_plan["plan_fingerprint"]), 64)

        create_arguments = {
            "upload_id": self.upload_id,
            "source_sha256": first_plan["source_sha256"],
            "plan_fingerprint": first_plan["plan_fingerprint"],
            "idempotency_key": "build-create-0001",
            "confirmed": True,
        }
        created = self.service.build_create(create_arguments, self.context)
        replayed = self.service.build_create(create_arguments, self.context)

        self.assertEqual(created["build_id"], replayed["build_id"])
        self.assertEqual(created["operation_id"], replayed["operation_id"])
        self.assertTrue(replayed["idempotent_replay"])
        self.assertEqual(len(self.builds.build_upload_calls), 1)
        self.assertTrue(self.builds.build_upload_calls[0]["run_install"])
        self.assertTrue(self.builds.build_upload_calls[0]["run_build"])

        with self.assertRaises(ToolExecutionError) as same_key_conflict:
            self.service.build_create(
                {**create_arguments, "plan_fingerprint": "f" * 64},
                self.context,
            )
        self.assertEqual(same_key_conflict.exception.code, "idempotency_conflict")

        with self.assertRaises(ToolExecutionError) as fingerprint_conflict:
            self.service.build_create(
                {
                    **create_arguments,
                    "plan_fingerprint": "f" * 64,
                    "idempotency_key": "build-create-bad-fingerprint-0001",
                },
                self.context,
            )
        self.assertEqual(fingerprint_conflict.exception.code, "plan_fingerprint_conflict")
        self.assertEqual(len(self.builds.build_upload_calls), 1)

    def test_delivery_resources_are_private_to_owner_but_admin_can_inspect(self) -> None:
        other = ToolInvocationContext(
            actor_id="actor-other",
            username="other-operator",
            auth_type="session",
            token_id=None,
            correlation_id="correlation-other",
        )
        admin = ToolInvocationContext(
            actor_id="actor-admin",
            username="admin",
            auth_type="session",
            token_id=None,
            correlation_id="correlation-admin",
            roles=("admin",),
            permissions=("*",),
        )

        with self.assertRaises(ToolExecutionError) as upload_denied:
            self.service.build_preflight({"upload_id": self.upload_id}, other)
        self.assertEqual(
            upload_denied.exception.code,
            "delivery_resource_not_found_or_forbidden",
        )
        self.assertEqual(
            self.service.build_plan({"upload_id": self.upload_id}, admin)["status"],
            "planned",
        )

        build_id = "build-private-0001"
        self.add_build(build_id, status="success")
        with self.assertRaises(ToolExecutionError) as build_denied:
            self.service.build_status({"build_id": build_id}, other)
        self.assertEqual(
            build_denied.exception.code,
            "delivery_resource_not_found_or_forbidden",
        )
        self.assertEqual(
            self.service.build_status({"build_id": build_id}, admin)["build_id"],
            build_id,
        )

    def test_deploy_defaults_are_safe_and_provenance_is_enforced(self) -> None:
        plan_fingerprint = "b" * 64
        success_build_id = "build-success-000001"
        self.add_build(
            success_build_id,
            status="success",
            plan_fingerprint=plan_fingerprint,
        )
        deployed = self.service.deploy_build(
            {
                "build_id": success_build_id,
                "source_sha256": self.source_sha256,
                "plan_fingerprint": plan_fingerprint,
                "idempotency_key": "deploy-default-0001",
                "confirmed": True,
            },
            self.context,
        )

        self.assertEqual(deployed["status"], "success")
        self.assertFalse(deployed["runtime_started"])
        deploy_call = copy.deepcopy(self.builds.deploy_calls[0])
        deployment_manifest = deploy_call.pop("manifest_override")
        self.assertEqual(
            deploy_call,
            {
                "build_id": success_build_id,
                "server_id": "fake-server",
                "start": False,
                "overwrite": False,
                "owner_id": "actor-pipeline",
            },
        )
        self.assertEqual(deployment_manifest["id"], "fake-server")
        self.assertEqual(deployment_manifest["launch"]["command"], "node")

        deployment_status = self.service.deployment_status(
            {"deployment_id": deployed["deployment_id"]},
            self.context,
        )
        self.assertEqual(
            {
                key: deployment_status[key]
                for key in (
                    "config_applied",
                    "runtime_started",
                    "rollback_attempted",
                    "rollback_succeeded",
                    "rollback_error",
                )
            },
            {
                "config_applied": True,
                "runtime_started": False,
                "rollback_attempted": False,
                "rollback_succeeded": None,
                "rollback_error": None,
            },
        )
        self.assertNotIn("error", deployment_status)
        output_schema = next(
            item
            for item in PROJECT_DELIVERY_TOOL_DEFINITIONS
            if item.id == "gate_deployment_status"
        ).metadata["outputSchema"]
        assert_json_schema_instance(self, deployment_status, output_schema)

        running_build_id = "build-running-000001"
        self.add_build(running_build_id, status="running")
        with self.assertRaises(ToolExecutionError) as not_ready:
            self.service.deploy_build(
                {
                    "build_id": running_build_id,
                    "source_sha256": self.source_sha256,
                    "plan_fingerprint": plan_fingerprint,
                    "idempotency_key": "deploy-not-ready-0001",
                    "confirmed": True,
                },
                self.context,
            )
        self.assertEqual(not_ready.exception.code, "build_not_ready")

        source_conflict_id = "build-source-bad-0001"
        self.add_build(source_conflict_id, status="success")
        with self.assertRaises(ToolExecutionError) as source_conflict:
            self.service.deploy_build(
                {
                    "build_id": source_conflict_id,
                    "source_sha256": "c" * 64,
                    "plan_fingerprint": plan_fingerprint,
                    "idempotency_key": "deploy-source-conflict-0001",
                    "confirmed": True,
                },
                self.context,
            )
        self.assertEqual(source_conflict.exception.code, "source_digest_conflict")

        plan_conflict_id = "build-plan-bad-000001"
        self.add_build(plan_conflict_id, status="success")
        with self.assertRaises(ToolExecutionError) as plan_conflict:
            self.service.deploy_build(
                {
                    "build_id": plan_conflict_id,
                    "source_sha256": self.source_sha256,
                    "plan_fingerprint": "c" * 64,
                    "idempotency_key": "deploy-plan-conflict-0001",
                    "confirmed": True,
                },
                self.context,
            )
        self.assertEqual(plan_conflict.exception.code, "plan_fingerprint_conflict")
        self.assertEqual(len(self.builds.deploy_calls), 1)

    def test_deploy_preserves_existing_managed_credential_reference_with_digest_cas(self) -> None:
        server_id = "credential-server"
        previous = McpServerManifest.model_validate(
            {
                "id": server_id,
                "name": "Credential server",
                "enabled": True,
                "launch": {
                    "type": "managed_process",
                    "command": "node",
                    "env": {"API_TOKEN": "${credential:cred-1}"},
                },
                "transport": {"type": "stdio"},
            }
        )
        self.configs.manifests[server_id] = previous  # type: ignore[assignment]
        self.runtime.add_server(server_id)
        self.service._claim_owner("mcp_server", server_id, self.context)
        self.service.credential_store = SimpleNamespace(
            get_credential=lambda credential_id: SimpleNamespace(
                id=credential_id,
                updated_at="2026-08-13T00:00:00+00:00",
                value="SECRET_MUST_NOT_BE_RETURNED",
            )
        )
        previous_digest = self.service._config_digest(server_id)
        credential_state = self.service._credential_state(previous, self.context.actor_id)
        build_id = "build-credential-0001"
        self.add_build(build_id, status="success", server_id=server_id)

        deployed = self.service.deploy_build(
            {
                "build_id": build_id,
                "source_sha256": self.source_sha256,
                "plan_fingerprint": "b" * 64,
                "server_id": server_id,
                "overwrite": True,
                "expected_previous_config_digest": previous_digest,
                "expected_credential_binding_digest": credential_state["binding_digest"],
                "idempotency_key": "deploy-credential-0001",
                "confirmed": True,
            },
            self.context,
        )

        manifest = self.builds.deploy_calls[-1]["manifest_override"]
        self.assertEqual(manifest["launch"]["env"]["API_TOKEN"], "${credential:cred-1}")
        serialized = json.dumps(deployed, ensure_ascii=False)
        self.assertNotIn("SECRET_MUST_NOT_BE_RETURNED", serialized)
        self.assertEqual(deployed["credential_state"]["binding_digest"], credential_state["binding_digest"])

        with self.assertRaises(ToolExecutionError) as conflict:
            self.service.deploy_build(
                {
                    "build_id": build_id,
                    "source_sha256": self.source_sha256,
                    "plan_fingerprint": "b" * 64,
                    "server_id": server_id,
                    "overwrite": True,
                    "expected_previous_config_digest": deployed["config_digest"],
                    "expected_credential_binding_digest": "f" * 64,
                    "idempotency_key": "deploy-credential-conflict-0001",
                    "confirmed": True,
                },
                self.context,
            )
        self.assertEqual(conflict.exception.code, "credential_binding_digest_conflict")

    def test_server_status_reports_config_digest_and_true_not_found(self) -> None:
        server_id = "configured-server"
        self.configs.manifests[server_id] = FakeManifest(
            {
                "id": server_id,
                "name": "Configured server",
                "enabled": True,
                "launch": {"type": "managed_process", "command": "node"},
                "transport": {"type": "stdio"},
            }
        )
        expected_digest = self.service._config_digest(server_id)
        self.runtime.add_server(
            server_id,
            status="running",
            manifest_digest=expected_digest,
        )
        self.service._claim_owner("mcp_server", server_id, self.context)

        present = self.service.server_status({"server_id": server_id}, self.context)
        present_again = self.service.server_status({"server_id": server_id}, self.context)
        self.assertTrue(present["config_present"])
        self.assertEqual(len(present["config_digest"]), 64)
        self.assertEqual(present["config_digest"], present_again["config_digest"])
        self.assertTrue(present["runtime_present"])
        self.assertEqual(present["runtime_manifest_digest"], expected_digest)
        self.assertEqual(present["status"], "running")

        missing = self.service.server_status(
            {"server_id": "fully-missing-server"},
            self.context,
        )
        self.assertEqual(missing["status"], "not_found")
        self.assertFalse(missing["runtime_present"])
        self.assertIsNone(missing["runtime_manifest_digest"])
        self.assertFalse(missing["config_present"])
        self.assertIsNone(missing["config_digest"])

    def test_server_start_requires_runtime_manifest_digest_match(self) -> None:
        server_id = "start-server"
        self.configs.manifests[server_id] = FakeManifest(
            {
                "id": server_id,
                "name": "Start server",
                "enabled": True,
                "launch": {"type": "managed_process", "command": "node"},
                "transport": {"type": "stdio"},
            }
        )
        expected_digest = self.service._config_digest(server_id)
        self.runtime.add_server(
            server_id,
            manifest_digest=expected_digest,
        )
        self.service._claim_owner("mcp_server", server_id, self.context)

        started = self.service.server_start(
            {
                "server_id": server_id,
                "expected_config_digest": expected_digest,
                "idempotency_key": "start-matching-runtime-0001",
                "confirmed": True,
            },
            self.context,
        )
        self.assertEqual(started["status"], "running")
        self.assertEqual(
            self.runtime.start_requests[-1],
            (server_id, expected_digest),
        )

        self.runtime.manifest_digests[server_id] = "f" * 64
        with self.assertRaises(ToolExecutionError) as conflict:
            self.service.server_start(
                {
                    "server_id": server_id,
                    "expected_config_digest": expected_digest,
                    "idempotency_key": "start-conflicting-runtime-0001",
                    "confirmed": True,
                },
                self.context,
            )
        self.assertEqual(conflict.exception.code, "runtime_manifest_digest_conflict")
        self.assertEqual(
            conflict.exception.details["runtime_manifest_digest"],
            "f" * 64,
        )

    def test_server_refresh_tools_is_cas_guarded_idempotent_and_never_expands_permission(self) -> None:
        server_id = "refresh-server"
        self.configs.manifests[server_id] = FakeManifest(
            {
                "id": server_id,
                "name": "Refresh server",
                "enabled": True,
                "launch": {"type": "managed_process", "command": "node"},
                "transport": {"type": "stdio"},
            }
        )
        digest = self.service._config_digest(server_id)
        self.runtime.add_server(server_id, status="running", manifest_digest=digest)
        self.service._claim_owner("mcp_server", server_id, self.context)
        arguments = {
            "server_id": server_id,
            "expected_config_digest": digest,
            "idempotency_key": "refresh-tools-0001",
            "confirmed": True,
        }

        refreshed = self.service.server_refresh_tools(arguments, self.context)
        replayed = self.service.server_refresh_tools(arguments, self.context)

        self.assertEqual(refreshed["status"], "needs_review")
        self.assertFalse(refreshed["effective_permissions_expanded"])
        self.assertEqual(refreshed["tool_snapshot_digest"], "d" * 64)
        self.assertEqual(replayed["operation_id"], refreshed["operation_id"])
        self.assertTrue(replayed["idempotent_replay"])
        self.assertEqual(self.runtime.refresh_requests.count(server_id), 1)
        self.assertEqual(
            self.reconciliations,
            [(server_id, [f"mcp:{server_id}:read_file"], "actor-pipeline")],
        )

    def test_build_status_redacts_tokens_passwords_and_bearer_values(self) -> None:
        build_id = "build-log-redact-0001"
        self.add_build(
            build_id,
            status="failed",
            error="token=build-error-secret",
        )
        self.builds.logs[build_id] = [
            {
                "sequence": 1,
                "phase": "build",
                "level": "error",
                "message": "Authorization: Bearer bearer-secret-123",
                "command": ["fake-command", "--token=command-secret-456"],
                "returncode": 1,
                "stdout": "password=stdout-secret-789",
                "stderr": "token=stderr-secret-987",
                "duration_ms": 5,
                "started_at": "2026-08-12T00:00:00+00:00",
                "finished_at": "2026-08-12T00:00:01+00:00",
            }
        ]

        result = self.service.build_status(
            {"build_id": build_id, "after_sequence": -1, "log_limit": 10},
            self.context,
        )
        serialized = json.dumps(result, ensure_ascii=False)

        for secret in (
            "build-error-secret",
            "bearer-secret-123",
            "command-secret-456",
            "stdout-secret-789",
            "stderr-secret-987",
        ):
            with self.subTest(secret=secret):
                self.assertNotIn(secret, serialized)
        self.assertIn("[REDACTED]", serialized)
        self.assertNotIn("error", result)
        self.assertEqual(result["failure_message"], "token=[REDACTED]")
        self.assertEqual(result["next_sequence"], 1)
        self.assertTrue(result["terminal"])
        output_schema = next(
            item
            for item in PROJECT_DELIVERY_TOOL_DEFINITIONS
            if item.id == "gate_build_status"
        ).metadata["outputSchema"]
        assert_json_schema_instance(self, result, output_schema)


if __name__ == "__main__":
    unittest.main()

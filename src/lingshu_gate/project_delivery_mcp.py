"""Lingshu Gate 项目上传、构建和部署的受控 MCP 工具。"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import shutil
import sqlite3
import threading
import zipfile
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lingshu_gate.build_deploy import (
    TERMINAL_BUILD_STATUSES,
    BuildBlocked,
    BuildDeployStore,
    LocalExecutionBlocked,
)
from lingshu_gate.build_plan import validate_plan
from lingshu_gate.credential_refs import extract_credential_refs
from lingshu_gate.credential_store import CredentialStore
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.mcp_config_store import McpConfigStore
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.mcp_runtime import McpManifestDigestConflict, McpRuntimeManager
from lingshu_gate.models import ToolDefinition
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.project_uploads import MAX_ZIP_BYTES, ProjectUploadStore
from lingshu_gate.registry import (
    ToolExecutionError,
    ToolInvocationContext,
    ToolRegistry,
)
from lingshu_gate.user_credential_store import UserCredentialStore

SERVER_ID = "gate-delivery"
MAX_CHUNK_BYTES = 512 * 1024
MAX_BASE64_CHARS = ((MAX_CHUNK_BYTES + 2) // 3) * 4
TRANSFER_TTL = timedelta(hours=2)
TRANSFER_WORK_LEASE = timedelta(minutes=30)
IDEMPOTENCY_PENDING_LEASE = timedelta(minutes=30)
SHA256_PATTERN = r"^[0-9a-fA-F]{64}$"
IDEMPOTENCY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$"
SERVER_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
RUNTIME_VALUES = Literal["node", "python", "docker"]
CREDENTIAL_POLICIES = Literal["preserve_existing", "require_none"]
SENSITIVE_OUTPUT_KEY = re.compile(
    r"(?:password|passwd|secret|token|authorization|cookie|credential|api[_-]?key|private[_-]?key)",
    re.IGNORECASE,
)
BEARER_TEXT_PATTERN = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
INLINE_SECRET_PATTERN = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization|cookie|credential)\b"
    r"(\s*[:=]\s*)([^\s,;]+)"
)
FLAG_SECRET_PATTERN = re.compile(
    r"(?i)(--(?:password|passwd|secret|token|api[_-]?key|authorization|cookie|credential)(?:=|\s+))"
    r"([^\s]+)"
)
MAX_LOG_TEXT = 2_000


class _StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class UploadBeginInput(_StrictInput):
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1, le=MAX_ZIP_BYTES)
    sha256: str = Field(pattern=SHA256_PATTERN)
    idempotency_key: str = Field(pattern=IDEMPOTENCY_PATTERN)
    confirmed: Literal[True]


class UploadChunkInput(_StrictInput):
    transfer_id: str = Field(min_length=16, max_length=64)
    offset: int = Field(ge=0, le=MAX_ZIP_BYTES)
    data_base64: str = Field(min_length=4, max_length=MAX_BASE64_CHARS)
    chunk_sha256: str = Field(pattern=SHA256_PATTERN)
    idempotency_key: str = Field(pattern=IDEMPOTENCY_PATTERN)


class UploadCommitInput(_StrictInput):
    transfer_id: str = Field(min_length=16, max_length=64)
    idempotency_key: str = Field(pattern=IDEMPOTENCY_PATTERN)


class UploadAbortInput(UploadCommitInput):
    confirmed: Literal[True]


class BuildPreflightInput(_StrictInput):
    upload_id: str = Field(min_length=16, max_length=64)
    runtime_override: RUNTIME_VALUES | None = None
    project_root: str | None = Field(default=None, max_length=500)
    refresh: bool = False


class BuildPlanInput(BuildPreflightInput):
    run_install: bool = True
    run_build: bool = True


class BuildCreateInput(_StrictInput):
    upload_id: str = Field(min_length=16, max_length=64)
    runtime_override: RUNTIME_VALUES | None = None
    project_root: str | None = Field(default=None, max_length=500)
    run_install: bool = True
    run_build: bool = True
    timeout_seconds: int = Field(default=300, ge=1, le=1_800)
    source_sha256: str = Field(pattern=SHA256_PATTERN)
    plan_fingerprint: str = Field(pattern=SHA256_PATTERN)
    idempotency_key: str = Field(pattern=IDEMPOTENCY_PATTERN)
    confirmed: Literal[True]


class BuildStatusInput(_StrictInput):
    build_id: str = Field(min_length=16, max_length=64)
    after_sequence: int = Field(default=-1, ge=-1)
    log_limit: int = Field(default=100, ge=1, le=200)


class BuildCancelInput(_StrictInput):
    build_id: str = Field(min_length=16, max_length=64)
    idempotency_key: str = Field(pattern=IDEMPOTENCY_PATTERN)
    confirmed: Literal[True]


class DeployBuildInput(_StrictInput):
    build_id: str = Field(min_length=16, max_length=64)
    source_sha256: str = Field(pattern=SHA256_PATTERN)
    plan_fingerprint: str = Field(pattern=SHA256_PATTERN)
    server_id: str | None = Field(default=None, pattern=SERVER_ID_PATTERN)
    overwrite: bool = False
    start: bool = False
    expected_previous_config_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    credential_policy: CREDENTIAL_POLICIES = "preserve_existing"
    expected_credential_binding_digest: str | None = Field(default=None, pattern=SHA256_PATTERN)
    refresh_tools: bool = True
    idempotency_key: str = Field(pattern=IDEMPOTENCY_PATTERN)
    confirmed: Literal[True]


class DeploymentStatusInput(_StrictInput):
    deployment_id: str = Field(min_length=16, max_length=64)


class ServerStartInput(_StrictInput):
    server_id: str = Field(pattern=SERVER_ID_PATTERN)
    expected_config_digest: str = Field(pattern=SHA256_PATTERN)
    refresh_tools: bool = True
    idempotency_key: str = Field(pattern=IDEMPOTENCY_PATTERN)
    confirmed: Literal[True]


class ServerStatusInput(_StrictInput):
    server_id: str = Field(pattern=SERVER_ID_PATTERN)


class ServerRefreshToolsInput(_StrictInput):
    server_id: str = Field(pattern=SERVER_ID_PATTERN)
    expected_config_digest: str = Field(pattern=SHA256_PATTERN)
    idempotency_key: str = Field(pattern=IDEMPOTENCY_PATTERN)
    confirmed: Literal[True]


InputModel = TypeVar("InputModel", bound=BaseModel)
IdempotentAction = Callable[[str], tuple[dict[str, Any], str | None]]
TargetAccessChecker = Callable[[ToolInvocationContext, str, str], bool]
ToolClassificationReconciler = Callable[
    [str, list[ToolDefinition], str],
    dict[str, Any],
]


def _parse_input(model: type[InputModel], arguments: dict[str, Any]) -> InputModel:
    try:
        return model.model_validate(arguments)
    except ValidationError as exc:
        violations = [
            {
                "field": ".".join(str(part) for part in item.get("loc", ())),
                "message": str(item.get("msg") or "invalid value"),
                "type": str(item.get("type") or "validation_error"),
            }
            for item in exc.errors(include_url=False)
        ]
        raise ToolExecutionError(
            "invalid_arguments",
            "工具参数校验失败",
            next_action="修正 details.violations 中列出的字段后，使用新的幂等键重试写操作。",
            details={"violations": violations},
        ) from exc


def _input_schema(model: type[BaseModel]) -> dict[str, Any]:
    return model.model_json_schema()


def _output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "operation_id": {"type": "string"},
            "correlation_id": {"type": "string"},
            "failure_message": {"type": ["string", "null"]},
            "error": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "retryable": {"type": "boolean"},
                    "next_action": {"type": "string"},
                    "details": {"type": "object"},
                },
                "required": ["code", "message", "retryable", "next_action", "details"],
                "additionalProperties": False,
            },
        },
        "oneOf": [{"required": ["status"]}, {"required": ["error"]}],
        "additionalProperties": True,
    }


def _annotations(*, read_only: bool, destructive: bool, open_world: bool) -> dict[str, bool]:
    return {
        "readOnlyHint": read_only,
        "destructiveHint": destructive,
        "idempotentHint": True,
        "openWorldHint": open_world,
    }


def _definition(
    tool_id: str,
    name: str,
    description: str,
    model: type[BaseModel],
    *,
    permission: str,
    read_only: bool,
    destructive: bool,
    open_world: bool,
    sensitive_inputs: list[str] | None = None,
    sensitive_outputs: list[str] | None = None,
) -> ToolDefinition:
    metadata: dict[str, Any] = {
        "server_id": SERVER_ID,
        "required_control_permission": "operations.manage",
        "annotations": _annotations(
            read_only=read_only,
            destructive=destructive,
            open_world=open_world,
        ),
        "outputSchema": _output_schema(),
    }
    if sensitive_inputs:
        metadata["sensitive_input_fields"] = sensitive_inputs
    if sensitive_outputs:
        metadata["sensitive_output_fields"] = sensitive_outputs
    return ToolDefinition(
        id=tool_id,
        name=name,
        description=description,
        permission=permission,
        input_schema=_input_schema(model),
        source="builtin",
        metadata=metadata,
    )


PROJECT_DELIVERY_TOOL_DEFINITIONS = [
    _definition(
        "gate_project_upload_begin",
        "开始项目分块上传",
        "创建受控 ZIP 分块上传会话。必须先在本地计算文件大小和 SHA-256。",
        UploadBeginInput,
        permission="write:project_delivery",
        read_only=False,
        destructive=False,
        open_world=False,
    ),
    _definition(
        "gate_project_upload_chunk",
        "上传项目分块",
        "按精确 offset 上传一个不超过 512 KiB 的 base64 分块，并校验分块 SHA-256。",
        UploadChunkInput,
        permission="write:project_delivery",
        read_only=False,
        destructive=False,
        open_world=False,
        sensitive_inputs=["data_base64"],
    ),
    _definition(
        "gate_project_upload_commit",
        "提交项目上传",
        "校验完整 ZIP 大小和 SHA-256，然后执行安全解压与项目分析。",
        UploadCommitInput,
        permission="write:project_delivery",
        read_only=False,
        destructive=False,
        open_world=False,
    ),
    _definition(
        "gate_project_upload_abort",
        "放弃项目上传",
        "明确放弃未提交的上传会话并清理临时分块。",
        UploadAbortInput,
        permission="write:project_delivery",
        read_only=False,
        destructive=True,
        open_world=False,
    ),
    _definition(
        "gate_build_preflight",
        "项目构建预检",
        "只读检查项目根、运行时、工具链和阻断项，不创建构建任务。",
        BuildPreflightInput,
        permission="read:project_delivery",
        read_only=True,
        destructive=False,
        open_world=False,
    ),
    _definition(
        "gate_build_plan",
        "生成构建计划",
        "生成并校验将要执行的标准构建步骤，返回绑定源码摘要的计划指纹。",
        BuildPlanInput,
        permission="read:project_delivery",
        read_only=True,
        destructive=False,
        open_world=False,
    ),
    _definition(
        "gate_build_create",
        "创建项目构建",
        "在源码摘要和计划指纹一致后创建异步构建；不接受自定义命令。",
        BuildCreateInput,
        permission="write:project_delivery",
        read_only=False,
        destructive=True,
        open_world=True,
    ),
    _definition(
        "gate_build_status",
        "查询构建状态",
        "查询构建终态、步骤和游标化脱敏日志。",
        BuildStatusInput,
        permission="read:project_delivery",
        read_only=True,
        destructive=False,
        open_world=False,
        sensitive_outputs=["logs"],
    ),
    _definition(
        "gate_build_cancel",
        "请求取消构建",
        "发送停止请求；运行中的命令及其进程组会被终止，继续轮询直到构建进入终态。",
        BuildCancelInput,
        permission="write:project_delivery",
        read_only=False,
        destructive=True,
        open_world=False,
    ),
    _definition(
        "gate_deploy_build",
        "部署构建产物",
        "部署成功构建。默认不覆盖现有配置且不启动；启动失败会执行目标级补偿。",
        DeployBuildInput,
        permission="write:project_delivery",
        read_only=False,
        destructive=True,
        open_world=True,
    ),
    _definition(
        "gate_deployment_status",
        "查询部署状态",
        "查询部署记录及其目标 MCP Server 当前状态。",
        DeploymentStatusInput,
        permission="read:project_delivery",
        read_only=True,
        destructive=False,
        open_world=False,
    ),
    _definition(
        "gate_server_start",
        "启动目标 MCP Server",
        "在配置摘要一致后显式启动一个已部署的 MCP Server。",
        ServerStartInput,
        permission="write:project_delivery",
        read_only=False,
        destructive=True,
        open_world=True,
    ),
    _definition(
        "gate_server_status",
        "查询 MCP Server 状态",
        "查询目标 MCP Server 的期望状态、运行状态、健康和工具数量。",
        ServerStatusInput,
        permission="read:project_delivery",
        read_only=True,
        destructive=False,
        open_world=False,
    ),
    _definition(
        "gate_server_refresh_tools",
        "刷新 MCP Server 工具",
        "重新执行目标 Server 的 tools/list，原子替换 Registry 工具并刷新读写分类对账；不会发布分类或扩大权限。",
        ServerRefreshToolsInput,
        permission="write:project_delivery",
        read_only=False,
        destructive=False,
        open_world=True,
    ),
]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _utc_now()).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _safe_json_loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        loaded = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _request_digest(arguments: dict[str, Any]) -> str:
    safe_arguments = dict(arguments)
    data_base64 = safe_arguments.pop("data_base64", None)
    if isinstance(data_base64, str):
        safe_arguments["data_base64_digest"] = hashlib.sha256(data_base64.encode("ascii")).hexdigest()
        safe_arguments["data_base64_chars"] = len(data_base64)
    return _sha256_json(safe_arguments)


def _redact_text(value: Any) -> str:
    text = str(value or "")
    try:
        structured = json.loads(text)
    except (TypeError, ValueError):
        structured = None
    if isinstance(structured, (dict, list)):
        text = _canonical_json(_redact_structure(structured))
    redacted = BEARER_TEXT_PATTERN.sub("Bearer [REDACTED]", text)
    redacted = INLINE_SECRET_PATTERN.sub(r"\1\2[REDACTED]", redacted)
    redacted = FLAG_SECRET_PATTERN.sub(r"\1[REDACTED]", redacted)
    if len(redacted) > MAX_LOG_TEXT:
        return f"{redacted[:MAX_LOG_TEXT]}…[TRUNCATED:{len(redacted)}]"
    return redacted


def _redact_structure(value: Any, *, key: str | None = None) -> Any:
    if key and SENSITIVE_OUTPUT_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(item_key): _redact_structure(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [_redact_structure(item) for item in value]
    if isinstance(value, str):
        sanitized = BEARER_TEXT_PATTERN.sub("Bearer [REDACTED]", value)
        sanitized = INLINE_SECRET_PATTERN.sub(r"\1\2[REDACTED]", sanitized)
        return FLAG_SECRET_PATTERN.sub(r"\1[REDACTED]", sanitized)
    return value


class ProjectDeliveryMcpService:
    """复用 Gate Store，并在 MCP 边界补齐校验、幂等和来源绑定。"""

    def __init__(
        self,
        database: SQLiteDatabase,
        data_dir: Path,
        uploads: ProjectUploadStore,
        builds: BuildDeployStore,
        configs: McpConfigStore,
        runtime: McpRuntimeManager,
        observability: ObservabilityStore,
        target_access_checker: TargetAccessChecker | None = None,
        credential_store: CredentialStore | None = None,
        user_credential_store: UserCredentialStore | None = None,
        tool_classification_reconciler: ToolClassificationReconciler | None = None,
    ) -> None:
        self.database = database
        self.uploads = uploads
        self.builds = builds
        self.configs = configs
        self.runtime = runtime
        self.observability = observability
        self.target_access_checker = target_access_checker
        self.credential_store = credential_store
        self.user_credential_store = user_credential_store
        self.tool_classification_reconciler = tool_classification_reconciler
        self.transfer_root = data_dir / "project-upload-transfers"
        self.transfer_root.mkdir(parents=True, exist_ok=True)
        self._transfer_lock = threading.RLock()
        self._deployment_lock = threading.RLock()

    @staticmethod
    def _is_admin_context(context: ToolInvocationContext) -> bool:
        return "admin" in context.roles or "*" in context.permissions

    def _owner_for(self, resource_type: str, resource_id: str) -> str | None:
        row = self.database.query_one(
            """
            SELECT owner_id FROM project_delivery_resource_owners
            WHERE resource_type = ? AND resource_id = ?
            """,
            (resource_type, resource_id),
        )
        return str(row["owner_id"]) if row is not None else None

    def _claim_owner(
        self,
        resource_type: str,
        resource_id: str,
        context: ToolInvocationContext,
    ) -> None:
        now = _iso()
        self.database.execute(
            """
            INSERT OR IGNORE INTO project_delivery_resource_owners (
                resource_type, resource_id, owner_id, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (resource_type, resource_id, context.actor_id, now, now),
        )
        owner = self._owner_for(resource_type, resource_id)
        if owner != context.actor_id and not self._is_admin_context(context):
            raise ToolExecutionError(
                "delivery_resource_not_found_or_forbidden",
                "自动交付资源不存在或当前调用者无权访问",
                next_action="确认资源 ID、资源所有者和目标授权。",
            )

    def _assert_owner(
        self,
        resource_type: str,
        resource_id: str,
        context: ToolInvocationContext,
    ) -> None:
        if self._is_admin_context(context):
            return
        if self._owner_for(resource_type, resource_id) == context.actor_id:
            return
        raise ToolExecutionError(
            "delivery_resource_not_found_or_forbidden",
            "自动交付资源不存在或当前调用者无权访问",
            next_action="确认资源 ID、资源所有者和目标授权。",
        )

    def _assert_target_access(
        self,
        server_id: str,
        required_access: str,
        context: ToolInvocationContext,
    ) -> None:
        owner = self._owner_for("mcp_server", server_id)
        if self._is_admin_context(context) or owner == context.actor_id:
            return
        if self.target_access_checker and self.target_access_checker(
            context,
            server_id,
            required_access,
        ):
            return
        raise ToolExecutionError(
            "target_server_not_found_or_forbidden",
            "目标 MCP Server 不存在或当前调用者缺少服务级授权",
            next_action="请管理员授予该 server_id 的服务级 read/write grant。",
        )

    def _reserve_operation(
        self,
        context: ToolInvocationContext,
        tool_id: str,
        idempotency_key: str,
        arguments: dict[str, Any],
    ) -> tuple[str, dict[str, Any] | ToolExecutionError | None]:
        request_digest = _request_digest(arguments)
        operation_id = uuid4().hex
        now = _iso()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                connection.execute(
                    """
                    INSERT INTO mcp_idempotent_operations (
                        id, actor_id, tool_id, idempotency_key, request_digest,
                        status, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
                    """,
                    (
                        operation_id,
                        context.actor_id,
                        tool_id,
                        idempotency_key,
                        request_digest,
                        now,
                        now,
                    ),
                )
            except sqlite3.IntegrityError:
                row = connection.execute(
                    """
                    SELECT * FROM mcp_idempotent_operations
                    WHERE actor_id = ? AND tool_id = ? AND idempotency_key = ?
                    """,
                    (context.actor_id, tool_id, idempotency_key),
                ).fetchone()
                if row is None:
                    raise
                operation_id = str(row["id"])
                if str(row["request_digest"]) != request_digest:
                    return operation_id, ToolExecutionError(
                        "idempotency_conflict",
                        "同一幂等键已绑定到不同请求",
                        next_action="生成新的 idempotency_key，并重新确认本次操作摘要。",
                        details={"operation_id": operation_id, "tool_id": tool_id},
                    )
                status = str(row["status"])
                if status == "succeeded":
                    result = _safe_json_loads(row["result_json"])
                    result["idempotent_replay"] = True
                    result["replay_correlation_id"] = context.correlation_id
                    return operation_id, result
                if status == "failed":
                    error = _safe_json_loads(row["error_json"]).get("error")
                    if isinstance(error, dict):
                        return operation_id, ToolExecutionError(
                            str(error.get("code") or "operation_failed"),
                            str(error.get("message") or "先前的同幂等请求已经失败"),
                            retryable=bool(error.get("retryable")),
                            next_action=str(error.get("next_action") or "使用新的幂等键重试。"),
                            details=dict(error.get("details") or {}),
                        )
                if status == "pending":
                    last_updated_at = str(row["updated_at"] or "")
                    lease_cutoff = _iso(_utc_now() - IDEMPOTENCY_PENDING_LEASE)
                    if not last_updated_at or last_updated_at <= lease_cutoff:
                        interrupted = ToolExecutionError(
                            "operation_interrupted",
                            "先前的同幂等操作已超出租约，完成状态无法安全确认",
                            retryable=False,
                            next_action=(
                                "先查询对应上传、构建、部署或服务状态；确认副作用未生效后，"
                                "使用新的 idempotency_key 重试。原幂等键不会自动重放。"
                            ),
                            details={
                                "operation_id": operation_id,
                                "tool_id": tool_id,
                                "last_updated_at": last_updated_at or None,
                                "lease_seconds": int(
                                    IDEMPOTENCY_PENDING_LEASE.total_seconds()
                                ),
                                "completion_state": "unknown",
                            },
                        )
                        updated = connection.execute(
                            """
                            UPDATE mcp_idempotent_operations
                            SET status = 'failed', error_json = ?, updated_at = ?
                            WHERE id = ? AND status = 'pending' AND updated_at = ?
                            """,
                            (
                                _canonical_json(interrupted.to_payload()),
                                now,
                                operation_id,
                                last_updated_at,
                            ),
                        )
                        if updated.rowcount == 1:
                            return operation_id, interrupted
                return operation_id, ToolExecutionError(
                    "operation_in_progress",
                    "同一幂等请求正在处理中",
                    retryable=True,
                    next_action="稍后使用相同参数和幂等键重试。",
                    details={"operation_id": operation_id, "tool_id": tool_id},
                )
        return operation_id, None

    def _complete_operation(
        self,
        operation_id: str,
        *,
        result: dict[str, Any],
        resource_type: str,
        resource_id: str | None,
    ) -> None:
        with self.database.connect() as connection:
            updated = connection.execute(
                """
                UPDATE mcp_idempotent_operations
                SET status = 'succeeded', resource_type = ?, resource_id = ?,
                    result_json = ?, error_json = '{}', updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (
                    resource_type,
                    resource_id,
                    _canonical_json(result),
                    _iso(),
                    operation_id,
                ),
            )
            if updated.rowcount != 1:
                current = connection.execute(
                    "SELECT status FROM mcp_idempotent_operations WHERE id = ?",
                    (operation_id,),
                ).fetchone()
                raise ToolExecutionError(
                    "operation_completion_conflict",
                    "操作执行结束，但幂等记录已不再处于 pending 状态",
                    retryable=False,
                    next_action="查询相关资源状态；不要用原幂等键自动重放副作用。",
                    details={
                        "operation_id": operation_id,
                        "operation_status": (
                            str(current["status"]) if current is not None else "missing"
                        ),
                    },
                )

    def _fail_operation(self, operation_id: str, error: ToolExecutionError) -> None:
        self.database.execute(
            """
            UPDATE mcp_idempotent_operations
            SET status = 'failed', error_json = ?, updated_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (_canonical_json(error.to_payload()), _iso(), operation_id),
        )

    def _run_idempotent(
        self,
        context: ToolInvocationContext,
        tool_id: str,
        idempotency_key: str,
        arguments: dict[str, Any],
        resource_type: str,
        action: IdempotentAction,
    ) -> dict[str, Any]:
        operation_id, replay = self._reserve_operation(
            context,
            tool_id,
            idempotency_key,
            arguments,
        )
        if isinstance(replay, ToolExecutionError):
            raise replay
        if isinstance(replay, dict):
            return replay
        try:
            result, resource_id = action(operation_id)
            result.setdefault("operation_id", operation_id)
            result.setdefault("correlation_id", context.correlation_id)
            self._complete_operation(
                operation_id,
                result=result,
                resource_type=resource_type,
                resource_id=resource_id,
            )
            return result
        except ToolExecutionError as exc:
            self._fail_operation(operation_id, exc)
            raise
        except Exception as exc:  # noqa: BLE001 - 工具边界不泄露堆栈和内部路径
            normalized = ToolExecutionError(
                "internal_error",
                "Gate 在处理操作时发生内部错误",
                retryable=False,
                next_action="查看 Gate 服务端审计日志后，使用新的幂等键重试。",
                details={"operation_id": operation_id, "error_type": type(exc).__name__},
            )
            self._fail_operation(operation_id, normalized)
            raise normalized from exc

    def _transfer_path(self, transfer_id: str) -> Path:
        candidate = (self.transfer_root / transfer_id / "source.zip.part").resolve()
        root = self.transfer_root.resolve()
        if root not in candidate.parents:
            raise ToolExecutionError("unsafe_transfer_path", "上传临时路径越界")
        return candidate

    def _delete_transfer_files(self, transfer_id: str) -> None:
        candidate = self._transfer_path(transfer_id).parent
        if candidate.exists():
            shutil.rmtree(candidate)

    @staticmethod
    def _commit_upload_marker(transfer_id: str, filename: str) -> str:
        return f".gate-transfer-{transfer_id}-{filename}"

    def _commit_upload_candidates(self, transfer: Any) -> list[dict[str, Any]]:
        marker = self._commit_upload_marker(
            str(transfer["id"]),
            str(transfer["filename"]),
        )
        rows = self.database.query_all(
            "SELECT id FROM project_uploads WHERE filename = ? ORDER BY created_at",
            (marker,),
        )
        return [self.uploads.get_upload(str(row["id"])) for row in rows]

    def _validate_commit_candidate(self, transfer: Any, upload: dict[str, Any]) -> None:
        upload_id = str(upload.get("id") or "")
        uploads_root = self.uploads.root.resolve()
        source_path = (self.uploads.root / upload_id / "source.zip").resolve()
        if uploads_root not in source_path.parents or not source_path.is_file():
            raise ToolExecutionError(
                "upload_commit_recovery_conflict",
                "提交恢复候选缺少受控 source.zip",
                next_action="保留 transfer 和 upload，由管理员检查存储一致性。",
                details={"transfer_id": str(transfer["id"]), "upload_id": upload_id},
            )
        expected_size = int(transfer["expected_size_bytes"])
        if source_path.stat().st_size != expected_size:
            raise ToolExecutionError(
                "upload_commit_recovery_conflict",
                "提交恢复候选大小与 transfer 声明不一致",
                next_action="保留 transfer 和 upload，由管理员检查存储一致性。",
                details={"transfer_id": str(transfer["id"]), "upload_id": upload_id},
            )
        digest = hashlib.sha256()
        with source_path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
        if digest.hexdigest() != str(transfer["expected_sha256"]):
            raise ToolExecutionError(
                "upload_commit_recovery_conflict",
                "提交恢复候选摘要与 transfer 声明不一致",
                next_action="保留 transfer 和 upload，由管理员检查存储一致性。",
                details={"transfer_id": str(transfer["id"]), "upload_id": upload_id},
            )

    def _finalize_transfer_upload(
        self,
        transfer: Any,
        upload: dict[str, Any],
        actor_id: str,
    ) -> dict[str, Any]:
        """原子绑定 upload owner 与 transfer，避免留下无 owner 的正式资源。"""

        self._validate_commit_candidate(transfer, upload)
        transfer_id = str(transfer["id"])
        upload_id = str(upload["id"])
        filename = str(transfer["filename"])
        marker = self._commit_upload_marker(transfer_id, filename)
        analysis = dict(upload.get("analysis") or {})
        analysis["source_sha256"] = str(transfer["expected_sha256"])
        analysis["source_size_bytes"] = int(transfer["expected_size_bytes"])
        now = _iso()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            current = connection.execute(
                "SELECT status, upload_id FROM project_upload_transfers WHERE id = ? AND actor_id = ?",
                (transfer_id, actor_id),
            ).fetchone()
            if current is None:
                raise ToolExecutionError(
                    "upload_transfer_not_found",
                    "上传会话不存在或不属于当前调用者",
                    next_action="重新调用 gate_project_upload_begin。",
                )
            if (
                str(current["status"]) == "committed"
                and str(current["upload_id"] or "") == upload_id
            ):
                return self.uploads.get_upload(upload_id)
            if str(current["status"]) != "committing":
                raise ToolExecutionError(
                    "upload_transfer_state_conflict",
                    "绑定正式 upload 时 transfer 已不再处于 committing",
                    next_action="查询 transfer 与 upload 状态；不要重复执行 save_zip。",
                    details={"transfer_id": transfer_id, "upload_id": upload_id},
                )
            updated_upload = connection.execute(
                """
                UPDATE project_uploads
                SET filename = ?, analysis_json = ?, updated_at = ?
                WHERE id = ? AND filename = ?
                """,
                (filename, _canonical_json(analysis), now, upload_id, marker),
            )
            if updated_upload.rowcount != 1:
                raise ToolExecutionError(
                    "upload_commit_recovery_conflict",
                    "提交候选在绑定前已被修改",
                    next_action="保留 transfer 和 upload，由管理员检查存储一致性。",
                    details={"transfer_id": transfer_id, "upload_id": upload_id},
                )
            connection.execute(
                """
                INSERT OR IGNORE INTO project_delivery_resource_owners (
                    resource_type, resource_id, owner_id, created_at, updated_at
                ) VALUES ('upload', ?, ?, ?, ?)
                """,
                (upload_id, actor_id, now, now),
            )
            owner = connection.execute(
                """
                SELECT owner_id FROM project_delivery_resource_owners
                WHERE resource_type = 'upload' AND resource_id = ?
                """,
                (upload_id,),
            ).fetchone()
            if owner is None or str(owner["owner_id"]) != actor_id:
                raise ToolExecutionError(
                    "delivery_resource_not_found_or_forbidden",
                    "正式 upload 已被其他所有者绑定",
                    next_action="保留 transfer 和 upload，由管理员检查资源所有权。",
                )
            committed = connection.execute(
                """
                UPDATE project_upload_transfers
                SET status = 'committed', upload_id = ?, updated_at = ?
                WHERE id = ? AND actor_id = ? AND status = 'committing'
                """,
                (upload_id, now, transfer_id, actor_id),
            )
            if committed.rowcount != 1:
                raise ToolExecutionError(
                    "upload_transfer_state_conflict",
                    "正式 upload 已保存，但 transfer 提交状态发生冲突",
                    next_action="查询 transfer 与 upload 状态；不要重复执行 save_zip。",
                    details={"transfer_id": transfer_id, "upload_id": upload_id},
                )
        upload["filename"] = filename
        upload["analysis"] = analysis
        upload["updated_at"] = now
        return upload

    def _recover_stale_transfer(self, transfer: Any) -> Any:
        status = str(transfer["status"])
        if status not in {"writing", "committing"}:
            return transfer
        lease_cutoff = _iso(_utc_now() - TRANSFER_WORK_LEASE)
        lease_updated_at = str(transfer["updated_at"] or "")
        if lease_updated_at and lease_updated_at > lease_cutoff:
            return transfer

        transfer_id = str(transfer["id"])
        actor_id = str(transfer["actor_id"])
        if status == "writing":
            transfer_path = self._transfer_path(transfer_id)
            received = int(transfer["received_size_bytes"])
            with self.database.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                current = connection.execute(
                    "SELECT status, updated_at FROM project_upload_transfers WHERE id = ? AND actor_id = ?",
                    (transfer_id, actor_id),
                ).fetchone()
                if (
                    current is None
                    or str(current["status"]) != "writing"
                    or str(current["updated_at"] or "") != lease_updated_at
                ):
                    return self.database.query_one(
                        "SELECT * FROM project_upload_transfers WHERE id = ? AND actor_id = ?",
                        (transfer_id, actor_id),
                    )
                if not transfer_path.is_file() or transfer_path.stat().st_size < received:
                    connection.execute(
                        """
                        UPDATE project_upload_transfers
                        SET status = 'interrupted', updated_at = ?
                        WHERE id = ? AND actor_id = ? AND status = 'writing' AND updated_at = ?
                        """,
                        (_iso(), transfer_id, actor_id, lease_updated_at),
                    )
                else:
                    with transfer_path.open("r+b") as stream:
                        stream.truncate(received)
                        stream.flush()
                        os.fsync(stream.fileno())
                    connection.execute(
                        """
                        UPDATE project_upload_transfers
                        SET status = 'open', updated_at = ?
                        WHERE id = ? AND actor_id = ? AND status = 'writing' AND updated_at = ?
                        """,
                        (_iso(), transfer_id, actor_id, lease_updated_at),
                    )
        else:
            candidates = self._commit_upload_candidates(transfer)
            if len(candidates) == 1:
                self._finalize_transfer_upload(transfer, candidates[0], actor_id)
            elif len(candidates) == 0:
                self.database.execute(
                    """
                    UPDATE project_upload_transfers
                    SET status = 'open', updated_at = ?
                    WHERE id = ? AND actor_id = ? AND status = 'committing' AND updated_at = ?
                    """,
                    (_iso(), transfer_id, actor_id, lease_updated_at),
                )
            else:
                self.database.execute(
                    """
                    UPDATE project_upload_transfers
                    SET status = 'interrupted', updated_at = ?
                    WHERE id = ? AND actor_id = ? AND status = 'committing' AND updated_at = ?
                    """,
                    (_iso(), transfer_id, actor_id, lease_updated_at),
                )
                raise ToolExecutionError(
                    "upload_commit_recovery_conflict",
                    "同一 transfer 找到多个提交候选，无法安全选择",
                    next_action="保留 transfer 和候选 upload，由管理员检查后处理。",
                    details={
                        "transfer_id": transfer_id,
                        "candidate_upload_ids": [str(item["id"]) for item in candidates],
                    },
                )
        refreshed = self.database.query_one(
            "SELECT * FROM project_upload_transfers WHERE id = ? AND actor_id = ?",
            (transfer_id, actor_id),
        )
        return refreshed if refreshed is not None else transfer

    def _cleanup_expired_transfers(self) -> None:
        now = _iso()
        lease_cutoff = _iso(_utc_now() - TRANSFER_WORK_LEASE)
        with self._transfer_lock:
            rows = self.database.query_all(
                """
                SELECT * FROM project_upload_transfers
                WHERE (status = 'open' AND expires_at < ?)
                   OR (status IN ('writing', 'committing') AND updated_at <= ?)
                """,
                (now, lease_cutoff),
            )
            for row in rows:
                transfer_id = str(row["id"])
                try:
                    row = self._recover_stale_transfer(row)
                except ToolExecutionError:
                    continue
                if str(row["status"]) == "committed":
                    self._delete_transfer_files(transfer_id)
                    continue
                if str(row["status"]) != "open" or str(row["expires_at"]) >= now:
                    continue
                with self.database.connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    claimed = connection.execute(
                        """
                        UPDATE project_upload_transfers
                        SET status = 'expired', updated_at = ?
                        WHERE id = ? AND status = 'open' AND expires_at < ?
                        """,
                        (now, transfer_id, now),
                    )
                if claimed.rowcount == 1:
                    self._delete_transfer_files(transfer_id)

    def _get_transfer(self, transfer_id: str, actor_id: str) -> Any:
        with self._transfer_lock:
            row = self.database.query_one(
                "SELECT * FROM project_upload_transfers WHERE id = ? AND actor_id = ?",
                (transfer_id, actor_id),
            )
            if row is None:
                raise ToolExecutionError(
                    "upload_transfer_not_found",
                    "上传会话不存在或不属于当前调用者",
                    next_action="重新调用 gate_project_upload_begin。",
                )
            row = self._recover_stale_transfer(row)
            now = _iso()
            if str(row["status"]) == "open" and str(row["expires_at"]) < now:
                with self.database.connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    claimed = connection.execute(
                        """
                        UPDATE project_upload_transfers
                        SET status = 'expired', updated_at = ?
                        WHERE id = ? AND actor_id = ? AND status = 'open'
                          AND expires_at < ?
                        """,
                        (now, transfer_id, actor_id, now),
                    )
                if claimed.rowcount == 1:
                    self._delete_transfer_files(transfer_id)
                    raise ToolExecutionError(
                        "upload_transfer_expired",
                        "上传会话已经过期",
                        next_action="重新开始上传。",
                    )
                refreshed = self.database.query_one(
                    "SELECT * FROM project_upload_transfers WHERE id = ? AND actor_id = ?",
                    (transfer_id, actor_id),
                )
                if refreshed is None:
                    raise ToolExecutionError(
                        "upload_transfer_not_found",
                        "上传会话不存在或不属于当前调用者",
                        next_action="重新调用 gate_project_upload_begin。",
                    )
                row = refreshed
            return row

    def project_upload_begin(
        self,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        request = _parse_input(UploadBeginInput, arguments)

        def action(operation_id: str) -> tuple[dict[str, Any], str | None]:
            filename = request.filename.strip()
            if (
                not filename.lower().endswith(".zip")
                or filename in {".", ".."}
                or "/" in filename
                or "\\" in filename
            ):
                raise ToolExecutionError(
                    "invalid_archive_name",
                    "filename 必须是没有路径片段的 .zip 文件名",
                    next_action="使用本地 ZIP 的基本文件名重新发起上传。",
                )
            self._cleanup_expired_transfers()
            transfer_id = uuid4().hex
            transfer_path = self._transfer_path(transfer_id)
            expires_at = _iso(_utc_now() + TRANSFER_TTL)
            now = _iso()
            try:
                transfer_path.parent.mkdir(parents=True, exist_ok=False)
                transfer_path.touch(exist_ok=False)
                self.database.execute(
                    """
                    INSERT INTO project_upload_transfers (
                        id, actor_id, filename, expected_size_bytes, expected_sha256,
                        received_size_bytes, status, temp_path, expires_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, 0, 'open', ?, ?, ?, ?)
                    """,
                    (
                        transfer_id,
                        context.actor_id,
                        filename,
                        request.size_bytes,
                        request.sha256.lower(),
                        str(transfer_path),
                        expires_at,
                        now,
                        now,
                    ),
                )
            except Exception:
                shutil.rmtree(transfer_path.parent, ignore_errors=True)
                raise
            self.observability.emit_event(
                "gate.project_upload.transfer_started",
                source="project_delivery_mcp",
                subject_type="upload_transfer",
                subject_id=transfer_id,
                payload={
                    "actor_id": context.actor_id,
                    "size_bytes": request.size_bytes,
                    "sha256": request.sha256.lower(),
                    "operation_id": operation_id,
                },
            )
            return (
                {
                    "status": "open",
                    "transfer_id": transfer_id,
                    "chunk_size": MAX_CHUNK_BYTES,
                    "next_offset": 0,
                    "expires_at": expires_at,
                },
                transfer_id,
            )

        return self._run_idempotent(
            context,
            "gate_project_upload_begin",
            request.idempotency_key,
            arguments,
            "upload_transfer",
            action,
        )

    def project_upload_chunk(
        self,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        request = _parse_input(UploadChunkInput, arguments)

        def action(operation_id: str) -> tuple[dict[str, Any], str | None]:
            try:
                content = base64.b64decode(request.data_base64, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ToolExecutionError(
                    "invalid_chunk_encoding",
                    "data_base64 不是有效的 base64 数据",
                    next_action="重新读取相同 offset 的本地分块并编码。",
                ) from exc
            if not content or len(content) > MAX_CHUNK_BYTES:
                raise ToolExecutionError(
                    "invalid_chunk_size",
                    f"分块原始大小必须在 1 到 {MAX_CHUNK_BYTES} 字节之间",
                    next_action="按 begin 返回的 chunk_size 重新切分。",
                    details={"decoded_size_bytes": len(content)},
                )
            actual_chunk_sha256 = hashlib.sha256(content).hexdigest()
            if actual_chunk_sha256 != request.chunk_sha256.lower():
                raise ToolExecutionError(
                    "chunk_digest_mismatch",
                    "分块 SHA-256 校验失败",
                    next_action="重新读取该 offset 的本地分块后重试。",
                    details={"actual_sha256": actual_chunk_sha256},
                )

            with self._transfer_lock:
                transfer = self._get_transfer(request.transfer_id, context.actor_id)
                status = str(transfer["status"])
                if status != "open":
                    raise ToolExecutionError(
                        "upload_transfer_not_open",
                        f"上传会话当前状态为 {status}",
                        next_action="查询或重新开始上传。",
                        details={"status": status},
                    )
                received = int(transfer["received_size_bytes"])
                expected = int(transfer["expected_size_bytes"])
                if request.offset < received:
                    chunk = self.database.query_one(
                        """
                        SELECT * FROM project_upload_transfer_chunks
                        WHERE transfer_id = ? AND offset_bytes = ?
                        """,
                        (request.transfer_id, request.offset),
                    )
                    if (
                        chunk is not None
                        and int(chunk["size_bytes"]) == len(content)
                        and str(chunk["sha256"]) == actual_chunk_sha256
                    ):
                        return (
                            {
                                "status": "open",
                                "transfer_id": request.transfer_id,
                                "accepted_bytes": 0,
                                "next_offset": received,
                                "complete": received == expected,
                                "chunk_replayed": True,
                            },
                            request.transfer_id,
                        )
                    raise ToolExecutionError(
                        "chunk_offset_conflict",
                        "该 offset 已经写入不同内容",
                        next_action="按 next_offset 继续，不要覆盖已确认分块。",
                        details={"next_offset": received},
                    )
                if request.offset > received:
                    raise ToolExecutionError(
                        "chunk_out_of_order",
                        "分块 offset 超过服务端 next_offset",
                        retryable=True,
                        next_action="从 details.next_offset 继续上传。",
                        details={"next_offset": received},
                    )
                if received + len(content) > expected:
                    raise ToolExecutionError(
                        "upload_size_exceeded",
                        "分块会使总大小超过 begin 声明值",
                        next_action="检查本地 ZIP 大小并重新开始上传。",
                        details={"expected_size_bytes": expected, "next_offset": received},
                    )

                transfer_path = self._transfer_path(request.transfer_id)
                if not transfer_path.exists() or transfer_path.stat().st_size != received:
                    raise ToolExecutionError(
                        "upload_staging_inconsistent",
                        "上传临时文件与服务端游标不一致",
                        next_action="放弃当前会话并重新上传。",
                    )
                now = _iso()
                with self.database.connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    claimed = connection.execute(
                        """
                        UPDATE project_upload_transfers
                        SET status = 'writing', updated_at = ?
                        WHERE id = ? AND actor_id = ? AND status = 'open'
                          AND received_size_bytes = ? AND expires_at >= ?
                        """,
                        (
                            now,
                            request.transfer_id,
                            context.actor_id,
                            received,
                            now,
                        ),
                    )
                if claimed.rowcount != 1:
                    raise ToolExecutionError(
                        "upload_transfer_state_conflict",
                        "写入分块前上传会话状态或服务端游标已变化",
                        retryable=False,
                        next_action="查询上传会话状态；不要覆盖 staging，请重新开始上传。",
                        details={
                            "transfer_id": request.transfer_id,
                            "expected_offset": received,
                        },
                    )

                next_offset = received + len(content)
                try:
                    with transfer_path.open("r+b") as stream:
                        stream.seek(received)
                        stream.write(content)
                        stream.flush()
                        os.fsync(stream.fileno())
                    with self.database.connect() as connection:
                        connection.execute("BEGIN IMMEDIATE")
                        connection.execute(
                            """
                            INSERT INTO project_upload_transfer_chunks (
                                transfer_id, offset_bytes, size_bytes, sha256, created_at
                            ) VALUES (?, ?, ?, ?, ?)
                            """,
                            (
                                request.transfer_id,
                                request.offset,
                                len(content),
                                actual_chunk_sha256,
                                now,
                            ),
                        )
                        advanced = connection.execute(
                            """
                            UPDATE project_upload_transfers
                            SET received_size_bytes = ?, status = 'open', updated_at = ?
                            WHERE id = ? AND actor_id = ? AND status = 'writing'
                              AND received_size_bytes = ?
                            """,
                            (
                                next_offset,
                                now,
                                request.transfer_id,
                                context.actor_id,
                                received,
                            ),
                        )
                        if advanced.rowcount != 1:
                            raise ToolExecutionError(
                                "upload_transfer_state_conflict",
                                "写入分块期间上传会话状态或服务端游标已变化",
                                retryable=False,
                                next_action="查询上传会话状态；不要覆盖 staging，请重新开始上传。",
                                details={
                                    "transfer_id": request.transfer_id,
                                    "expected_offset": received,
                                },
                            )
                except Exception:
                    with self.database.connect() as connection:
                        connection.execute("BEGIN IMMEDIATE")
                        owned = connection.execute(
                            """
                            SELECT 1 FROM project_upload_transfers
                            WHERE id = ? AND actor_id = ? AND status = 'writing'
                              AND received_size_bytes = ?
                            """,
                            (request.transfer_id, context.actor_id, received),
                        ).fetchone()
                        if owned is not None:
                            if transfer_path.exists():
                                with transfer_path.open("r+b") as stream:
                                    stream.truncate(received)
                            connection.execute(
                                """
                                UPDATE project_upload_transfers
                                SET status = 'open', updated_at = ?
                                WHERE id = ? AND actor_id = ? AND status = 'writing'
                                  AND received_size_bytes = ?
                                """,
                                (
                                    _iso(),
                                    request.transfer_id,
                                    context.actor_id,
                                    received,
                                ),
                            )
                    raise
            return (
                {
                    "status": "open",
                    "transfer_id": request.transfer_id,
                    "accepted_bytes": len(content),
                    "next_offset": next_offset,
                    "complete": next_offset == expected,
                    "chunk_replayed": False,
                },
                request.transfer_id,
            )

        return self._run_idempotent(
            context,
            "gate_project_upload_chunk",
            request.idempotency_key,
            arguments,
            "upload_transfer",
            action,
        )

    def project_upload_commit(
        self,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        request = _parse_input(UploadCommitInput, arguments)

        def action(operation_id: str) -> tuple[dict[str, Any], str | None]:
            with self._transfer_lock:
                transfer = self._get_transfer(request.transfer_id, context.actor_id)
                status = str(transfer["status"])
                if status == "committed" and transfer["upload_id"]:
                    upload = self.uploads.get_upload(str(transfer["upload_id"]))
                    self._delete_transfer_files(request.transfer_id)
                    return self._upload_result(upload), str(upload["id"])
                if status != "open":
                    raise ToolExecutionError(
                        "upload_transfer_not_open",
                        f"上传会话当前状态为 {status}",
                        next_action="重新开始上传。",
                    )
                received = int(transfer["received_size_bytes"])
                expected = int(transfer["expected_size_bytes"])
                if received != expected:
                    raise ToolExecutionError(
                        "upload_incomplete",
                        "尚未收到完整 ZIP",
                        retryable=True,
                        next_action="从 details.next_offset 继续上传。",
                        details={"next_offset": received, "expected_size_bytes": expected},
                    )
                transfer_path = self._transfer_path(request.transfer_id)
                if not transfer_path.exists() or transfer_path.stat().st_size != expected:
                    raise ToolExecutionError(
                        "upload_staging_inconsistent",
                        "上传临时文件大小不一致",
                        next_action="放弃当前会话并重新上传。",
                    )
                digest = hashlib.sha256()
                with transfer_path.open("rb") as stream:
                    while block := stream.read(1024 * 1024):
                        digest.update(block)
                source_sha256 = digest.hexdigest()
                if source_sha256 != str(transfer["expected_sha256"]):
                    raise ToolExecutionError(
                        "digest_mismatch",
                        "完整 ZIP 的 SHA-256 与 begin 声明值不一致",
                        next_action="核对本地 ZIP 摘要并重新开始上传。",
                        details={"actual_sha256": source_sha256},
                    )

                claim_time = _iso()
                with self.database.connect() as connection:
                    connection.execute("BEGIN IMMEDIATE")
                    claimed = connection.execute(
                        """
                        UPDATE project_upload_transfers
                        SET status = 'committing', updated_at = ?
                        WHERE id = ? AND actor_id = ? AND status = 'open'
                          AND received_size_bytes = ? AND expires_at >= ?
                        """,
                        (
                            claim_time,
                            request.transfer_id,
                            context.actor_id,
                            expected,
                            claim_time,
                        ),
                    )
                if claimed.rowcount != 1:
                    raise ToolExecutionError(
                        "upload_transfer_state_conflict",
                        "提交前上传会话状态或服务端游标已变化",
                        retryable=False,
                        next_action="查询上传会话状态；不要删除 staging，请重新开始上传。",
                        details={"transfer_id": request.transfer_id},
                    )
                try:
                    upload = self.uploads.save_zip(
                        filename=self._commit_upload_marker(
                            request.transfer_id,
                            str(transfer["filename"]),
                        ),
                        content=transfer_path.read_bytes(),
                    )
                except (ValueError, zipfile.BadZipFile) as exc:
                    self.database.execute(
                        """
                        UPDATE project_upload_transfers
                        SET status = 'open', updated_at = ?
                        WHERE id = ? AND actor_id = ? AND status = 'committing'
                        """,
                        (_iso(), request.transfer_id, context.actor_id),
                    )
                    raise ToolExecutionError(
                        "invalid_archive",
                        f"ZIP 校验或项目分析失败：{_redact_text(exc)}",
                        next_action="修复 ZIP 结构、路径或大小限制后重新上传。",
                    ) from exc
                except Exception:
                    self.database.execute(
                        """
                        UPDATE project_upload_transfers
                        SET status = 'open', updated_at = ?
                        WHERE id = ? AND actor_id = ? AND status = 'committing'
                        """,
                        (_iso(), request.transfer_id, context.actor_id),
                    )
                    raise
                # save_zip 是文件系统与数据库副作用。之后失败时保留 committing
                # 和带 transfer 标记的候选，由租约恢复完成绑定，绝不再次 save_zip。
                upload = self._finalize_transfer_upload(
                    transfer,
                    upload,
                    context.actor_id,
                )
                self._delete_transfer_files(request.transfer_id)
                self.observability.emit_event(
                    "gate.project_upload.committed",
                    source="project_delivery_mcp",
                    subject_type="upload",
                    subject_id=str(upload["id"]),
                    payload={
                        "transfer_id": request.transfer_id,
                        "actor_id": context.actor_id,
                        "source_sha256": source_sha256,
                        "operation_id": operation_id,
                    },
                )
                return self._upload_result(upload), str(upload["id"])

        return self._run_idempotent(
            context,
            "gate_project_upload_commit",
            request.idempotency_key,
            arguments,
            "upload",
            action,
        )

    def project_upload_abort(
        self,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        request = _parse_input(UploadAbortInput, arguments)

        def action(operation_id: str) -> tuple[dict[str, Any], str | None]:
            with self._transfer_lock:
                transfer = self._get_transfer(request.transfer_id, context.actor_id)
                status = str(transfer["status"])
                if status == "committed":
                    raise ToolExecutionError(
                        "upload_already_committed",
                        "上传已经提交，abort 不会删除正式 upload",
                        next_action="如需删除正式上传，请使用受控资源删除接口。",
                    )
                if status == "committing":
                    raise ToolExecutionError(
                        "upload_commit_in_progress",
                        "上传会话正在提交，当前不能 abort",
                        retryable=True,
                        next_action="稍后查询提交结果；不要并发删除 staging。",
                    )
                if status != "aborted":
                    with self.database.connect() as connection:
                        connection.execute("BEGIN IMMEDIATE")
                        aborted = connection.execute(
                            """
                            UPDATE project_upload_transfers
                            SET status = 'aborted', updated_at = ?
                            WHERE id = ? AND actor_id = ? AND status = 'open'
                            """,
                            (_iso(), request.transfer_id, context.actor_id),
                        )
                    if aborted.rowcount != 1:
                        raise ToolExecutionError(
                            "upload_transfer_state_conflict",
                            "终止上传时会话状态已被其他操作推进",
                            retryable=False,
                            next_action="查询上传会话状态；不要并发删除 staging。",
                            details={"transfer_id": request.transfer_id},
                        )
                    self._delete_transfer_files(request.transfer_id)
            self.observability.emit_event(
                "gate.project_upload.aborted",
                source="project_delivery_mcp",
                subject_type="upload_transfer",
                subject_id=request.transfer_id,
                payload={"actor_id": context.actor_id, "operation_id": operation_id},
            )
            return (
                {"status": "aborted", "transfer_id": request.transfer_id},
                request.transfer_id,
            )

        return self._run_idempotent(
            context,
            "gate_project_upload_abort",
            request.idempotency_key,
            arguments,
            "upload_transfer",
            action,
        )

    @staticmethod
    def _upload_result(upload: dict[str, Any]) -> dict[str, Any]:
        analysis = dict(upload.get("analysis") or {})
        return {
            "status": "committed",
            "upload": {
                "id": str(upload.get("id") or ""),
                "filename": str(upload.get("filename") or ""),
                "status": str(upload.get("status") or ""),
                "detected_runtime": str(upload.get("detected_runtime") or "unknown"),
                "analysis": analysis,
            },
            "source_sha256": str(analysis.get("source_sha256") or ""),
            "source_size_bytes": int(analysis.get("source_size_bytes") or 0),
        }

    def _get_upload(self, upload_id: str) -> dict[str, Any]:
        try:
            return self.uploads.get_upload(upload_id)
        except KeyError as exc:
            raise ToolExecutionError(
                "upload_not_found",
                "找不到指定 upload",
                next_action="确认 upload_id，或重新上传项目。",
                details={"upload_id": upload_id},
            ) from exc

    def _source_sha256(self, upload: dict[str, Any]) -> str:
        source_sha256 = str((upload.get("analysis") or {}).get("source_sha256") or "")
        if not re.fullmatch(SHA256_PATTERN, source_sha256):
            raise ToolExecutionError(
                "upload_provenance_missing",
                "该 upload 缺少 MCP 分块上传写入的源码摘要",
                next_action="通过 gate_project_upload_begin/chunk/commit 重新上传。",
                details={"upload_id": upload.get("id")},
            )
        return source_sha256.lower()

    def _plan_bundle(
        self,
        request: BuildPlanInput | BuildCreateInput,
        *,
        refresh: bool,
    ) -> tuple[dict[str, Any], str, str]:
        upload = self._get_upload(request.upload_id)
        source_sha256 = self._source_sha256(upload)
        try:
            bundle = self.builds.plan_upload(
                request.upload_id,
                runtime_override=request.runtime_override,
                project_root=request.project_root,
                run_install=request.run_install,
                run_build=request.run_build,
                refresh=refresh,
            )
        except (KeyError, ValueError) as exc:
            raise ToolExecutionError(
                "preflight_failed",
                f"无法生成构建计划：{_redact_text(exc)}",
                next_action="检查 runtime_override、project_root 和预检结果。",
            ) from exc
        normalized = validate_plan(dict(bundle.get("plan") or {}))
        bundle["validation"] = {
            "ok": normalized["ok"],
            "errors": normalized["errors"],
        }
        if normalized["ok"]:
            # 指纹和执行器都使用同一份标准化 IR，避免确认后再补默认值。
            bundle["plan"] = normalized["normalized"]
        fingerprint_payload = {
            "upload_id": request.upload_id,
            "source_sha256": source_sha256,
            "runtime_override": request.runtime_override,
            "project_root": request.project_root,
            "run_install": request.run_install,
            "run_build": request.run_build,
            "plan": bundle.get("plan") or {},
            "validation": bundle.get("validation") or {},
        }
        return bundle, source_sha256, _sha256_json(fingerprint_payload)

    def build_preflight(
        self,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        request = _parse_input(BuildPreflightInput, arguments)
        self._assert_owner("upload", request.upload_id, context)
        self._get_upload(request.upload_id)
        try:
            preflight = self.builds.preflight_upload(
                request.upload_id,
                runtime_override=request.runtime_override,
                project_root=request.project_root,
                refresh=request.refresh,
            )
        except (KeyError, ValueError) as exc:
            raise ToolExecutionError(
                "preflight_failed",
                f"构建预检失败：{_redact_text(exc)}",
                next_action="修正项目根或运行时选择后重试。",
            ) from exc
        return {
            "status": str(preflight.get("status") or "unknown"),
            "upload_id": request.upload_id,
            "runtime": preflight.get("runtime"),
            "project_root_dir": preflight.get("project_root_dir"),
            "checks": preflight.get("checks") or [],
            "tools": preflight.get("tools") or {},
            "recommendations": preflight.get("recommendations") or [],
            "cache": preflight.get("cache") or {},
            "diff": preflight.get("diff") or {},
        }

    def build_plan(
        self,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        request = _parse_input(BuildPlanInput, arguments)
        self._assert_owner("upload", request.upload_id, context)
        bundle, source_sha256, plan_fingerprint = self._plan_bundle(
            request,
            refresh=request.refresh,
        )
        return {
            "status": "planned",
            "upload_id": request.upload_id,
            "source_sha256": source_sha256,
            "plan_fingerprint": plan_fingerprint,
            "preflight": bundle.get("preflight") or {},
            "plan": bundle.get("plan") or {},
            "validation": bundle.get("validation") or {},
        }

    def build_create(
        self,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        request = _parse_input(BuildCreateInput, arguments)
        self._assert_owner("upload", request.upload_id, context)

        def action(operation_id: str) -> tuple[dict[str, Any], str | None]:
            bundle, source_sha256, plan_fingerprint = self._plan_bundle(
                request,
                refresh=True,
            )
            if source_sha256 != request.source_sha256.lower():
                raise ToolExecutionError(
                    "source_digest_conflict",
                    "确认的 source_sha256 与当前 upload 不一致",
                    next_action="重新调用 gate_build_plan 并确认新摘要。",
                    details={"actual_source_sha256": source_sha256},
                )
            if plan_fingerprint != request.plan_fingerprint.lower():
                raise ToolExecutionError(
                    "plan_fingerprint_conflict",
                    "确认的构建计划已发生变化",
                    next_action="重新查看 gate_build_plan 的精确命令并再次确认。",
                    details={"actual_plan_fingerprint": plan_fingerprint},
                )
            validation = bundle.get("validation") or {}
            plan = bundle.get("plan") or {}
            if not validation.get("ok") or not plan.get("buildable"):
                raise ToolExecutionError(
                    "build_plan_blocked",
                    "构建计划未通过校验或项目当前不可构建",
                    next_action="解决 preflight/validation 阻断项后重新生成计划。",
                    details={
                        "validation": validation,
                        "preflight_status": (bundle.get("preflight") or {}).get("status"),
                    },
                )
            try:
                build = self.builds.build_upload(
                    request.upload_id,
                    run_install=request.run_install,
                    run_build=request.run_build,
                    timeout_seconds=request.timeout_seconds,
                    runtime_override=request.runtime_override,
                    project_root=request.project_root,
                    prepared_preflight=dict(bundle.get("preflight") or {}),
                    source_sha256=source_sha256,
                    plan_fingerprint=plan_fingerprint,
                    operation_id=operation_id,
                    owner_id=context.actor_id,
                )
            except LocalExecutionBlocked as exc:
                raise ToolExecutionError(
                    exc.code,
                    exc.message,
                    next_action=(
                        "在 local 运行角色中执行构建；"
                        "Core 仅保留分析与计划能力。"
                    ),
                    details=exc.detail(),
                ) from exc
            except BuildBlocked as exc:
                raise ToolExecutionError(
                    str(exc.code or "build_blocked"),
                    str(exc.message or "构建被预检阻断"),
                    next_action="解决 details.preflight 中的阻断项后重新生成计划。",
                    details={"preflight": exc.preflight},
                ) from exc
            except (KeyError, ValueError) as exc:
                raise ToolExecutionError(
                    "build_create_failed",
                    f"创建构建失败：{_redact_text(exc)}",
                    next_action="检查计划和 upload 状态后使用新的幂等键重试。",
                ) from exc
            build_id = str(build["id"])
            build = self.builds.get_build(build_id)
            self._claim_owner("build", build_id, context)
            self.observability.emit_event(
                "gate.build.mcp_created",
                source="project_delivery_mcp",
                subject_type="build",
                subject_id=build_id,
                payload={
                    "actor_id": context.actor_id,
                    "source_sha256": source_sha256,
                    "plan_fingerprint": plan_fingerprint,
                    "operation_id": operation_id,
                },
            )
            result = self._build_result(build)
            result["terminal"] = str(build.get("status")) in TERMINAL_BUILD_STATUSES
            result["poll_after_ms"] = 1_000
            return result, build_id

        return self._run_idempotent(
            context,
            "gate_build_create",
            request.idempotency_key,
            arguments,
            "build",
            action,
        )

    def build_status(
        self,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        request = _parse_input(BuildStatusInput, arguments)
        self._assert_owner("build", request.build_id, context)
        try:
            build = self.builds.get_build(request.build_id)
            rows = self.builds.list_build_logs(
                request.build_id,
                limit=request.log_limit + 1,
                after_sequence=request.after_sequence,
            )
        except KeyError as exc:
            raise ToolExecutionError(
                "build_not_found",
                "找不到指定构建",
                next_action="确认 build_id。",
            ) from exc
        has_more = len(rows) > request.log_limit
        rows = rows[: request.log_limit]
        next_sequence = request.after_sequence
        if rows:
            next_sequence = int(rows[-1].get("sequence") or 0)
        result = self._build_result(build)
        result.update(
            {
                "terminal": str(build.get("status")) in TERMINAL_BUILD_STATUSES,
                "logs": [self._build_log_result(row) for row in rows],
                "next_sequence": next_sequence,
                "has_more": has_more,
                "poll_after_ms": 0
                if str(build.get("status")) in TERMINAL_BUILD_STATUSES
                else 1_000,
            }
        )
        return result

    def build_cancel(
        self,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        request = _parse_input(BuildCancelInput, arguments)
        self._assert_owner("build", request.build_id, context)

        def action(operation_id: str) -> tuple[dict[str, Any], str | None]:
            try:
                build = self.builds.cancel_build(request.build_id)
            except KeyError as exc:
                raise ToolExecutionError(
                    "build_not_found",
                    "找不到指定构建",
                    next_action="确认 build_id。",
                ) from exc
            except ValueError as exc:
                raise ToolExecutionError(
                    "build_not_cancellable",
                    f"构建无法取消：{_redact_text(exc)}",
                    next_action="查询构建终态；取消只对 queued/running 有效。",
                ) from exc
            self.observability.emit_event(
                "gate.build.mcp_cancel_requested",
                source="project_delivery_mcp",
                subject_type="build",
                subject_id=request.build_id,
                payload={"actor_id": context.actor_id, "operation_id": operation_id},
            )
            result = self._build_result(build)
            result.update(
                {
                    "terminal": str(build.get("status")) in TERMINAL_BUILD_STATUSES,
                    "cancel_semantics": "a stop request was sent; the running command and its process group will be terminated; poll until terminal",
                    "poll_after_ms": 1_000,
                }
            )
            return result, request.build_id

        return self._run_idempotent(
            context,
            "gate_build_cancel",
            request.idempotency_key,
            arguments,
            "build",
            action,
        )

    @staticmethod
    def _build_result(build: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": str(build.get("status") or "unknown"),
            "build_id": str(build.get("id") or ""),
            "upload_id": str(build.get("upload_id") or ""),
            "runtime": str(build.get("runtime") or "unknown"),
            "source_sha256": str(build.get("source_sha256") or ""),
            "plan_fingerprint": str(build.get("plan_fingerprint") or ""),
            "steps": build.get("steps") or [],
            "failure_message": (
                _redact_text(build.get("error")) if build.get("error") else None
            ),
            "failure_hint": build.get("failure_hint"),
            "created_at": build.get("created_at"),
            "updated_at": build.get("updated_at"),
        }

    @staticmethod
    def _build_log_result(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "sequence": int(row.get("sequence") or 0),
            "phase": str(row.get("phase") or ""),
            "level": str(row.get("level") or "info"),
            "message": _redact_text(row.get("message")),
            "command": [_redact_text(item) for item in (row.get("command") or [])],
            "returncode": row.get("returncode"),
            "stdout": _redact_text(row.get("stdout")),
            "stderr": _redact_text(row.get("stderr")),
            "duration_ms": row.get("duration_ms"),
            "started_at": row.get("started_at"),
            "finished_at": row.get("finished_at"),
        }

    def _get_build(self, build_id: str) -> dict[str, Any]:
        try:
            return self.builds.get_build(build_id)
        except KeyError as exc:
            raise ToolExecutionError(
                "build_not_found",
                "找不到指定构建",
                next_action="确认 build_id。",
                details={"build_id": build_id},
            ) from exc

    @staticmethod
    def _assert_build_provenance(
        build: dict[str, Any],
        source_sha256: str,
        plan_fingerprint: str,
    ) -> None:
        if str(build.get("source_sha256") or "").lower() != source_sha256.lower():
            raise ToolExecutionError(
                "source_digest_conflict",
                "构建记录的源码摘要与确认值不一致",
                next_action="重新查询构建状态和上传来源。",
            )
        if str(build.get("plan_fingerprint") or "").lower() != plan_fingerprint.lower():
            raise ToolExecutionError(
                "plan_fingerprint_conflict",
                "构建记录的计划指纹与确认值不一致",
                next_action="重新查询构建状态和已确认计划。",
            )

    def _config_digest(self, server_id: str) -> str:
        manifest = self.configs.load_manifest(server_id)
        return _sha256_json(
            manifest.model_dump(mode="json", exclude={"manifest_path"})
        )

    def _credential_state(
        self,
        manifest: McpServerManifest,
        actor_id: str,
    ) -> dict[str, Any]:
        """只返回受管引用和用户 Slot 元数据，不读取秘密、密文或明文哈希。"""

        managed_refs: list[dict[str, Any]] = []
        ref_sources = (
            ("launch.env", manifest.launch.env),
            ("launch.environment", manifest.launch.environment),
            ("transport.headers", manifest.transport.headers),
        )
        for prefix, values in ref_sources:
            for key, value in sorted(values.items()):
                for credential_id in sorted(set(extract_credential_refs(str(value)))):
                    configured = False
                    updated_at: str | None = None
                    if self.credential_store is not None:
                        try:
                            credential = self.credential_store.get_credential(credential_id)
                        except KeyError:
                            pass
                        else:
                            configured = True
                            updated_at = credential.updated_at
                    managed_refs.append(
                        {
                            "location": f"{prefix}.{key}",
                            "credential_id": credential_id,
                            "configured": configured,
                            "updated_at": updated_at,
                        }
                    )

        user_slots: list[dict[str, Any]] = []
        for slot in sorted(manifest.user_credentials, key=lambda item: item.id):
            binding = (
                self.user_credential_store.get_binding(actor_id, manifest.id, slot.id)
                if self.user_credential_store is not None
                else None
            )
            user_slots.append(
                {
                    "slot_id": slot.id,
                    "required": slot.required,
                    "injection": slot.injection.model_dump(mode="json"),
                    "configured_for_actor": binding is not None,
                    "updated_at": binding.get("updated_at") if binding else None,
                }
            )

        digest_payload = {
            "server_id": manifest.id,
            "managed_refs": managed_refs,
            "user_slots": user_slots,
        }
        missing_managed = [
            {"location": item["location"], "credential_id": item["credential_id"]}
            for item in managed_refs
            if not item["configured"]
        ]
        missing_required_slots = [
            item["slot_id"]
            for item in user_slots
            if item["required"] and not item["configured_for_actor"]
        ]
        return {
            **digest_payload,
            "has_credentials": bool(managed_refs or user_slots),
            "binding_digest": _sha256_json(digest_payload),
            "missing_managed_refs": missing_managed,
            "missing_required_slots": missing_required_slots,
        }

    def _prepare_deployment_manifest(
        self,
        candidate: dict[str, Any],
        previous: McpServerManifest | None,
        *,
        actor_id: str,
        credential_policy: str,
        expected_binding_digest: str | None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        next_manifest = McpServerManifest.model_validate(candidate)
        previous_state = (
            self._credential_state(previous, actor_id)
            if previous is not None
            else None
        )
        if previous_state and previous_state["has_credentials"]:
            if credential_policy == "require_none":
                raise ToolExecutionError(
                    "existing_credentials_not_allowed",
                    "目标配置仍包含受管凭据引用或用户凭据 Slot",
                    next_action="改用 preserve_existing 并确认凭据绑定摘要，或先由管理员解除绑定。",
                )
            if expected_binding_digest is None:
                raise ToolExecutionError(
                    "credential_binding_digest_required",
                    "继承已有凭据必须提供 expected_credential_binding_digest",
                    next_action="重新查询 gate_server_status，核对脱敏凭据状态后确认部署。",
                    details={"current_credential_binding_digest": previous_state["binding_digest"]},
                )
            if previous_state["binding_digest"] != expected_binding_digest.lower():
                raise ToolExecutionError(
                    "credential_binding_digest_conflict",
                    "凭据绑定状态在部署确认后发生变化",
                    next_action="重新查询脱敏凭据状态并重新确认部署。",
                    details={"current_credential_binding_digest": previous_state["binding_digest"]},
                )
            if previous_state["missing_managed_refs"] or previous_state["missing_required_slots"]:
                raise ToolExecutionError(
                    "credential_binding_invalid",
                    "已有凭据引用失效或当前调用者缺少必填用户凭据",
                    next_action="修复受管 Credential 或当前用户 Slot 绑定后重试。",
                    details={
                        "missing_managed_refs": previous_state["missing_managed_refs"],
                        "missing_required_slots": previous_state["missing_required_slots"],
                    },
                )
            if previous is None:
                raise RuntimeError("credential state exists without a previous manifest")
            next_manifest = self._merge_managed_credentials(previous, next_manifest)
        elif expected_binding_digest is not None:
            raise ToolExecutionError(
                "credential_binding_missing",
                "确认时存在的凭据绑定目前不存在",
                next_action="重新查询目标配置和凭据状态后重新确认。",
            )

        next_state = self._credential_state(next_manifest, actor_id)
        if credential_policy == "require_none" and next_state["has_credentials"]:
            raise ToolExecutionError(
                "candidate_credentials_not_allowed",
                "credential_policy=require_none 但候选配置包含凭据引用或 Slot",
                next_action="移除候选凭据声明，或改用 preserve_existing 并确认绑定摘要。",
            )
        if next_state["missing_managed_refs"] or next_state["missing_required_slots"]:
            raise ToolExecutionError(
                "credential_binding_invalid",
                "候选配置包含失效凭据引用或缺少必填用户凭据",
                next_action="先在 Gate 绑定凭据，再使用新的幂等键部署。",
                details={
                    "missing_managed_refs": next_state["missing_managed_refs"],
                    "missing_required_slots": next_state["missing_required_slots"],
                },
            )
        return (
            next_manifest.model_dump(mode="json", exclude={"manifest_path"}),
            next_state,
        )

    @staticmethod
    def _merge_managed_credentials(
        previous: McpServerManifest,
        candidate: McpServerManifest,
    ) -> McpServerManifest:
        merged = candidate.model_copy(deep=True)
        maps = (
            ("launch.env", previous.launch.env, merged.launch.env),
            ("launch.environment", previous.launch.environment, merged.launch.environment),
            ("transport.headers", previous.transport.headers, merged.transport.headers),
        )
        for location, old_values, new_values in maps:
            for key, old_value in old_values.items():
                if not extract_credential_refs(str(old_value)):
                    continue
                if key not in new_values:
                    new_values[key] = old_value
                    continue
                if new_values[key] != old_value:
                    raise ToolExecutionError(
                        "credential_reference_conflict",
                        f"候选配置与旧受管凭据引用冲突：{location}.{key}",
                        next_action="保持同一受管引用，或先单独完成凭据迁移。",
                    )

        candidate_slots = {slot.id: slot for slot in merged.user_credentials}
        for previous_slot in previous.user_credentials:
            current = candidate_slots.get(previous_slot.id)
            if current is None:
                merged.user_credentials.append(previous_slot.model_copy(deep=True))
                continue
            if current.model_dump(mode="json") != previous_slot.model_dump(mode="json"):
                raise ToolExecutionError(
                    "credential_slot_conflict",
                    f"候选配置与旧用户凭据 Slot 声明冲突：{previous_slot.id}",
                    next_action="保持原 Slot 注入声明，或先通过独立迁移流程修改。",
                )
        return McpServerManifest.model_validate(
            merged.model_dump(mode="json", exclude={"manifest_path"})
        )

    def _refresh_server_tools(
        self,
        server_id: str,
        context: ToolInvocationContext,
        *,
        fail_on_error: bool,
    ) -> dict[str, Any]:
        try:
            reconciler = self.tool_classification_reconciler
            if reconciler is None:
                raise RuntimeError("tool classification reconciler is not configured")
            reconciliation: dict[str, Any] | None = None

            def reconcile_before_replace(definitions: list[ToolDefinition]) -> None:
                nonlocal reconciliation
                reconciliation = reconciler(
                    server_id,
                    definitions,
                    context.actor_id,
                )

            refreshed = self.runtime.refresh_server_tools(
                server_id,
                before_replace=reconcile_before_replace,
            )
            refreshed.pop("definitions")
            if reconciliation is None:
                raise RuntimeError("tool classification reconciliation did not complete")
            needs_review = int(reconciliation["counts"]["needs_review"])
            result = {
                "status": "needs_review" if needs_review else "ready",
                **refreshed,
                **reconciliation,
            }
            self.observability.emit_event(
                "gate.mcp.server_tools_refreshed",
                source="project_delivery_mcp",
                subject_type="mcp_server",
                subject_id=server_id,
                payload={
                    "actor_id": context.actor_id,
                    "tool_snapshot_digest": result["tool_snapshot_digest"],
                    "counts": result["counts"],
                    "effective_permissions_expanded": False,
                },
            )
            return result
        except Exception as exc:  # noqa: BLE001 - 自动刷新需要返回可恢复的部分完成状态
            if fail_on_error:
                raise ToolExecutionError(
                    "tool_refresh_failed",
                    f"目标工具刷新失败：{_redact_text(exc)}",
                    next_action="确认 Server 仍在运行后，使用新的幂等键重试 gate_server_refresh_tools。",
                    details={"server_id": server_id},
                ) from exc
            return {
                "status": "failed",
                "server_id": server_id,
                "failure_message": _redact_text(exc),
                "effective_permissions_expanded": False,
            }

    def deploy_build(
        self,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        request = _parse_input(DeployBuildInput, arguments)
        self._assert_owner("build", request.build_id, context)

        def action(operation_id: str) -> tuple[dict[str, Any], str | None]:
            build = self._get_build(request.build_id)
            if str(build.get("status")) != "success":
                raise ToolExecutionError(
                    "build_not_ready",
                    f"只有 success 构建可以部署，当前为 {build.get('status') or 'unknown'}",
                    retryable=str(build.get("status")) in {"queued", "running", "cancel_requested"},
                    next_action="等待构建终态；失败构建需先修复并创建新构建。",
                )
            self._assert_build_provenance(
                build,
                request.source_sha256,
                request.plan_fingerprint,
            )
            build_manifest = dict(build.get("manifest") or {})
            server_id = str(request.server_id or build_manifest.get("id") or "").strip()
            if not re.fullmatch(SERVER_ID_PATTERN, server_id):
                raise ToolExecutionError(
                    "invalid_server_id",
                    "构建产物没有安全、有效的 server_id",
                    next_action="显式提供满足字母数字、点、下划线、短横线规则的 server_id。",
                )
            build_manifest["id"] = server_id
            build_manifest["name"] = build_manifest.get("name") or server_id

            # 摘要检查与配置写入必须在同一进程内串行，避免两个不同幂等键同时覆盖目标。
            with self._deployment_lock:
                previous_digest: str | None = None
                previous_manifest: McpServerManifest | None = None
                try:
                    previous_manifest = self.configs.load_manifest(server_id)
                    previous_digest = _sha256_json(
                        previous_manifest.model_dump(
                            mode="json",
                            exclude={"manifest_path"},
                        )
                    )
                except KeyError:
                    previous_digest = None
                target_exists = (
                    previous_digest is not None
                    or self._owner_for("mcp_server", server_id) is not None
                    or self.runtime.has_server(server_id)
                )
                if target_exists:
                    self._assert_target_access(server_id, "write", context)
                if previous_digest is not None and not request.overwrite:
                    raise ToolExecutionError(
                        "server_conflict",
                        "目标 server_id 已存在，默认不会覆盖",
                        next_action="检查现有配置；如确需覆盖，确认当前摘要后设置 overwrite=true。",
                        details={
                            "server_id": server_id,
                            "current_config_digest": previous_digest,
                        },
                    )
                if previous_digest is not None:
                    if request.expected_previous_config_digest is None:
                        raise ToolExecutionError(
                            "previous_config_digest_required",
                            "覆盖已有配置必须提供 expected_previous_config_digest",
                            next_action="读取当前摘要、检查差异并重新确认覆盖。",
                            details={"current_config_digest": previous_digest},
                        )
                    if previous_digest != request.expected_previous_config_digest.lower():
                        raise ToolExecutionError(
                            "previous_config_digest_conflict",
                            "目标配置在确认后发生变化",
                            next_action="重新检查当前配置摘要并重新确认。",
                            details={"current_config_digest": previous_digest},
                        )
                elif request.expected_previous_config_digest is not None:
                    raise ToolExecutionError(
                        "previous_config_missing",
                        "确认时存在的目标配置目前已不存在",
                        next_action="重新检查部署目标并重新确认。",
                    )
                deployment_manifest, credential_state = self._prepare_deployment_manifest(
                    build_manifest,
                    previous_manifest,
                    actor_id=context.actor_id,
                    credential_policy=request.credential_policy,
                    expected_binding_digest=request.expected_credential_binding_digest,
                )
                try:
                    deployment = self.builds.deploy_build(
                        request.build_id,
                        server_id=server_id,
                        start=request.start,
                        overwrite=request.overwrite,
                        owner_id=context.actor_id,
                        manifest_override=deployment_manifest,
                    )
                except LocalExecutionBlocked as exc:
                    raise ToolExecutionError(
                        exc.code,
                        exc.message,
                        next_action=(
                            "在 local 运行角色中执行部署；"
                            "Core 不写入托管工作负载配置。"
                        ),
                        details=exc.detail(),
                    ) from exc
                except (KeyError, ValueError) as exc:
                    raise ToolExecutionError(
                        "deploy_failed",
                        f"部署失败：{_redact_text(exc)}",
                        next_action="检查构建产物和目标配置后使用新的幂等键重试。",
                    ) from exc
            deployment_id = str(deployment.get("id") or "")
            if str(deployment.get("status")) != "success":
                raise ToolExecutionError(
                    "deploy_failed",
                    f"部署未成功：{_redact_text(deployment.get('error'))}",
                    next_action="检查 deployment_id 对应审计信息和目标 Runtime 状态。",
                    details={
                        "deployment_id": deployment_id,
                        "server_id": server_id,
                        "config_applied": bool(deployment.get("config_applied")),
                        "runtime_started": bool(deployment.get("runtime_started")),
                        "rollback_attempted": bool(deployment.get("rollback_attempted")),
                        "rollback_succeeded": deployment.get("rollback_succeeded"),
                        "rollback_error": _redact_text(deployment.get("rollback_error")),
                    },
                )
            if request.start and not bool(deployment.get("started")):
                raise ToolExecutionError(
                    "server_start_failed",
                    "部署记录成功但目标服务未达到 running",
                    next_action="查询 deployment/server 状态并检查启动日志。",
                    details={"deployment_id": deployment_id, "server_id": server_id},
                )
            self._claim_owner("deployment", deployment_id, context)
            self._claim_owner("mcp_server", server_id, context)
            config_digest = self._config_digest(server_id)
            server = self._server_result(server_id)
            tool_refresh = (
                self._refresh_server_tools(server_id, context, fail_on_error=False)
                if request.start and request.refresh_tools
                else {
                    "status": "not_requested" if not request.refresh_tools else "not_running",
                    "server_id": server_id,
                    "effective_permissions_expanded": False,
                }
            )
            self.observability.emit_event(
                "gate.deployment.mcp_completed",
                source="project_delivery_mcp",
                subject_type="deployment",
                subject_id=deployment_id,
                payload={
                    "actor_id": context.actor_id,
                    "server_id": server_id,
                    "overwrite": request.overwrite,
                    "start": request.start,
                    "operation_id": operation_id,
                },
            )
            return (
                {
                    "status": "success",
                    "deployment_id": deployment_id,
                    "build_id": request.build_id,
                    "server_id": server_id,
                    "config_digest": config_digest,
                    "previous_config_digest": previous_digest,
                    "config_applied": bool(deployment.get("config_applied")),
                    "runtime_started": bool(deployment.get("runtime_started")),
                    "credential_state": credential_state,
                    "tool_refresh": tool_refresh,
                    "terminal": True,
                    "server": server,
                },
                deployment_id,
            )

        return self._run_idempotent(
            context,
            "gate_deploy_build",
            request.idempotency_key,
            arguments,
            "deployment",
            action,
        )

    def deployment_status(
        self,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        request = _parse_input(DeploymentStatusInput, arguments)
        self._assert_owner("deployment", request.deployment_id, context)
        try:
            deployment = self.builds.get_deployment(request.deployment_id)
        except KeyError as exc:
            raise ToolExecutionError(
                "deployment_not_found",
                "找不到指定部署记录",
                next_action="确认 deployment_id。",
            ) from exc
        server_id = str(deployment.get("server_id") or "")
        server: dict[str, Any] | None
        try:
            server = self._server_result(server_id)
        except ToolExecutionError:
            server = None
        return {
            "status": str(deployment.get("status") or "unknown"),
            "deployment_id": request.deployment_id,
            "build_id": str(deployment.get("build_id") or ""),
            "server_id": server_id,
            "started": bool(deployment.get("started")),
            "terminal": str(deployment.get("status")) in {"success", "failed"},
            "failure_message": (
                _redact_text(deployment.get("error")) if deployment.get("error") else None
            ),
            "config_applied": bool(deployment.get("config_applied")),
            "runtime_started": bool(deployment.get("runtime_started")),
            "rollback_attempted": bool(deployment.get("rollback_attempted")),
            "rollback_succeeded": deployment.get("rollback_succeeded"),
            "rollback_error": (
                _redact_text(deployment.get("rollback_error"))
                if deployment.get("rollback_error")
                else None
            ),
            "server": server,
            "created_at": deployment.get("created_at"),
            "updated_at": deployment.get("updated_at"),
        }

    def server_start(
        self,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        request = _parse_input(ServerStartInput, arguments)
        self._assert_target_access(request.server_id, "write", context)

        def action(operation_id: str) -> tuple[dict[str, Any], str | None]:
            try:
                config_digest = self._config_digest(request.server_id)
            except KeyError as exc:
                raise ToolExecutionError(
                    "server_config_not_found",
                    "找不到目标 MCP Server 配置",
                    next_action="先完成部署，或确认 server_id。",
                ) from exc
            if config_digest != request.expected_config_digest.lower():
                raise ToolExecutionError(
                    "config_digest_conflict",
                    "目标配置在启动确认后发生变化",
                    next_action="重新检查配置摘要和启动命令后确认。",
                    details={"current_config_digest": config_digest},
                )
            try:
                server = self.runtime.request_start_if_manifest_digest(
                    request.server_id,
                    request.expected_config_digest,
                )
            except KeyError as exc:
                raise ToolExecutionError(
                    "server_not_loaded",
                    "目标 MCP Server 尚未加载到 Runtime",
                    next_action="重新部署或由管理员显式应用该配置。",
                ) from exc
            except McpManifestDigestConflict as exc:
                raise ToolExecutionError(
                    "runtime_manifest_digest_conflict",
                    "目标 Runtime 的实际 Manifest 已与确认摘要不一致",
                    next_action="重新查询服务状态，核对 Runtime 摘要后再确认启动。",
                    details={
                        "server_id": exc.server_id,
                        "expected_config_digest": exc.expected_digest,
                        "runtime_manifest_digest": exc.actual_digest,
                    },
                ) from exc
            if server.status != "running":
                raise ToolExecutionError(
                    "server_start_failed",
                    f"目标服务未达到 running：{server.status}",
                    next_action="查询 server 状态和脱敏日志，修复后使用新的幂等键重试。",
                    details={
                        "server_id": request.server_id,
                        "status": server.status,
                        "last_error": _redact_text(server.last_error),
                    },
                )
            self.observability.emit_event(
                "gate.mcp.server_started",
                source="project_delivery_mcp",
                subject_type="mcp_server",
                subject_id=request.server_id,
                payload={"actor_id": context.actor_id, "operation_id": operation_id},
            )
            result = self._server_result(request.server_id)
            result["tool_refresh"] = (
                self._refresh_server_tools(
                    request.server_id,
                    context,
                    fail_on_error=False,
                )
                if request.refresh_tools
                else {
                    "status": "not_requested",
                    "server_id": request.server_id,
                    "effective_permissions_expanded": False,
                }
            )
            return result, request.server_id

        return self._run_idempotent(
            context,
            "gate_server_start",
            request.idempotency_key,
            arguments,
            "mcp_server",
            action,
        )

    def server_status(
        self,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        request = _parse_input(ServerStatusInput, arguments)
        known_target = (
            self._owner_for("mcp_server", request.server_id) is not None
            or self.runtime.has_server(request.server_id)
        )
        if not known_target:
            try:
                self._config_digest(request.server_id)
            except KeyError:
                pass
            else:
                known_target = True
        if known_target:
            self._assert_target_access(request.server_id, "read", context)
        try:
            result = self._server_result(request.server_id)
            result["runtime_present"] = True
            result["runtime_manifest_digest"] = self.runtime.get_manifest_digest(
                request.server_id
            )
        except ToolExecutionError as exc:
            if exc.code != "server_not_found":
                raise
            result = {
                "status": "not_loaded",
                "server_id": request.server_id,
                "desired_state": "unknown",
                "effective_should_run": False,
                "tool_count": 0,
                "health_status": "unknown",
                "last_error": None,
                "pid": None,
                "updated_at": None,
                "runtime_present": False,
                "runtime_manifest_digest": None,
            }
        try:
            result["config_digest"] = self._config_digest(request.server_id)
            result["config_present"] = True
            manifest = self.configs.load_manifest(request.server_id)
            result["credential_state"] = self._credential_state(
                manifest,
                context.actor_id,
            )
        except KeyError:
            result["config_digest"] = None
            result["config_present"] = False
            result["credential_state"] = None
            if not result["runtime_present"]:
                result["status"] = "not_found"
        return result

    def server_refresh_tools(
        self,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        request = _parse_input(ServerRefreshToolsInput, arguments)
        self._assert_target_access(request.server_id, "write", context)

        def action(operation_id: str) -> tuple[dict[str, Any], str | None]:
            try:
                config_digest = self._config_digest(request.server_id)
            except KeyError as exc:
                raise ToolExecutionError(
                    "server_config_not_found",
                    "找不到目标 MCP Server 配置",
                    next_action="先完成部署，或确认 server_id。",
                ) from exc
            if config_digest != request.expected_config_digest.lower():
                raise ToolExecutionError(
                    "config_digest_conflict",
                    "目标配置在工具刷新确认后发生变化",
                    next_action="重新查询 server 状态和配置摘要后再确认刷新。",
                    details={"current_config_digest": config_digest},
                )
            result = self._refresh_server_tools(
                request.server_id,
                context,
                fail_on_error=True,
            )
            result["operation_id"] = operation_id
            return result, request.server_id

        return self._run_idempotent(
            context,
            "gate_server_refresh_tools",
            request.idempotency_key,
            arguments,
            "mcp_server",
            action,
        )

    def _server_result(self, server_id: str) -> dict[str, Any]:
        try:
            server = self.runtime.get_server(server_id)
        except KeyError as exc:
            raise ToolExecutionError(
                "server_not_found",
                "找不到目标 MCP Server Runtime",
                next_action="确认 server_id 或先部署该服务。",
                details={"server_id": server_id},
            ) from exc
        return {
            "status": server.status,
            "server_id": server.id,
            "desired_state": server.desired_state,
            "effective_should_run": server.effective_should_run,
            "tool_count": server.tool_count,
            "health_status": server.health_status,
            "last_error": _redact_text(server.last_error) if server.last_error else None,
            "pid": server.pid,
            "updated_at": server.desired_state_updated_at,
        }


def register_project_delivery_tools(
    registry: ToolRegistry,
    service: ProjectDeliveryMcpService,
) -> None:
    handlers: dict[str, Callable[[dict[str, Any], ToolInvocationContext], dict[str, Any]]] = {
        "gate_project_upload_begin": service.project_upload_begin,
        "gate_project_upload_chunk": service.project_upload_chunk,
        "gate_project_upload_commit": service.project_upload_commit,
        "gate_project_upload_abort": service.project_upload_abort,
        "gate_build_preflight": service.build_preflight,
        "gate_build_plan": service.build_plan,
        "gate_build_create": service.build_create,
        "gate_build_status": service.build_status,
        "gate_build_cancel": service.build_cancel,
        "gate_deploy_build": service.deploy_build,
        "gate_deployment_status": service.deployment_status,
        "gate_server_start": service.server_start,
        "gate_server_status": service.server_status,
        "gate_server_refresh_tools": service.server_refresh_tools,
    }
    for definition in PROJECT_DELIVERY_TOOL_DEFINITIONS:
        registry.register(
            definition,
            handlers[definition.id],
            contextual=True,
        )

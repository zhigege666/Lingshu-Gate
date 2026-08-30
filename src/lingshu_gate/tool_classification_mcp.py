"""Lingshu Gate 工具读写分类治理工具。"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Callable
from typing import Any, Literal, TypeVar
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lingshu_gate.access_control import (
    AccessControlStore,
    ClassificationConfirmationConflictError,
    iso_now,
)
from lingshu_gate.models import ToolDefinition
from lingshu_gate.registry import ToolExecutionError, ToolInvocationContext, ToolRegistry

CLASSIFICATION_SERVER_ID = "gate-control"
CLASSIFICATION_PERMISSION = "classifications.manage"
SERVER_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$"
IDEMPOTENCY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$"


class _StrictInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ToolClassificationListInput(_StrictInput):
    server_id: str | None = Field(default=None, pattern=SERVER_ID_PATTERN)
    status: Literal["needs_review", "pending", "stale", "published"] | None = None


class ToolClassificationAnalyzeInput(_StrictInput):
    server_id: str | None = Field(default=None, pattern=SERVER_ID_PATTERN)
    idempotency_key: str = Field(pattern=IDEMPOTENCY_PATTERN)
    confirmed: Literal[True]


class ToolClassificationReviewItem(_StrictInput):
    server_id: str = Field(min_length=1, max_length=128, pattern=SERVER_ID_PATTERN)
    tool_id: str = Field(min_length=1, max_length=255)
    expected_fingerprint: str = Field(min_length=1, max_length=128)


class ToolClassificationReviewInput(_StrictInput):
    items: list[ToolClassificationReviewItem] = Field(min_length=1, max_length=500)
    note: str = Field(default="", max_length=2_000)
    idempotency_key: str = Field(pattern=IDEMPOTENCY_PATTERN)
    confirmed: Literal[True]


class ToolClassificationPublishInput(_StrictInput):
    server_id: str | None = Field(default=None, pattern=SERVER_ID_PATTERN)
    tool_ids: list[str] = Field(default_factory=list, max_length=500)
    idempotency_key: str = Field(pattern=IDEMPOTENCY_PATTERN)
    confirmed: Literal[True]


InputModel = TypeVar("InputModel", bound=BaseModel)


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
            next_action="修正 details.violations 中列出的字段后重试。",
            details={"violations": violations},
        ) from exc


def _input_schema(model: type[BaseModel]) -> dict[str, Any]:
    return model.model_json_schema()


def _output_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "status": {"type": "string"},
            "classifications": {"type": "array"},
            "counts": {"type": "object"},
            "confirmed": {"type": "array"},
            "skipped": {"type": "array"},
            "published": {"type": "array"},
            "published_count": {"type": "integer"},
            "error": {"type": "object"},
        },
        "additionalProperties": True,
    }


def _definition(
    tool_id: str,
    name: str,
    description: str,
    model: type[BaseModel],
    *,
    permission: str,
    read_only: bool,
) -> ToolDefinition:
    metadata = {
        "server_id": CLASSIFICATION_SERVER_ID,
        "required_control_permission": CLASSIFICATION_PERMISSION,
        # 分类治理工具必须能在下游工具尚未发布时被分类审核员发现，
        # 但仍由 evaluate() 强制校验 classifications.manage。
        "classification_control_plane": True,
        "annotations": {
            "readOnlyHint": read_only,
            "destructiveHint": not read_only,
            "idempotentHint": True,
            "openWorldHint": False,
        },
        "outputSchema": _output_schema(),
    }
    return ToolDefinition(
        id=tool_id,
        name=name,
        description=description,
        permission=permission,
        input_schema=_input_schema(model),
        source="builtin",
        metadata=metadata,
    )


CLASSIFICATION_TOOL_DEFINITIONS = [
    _definition(
        "gate_tool_classification_list",
        "查询工具读写分类",
        "同步当前 Registry 工具并返回读写分类、fingerprint 和 needs_review 状态；只读，不确认或发布。需要 classifications.manage。",
        ToolClassificationListInput,
        permission="read:tool_classifications",
        read_only=True,
    ),
    _definition(
        "gate_tool_classification_analyze",
        "自动校验工具读写分类",
        "按当前工具元数据刷新规则建议；不会确认、发布或扩大权限。需要 confirmed=true 和 classifications.manage。",
        ToolClassificationAnalyzeInput,
        permission="write:tool_classifications",
        read_only=False,
    ),
    _definition(
        "gate_tool_classification_review",
        "审核并确认工具读写分类",
        "按 fingerprint 原子批量确认分类结论，确认后进入待发布状态；不会直接改变运行时授权。需要 confirmed=true 和 classifications.manage。",
        ToolClassificationReviewInput,
        permission="write:tool_classifications",
        read_only=False,
    ),
    _definition(
        "gate_tool_classification_publish",
        "发布工具读写分类",
        "发布指定 MCP Server 或工具的已确认读写分类，使其进入工具发现和调用授权链路；必须明确发布范围。需要 confirmed=true 和 classifications.manage。",
        ToolClassificationPublishInput,
        permission="write:tool_classifications",
        read_only=False,
    ),
]


class ToolClassificationMcpService:
    """把既有分类状态机安全地暴露为带身份上下文的 MCP 工具。"""

    def __init__(
        self,
        access_store: AccessControlStore,
        registry: ToolRegistry,
    ) -> None:
        self.access_store = access_store
        self.registry = registry

    def list_classifications(
        self,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        request = _parse_input(ToolClassificationListInput, arguments)
        self._require_permission(context)
        self._synchronize()
        classifications = self.access_store.list_classifications(server_id=request.server_id)
        classifications = self._filter_status(classifications, request.status)
        return self._with_summary(
            classifications,
            server_id=request.server_id,
            status=request.status,
        )

    def analyze_classifications(
        self,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        request = _parse_input(ToolClassificationAnalyzeInput, arguments)
        self._require_permission(context)

        def action() -> dict[str, Any]:
            self._synchronize()
            definitions = self._definitions(request.server_id)
            classifications = self.access_store.analyze_tools(definitions)
            if request.server_id:
                classifications = [
                    item
                    for item in classifications
                    if item["server_id"] == request.server_id
                ]
            return self._with_summary(classifications, server_id=request.server_id)

        return self._run_idempotent(
            context,
            "gate_tool_classification_analyze",
            request.idempotency_key,
            arguments,
            resource_id=request.server_id or "all",
            action=action,
        )

    def review_classifications(
        self,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        request = _parse_input(ToolClassificationReviewInput, arguments)
        self._require_permission(context)

        def action() -> dict[str, Any]:
            self._synchronize()
            try:
                result = self.access_store.confirm_classifications(
                    reviewer_id=context.actor_id,
                    items=[item.model_dump() for item in request.items],
                    note=request.note,
                )
            except ClassificationConfirmationConflictError as exc:
                raise ToolExecutionError(
                    "classification_fingerprint_conflict",
                    str(exc),
                    next_action="重新调用 gate_tool_classification_list 获取最新 fingerprint 后再审核。",
                ) from exc
            return {
                "status": "pending" if result["confirmed_count"] else "needs_review",
                **result,
            }

        return self._run_idempotent(
            context,
            "gate_tool_classification_review",
            request.idempotency_key,
            arguments,
            resource_id=request.items[0].server_id,
            action=action,
        )

    def publish_classifications(
        self,
        arguments: dict[str, Any],
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        request = _parse_input(ToolClassificationPublishInput, arguments)
        self._require_permission(context)
        tool_ids = sorted({item.strip() for item in request.tool_ids if item.strip()})
        if not request.server_id and not tool_ids:
            raise ToolExecutionError(
                "publish_scope_required",
                "发布分类必须提供 server_id 或至少一个 tool_id",
                next_action="先调用 gate_tool_classification_list 确认发布范围，再使用新的幂等键重试。",
            )

        def action() -> dict[str, Any]:
            self._synchronize()
            before = self._select_target(request.server_id, tool_ids)
            self.access_store.publish_classifications(
                reviewer_id=context.actor_id,
                server_id=request.server_id,
                tool_ids=tool_ids,
            )
            after = self._select_target(request.server_id, tool_ids)
            before_by_key = {
                (item["server_id"], item["tool_id"]): item
                for item in before
            }
            published = [
                item
                for item in after
                if item["status"] == "published"
                and before_by_key.get(
                    (item["server_id"], item["tool_id"]),
                    {"status": "unknown"},
                )["status"]
                != "published"
            ]
            needs_review = [item for item in after if item["status"] != "published"]
            return {
                "status": "published" if not needs_review else "needs_review",
                "server_id": request.server_id,
                "tool_ids": tool_ids,
                "published": published,
                "published_count": len(published),
                "needs_review_count": len(needs_review),
                "classifications": after,
            }

        return self._run_idempotent(
            context,
            "gate_tool_classification_publish",
            request.idempotency_key,
            {**arguments, "tool_ids": tool_ids},
            resource_id=request.server_id or ",".join(tool_ids),
            action=action,
        )

    def _require_permission(self, context: ToolInvocationContext) -> None:
        roles = set(context.roles)
        permissions = set(context.permissions)
        if "admin" in roles or "*" in permissions or CLASSIFICATION_PERMISSION in permissions:
            if context.auth_type == "token" and context.scopes:
                if not {"*", CLASSIFICATION_PERMISSION}.intersection(context.scopes):
                    raise ToolExecutionError(
                        "classification_permission_required",
                        "当前 API Token 未授予 classifications.manage scope",
                        next_action="换用具有 classifications.manage scope 的 Token。",
                    )
            return
        raise ToolExecutionError(
            "classification_permission_required",
            "当前调用者没有 classifications.manage 控制面权限",
            next_action="请由 Gate 管理员授予 classifications.manage 后重试。",
        )

    def _synchronize(self) -> None:
        self.access_store.synchronize_tools(self.registry.list_definitions())

    def _run_idempotent(
        self,
        context: ToolInvocationContext,
        tool_id: str,
        idempotency_key: str,
        arguments: dict[str, Any],
        *,
        resource_id: str,
        action: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        """复用 Gate 的持久化幂等表，避免审核/发布重试重复产生副作用。"""

        request_digest = hashlib.sha256(
            json.dumps(
                arguments,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        operation_id = uuid4().hex
        now = iso_now()
        with self.access_store.database.connect() as connection:
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
                    raise ToolExecutionError(
                        "idempotency_conflict",
                        "同一幂等键已绑定到不同请求",
                        next_action="生成新的 idempotency_key，并重新确认本次分类操作。",
                        details={"operation_id": operation_id, "tool_id": tool_id},
                    )
                if str(row["status"]) == "succeeded":
                    replay = json.loads(str(row["result_json"] or "{}"))
                    replay["idempotent_replay"] = True
                    replay["replay_correlation_id"] = context.correlation_id
                    return replay
                if str(row["status"]) == "failed":
                    error = json.loads(str(row["error_json"] or "{}")).get("error")
                    if isinstance(error, dict):
                        raise ToolExecutionError(
                            str(error.get("code") or "operation_failed"),
                            str(error.get("message") or "先前的同幂等请求已经失败"),
                            retryable=bool(error.get("retryable")),
                            next_action=str(error.get("next_action") or "使用新的幂等键重试。"),
                            details=dict(error.get("details") or {}),
                        )
                raise ToolExecutionError(
                    "operation_in_progress",
                    "同一幂等请求正在处理中",
                    retryable=True,
                    next_action="稍后使用相同参数和幂等键重试。",
                    details={"operation_id": operation_id, "tool_id": tool_id},
                )

        try:
            result = action()
            result.setdefault("operation_id", operation_id)
            result.setdefault("correlation_id", context.correlation_id)
            self.access_store.database.execute(
                """
                UPDATE mcp_idempotent_operations
                SET status = 'succeeded', resource_type = 'tool_classification',
                    resource_id = ?, result_json = ?, error_json = '{}', updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (
                    resource_id,
                    json.dumps(result, ensure_ascii=False, sort_keys=True, default=str),
                    iso_now(),
                    operation_id,
                ),
            )
            return result
        except ToolExecutionError as exc:
            self.access_store.database.execute(
                """
                UPDATE mcp_idempotent_operations
                SET status = 'failed', error_json = ?, updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (json.dumps(exc.to_payload(), ensure_ascii=False), iso_now(), operation_id),
            )
            raise
        except Exception as exc:  # noqa: BLE001 - 工具边界统一返回结构化错误
            normalized = ToolExecutionError(
                "internal_error",
                "Gate 在处理分类操作时发生内部错误",
                next_action="查看 Gate 服务端审计日志后，使用新的幂等键重试。",
                details={"operation_id": operation_id, "error_type": type(exc).__name__},
            )
            self.access_store.database.execute(
                """
                UPDATE mcp_idempotent_operations
                SET status = 'failed', error_json = ?, updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (json.dumps(normalized.to_payload(), ensure_ascii=False), iso_now(), operation_id),
            )
            raise normalized from exc

    def _definitions(self, server_id: str | None) -> list[ToolDefinition]:
        definitions = self.registry.list_definitions()
        if not server_id:
            return definitions
        return [item for item in definitions if _server_id(item) == server_id]

    def _select_target(
        self,
        server_id: str | None,
        tool_ids: list[str],
    ) -> list[dict[str, Any]]:
        classifications = self.access_store.list_classifications(server_id=server_id)
        if not tool_ids:
            return classifications
        selected = set(tool_ids)
        return [item for item in classifications if item["tool_id"] in selected]

    @staticmethod
    def _filter_status(
        classifications: list[dict[str, Any]],
        status: str | None,
    ) -> list[dict[str, Any]]:
        if status == "needs_review":
            return [item for item in classifications if item["status"] != "published"]
        if status:
            return [item for item in classifications if item["status"] == status]
        return classifications

    @staticmethod
    def _with_summary(
        classifications: list[dict[str, Any]],
        *,
        server_id: str | None,
        status: str | None = None,
    ) -> dict[str, Any]:
        counts = {
            "total": len(classifications),
            "needs_review": sum(item["status"] != "published" for item in classifications),
            "pending": sum(item["status"] == "pending" for item in classifications),
            "stale": sum(item["status"] == "stale" for item in classifications),
            "published": sum(item["status"] == "published" for item in classifications),
        }
        return {
            "server_id": server_id,
            "status": status,
            "classifications": classifications,
            "counts": counts,
        }


def _server_id(definition: ToolDefinition) -> str:
    value = definition.metadata.get("server_id")
    return str(value).strip() if value else "builtin"


def register_tool_classification_tools(
    registry: ToolRegistry,
    service: ToolClassificationMcpService,
) -> None:
    handlers = {
        "gate_tool_classification_list": service.list_classifications,
        "gate_tool_classification_analyze": service.analyze_classifications,
        "gate_tool_classification_review": service.review_classifications,
        "gate_tool_classification_publish": service.publish_classifications,
    }
    for definition in CLASSIFICATION_TOOL_DEFINITIONS:
        registry.register(definition, handlers[definition.id], contextual=True)

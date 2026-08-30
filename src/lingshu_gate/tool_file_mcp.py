"""通用 fileRef 分块上传 MCP 工具。"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from lingshu_gate.models import ToolDefinition
from lingshu_gate.registry import ToolExecutionError, ToolInvocationContext, ToolRegistry
from lingshu_gate.tool_files import (
    MAX_TOOL_FILE_BYTES,
    MAX_TOOL_FILE_CHUNK_BYTES,
    ToolFileError,
    ToolFileStore,
)

SERVER_ID = "gate-tool-files"
SHA256_PATTERN = r"^[0-9a-fA-F]{64}$"
IDEMPOTENCY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$"
MAX_BASE64_CHARS = ((MAX_TOOL_FILE_CHUNK_BYTES + 2) // 3) * 4


class _Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FileBeginInput(_Input):
    filename: str = Field(min_length=1, max_length=255)
    size_bytes: int = Field(ge=1, le=MAX_TOOL_FILE_BYTES)
    sha256: str = Field(pattern=SHA256_PATTERN)
    idempotency_key: str = Field(pattern=IDEMPOTENCY_PATTERN)
    confirmed: Literal[True]


class FileChunkInput(_Input):
    transfer_id: str = Field(min_length=16, max_length=64)
    offset: int = Field(ge=0, le=MAX_TOOL_FILE_BYTES)
    data_base64: str = Field(min_length=4, max_length=MAX_BASE64_CHARS)
    chunk_sha256: str = Field(pattern=SHA256_PATTERN)
    idempotency_key: str = Field(pattern=IDEMPOTENCY_PATTERN)


class FileCommitInput(_Input):
    transfer_id: str = Field(min_length=16, max_length=64)
    idempotency_key: str = Field(pattern=IDEMPOTENCY_PATTERN)


class FileAbortInput(FileCommitInput):
    confirmed: Literal[True]


def _definition(tool_id: str, name: str, description: str, model: type[BaseModel], *, destructive: bool = False) -> ToolDefinition:
    return ToolDefinition(
        id=tool_id,
        name=name,
        description=description,
        permission="write:tool_files",
        input_schema=model.model_json_schema(),
        source="builtin",
        metadata={
            "server_id": SERVER_ID,
            "required_control_permission": "operations.manage",
            "annotations": {
                "readOnlyHint": False,
                "destructiveHint": destructive,
                "idempotentHint": True,
                "openWorldHint": False,
            },
            **({"sensitive_input_fields": ["data_base64"]} if tool_id.endswith("_chunk") else {}),
        },
    )


TOOL_FILE_DEFINITIONS = [
    _definition("gate_file_upload_begin", "开始通用文件上传", "创建最大 4 MiB 的受控分块上传会话。", FileBeginInput),
    _definition("gate_file_upload_chunk", "上传通用文件分块", "按 offset 上传最大 512 KiB 的 Base64 分块。", FileChunkInput),
    _definition("gate_file_upload_commit", "提交通用文件上传", "校验完整文件并返回短期有效、用户绑定的 fileRef。", FileCommitInput),
    _definition("gate_file_upload_abort", "放弃通用文件上传", "放弃未提交会话并清理临时内容。", FileAbortInput, destructive=True),
]


class ToolFileMcpService:
    def __init__(self, store: ToolFileStore) -> None:
        self.store = store

    @staticmethod
    def _parse(model: type[BaseModel], arguments: dict[str, Any]):
        try:
            return model.model_validate(arguments)
        except ValidationError as exc:
            raise ToolExecutionError(
                "invalid_arguments",
                "工具参数校验失败",
                next_action="修正参数后使用新的幂等键重试。",
                details={"violations": exc.errors(include_url=False)},
            ) from exc

    @staticmethod
    def _run(action: Callable[[], dict[str, object]]) -> dict[str, object]:
        try:
            return action()
        except ToolFileError as exc:
            raise ToolExecutionError(exc.code, str(exc), next_action="检查文件状态、归属和有效期后重试。") from exc

    def begin(self, arguments: dict[str, Any], context: ToolInvocationContext) -> dict[str, object]:
        data = self._parse(FileBeginInput, arguments)
        return self._run(lambda: self.store.begin(actor_id=context.actor_id, **data.model_dump(exclude={"confirmed"})))

    def chunk(self, arguments: dict[str, Any], context: ToolInvocationContext) -> dict[str, object]:
        data = self._parse(FileChunkInput, arguments)
        try:
            decoded = base64.b64decode(data.data_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ToolExecutionError("invalid_base64", "data_base64 不是有效的 Base64") from exc
        return self._run(
            lambda: self.store.append_chunk(
                actor_id=context.actor_id,
                transfer_id=data.transfer_id,
                offset=data.offset,
                data=decoded,
                chunk_sha256=data.chunk_sha256,
                idempotency_key=data.idempotency_key,
            )
        )

    def commit(self, arguments: dict[str, Any], context: ToolInvocationContext) -> dict[str, object]:
        data = self._parse(FileCommitInput, arguments)
        return self._run(lambda: self.store.commit(actor_id=context.actor_id, **data.model_dump()))

    def abort(self, arguments: dict[str, Any], context: ToolInvocationContext) -> dict[str, object]:
        data = self._parse(FileAbortInput, arguments)
        return self._run(
            lambda: self.store.abort(actor_id=context.actor_id, transfer_id=data.transfer_id)
        )


def register_tool_file_tools(registry: ToolRegistry, service: ToolFileMcpService) -> None:
    handlers = {
        "gate_file_upload_begin": service.begin,
        "gate_file_upload_chunk": service.chunk,
        "gate_file_upload_commit": service.commit,
        "gate_file_upload_abort": service.abort,
    }
    for definition in TOOL_FILE_DEFINITIONS:
        registry.register(definition, handlers[definition.id], contextual=True)

"""In-memory tool registry for Lingshu Gate."""

from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from lingshu_gate.logging import log_event
from lingshu_gate.models import ToolDefinition, ToolInvokeResponse

ToolHandler = Callable[..., dict[str, Any]]
logger = logging.getLogger(__name__)
SENSITIVE_LOG_KEY = re.compile(
    r"(?:password|passwd|secret|token|authorization|cookie|credential|api[_-]?key|private[_-]?key|data_base64)",
    re.IGNORECASE,
)
MAX_LOG_STRING_LENGTH = 4_096
MAX_LOG_COLLECTION_ITEMS = 100


@dataclass(frozen=True)
class ToolInvocationContext:
    """经过统一鉴权的调用身份；上下文不能由工具参数伪造。"""

    actor_id: str
    username: str
    auth_type: str
    token_id: str | None
    correlation_id: str
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    scopes: tuple[str, ...] = ()


class ToolExecutionError(RuntimeError):
    """携带稳定错误码的工具业务错误。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        next_action: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.next_action = next_action
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "retryable": self.retryable,
                "next_action": self.next_action,
                "details": self.details,
            }
        }


@dataclass(frozen=True)
class ToolRecord:
    definition: ToolDefinition
    handler: ToolHandler
    contextual: bool = False


class ToolNotFoundError(KeyError):
    """Raised when a requested tool is not registered."""


class ToolRegistry:
    """In-memory runtime registry with dynamic source-based registration."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolRecord] = {}
        self._lock = threading.RLock()

    def register(
        self,
        definition: ToolDefinition,
        handler: ToolHandler,
        *,
        replace: bool = False,
        contextual: bool = False,
    ) -> None:
        with self._lock:
            if definition.id in self._tools and not replace:
                raise ValueError(f"Tool already registered: {definition.id}")
            self._tools[definition.id] = ToolRecord(
                definition=definition,
                handler=handler,
                contextual=contextual,
            )
        log_event(
            logger,
            logging.INFO,
            "gate.tool.registered",
            "Tool registered",
            tool_id=definition.id,
            source=definition.source,
            metadata=definition.metadata,
        )

    def unregister_by_metadata(
        self,
        key: str,
        value: Any,
        *,
        source: str | None = None,
    ) -> int:
        """按元数据注销工具；可额外限定工具来源，避免误删内置工具。"""

        with self._lock:
            removed = [
                tool_id
                for tool_id, record in self._tools.items()
                if record.definition.metadata.get(key) == value
                and (source is None or record.definition.source == source)
            ]
            for tool_id in removed:
                self._tools.pop(tool_id, None)
        for tool_id in removed:
            log_event(
                logger,
                logging.INFO,
                "gate.tool.unregistered",
                "Tool unregistered",
                tool_id=tool_id,
                key=key,
                value=value,
                source=source,
            )
        return len(removed)

    def replace_by_metadata(
        self,
        key: str,
        value: Any,
        records: Iterable[ToolRecord],
        *,
        source: str | None = None,
    ) -> dict[str, int]:
        """先校验完整替换集，再一次性替换目标工具，避免暴露部分刷新快照。"""

        replacement: dict[str, ToolRecord] = {}
        for record in records:
            definition = record.definition
            if definition.metadata.get(key) != value:
                raise ValueError(
                    f"Replacement tool metadata mismatch: {definition.id} {key}"
                )
            if source is not None and definition.source != source:
                raise ValueError(
                    f"Replacement tool source mismatch: {definition.id}"
                )
            if definition.id in replacement:
                raise ValueError(f"Duplicate replacement tool: {definition.id}")
            replacement[definition.id] = record

        with self._lock:
            retained = {
                tool_id: record
                for tool_id, record in self._tools.items()
                if not (
                    record.definition.metadata.get(key) == value
                    and (source is None or record.definition.source == source)
                )
            }
            conflicts = sorted(set(retained) & set(replacement))
            if conflicts:
                raise ValueError(
                    "Replacement tool conflicts with another source: "
                    + ", ".join(conflicts)
                )

            removed_count = len(self._tools) - len(retained)
            # One assignment publishes the complete replacement snapshot. Readers
            # protected by the same lock can never observe a partially refreshed set.
            self._tools = {**retained, **replacement}
        log_event(
            logger,
            logging.INFO,
            "gate.tool.snapshot_replaced",
            "Tool snapshot replaced",
            key=key,
            value=value,
            source=source,
            removed_count=removed_count,
            registered_count=len(replacement),
        )
        return {
            "removed_count": removed_count,
            "registered_count": len(replacement),
        }

    def list_definitions(self) -> list[ToolDefinition]:
        with self._lock:
            return [record.definition for record in self._tools.values()]

    def get_definition(self, tool_id: str) -> ToolDefinition:
        with self._lock:
            try:
                return self._tools[tool_id].definition
            except KeyError as exc:
                raise ToolNotFoundError(tool_id) from exc

    def invoke(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        *,
        context: ToolInvocationContext | None = None,
    ) -> ToolInvokeResponse:
        # Only protect snapshot lookup. Handlers can perform long-running I/O and
        # may themselves register tools, so invoking them while holding the registry
        # lock would serialize unrelated traffic and risk lock-order deadlocks.
        with self._lock:
            try:
                record = self._tools[tool_id]
            except KeyError as exc:
                raise ToolNotFoundError(tool_id) from exc

        sensitive_inputs = _metadata_fields(record.definition.metadata, "sensitive_input_fields")
        sensitive_outputs = _metadata_fields(record.definition.metadata, "sensitive_output_fields")
        log_event(
            logger,
            logging.INFO,
            "gate.tool.invoke_started",
            "Tool invocation started",
            tool_id=tool_id,
            source=record.definition.source,
            arguments=_safe_log_value(arguments, sensitive_fields=sensitive_inputs),
        )
        try:
            if record.contextual:
                if context is None:
                    raise ToolExecutionError(
                        "invocation_context_missing",
                        "Authenticated tool invocation context is required",
                    )
                output = record.handler(arguments, context)
            else:
                output = record.handler(arguments)
            log_event(
                logger,
                logging.INFO,
                "gate.tool.invoke_succeeded",
                "Tool invocation succeeded",
                tool_id=tool_id,
                source=record.definition.source,
                output=_safe_log_value(output, sensitive_fields=sensitive_outputs),
            )
            return ToolInvokeResponse(ok=True, tool_id=tool_id, output=output)
        except ToolExecutionError as exc:
            payload = exc.to_payload()
            log_event(
                logger,
                logging.WARNING,
                "gate.tool.invoke_rejected",
                "Tool invocation returned a business error",
                tool_id=tool_id,
                source=record.definition.source,
                error=_safe_log_value(payload, sensitive_fields=sensitive_outputs),
            )
            return ToolInvokeResponse(ok=False, tool_id=tool_id, output=payload, error=exc.message)
        except Exception as exc:  # noqa: BLE001 - tool boundary must normalize errors
            log_event(
                logger,
                logging.ERROR,
                "gate.tool.invoke_failed",
                "Tool invocation failed",
                tool_id=tool_id,
                source=record.definition.source,
                error=str(exc),
                exc_info=True,
            )
            return ToolInvokeResponse(ok=False, tool_id=tool_id, error=str(exc))


def _metadata_fields(metadata: dict[str, Any], name: str) -> frozenset[str]:
    raw = metadata.get(name)
    if not isinstance(raw, list):
        return frozenset()
    return frozenset(str(item).strip().lower() for item in raw if str(item).strip())


def _safe_log_value(
    value: Any,
    *,
    key: str | None = None,
    sensitive_fields: frozenset[str] = frozenset(),
    depth: int = 0,
) -> Any:
    """只生成日志副本；不改变工具实际参数和返回值。"""

    if key and (key.lower() in sensitive_fields or SENSITIVE_LOG_KEY.search(key)):
        return "[REDACTED]"
    if depth >= 8:
        return "[TRUNCATED_DEPTH]"
    if isinstance(value, dict):
        items = list(value.items())
        object_result: dict[str, Any] = {
            str(item_key): _safe_log_value(
                item_value,
                key=str(item_key),
                sensitive_fields=sensitive_fields,
                depth=depth + 1,
            )
            for item_key, item_value in items[:MAX_LOG_COLLECTION_ITEMS]
        }
        if len(items) > MAX_LOG_COLLECTION_ITEMS:
            object_result["_truncated_items"] = len(items) - MAX_LOG_COLLECTION_ITEMS
        return object_result
    if isinstance(value, (list, tuple)):
        list_result = [
            _safe_log_value(item, sensitive_fields=sensitive_fields, depth=depth + 1)
            for item in list(value)[:MAX_LOG_COLLECTION_ITEMS]
        ]
        if len(value) > MAX_LOG_COLLECTION_ITEMS:
            list_result.append(f"[TRUNCATED_ITEMS:{len(value) - MAX_LOG_COLLECTION_ITEMS}]")
        return list_result
    if isinstance(value, bytes):
        return f"[BYTES:{len(value)}]"
    if isinstance(value, str) and len(value) > MAX_LOG_STRING_LENGTH:
        return f"{value[:MAX_LOG_STRING_LENGTH]}…[TRUNCATED:{len(value)}]"
    return value

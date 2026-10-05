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
from lingshu_gate.domain.tool_structure import FrozenToolDefinition, freeze_tool_definition

ToolHandler = Callable[..., dict[str, Any]]
CatalogListener = Callable[[dict[str, ToolDefinition | None]], None]
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
    delegated_scopes: tuple[str, ...] | None = None
    session_id: str | None = None
    oauth_builtin: bool = False
    oauth_issuer: str | None = None
    oauth_resource: str | None = None
    oauth_client_id: str | None = None
    oauth_grant_id: str | None = None
    oauth_family_id: str | None = None
    oauth_token_expires_at: int = 0
    oauth_target_revision: int = 0
    oauth_tool_snapshots: tuple[tuple[str, str], ...] = ()


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


@dataclass(frozen=True)
class RegistryToolSnapshot:
    structure: FrozenToolDefinition
    revision: int


class ToolDispatchRejectedError(ToolExecutionError):
    """The selected record changed before dispatch; no handler was entered."""


@dataclass(frozen=True)
class McpRegistrySnapshot:
    revisions: tuple[tuple[str, int], ...]
    tools: tuple[RegistryToolSnapshot, ...]


class RegistrySnapshotCapacityError(ValueError):
    """An indexed read cannot allocate an unbounded candidate snapshot."""


class ToolNotFoundError(KeyError):
    """Raised when a requested tool is not registered."""


class ToolRegistry:
    """In-memory runtime registry with dynamic source-based registration."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolRecord] = {}
        self._lock = threading.RLock()
        self._revision = 0
        self._structures: dict[str, FrozenToolDefinition] = {}
        self._mcp_index: dict[str, dict[str, RegistryToolSnapshot]] = {}
        self._mcp_revisions: dict[str, int] = {}
        self._catalog_listeners: list[CatalogListener] = []

    def subscribe_catalog(self, listener: CatalogListener) -> None:
        """Seed atomically; listeners only enqueue and never do I/O or callbacks."""
        with self._lock:
            listener({key: record.definition for key, record in self._tools.items()})
            self._catalog_listeners.append(listener)

    def _notify_catalog(self, changes: dict[str, ToolDefinition | None]) -> None:
        for listener in self._catalog_listeners:
            listener(changes)

    def _index_change(self, previous: ToolRecord | None, current: ToolRecord | None,
                      structure: FrozenToolDefinition | None = None) -> None:
        for record, remove in ((previous, True), (current, False)):
            if record is None or record.definition.source != "mcp":
                continue
            instance = record.definition.metadata.get("server_id")
            if not isinstance(instance, str):
                continue
            self._mcp_revisions[instance] = self._revision
            entries = self._mcp_index.setdefault(instance, {})
            if remove:
                entries.pop(record.definition.id, None)
            else:
                assert structure is not None
                entries[record.definition.id] = RegistryToolSnapshot(structure, self._revision)
            if not entries:
                self._mcp_index.pop(instance, None)

    def register(
        self,
        definition: ToolDefinition,
        handler: ToolHandler,
        *,
        replace: bool = False,
        contextual: bool = False,
    ) -> None:
        structure = freeze_tool_definition(definition)
        owned = structure.copy_definition()
        with self._lock:
            if owned.id in self._tools and not replace:
                raise ValueError(f"Tool already registered: {owned.id}")
            previous = self._tools.get(owned.id)
            current = ToolRecord(
                definition=owned,
                handler=handler,
                contextual=contextual,
            )
            self._revision += 1
            self._index_change(previous, current, structure)
            self._structures[owned.id] = structure
            self._tools[owned.id] = current
            self._notify_catalog({owned.id: owned})
        log_event(
            logger,
            logging.INFO,
            "gate.tool.registered",
            "Tool registered",
            tool_id=owned.id,
            source=owned.source,
            metadata=owned.metadata,
        )

    def update_definition(self, definition: ToolDefinition) -> None:
        """Explicit structural publication; preserve the original handler/context."""
        structure = freeze_tool_definition(definition)
        owned = structure.copy_definition()
        with self._lock:
            previous = self._tools.get(owned.id)
            if previous is None:
                raise ToolNotFoundError(owned.id)
            if (owned.source != previous.definition.source
                    or any(owned.metadata.get(key) != previous.definition.metadata.get(key)
                           for key in ("server_id", "original_tool_name"))):
                raise ValueError("Tool identity changes require explicit registration with a handler")
            current = ToolRecord(owned, previous.handler, previous.contextual)
            self._revision += 1
            self._index_change(previous, current, structure)
            self._structures[owned.id] = structure
            self._tools[owned.id] = current
            self._notify_catalog({owned.id: owned})

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
            if removed:
                self._revision += 1
            for tool_id in removed:
                self._index_change(self._tools.pop(tool_id), None)
                self._structures.pop(tool_id)
            if removed:
                self._notify_catalog(dict.fromkeys(removed))
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
        structures: dict[str, FrozenToolDefinition] = {}
        for record in records:
            structure = freeze_tool_definition(record.definition)
            definition = structure.copy_definition()
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
            replacement[definition.id] = ToolRecord(definition, record.handler, record.contextual)
            structures[definition.id] = structure

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
            retired_ids = self._tools.keys() - retained.keys() - replacement.keys()
            self._revision += 1
            for tool_id in self._tools.keys() - retained.keys():
                self._index_change(self._tools[tool_id], None)
                self._structures.pop(tool_id)
            for tool_id, record in replacement.items():
                self._index_change(None, record, structures[tool_id])
            self._structures.update(structures)
            # One assignment publishes the complete replacement snapshot. Readers
            # protected by the same lock can never observe a partially refreshed set.
            self._tools = {**retained, **replacement}
            changes: dict[str, ToolDefinition | None] = dict.fromkeys(retired_ids)
            changes.update({tool_id: record.definition for tool_id, record in replacement.items()})
            self._notify_catalog(changes)
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
            structures = tuple(self._structures.values())
        return [structure.copy_definition() for structure in structures]

    def mcp_snapshot(self, instance_ids: Iterable[str], *, max_tools: int) -> McpRegistrySnapshot:
        """Read only selected instance buckets; definitions change through publication APIs."""
        instances = sorted(set(instance_ids))
        with self._lock:
            if sum(len(self._mcp_index.get(instance, {})) for instance in instances) > max_tools:
                raise RegistrySnapshotCapacityError("indexed_catalog_capacity")
            revisions = tuple((instance, self._mcp_revisions.get(instance, 0)) for instance in instances)
            return McpRegistrySnapshot(revisions, tuple(entry for instance in instances
                for entry in self._mcp_index.get(instance, {}).values()))

    def mcp_snapshot_current(self, revisions: tuple[tuple[str, int], ...]) -> bool:
        with self._lock:
            return all(self._mcp_revisions.get(instance, 0) == revision for instance, revision in revisions)

    def get_definition(self, tool_id: str) -> ToolDefinition:
        with self._lock:
            try:
                structure = self._structures[tool_id]
            except KeyError as exc:
                raise ToolNotFoundError(tool_id) from exc
        return structure.copy_definition()

    def invoke(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        *,
        context: ToolInvocationContext | None = None,
        dispatch_guard: Callable[[], None] | None = None,
        expected_definition: ToolDefinition | None = None,
    ) -> ToolInvokeResponse:
        # Only protect snapshot lookup. Handlers can perform long-running I/O and
        # may themselves register tools, so invoking them while holding the registry
        # lock would serialize unrelated traffic and risk lock-order deadlocks.
        # Credential/database reads precede the registry lock to avoid lock cycles.
        if dispatch_guard is not None:
            dispatch_guard()
        with self._lock:
            try:
                record = self._tools[tool_id]
            except KeyError as exc:
                raise ToolNotFoundError(tool_id) from exc
            if (expected_definition is not None
                    and record.definition.model_dump(mode="json") != expected_definition.model_dump(mode="json")):
                raise ToolDispatchRejectedError("catalog_schema_revision_conflict",
                    "The selected registry record changed before dispatch.")

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

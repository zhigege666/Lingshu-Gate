"""In-memory tool registry for Lingshu Gate."""

from __future__ import annotations

from lingshu_gate.telemetry import mark_execution_started, observed_builtin, queue_lock, remember_failure

import logging
import hashlib
import json
import re
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace as replace_dataclass
from typing import Any

from lingshu_gate.logging import log_event
from lingshu_gate.models import ToolDefinition, ToolInvokeResponse
from lingshu_gate.domain.tool_structure import FrozenToolDefinition, freeze_tool_definition
from lingshu_gate.argument_preparation import ArgumentPreparer, owned_arguments

ToolHandler = Callable[..., dict[str, Any]]
CatalogListener = Callable[[dict[str, ToolDefinition | None], frozenset[str]], None]
logger = logging.getLogger(__name__)
SENSITIVE_LOG_KEY = re.compile(
    r"(?:password|passwd|secret|token|authorization|cookie|credential|api[_-]?key|private[_-]?key|data_base64)",
    re.IGNORECASE,
)
MAX_LOG_STRING_LENGTH = 4_096
MAX_LOG_COLLECTION_ITEMS = 100


def tool_definition_revision(definition: ToolDefinition) -> str:
    """Exact registered descriptor revision for guarded delayed dispatch."""
    raw = json.dumps(definition.model_dump(), sort_keys=True, ensure_ascii=False,
                     separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


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
    oauth_subject: str | None = None
    oauth_audiences: tuple[str, ...] = ()
    oauth_jwks_uri: str | None = None
    external_grant_id: str | None = None
    external_server_ids: tuple[str, ...] = ()
    external_tool_ids: tuple[str, ...] = ()
    external_access: tuple[str, ...] = ()
    external_expires_at: str | None = None
    external_rate_per_minute: int = 0
    external_concurrency: int = 0
    receipt_tool_id: str | None = field(default=None, repr=False, compare=False)
    receipt_arguments_json: str | None = field(default=None, repr=False, compare=False)


def receipt_arguments(context: ToolInvocationContext, tool_id: str, fallback: dict[str, Any]) -> dict[str, Any]:
    """Preserve existing idempotency digests without changing effective inputs."""
    if context.receipt_tool_id == tool_id and context.receipt_arguments_json is not None:
        return json.loads(context.receipt_arguments_json)
    return fallback


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
    argument_preparer: ArgumentPreparer | None = None


@dataclass(frozen=True)
class PreparedInvocation:
    record: ToolRecord = field(repr=False)
    definition_revision: str
    arguments: dict[str, Any] = field(repr=False)
    receipt_arguments_json: str = field(repr=False)


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
        # 临时下线只保留不可调用的定义，用于恢复后识别真正被移除的工具；不保留旧 handler。
        self._unavailable_structures: dict[str, FrozenToolDefinition] = {}
        self._mcp_index: dict[str, dict[str, RegistryToolSnapshot]] = {}
        self._mcp_revisions: dict[str, int] = {}
        self._catalog_listeners: list[CatalogListener] = []

    def subscribe_catalog(self, listener: CatalogListener) -> None:
        """Seed atomically; listeners only enqueue and never do I/O or callbacks."""
        with self._lock:
            listener({key: record.definition for key, record in self._tools.items()}, frozenset())
            self._catalog_listeners.append(listener)

    def _notify_catalog(self, changes: dict[str, ToolDefinition | None], *,
                        retired: frozenset[str] | None = None) -> None:
        if retired is None:
            retired = frozenset(key for key, definition in changes.items() if definition is None)
        for listener in self._catalog_listeners:
            listener(changes, retired)

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
        argument_preparer: ArgumentPreparer | None = None,
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
                argument_preparer=argument_preparer,
            )
            self._revision += 1
            self._index_change(previous, current, structure)
            self._structures[owned.id] = structure
            self._unavailable_structures.pop(owned.id, None)
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
            current = ToolRecord(owned, previous.handler, previous.contextual, previous.argument_preparer)
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
        retire: bool = True,
    ) -> int:
        """按元数据注销工具；临时不可用时保留审核，真实移除默认使审核失效。"""

        with self._lock:
            removed = [
                tool_id
                for tool_id, record in self._tools.items()
                if record.definition.metadata.get(key) == value
                and (source is None or record.definition.source == source)
            ]
            unavailable = {
                tool_id for tool_id, structure in self._unavailable_structures.items()
                if structure.metadata.get(key) == value and (source is None or structure.source == source)
            } if retire else set()
            changed_ids = set(removed) | unavailable
            if changed_ids:
                self._revision += 1
            for tool_id in removed:
                if not retire:
                    self._unavailable_structures[tool_id] = self._structures[tool_id]
                self._index_change(self._tools.pop(tool_id), None)
                self._structures.pop(tool_id)
            if retire:
                for tool_id in changed_ids:
                    self._unavailable_structures.pop(tool_id, None)
            if changed_ids:
                self._notify_catalog(dict.fromkeys(changed_ids),
                                     retired=frozenset(changed_ids) if retire else frozenset())
        for tool_id in sorted(changed_ids):
            log_event(
                logger,
                logging.INFO,
                "gate.tool.unregistered",
                "Tool unregistered",
                tool_id=tool_id,
                key=key,
                value=value,
                source=source,
                retired=retire,
            )
        return len(changed_ids)

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
            replacement[definition.id] = ToolRecord(definition, record.handler, record.contextual, record.argument_preparer)
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
            unavailable = {
                tool_id for tool_id, structure in self._unavailable_structures.items()
                if structure.metadata.get(key) == value and (source is None or structure.source == source)
            }
            conflicts = sorted((set(retained) | (self._unavailable_structures.keys() - unavailable)) & set(replacement))
            if conflicts:
                raise ValueError(
                    "Replacement tool conflicts with another source: "
                    + ", ".join(conflicts)
                )

            removed_count = len(self._tools) - len(retained)
            # 重启后完整 tools/list 仍缺失的旧工具才是真实移除；相同定义继续复用原审核。
            retired_ids = (self._tools.keys() - retained.keys() | unavailable) - replacement.keys()
            self._revision += 1
            for tool_id in self._tools.keys() - retained.keys():
                self._index_change(self._tools[tool_id], None)
                self._structures.pop(tool_id)
            for tool_id, record in replacement.items():
                self._index_change(None, record, structures[tool_id])
            self._structures.update(structures)
            for tool_id in unavailable:
                self._unavailable_structures.pop(tool_id)
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

    def get_definitions(self, tool_ids: Iterable[str]) -> list[ToolDefinition]:
        """Read one atomic snapshot of requested IDs without traversing the registry."""
        requested = tuple(dict.fromkeys(tool_ids))
        with self._lock:
            return [self._structures[key].copy_definition() for key in requested if key in self._structures]

    def get_definition(self, tool_id: str) -> ToolDefinition:
        with self._lock:
            try:
                structure = self._structures[tool_id]
            except KeyError as exc:
                raise ToolNotFoundError(tool_id) from exc
        return structure.copy_definition()

    def prepare(self, tool_id: str, arguments: dict[str, Any], *, expected_definition: ToolDefinition | None = None) -> PreparedInvocation:
        with queue_lock(self._lock):
            record = self._tools.get(tool_id)
            if record is None:
                raise ToolNotFoundError(tool_id)
            revision = tool_definition_revision(record.definition)
            if expected_definition is not None and revision != tool_definition_revision(expected_definition):
                raise ToolDispatchRejectedError("catalog_schema_revision_conflict", "The selected tool definition changed before preparation.")
        effective = owned_arguments(arguments)
        raw = json.dumps(effective, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if record.argument_preparer is not None:
            effective = owned_arguments(record.argument_preparer(effective))
        return PreparedInvocation(record, revision, effective, raw)

    @observed_builtin
    def invoke(
        self,
        tool_id: str,
        arguments: dict[str, Any],
        *,
        context: ToolInvocationContext | None = None,
        dispatch_guard: Callable[[], None] | None = None,
        expected_definition: ToolDefinition | None = None,
        prepared: PreparedInvocation | None = None,
        arguments_guard: Callable[[dict[str, Any]], None] | None = None,
        dispatch_started: Callable[[], None] | None = None,
    ) -> ToolInvokeResponse:
        # Only protect snapshot lookup. Handlers can perform long-running I/O and
        # may themselves register tools, so invoking them while holding the registry
        # lock would serialize unrelated traffic and risk lock-order deadlocks.
        prepared = prepared or self.prepare(tool_id, arguments, expected_definition=expected_definition)
        arguments = prepared.arguments
        with queue_lock(self._lock):
            try:
                record = self._tools[tool_id]
            except KeyError as exc:
                raise ToolNotFoundError(tool_id) from exc
            if (expected_definition is not None
                    and record.definition.model_dump(mode="json") != expected_definition.model_dump(mode="json")):
                raise ToolDispatchRejectedError("catalog_schema_revision_conflict",
                    "The selected registry record changed before dispatch.")
            if record is not prepared.record:
                raise ToolDispatchRejectedError("catalog_schema_revision_conflict", "The selected executor changed before dispatch.")

        # No database/authority callback runs under the registry lock. Perform
        # both final guards after queueing, on the same owned values as handler.
        if dispatch_guard is not None:
            dispatch_guard()
        if arguments_guard is not None:
            arguments_guard(arguments)
        # A guard may itself publish or await a replacement. Read the current
        # record without another blocking lock after the final policy check.
        if self._tools.get(tool_id) is not record:
            raise ToolDispatchRejectedError("catalog_schema_revision_conflict", "The selected executor changed during dispatch checks.")
        if context is not None:
            context = replace_dataclass(context, receipt_tool_id=tool_id,
                                        receipt_arguments_json=prepared.receipt_arguments_json)

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
                if dispatch_started is not None:
                    dispatch_started()
                mark_execution_started()
                output = record.handler(arguments, context)
            else:
                if dispatch_started is not None:
                    dispatch_started()
                mark_execution_started()
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
            remember_failure(exc)
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
            remember_failure(exc)
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

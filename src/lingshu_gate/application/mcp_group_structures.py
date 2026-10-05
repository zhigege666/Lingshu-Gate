"""Bounded structural memoization; no principals, reviews, grants or visibility."""
from __future__ import annotations

import threading
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass

from lingshu_gate.access_control import _tool_fingerprint
from lingshu_gate.domain.mcp_group_catalog import (
    NormalizedToolContract, normalize_tool_contract, uncomparable_contract,
)
from lingshu_gate.domain.tool_structure import FrozenToolDefinition
from lingshu_gate.domain.mcp_groups import McpGroupError
from lingshu_gate.registry import RegistryToolSnapshot

MAX_STRUCTURE_CACHE_ENTRIES = 50_000
MAX_STRUCTURE_CACHE_BYTES = 64 * 1024 * 1024
PREPARATION_WAIT_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class PreparedToolStructure:
    definition: FrozenToolDefinition
    fingerprint: str
    contract: NormalizedToolContract
    cache_bytes: int


def prepare_tool_structure(entry: RegistryToolSnapshot) -> PreparedToolStructure:
    # Registry bounds and isolates this identity; retain no mutable temporary.
    definition = entry.structure.copy_definition()
    fingerprint = _tool_fingerprint(definition)
    try:
        contract = normalize_tool_contract(definition)
    except (ValueError, TypeError, AttributeError):
        contract = uncomparable_contract("outputSchema" in definition.metadata)
    return PreparedToolStructure(entry.structure, fingerprint, contract,
        entry.structure.byte_count + contract.byte_count + len(fingerprint) + 512)


class ToolStructureCache:
    def __init__(self, *, max_entries: int = MAX_STRUCTURE_CACHE_ENTRIES,
                 max_bytes: int = MAX_STRUCTURE_CACHE_BYTES) -> None:
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self._entries: OrderedDict[tuple[int, FrozenToolDefinition], PreparedToolStructure] = OrderedDict()
        self._bytes = 0
        self._lock = threading.Lock()
        self._preparation_locks = tuple(threading.Lock() for _ in range(64))

    def get_many(self, entries: Iterable[RegistryToolSnapshot]) -> list[PreparedToolStructure]:
        items = tuple(entries)
        # Hold every hit before inserting misses can evict an unvisited hit.
        # These request-local references contain only immutable structure.
        with self._lock:
            hits = []
            for entry in items:
                key = (entry.revision, entry.structure)
                cached = self._entries.get(key)
                hits.append(cached)
                if cached is not None:
                    self._entries.move_to_end(key)
        return [cached if cached is not None else self.get(entry)
                for entry, cached in zip(items, hits, strict=True)]

    def get(self, entry: RegistryToolSnapshot) -> PreparedToolStructure:
        key = (entry.revision, entry.structure)
        with self._lock:
            cached = self._entries.get(key)
            if cached is not None:
                self._entries.move_to_end(key)
                return cached
        # Fixed stripes bound coordination memory and prevent duplicate cold
        # preparation. No Registry/config/database/global cache lock is held.
        preparation_lock = self._preparation_locks[hash(key) % len(self._preparation_locks)]
        if not preparation_lock.acquire(timeout=PREPARATION_WAIT_SECONDS):
            raise McpGroupError("group_catalog_busy", "Structural preparation is busy; retry this read.", 409)
        try:
            with self._lock:
                cached = self._entries.get(key)
                if cached is not None:
                    self._entries.move_to_end(key)
                    return cached
            prepared = prepare_tool_structure(entry)
            with self._lock:
                if self.max_entries < 1 or prepared.cache_bytes > self.max_bytes:
                    return prepared
                self._entries[key] = prepared
                self._bytes += prepared.cache_bytes
                while len(self._entries) > self.max_entries or self._bytes > self.max_bytes:
                    _, removed = self._entries.popitem(last=False)
                    self._bytes -= removed.cache_bytes
                return prepared
        finally:
            preparation_lock.release()

    def usage(self) -> tuple[int, int]:
        with self._lock:
            return len(self._entries), self._bytes

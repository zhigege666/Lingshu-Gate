"""Minimal normalized dependency/offline-worker contracts, not a downloader.

No npm/pnpm/Yarn lock-to-full-graph adapter, cache installer, network adapter or
worker is supplied. Producer limits also apply before parsing any lockfile.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import NoReturn
from urllib.parse import urlsplit

from lingshu_gate.git_source import SNAPSHOT_CHUNK_BYTES, digest_json
from lingshu_gate.network_settings import validate_endpoint
from lingshu_gate.ports.safe_network_executor import ExecutorReadiness
from lingshu_gate.registry import ToolExecutionError

SHA256 = re.compile(r"^[0-9a-f]{64}$")
DEPENDENCY_ID = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9._/@()+:-]{0,199}$")
GRAPH_LIMITS = {"nodes": 5_000, "edges": 20_000, "metadata_bytes": 4 * 1024 * 1024}
BUILD_LIMITS = {"timeout_seconds": 1_800, "memory_bytes": 16 * 1024 * 1024 * 1024, "cpu_millis": 16_000, "pids": 1_024}


def _deny(message: str) -> NoReturn:
    raise ToolExecutionError("offline_contract_invalid", message, next_action="Prepare a complete reviewed source/tool/dependency inventory; online fallback is prohibited.")


def parse_strong_sri(value: str) -> tuple[str, bytes]:
    """Validate one canonical strong content hash before any cache parsing."""
    if not isinstance(value, str) or len(value) > 128:
        _deny("Dependency integrity exceeds its bounded SRI field")
    matched = re.fullmatch(r"(sha256|sha384|sha512)-([A-Za-z0-9+/]+={0,2})", value)
    if not matched:
        _deny("Dependency integrity must be one explicit SHA-256/384/512 SRI; missing, weak or alternative algorithms are unsupported")
    try:
        decoded = base64.b64decode(matched[2], validate=True)
    except ValueError:
        _deny("Dependency SRI encoding is invalid")
    if len(decoded) != int(matched[1][3:]) // 8 or base64.b64encode(decoded).decode() != matched[2]:
        _deny("Dependency SRI length or canonical encoding is invalid")
    return matched[1], decoded


@dataclass(frozen=True)
class DependencyNode:
    """One normalized content node after all lock/peer/platform decisions.

    dependencies includes every selected transitive/dev/optional/peer edge.
    An adapter must prove complete importer/workspace closure before creating
    this record; this validator cannot infer omitted lockfile dependencies.
    """

    key: str
    source_url: str
    integrity: str
    dependencies: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerifiedDependencyGraph:
    nodes: tuple[DependencyNode, ...]
    roots: tuple[str, ...]
    sha256: str


def validate_dependency_graph(nodes: Iterable[DependencyNode], roots: tuple[str, ...], *, allowed_origins: frozenset[str]) -> VerifiedDependencyGraph:
    """Bound normalized records/edges as consumed; no downloads or lock parsing."""
    if not isinstance(roots, tuple) or not roots or len(roots) > GRAPH_LIMITS["nodes"] or any(not isinstance(root, str) or not DEPENDENCY_ID.fullmatch(root) for root in roots) or len(set(roots)) != len(roots):
        _deny("Dependency graph requires bounded, distinct importer roots")
    if not allowed_origins or len(allowed_origins) > 32:
        _deny("Dependency origin policy must be bounded and explicit")
    for origin in allowed_origins:
        if not isinstance(origin, str) or len(origin) > 2048:
            _deny("Dependency origin policy requires bounded HTTPS origins")
        try:
            validate_endpoint(origin, {"https"})
            parts = urlsplit(origin)
            if parts.path or origin != f"{parts.scheme}://{parts.netloc}":
                raise ValueError
        except ValueError:
            _deny("Dependency origin policy requires exact HTTPS origins")
    indexed: dict[str, DependencyNode] = {}
    edges = metadata_bytes = 0
    for node in nodes:
        if len(indexed) >= GRAPH_LIMITS["nodes"]:
            _deny("Dependency graph exceeds its node limit")
        if not isinstance(node, DependencyNode) or not isinstance(node.dependencies, tuple) or any(not isinstance(value, str) for value in (node.key, node.source_url, node.integrity)):
            _deny("Dependency graph requires immutable normalized records")
        if not DEPENDENCY_ID.fullmatch(node.key) or node.key in indexed:
            _deny("Dependency graph contains an invalid or duplicate content key")
        if len(node.source_url) > 2048 or len(node.integrity) > 128:
            _deny("Dependency graph record exceeds its metadata field limits")
        edges += len(node.dependencies)
        if edges > GRAPH_LIMITS["edges"]:
            _deny("Dependency graph exceeds its edge limit")
        if any(not isinstance(key, str) or not DEPENDENCY_ID.fullmatch(key) for key in node.dependencies) or len(set(node.dependencies)) != len(node.dependencies):
            _deny("Dependency edges must use distinct normalized content keys")
        metadata_bytes += len(node.key.encode()) + len(node.source_url.encode()) + len(node.integrity.encode()) + sum(len(key.encode()) for key in node.dependencies)
        if metadata_bytes > GRAPH_LIMITS["metadata_bytes"]:
            _deny("Dependency graph exceeds its metadata byte limit")
        parse_strong_sri(node.integrity)
        try:
            validate_endpoint(node.source_url, {"https"})
            parts = urlsplit(node.source_url)
            if f"{parts.scheme}://{parts.netloc}" not in allowed_origins:
                raise ValueError
        except ValueError:
            _deny("Dependency source is outside the exact HTTPS origin policy; Git/file/link sources need separate review")
        indexed[node.key] = node
    if any(root not in indexed for root in roots) or any(key not in indexed for node in indexed.values() for key in node.dependencies):
        _deny("Dependency graph is incomplete: importer root or transitive content is missing")
    reachable: set[str] = set()
    pending = list(roots)
    while pending:
        key = pending.pop()
        if key not in reachable:
            reachable.add(key)
            pending.extend(indexed[key].dependencies)
    if reachable != set(indexed):
        _deny("Dependency graph contains content outside the selected importer closure")
    ordered = tuple(indexed[key] for key in sorted(indexed))
    ordered_roots = tuple(sorted(roots))
    digest = digest_json({"roots": ordered_roots, "nodes": [{"key": node.key, "source_url": node.source_url, "integrity": node.integrity, "dependencies": sorted(node.dependencies)} for node in ordered]})
    return VerifiedDependencyGraph(ordered, ordered_roots, digest)


def verify_dependency_content(node: DependencyNode, chunks: Iterable[bytes], *, max_bytes: int) -> None:
    """Verify bounded downloaded/cache content; never fetch or extract it."""
    if type(max_bytes) is not int or not 0 < max_bytes <= 50 * 1024 * 1024:
        _deny("Dependency content requires a positive bounded byte limit")
    algorithm, expected = parse_strong_sri(node.integrity)
    digest = hashlib.new(algorithm)
    total = 0
    for chunk in chunks:
        if not isinstance(chunk, bytes) or not chunk or len(chunk) > SNAPSHOT_CHUNK_BYTES or total + len(chunk) > max_bytes:
            _deny("Dependency content exceeds its byte or producer chunk limit")
        total += len(chunk)
        digest.update(chunk)
    if not hmac.compare_digest(digest.digest(), expected):
        _deny("Dependency content does not match its pinned SRI")


@dataclass(frozen=True)
class OfflineBuildRequest:
    """Secret-free request for a future reviewed, physically offline worker.

    Digests select immutable content, not host paths, images or live registries.
    This is validated only by fixtures in this slice; it cannot execute builds.
    """

    source_sha256: str
    file_list_sha256: str
    toolchain_sha256: str
    dependency_graph_sha256: str
    cache_sha256: str
    command: tuple[str, ...]
    timeout_seconds: int
    memory_bytes: int
    cpu_millis: int
    pids: int
    environment: tuple[tuple[str, str], ...] = ()

    def validate(self, readiness: ExecutorReadiness) -> None:
        readiness.require("offline_build")
        if any(not isinstance(value, str) or not SHA256.fullmatch(value) for value in (self.source_sha256, self.file_list_sha256, self.toolchain_sha256, self.dependency_graph_sha256, self.cache_sha256)):
            _deny("Offline build content must be pinned by full SHA-256 digests")
        if not isinstance(self.command, tuple) or not self.command or len(self.command) > 128 or any(not isinstance(value, str) or not value or len(value) > 4096 or "\0" in value for value in self.command):
            _deny("Offline build command exceeds its argument limits")
        if any(type(value) is not int or not 0 < value <= BUILD_LIMITS[key] for key, value in (("timeout_seconds", self.timeout_seconds), ("memory_bytes", self.memory_bytes), ("cpu_millis", self.cpu_millis), ("pids", self.pids))):
            _deny("Offline builds require positive bounded deadline, CPU, memory and process limits")
        if not isinstance(self.environment, tuple) or len(self.environment) > 16 or any(not isinstance(pair, tuple) or len(pair) != 2 or any(not isinstance(value, str) for value in pair) for pair in self.environment):
            _deny("Offline build environment requires bounded immutable text pairs")
        if len({key for key, _ in self.environment}) != len(self.environment):
            _deny("Offline build environment must be bounded and distinct")
        for key, value in self.environment:
            if not isinstance(key, str) or not isinstance(value, str) or key not in {"LANG", "LC_ALL", "NODE_ENV", "CI", "SOURCE_DATE_EPOCH"} or len(value) > 256 or "\0" in value:
                _deny("Offline build environment cannot contain proxy, credential or tool bootstrap settings")

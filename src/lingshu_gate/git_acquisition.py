"""Bounded raw Git object verification/export; no network or executor adapter.

The backend owns trusted acquisition; this module never shells out or checks
out a tree. Verified bytes still pass the existing Core ZIP/inventory boundary.
"""

from __future__ import annotations

import hashlib
import io
import re
import stat
import threading
import time
import zipfile
from dataclasses import dataclass, field
from typing import Any, NoReturn
from urllib.parse import urlsplit

from lingshu_gate.git_source import (
    COMMIT_RE, GIT_ENVIRONMENT_POLICY, GIT_POLICY, SNAPSHOT_CHUNK_BYTES,
    GitSourceInput, SnapshotContentScanner, digest_json, repository_rule,
    snapshot_forbidden_values, validate_snapshot_path,
)
from lingshu_gate.network_settings import NetworkSelection
from lingshu_gate.ports.git_acquisition import GitObject, GitObjectReader, TrustedGitBackend
from lingshu_gate.ports.safe_network_executor import ExecutorReadiness, SafeExecutionCancelled
from lingshu_gate.project_uploads import MAX_EXTRACTED_BYTES, MAX_FILES, MAX_ZIP_BYTES
from lingshu_gate.registry import ToolExecutionError

OBJECT_LIMITS = {
    "transfer_bytes": MAX_ZIP_BYTES, "object_bytes": MAX_EXTRACTED_BYTES + 16 * 1024 * 1024,
    "objects": 10_000, "tree_entries": 10_000, "tree_bytes": 4 * 1024 * 1024,
    "commit_bytes": 64 * 1024,
}


class _SourceRejected(ToolExecutionError):
    """Fixed local policy messages, distinct from untrusted backend failures."""


def _reject(code: str, message: str) -> NoReturn:
    raise _SourceRejected(code, message, next_action="Review the complete source and request a new exact-commit import; no fallback is available.")


@dataclass(frozen=True)
class VerifiedSourceSnapshot:
    commit_sha: str
    content: bytes = field(repr=False)
    source_sha256: str
    file_list_sha256: str
    # Immutable inventory entries: path, byte count, SHA-256. No network material.
    files: tuple[tuple[str, int, str], ...]

    def inventory(self) -> list[dict[str, Any]]:
        return [{"path": path, "size_bytes": size, "sha256": digest} for path, size, digest in self.files]


class _BoundedZip(io.BytesIO):
    def __init__(self, maximum: int) -> None:
        super().__init__()
        self.maximum = maximum

    def write(self, data: Any) -> int:
        if self.tell() + len(data) > self.maximum:
            _reject("git_snapshot_size_limit", "Git snapshot exceeds the compressed byte limit")
        return super().write(data)


class _Budget:
    def __init__(self, limits: dict[str, int], deadline: float, cancel: threading.Event) -> None:
        self.limits, self.deadline, self.cancel = limits, deadline, cancel
        self.objects = self.object_bytes = self.entries = self.files = self.expanded = 0

    def checkpoint(self) -> None:
        if self.cancel.is_set():
            # A scanner cannot establish sandbox termination. Backend context
            # exit may upgrade this only after confirming whole-group cleanup.
            raise InterruptedError("Git acquisition cancellation needs backend termination evidence")
        if time.monotonic() >= self.deadline:
            raise TimeoutError("Git acquisition verification deadline exceeded")


class _ObjectStream:
    def __init__(self, item: GitObject, oid: str, kind: str, budget: _Budget) -> None:
        budget.checkpoint()
        if item.kind != kind:
            _reject("git_object_type_invalid", "Git object type does not match the commit tree")
        maximum = budget.limits.get(f"{kind}_bytes", budget.limits["expanded_bytes"])
        if type(item.size_bytes) is not int or not 0 <= item.size_bytes <= maximum:
            _reject("git_object_size_limit", "Git object exceeds its type-specific byte limit")
        budget.objects += 1
        if budget.objects > budget.limits["objects"] or budget.object_bytes + item.size_bytes > budget.limits["object_bytes"]:
            _reject("git_object_size_limit", "Git object count or total bytes exceed the acquisition limit")
        self.item, self.oid, self.budget = item, oid, budget
        self.remaining = item.size_bytes
        # The current public Git contract supports only SHA-1 / 40 hex IDs.
        # Collision-aware Git decoding belongs to the reviewed backend; this
        # compatibility digest is not a SHA-1 collision detector.
        self.digest = hashlib.sha1(f"{kind} {item.size_bytes}\0".encode("ascii"))

    def read(self, size: int) -> bytes:
        self.budget.checkpoint()
        requested = min(size, self.remaining, SNAPSHOT_CHUNK_BYTES)
        chunk = self.item.stream.read(requested)
        self.budget.checkpoint()
        if not isinstance(chunk, bytes) or len(chunk) > requested or (requested and not chunk):
            _reject("git_object_stream_invalid", "Git object stream is truncated or violates bounded reads")
        self.remaining -= len(chunk)
        self.budget.object_bytes += len(chunk)
        self.digest.update(chunk)
        return chunk

    def exact(self, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            if not self.remaining:
                _reject("git_object_stream_invalid", "Git tree object contains a truncated entry")
            data.extend(self.read(size - len(data)))
        return bytes(data)

    def field(self, delimiter: bytes, maximum: int) -> bytes:
        data = bytearray()
        while True:
            value = self.exact(1)
            if value == delimiter:
                return bytes(data)
            if len(data) >= maximum:
                _reject("git_tree_invalid", "Git tree entry name or mode exceeds its parser limit")
            data.extend(value)

    def finish(self) -> None:
        self.budget.checkpoint()
        extra = self.item.stream.read(1) if not self.remaining else b""
        self.budget.checkpoint()
        if self.remaining or extra != b"":
            _reject("git_object_stream_invalid", "Git object size does not match its declared size")
        if self.digest.hexdigest() != self.oid:
            _reject("git_object_hash_mismatch", "Git object content does not match the confirmed object ID")


def _commit_tree(objects: GitObjectReader, commit: str, budget: _Budget) -> str:
    with objects.open_object(commit) as item:
        reader = _ObjectStream(item, commit, "commit", budget)
        data = bytearray()
        while reader.remaining:
            data.extend(reader.read(SNAPSHOT_CHUNK_BYTES))
        reader.finish()
    headers, separator, _ = bytes(data).partition(b"\n\n")
    lines = headers.split(b"\n")
    if not separator or not re.fullmatch(rb"tree [0-9a-f]{40}", lines[0]) or sum(line.startswith(b"tree ") for line in lines) != 1:
        _reject("git_commit_invalid", "Git commit must identify one supported SHA-1 root tree")
    return lines[0][5:].decode("ascii")


def _tree_entries(objects: GitObjectReader, oid: str, prefix: str, budget: _Budget, forbidden: frozenset[bytes], seen: set[str]) -> list[tuple[str, str, str]]:
    entries: list[tuple[str, str, str]] = []
    with objects.open_object(oid) as item:
        reader = _ObjectStream(item, oid, "tree", budget)
        while reader.remaining:
            budget.entries += 1
            if budget.entries > budget.limits["tree_entries"]:
                _reject("git_tree_entry_limit", "Git tree entry count exceeds the acquisition limit")
            mode = reader.field(b" ", 6)
            raw_name = reader.field(b"\0", 255)
            child = reader.exact(20).hex()
            if mode == b"160000":
                _reject("git_submodule_unsupported", "Git submodules are unsupported, including outside the selected project")
            if mode == b"120000":
                _reject("git_symlink_unsupported", "Git symlinks are unsupported, including outside the selected project")
            if mode not in {b"40000", b"100644", b"100755"}:
                _reject("git_tree_mode_unsupported", "Git tree contains an unsupported file type")
            try:
                name = raw_name.decode("utf-8", errors="strict")
                if not name or "/" in name or name in {".", ".."}:
                    raise ValueError("Git tree entry must be one safe path component")
                if name.lower().endswith(".gitmodules"):
                    _reject("git_submodule_unsupported", "Git submodule configuration is unsupported, including outside the selected project")
                entry = zipfile.ZipInfo(prefix + name)
                entry.external_attr = (stat.S_IFDIR | 0o755 if mode == b"40000" else stat.S_IFREG | int(mode, 8) & 0o777) << 16
                path, key = validate_snapshot_path(entry, forbidden)
            except (UnicodeError, ValueError):
                _reject("git_snapshot_path_rejected", "Git source contains an unsafe, sensitive or unsupported path")
            if key in seen:
                _reject("git_snapshot_path_rejected", "Git source contains duplicate or ambiguous paths")
            seen.add(key)
            entries.append((path, mode.decode("ascii"), child))
        reader.finish()
    return entries


def _export_tree(objects: GitObjectReader, oid: str, prefix: str, budget: _Budget, forbidden: frozenset[bytes], seen: set[str], archive: zipfile.ZipFile, inventory: list[dict[str, Any]]) -> None:
    # Validate the complete bounded tree object/hash before traversing children.
    for path, mode, child in _tree_entries(objects, oid, prefix, budget, forbidden, seen):
        if mode == "40000":
            _export_tree(objects, child, path + "/", budget, forbidden, seen, archive, inventory)
            continue
        budget.files += 1
        if budget.files > budget.limits["files"]:
            _reject("git_snapshot_file_limit", "Git snapshot exceeds the file count limit")
        with objects.open_object(child) as item:
            reader = _ObjectStream(item, child, "blob", budget)
            if budget.expanded + item.size_bytes > budget.limits["expanded_bytes"]:
                _reject("git_snapshot_size_limit", "Git snapshot exceeds the expanded byte limit")
            budget.expanded += item.size_bytes
            scanner = SnapshotContentScanner(forbidden, item.size_bytes)
            entry = zipfile.ZipInfo(path)
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = (stat.S_IFREG | int(mode, 8) & 0o777) << 16
            with archive.open(entry, "w") as writer:
                while reader.remaining:
                    chunk = reader.read(SNAPSHOT_CHUNK_BYTES)
                    try:
                        scanner.update(chunk)
                    except ValueError as exc:
                        # Scanner messages are fixed text, never file contents.
                        _reject("git_snapshot_content_rejected", str(exc))
                    writer.write(chunk)
                reader.finish()
            inventory.append({"path": path, "size_bytes": scanner.size, "sha256": scanner.digest.hexdigest()})


def _validated_request(request: dict[str, Any]) -> dict[str, Any]:
    try:
        allowed = {"source", "network", "host_rule", "git_config", "environment_policy", "limits", "credential_revision", "commit_sha"}
        if set(request) - allowed or not isinstance(request["network"], dict):
            raise ValueError
        for phase in ("git", "install"):
            selected = NetworkSelection.model_validate(request["network"][phase])
            if selected.mode == "inherit" or (selected.mode == "profile" and (type(selected.version) is not int or selected.version < 1)):
                raise ValueError
        source = GitSourceInput.model_validate(request["source"])
        repository_rule(source.repository_url, [request["host_rule"]])
        if request["git_config"] != GIT_POLICY or request["environment_policy"] != GIT_ENVIRONMENT_POLICY:
            raise ValueError
        maxima = {"compressed_bytes": MAX_ZIP_BYTES, "expanded_bytes": MAX_EXTRACTED_BYTES, "files": MAX_FILES, "resolve_seconds": 15, "fetch_seconds": 120, "export_seconds": 30, **OBJECT_LIMITS}
        limits = dict(maxima)
        if not isinstance(request["limits"], dict):
            raise ValueError
        for key, value in request["limits"].items():
            if key == "retry_count" and type(value) is int and value == 0:
                continue
            if key not in maxima or type(value) is not int or not 0 < value <= maxima[key]:
                raise ValueError
            limits[key] = value
        # Bound acquisition transfer separately from the expanded object stream.
        limits["transfer_bytes"] = min(limits["transfer_bytes"], limits["compressed_bytes"])
        return {**request, "source": source.model_dump(), "limits": {**limits, "retry_count": 0}}
    except (KeyError, TypeError, ValueError):
        _reject("git_acquisition_request_invalid", "Git acquisition request violates the pinned source or safety limits")
    raise AssertionError("unreachable")


class VerifiedGitAcquisition:
    """Source-only adapter. It cannot satisfy or enable SafeNetworkExecutor."""

    def __init__(self, backend: TrustedGitBackend | None) -> None:
        self.backend = backend

    def _backend(self, request: dict[str, Any], material: dict[str, Any]) -> TrustedGitBackend:
        readiness = self.backend.readiness() if self.backend else ExecutorReadiness("missing", "unknown")
        try:
            readiness.require("git_acquisition")
        except ToolExecutionError as exc:
            raise _SourceRejected(exc.code, exc.message, next_action=exc.next_action, details=exc.details) from None
        if self.backend is None:
            _reject("safe_executor_unavailable", "No reviewed trusted Git backend is installed")
        proxy = material.get("proxy")
        if (request["network"]["git"]["mode"] == "profile") != bool(proxy):
            _reject("network_material_missing", "The pinned Git proxy selection and acquisition material do not match; direct fallback is prohibited")
        if proxy and urlsplit(proxy).scheme not in self.backend.proxy_schemes:
            _reject("proxy_scheme_unsupported", "The trusted acquisition backend does not support the selected proxy scheme")
        return self.backend

    def resolve_commit(self, request: dict[str, Any], *, material: dict[str, Any], timeout_seconds: int) -> str:
        prepared = _validated_request(request)
        if type(timeout_seconds) is not int or not 0 < timeout_seconds <= prepared["limits"]["resolve_seconds"]:
            _reject("git_acquisition_request_invalid", "Git resolution timeout exceeds the confirmed limit")
        temporary = dict(material)
        try:
            backend = self._backend(prepared, temporary)
            deadline = time.monotonic() + timeout_seconds
            sha = backend.resolve_commit(prepared, material=temporary, timeout_seconds=timeout_seconds)
            if time.monotonic() >= deadline:
                raise TimeoutError("Git resolution deadline exceeded")
            source = prepared["source"]
            if not isinstance(sha, str) or not COMMIT_RE.fullmatch(sha) or (source["ref_type"] == "commit" and sha != source["ref"]):
                _reject("git_commit_mismatch", "The backend did not resolve the exact supported SHA-1 commit")
            return sha
        except _SourceRejected:
            raise
        except TimeoutError:
            raise TimeoutError("Git resolution deadline exceeded") from None
        except Exception:
            _reject("git_resolution_failed", "Trusted Git commit resolution failed; backend output is withheld")
        finally:
            temporary.clear()

    def acquire_snapshot(self, request: dict[str, Any], *, material: dict[str, Any], cancel: threading.Event) -> VerifiedSourceSnapshot:
        prepared = _validated_request(request)
        commit = prepared.get("commit_sha")
        if not isinstance(commit, str) or not COMMIT_RE.fullmatch(commit) or (prepared["source"]["ref_type"] == "commit" and commit != prepared["source"]["ref"]):
            _reject("git_commit_mismatch", "Git acquisition requires the confirmed full SHA-1 commit")
        temporary = dict(material)
        try:
            backend = self._backend(prepared, temporary)
            forbidden = snapshot_forbidden_values([value for value in temporary.values() if isinstance(value, str)])
            deadline = time.monotonic() + prepared["limits"]["fetch_seconds"]
            budget = _Budget(prepared["limits"], deadline, cancel)
            budget.checkpoint()
            with backend.fetch_exact(prepared, material=temporary, cancel=cancel, deadline=deadline) as objects:
                if objects.object_format != "sha1":
                    _reject("git_object_format_unsupported", "Only SHA-1 Git repositories are supported; no object algorithm conversion is performed")
                if objects.commit_sha != commit:
                    _reject("git_commit_mismatch", "Fetched Git content does not match the confirmed commit")
                budget.deadline = min(deadline, time.monotonic() + prepared["limits"]["export_seconds"])
                tree = _commit_tree(objects, commit, budget)
                output = _BoundedZip(prepared["limits"]["compressed_bytes"])
                inventory: list[dict[str, Any]] = []
                with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=False) as archive:
                    _export_tree(objects, tree, "", budget, forbidden, set(), archive, inventory)
                budget.checkpoint()
                inventory.sort(key=lambda item: item["path"])
                project = prepared["source"]["project_root"]
                if not inventory or (project != "." and not any(item["path"].startswith(project + "/") for item in inventory)):
                    _reject("git_project_root_empty", "The selected Git project directory contains no regular files")
                content = output.getvalue()
                snapshot = VerifiedSourceSnapshot(commit, content, hashlib.sha256(content).hexdigest(), digest_json(inventory), tuple((entry["path"], entry["size_bytes"], entry["sha256"]) for entry in inventory))
            # Cleanup is part of the backend context, before publishing bytes.
            budget.checkpoint()
            return snapshot
        except _SourceRejected:
            raise
        except SafeExecutionCancelled:
            raise SafeExecutionCancelled("Trusted backend confirmed Git acquisition termination") from None
        except TimeoutError:
            raise TimeoutError("Git acquisition deadline exceeded") from None
        except InterruptedError:
            raise InterruptedError("Git acquisition completion or termination is unknown") from None
        except Exception:
            _reject("git_acquisition_failed", "Trusted Git acquisition failed; backend output is withheld")
        finally:
            temporary.clear()

    def export_snapshot(self, request: dict[str, Any], *, material: dict[str, Any], cancel: threading.Event) -> bytes:
        return self.acquire_snapshot(request, material=material, cancel=cancel).content

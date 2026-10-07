"""Synthetic raw objects only; no Git/network/container/credential operation."""

from __future__ import annotations

import base64
import hashlib
import io
import threading
import zipfile
from urllib.parse import quote
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch

import pytest

from lingshu_gate.git_acquisition import OBJECT_LIMITS, VerifiedGitAcquisition
from lingshu_gate.git_source import GIT_ENVIRONMENT_POLICY, GIT_POLICY, SNAPSHOT_CHUNK_BYTES, GitSourceInput, snapshot_inventory
from lingshu_gate.ports.git_acquisition import GitObject
from lingshu_gate.ports.safe_network_executor import PHASE_CHECKS, ROOTLESS_CHECKS, ExecutorReadiness, SafeExecutionCancelled, require_safe_executor
from lingshu_gate.project_uploads import MAX_EXTRACTED_BYTES, MAX_FILES, MAX_ZIP_BYTES
from lingshu_gate.registry import ToolExecutionError


class ObjectFixture:
    def __init__(self):
        self.objects = {}
        self.opened = []
        self.streams = []
        self.object_format = "sha1"
        self.partial_reads = None
        self.on_read = None
        self.oversized_reads = False

    def add(self, kind, data):
        # Canonical SHA-1 Git object identity for synthetic data, not password storage.
        oid = hashlib.sha1(f"{kind} {len(data)}\0".encode() + data).hexdigest()
        self.objects[oid] = (kind, data, len(data))
        return oid

    def tree(self, entries):
        data = b"".join(mode.encode() + b" " + name.encode() + b"\0" + bytes.fromhex(oid) for mode, name, oid in entries)
        return self.add("tree", data)

    def commit(self, tree, *, headers=None):
        self.commit_sha = self.add("commit", headers if headers is not None else f"tree {tree}\nauthor Fixture <fixture@example.invalid> 0 +0000\ncommitter Fixture <fixture@example.invalid> 0 +0000\n\nfixture\n".encode())
        return self.commit_sha

    @contextmanager
    def open_object(self, oid):
        self.opened.append(oid)
        kind, data, size = self.objects[oid]
        fixture = self

        class Stream(io.BytesIO):
            def __init__(self):
                super().__init__(data)
                self.requests = []

            def read(self, amount=-1):
                self.requests.append(amount)
                if fixture.on_read:
                    fixture.on_read()
                if fixture.oversized_reads:
                    return b"x" * (amount + 1)
                return super().read(min(amount, fixture.partial_reads) if fixture.partial_reads else amount)

        with Stream() as stream:
            self.streams.append(stream)
            yield GitObject(kind, size, stream)


class FixtureBackend:
    proxy_schemes = frozenset({"http", "https"})

    def __init__(self, objects):
        self.objects = objects
        self.resolved = objects.commit_sha
        self.requests = []
        self.materials = []
        self.cleanup = 0
        self.exit_error = None
        self.on_exit = None
        self.ready = ExecutorReadiness("linux_rootless_oci", "linux", ROOTLESS_CHECKS | PHASE_CHECKS["git_acquisition"])

    def readiness(self):
        # Unit evidence only; never injected into production composition.
        return self.ready

    def resolve_commit(self, request, *, material, timeout_seconds):
        self.requests.append(("resolve", deepcopy(request)))
        self.materials.append(material)
        return self.resolved

    @contextmanager
    def fetch_exact(self, request, *, material, cancel, deadline):
        self.requests.append(("fetch", deepcopy(request)))
        self.materials.append(material)
        try:
            yield self.objects
        finally:
            self.cleanup += 1
            if self.on_exit:
                self.on_exit()
        if self.exit_error:
            raise self.exit_error


def request(commit, **source_fields):
    return {
        "source": GitSourceInput(repository_url="https://git.example.invalid/example/repository.git", **source_fields).model_dump(),
        "network": {"settings_revision": 7, "git": {"mode": "direct"}, "install": {"mode": "direct"}},
        "host_rule": {"host": "git.example.invalid", "port": 443, "private_cidrs": []},
        "git_config": dict(GIT_POLICY), "environment_policy": dict(GIT_ENVIRONMENT_POLICY),
        "limits": {"compressed_bytes": MAX_ZIP_BYTES, "expanded_bytes": MAX_EXTRACTED_BYTES, "files": MAX_FILES, "resolve_seconds": 15, "fetch_seconds": 120, "export_seconds": 30, "retry_count": 0},
        "credential_revision": None, "commit_sha": commit,
    }


def source(entries=None):
    objects = ObjectFixture()
    entries = entries or [("100644", "index.js", b"export {};")]
    tree = objects.tree([(mode, name, objects.add("blob", data)) for mode, name, data in entries])
    objects.commit(tree)
    return objects, FixtureBackend(objects)


def acquire(objects, backend, prepared=None, **kwargs):
    return VerifiedGitAcquisition(backend).acquire_snapshot(prepared or request(objects.commit_sha), material=kwargs.get("material", {}), cancel=kwargs.get("cancel", threading.Event()))


def test_raw_export_preserves_files_modes_inventory_and_existing_zip_boundary(monkeypatch):
    objects, backend = source([
        ("100755", "entry.js", b"export {};// unfiltered"),
        ("100644", ".gitattributes", b"*.js filter=fixture export-ignore export-subst\n"),
    ])
    prepared = request(objects.commit_sha)
    prepared["network"]["git"] = {"mode": "profile", "profile_id": "fixture-profile", "version": 3}
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/untrusted/config")
    with patch("subprocess.Popen") as popen, patch("subprocess.run") as run:
        snapshot = acquire(objects, backend, prepared, material={"proxy": "https://proxy.example.invalid:443", "git_credential": "synthetic-acquisition-secret"})
    popen.assert_not_called()
    run.assert_not_called()
    assert backend.cleanup == 1 and all(stream.closed for stream in objects.streams)
    assert backend.materials == [{}]
    assert snapshot.source_sha256 == hashlib.sha256(snapshot.content).hexdigest()
    assert snapshot_inventory(snapshot.content, ".") == (snapshot.file_list_sha256, snapshot.inventory())
    assert snapshot.commit_sha == objects.commit_sha
    assert "export {};// unfiltered" not in repr(snapshot)
    with zipfile.ZipFile(io.BytesIO(snapshot.content)) as archive:
        assert archive.namelist() == ["entry.js", ".gitattributes"]
        assert archive.read("entry.js") == b"export {};// unfiltered"
        assert archive.getinfo("entry.js").external_attr >> 16 & 0o777 == 0o755
    captured = backend.requests[0][1]
    assert captured["network"]["git"] == {"mode": "profile", "profile_id": "fixture-profile", "version": 3}
    assert captured["git_config"] == GIT_POLICY and captured["environment_policy"] == GIT_ENVIRONMENT_POLICY
    assert captured["limits"]["transfer_bytes"] == MAX_ZIP_BYTES
    assert captured["limits"]["objects"] == OBJECT_LIMITS["objects"]


def test_resolution_and_fetch_remain_pinned_after_branch_moves():
    objects, backend = source()
    adapter = VerifiedGitAcquisition(backend)
    prepared = request(objects.commit_sha)
    assert adapter.resolve_commit(prepared, material={}, timeout_seconds=15) == objects.commit_sha
    backend.resolved = "f" * 40
    assert adapter.export_snapshot(prepared, material={}, cancel=threading.Event())
    assert [phase for phase, _ in backend.requests] == ["resolve", "fetch"]
    assert backend.requests[-1][1]["commit_sha"] == objects.commit_sha


@pytest.mark.parametrize("resolved", ["b" * 40, "a" * 64, "A" * 40, "tag-object", None])
def test_exact_commit_resolution_never_substitutes_or_converts_algorithm(resolved):
    objects, backend = source()
    backend.resolved = resolved
    with pytest.raises(ToolExecutionError) as denied:
        VerifiedGitAcquisition(backend).resolve_commit(request(objects.commit_sha, ref_type="commit", ref=objects.commit_sha), material={}, timeout_seconds=15)
    assert denied.value.code == "git_commit_mismatch" and not objects.opened


@pytest.mark.parametrize("mutation,code", [
    ("format", "git_object_format_unsupported"), ("commit", "git_commit_mismatch"),
    ("blob-hash", "git_object_hash_mismatch"), ("tree-hash", "git_object_hash_mismatch"),
    ("kind", "git_object_type_invalid"), ("truncated", "git_object_stream_invalid"),
    ("extra", "git_object_stream_invalid"), ("missing", "git_acquisition_failed"),
])
def test_object_format_type_hash_length_and_missing_object_fail_closed(mutation, code):
    objects, backend = source()
    commit = objects.commit_sha
    blob = next(oid for oid, (kind, _, _) in objects.objects.items() if kind == "blob")
    tree = next(oid for oid, (kind, _, _) in objects.objects.items() if kind == "tree")
    if mutation == "format":
        objects.object_format = "sha256"
    elif mutation == "commit":
        objects.commit_sha = "f" * 40
    elif mutation == "missing":
        del objects.objects[blob]
    else:
        target = tree if mutation == "tree-hash" else blob
        kind, data, size = objects.objects[target]
        if mutation == "kind":
            kind = "tree"
        elif mutation == "truncated":
            data = data[:-1]
        elif mutation == "extra":
            data += b"!"
        else:
            data = data.replace(b"index", b"other") if mutation == "tree-hash" else b"x" * size
        objects.objects[target] = (kind, data, size)
    with pytest.raises(ToolExecutionError) as denied:
        acquire(objects, backend, request(commit))
    assert denied.value.code == code
    assert backend.cleanup == 1 and all(stream.closed for stream in objects.streams)


@pytest.mark.parametrize("mode,name,code", [
    ("120000", "link", "git_symlink_unsupported"), ("160000", "module", "git_submodule_unsupported"),
    ("100600", "special", "git_tree_mode_unsupported"), ("100644", ".gitmodules", "git_submodule_unsupported"),
    ("100644", "..", "git_snapshot_path_rejected"), ("100644", "a/b", "git_snapshot_path_rejected"),
    ("100644", ".env", "git_snapshot_path_rejected"), ("100644", "CON", "git_snapshot_path_rejected"),
    ("100644", "bad\\name", "git_snapshot_path_rejected"), ("100644", "secret.pem", "git_snapshot_path_rejected"),
])
def test_full_tree_unsafe_entries_rejected_outside_selected_project(mode, name, code):
    objects = ObjectFixture()
    good = objects.tree([("100644", "index.js", objects.add("blob", b"export {};"))])
    bad = objects.tree([(mode, name, objects.add("blob", b"../../host"))])
    root = objects.tree([("40000", "project", good), ("40000", "unselected", bad)])
    objects.commit(root)
    backend = FixtureBackend(objects)
    with pytest.raises(ToolExecutionError) as denied:
        acquire(objects, backend, request(objects.commit_sha, project_root="project"))
    assert denied.value.code == code and backend.cleanup == 1


@pytest.mark.parametrize("names", [("File", "file"), ("same", "same"), ("a", "A")])
def test_casefold_duplicate_paths_rejected_before_blob_reads(names):
    objects, backend = source([("100644", name, b"x") for name in names])
    with pytest.raises(ToolExecutionError, match="duplicate or ambiguous"):
        acquire(objects, backend)
    assert len(objects.opened) == 2


@pytest.mark.parametrize("data", [
    b"version https://git-lfs.github.com/spec/v1\noid sha256:fixture\n", b"-----BEGIN PRIVATE KEY-----\n",
    b"ghp_" + b"x" * 24, b"synthetic-acquisition-secret", base64.b64encode(b"synthetic-acquisition-secret"),
])
def test_streamed_secret_lfs_and_encoded_material_rejection(data):
    objects, backend = source([("100644", "index.js", data)])
    objects.partial_reads = 3
    with pytest.raises(ToolExecutionError) as denied:
        acquire(objects, backend, material={"git_credential": "synthetic-acquisition-secret"})
    assert denied.value.code == "git_snapshot_content_rejected"
    assert "synthetic-acquisition-secret" not in str(denied.value)
    assert backend.materials == [{}]


@pytest.mark.parametrize("encoding", ["raw", "url", "base64"])
@pytest.mark.parametrize("field", ["git_credential", "proxy_credential"])
def test_reflected_bare_basic_or_proxy_secret_never_reaches_snapshot(field, encoding):
    secret = "fixture-reflected-token/+"
    reflected = secret if encoding == "raw" else quote(secret, safe="") if encoding == "url" else base64.b64encode(secret.encode()).decode()
    objects, backend = source([("100644", "index.js", reflected.encode())])
    objects.partial_reads = 3
    material = {field: "fixture-username:" + secret}
    with pytest.raises(ToolExecutionError) as rejected:
        acquire(objects, backend, material=material)
    assert rejected.value.code == "git_snapshot_content_rejected"
    assert secret not in str(rejected.value) and reflected not in str(rejected.value)
    assert backend.materials == [{}]
    assert objects.streams and all(stream.closed for stream in objects.streams)


def test_basic_username_alone_is_allowed_but_short_token_remains_scanned():
    objects, backend = source([("100644", "index.js", b"fixture-username is public")])
    assert acquire(objects, backend, material={"git_credential": "fixture-username:unique-private-token"}).inventory()
    objects, backend = source([("100644", "x.js", b"export {};")])
    with pytest.raises(ToolExecutionError) as rejected:
        acquire(objects, backend, material={"git_credential": "fixture-username:e"})
    assert rejected.value.code == "git_snapshot_content_rejected"


@pytest.mark.parametrize("limit,value,code", [
    ("objects", 1, "git_object_size_limit"), ("tree_entries", 1, "git_tree_entry_limit"),
    ("files", 1, "git_snapshot_file_limit"), ("expanded_bytes", 1, "git_object_size_limit"),
    ("object_bytes", 1, "git_object_size_limit"), ("commit_bytes", 1, "git_object_size_limit"),
    ("tree_bytes", 1, "git_object_size_limit"), ("compressed_bytes", 1, "git_snapshot_size_limit"),
])
def test_limits_are_applied_before_object_reads_or_during_zip_writes(limit, value, code):
    objects, backend = source([("100644", "one.js", b"one"), ("100644", "two.js", b"two")])
    prepared = request(objects.commit_sha)
    prepared["limits"][limit] = value
    with pytest.raises(ToolExecutionError) as denied:
        acquire(objects, backend, prepared)
    assert denied.value.code == code
    assert all(0 <= amount <= SNAPSHOT_CHUNK_BYTES for stream in objects.streams for amount in stream.requests)
    if limit in {"commit_bytes", "object_bytes"}:
        assert objects.streams[0].requests == []
    assert backend.cleanup == 1


@pytest.mark.parametrize("mutation", ["sha", "policy", "environment", "limit", "retries", "timeout", "host", "root"])
def test_mutated_request_never_reaches_backend(mutation):
    objects, backend = source()
    prepared = request(objects.commit_sha)
    if mutation == "sha":
        prepared["commit_sha"] = "a" * 64
    elif mutation == "policy":
        prepared["git_config"]["http.sslVerify"] = "false"
    elif mutation == "environment":
        prepared["environment_policy"]["GIT_ALLOW_PROTOCOL"] = "file"
    elif mutation == "host":
        prepared["host_rule"]["host"] = "other.example.invalid"
    elif mutation == "root":
        prepared["source"]["project_root"] = "../host"
    else:
        prepared["limits"][{"limit": "expanded_bytes", "retries": "retry_count", "timeout": "fetch_seconds"}[mutation]] = {"limit": MAX_EXTRACTED_BYTES + 1, "retries": 1, "timeout": True}[mutation]
    with pytest.raises(ToolExecutionError):
        acquire(objects, backend, prepared)
    assert not backend.requests and not objects.opened


def test_missing_or_partial_adapter_cannot_enable_production_facade_or_host_fallback():
    with patch("subprocess.Popen") as popen, patch("subprocess.run") as run:
        with pytest.raises(ToolExecutionError) as denied:
            VerifiedGitAcquisition(None).export_snapshot(request("a" * 40), material={}, cancel=threading.Event())
        assert denied.value.code == "safe_executor_unavailable"
        with pytest.raises(ToolExecutionError):
            require_safe_executor(VerifiedGitAcquisition(None))
    popen.assert_not_called()
    run.assert_not_called()


@pytest.mark.parametrize("missing", sorted(ROOTLESS_CHECKS | PHASE_CHECKS["git_acquisition"]))
def test_missing_actual_rootless_or_acquisition_evidence_blocks_before_fetch(missing):
    objects, backend = source()
    backend.ready = ExecutorReadiness("linux_rootless_oci", "linux", backend.ready.checks - {missing})
    with pytest.raises(ToolExecutionError) as denied:
        acquire(objects, backend)
    assert missing in denied.value.details["missing"] and not backend.requests


@pytest.mark.parametrize("signal,expected", [(InterruptedError("synthetic-secret"), InterruptedError), (SafeExecutionCancelled("synthetic-secret"), SafeExecutionCancelled), (TimeoutError("synthetic-secret"), TimeoutError), (RuntimeError("synthetic-secret"), ToolExecutionError), (ToolExecutionError("backend", "synthetic-secret"), ToolExecutionError)])
def test_cleanup_outcome_never_publishes_snapshot_or_leaks_backend_output(signal, expected):
    objects, backend = source()
    backend.exit_error = signal
    with pytest.raises(expected) as denied:
        acquire(objects, backend)
    assert "synthetic-secret" not in str(denied.value)
    assert backend.cleanup == 1 and backend.materials == [{}]


def test_pre_cancel_has_no_fetch_and_no_unearned_termination_claim():
    objects, backend = source()
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(InterruptedError) as interrupted:
        acquire(objects, backend, cancel=cancel)
    assert not isinstance(interrupted.value, SafeExecutionCancelled) and not backend.requests


def test_deadline_checked_before_each_object_read_and_after_cleanup():
    objects, backend = source()
    with patch("lingshu_gate.git_acquisition.time.monotonic", side_effect=[0, 0, 0, 0, 100]):
        with pytest.raises(TimeoutError):
            acquire(objects, backend)
    assert backend.cleanup == 1 and all(stream.closed for stream in objects.streams)


def test_large_blob_reads_are_bounded_and_secret_scan_covers_chunk_boundary():
    token = b"synthetic-acquisition-secret"
    objects, backend = source([("100644", "large.js", b"x" * (SNAPSHOT_CHUNK_BYTES - 7) + token)])
    with pytest.raises(ToolExecutionError, match="network material"):
        acquire(objects, backend, material={"git_credential": token.decode()})
    assert all(0 <= amount <= SNAPSHOT_CHUNK_BYTES for stream in objects.streams for amount in stream.requests)


def test_empty_or_missing_selected_project_is_not_a_successful_snapshot():
    objects, backend = source()
    with pytest.raises(ToolExecutionError) as denied:
        acquire(objects, backend, request(objects.commit_sha, project_root="missing"))
    assert denied.value.code == "git_project_root_empty"


@pytest.mark.parametrize("content", [b"version https://git-lfs.github.com/spec/v1\n", b"-----BEGIN PRIVATE KEY-----\n"])
def test_unsafe_content_in_unselected_subtree_is_not_ignored(content):
    objects = ObjectFixture()
    good = objects.tree([("100644", "index.js", objects.add("blob", b"export {};"))])
    bad = objects.tree([("100644", "pointer", objects.add("blob", content))])
    objects.commit(objects.tree([("40000", "project", good), ("40000", "unselected", bad)]))
    with pytest.raises(ToolExecutionError) as denied:
        acquire(objects, FixtureBackend(objects), request(objects.commit_sha, project_root="project"))
    assert denied.value.code == "git_snapshot_content_rejected"


@pytest.mark.parametrize("tree_data,code", [
    (b"100644 " + b"x" * 256 + b"\0" + b"x" * 20, "git_tree_invalid"),
    (b"0000000 file\0" + b"x" * 20, "git_tree_invalid"),
    (b"100644 file\0" + b"x" * 19, "git_object_stream_invalid"),
    (b"100644 \xff\0" + b"x" * 20, "git_snapshot_path_rejected"),
])
def test_malformed_tree_parser_fails_with_bounded_fields_before_child_reads(tree_data, code):
    objects = ObjectFixture()
    objects.commit(objects.add("tree", tree_data))
    backend = FixtureBackend(objects)
    with pytest.raises(ToolExecutionError) as denied:
        acquire(objects, backend)
    assert denied.value.code == code and len(objects.opened) == 2


@pytest.mark.parametrize("headers", [b"\n\n", b"tree " + b"a" * 64 + b"\n\n", b"tree " + b"a" * 40 + b"\ntree " + b"b" * 40 + b"\n\n"])
def test_commit_requires_one_supported_root_tree(headers):
    objects = ObjectFixture()
    objects.commit("a" * 40, headers=headers)
    with pytest.raises(ToolExecutionError) as denied:
        acquire(objects, FixtureBackend(objects))
    assert denied.value.code == "git_commit_invalid" and len(objects.opened) == 1


def test_producer_cannot_return_more_than_requested():
    objects, backend = source()
    objects.oversized_reads = True
    with pytest.raises(ToolExecutionError) as denied:
        acquire(objects, backend)
    assert denied.value.code == "git_object_stream_invalid" and backend.cleanup == 1


def test_cancel_during_read_closes_every_stream_and_keeps_unknown_outcome():
    objects, backend = source()
    cancel = threading.Event()
    objects.on_read = cancel.set
    with pytest.raises(InterruptedError) as interrupted:
        acquire(objects, backend, cancel=cancel)
    assert not isinstance(interrupted.value, SafeExecutionCancelled)
    assert backend.cleanup == 1 and all(stream.closed for stream in objects.streams)


def test_cleanup_that_exceeds_deadline_cannot_publish_completed_bytes():
    objects, backend = source()
    clock = [0]
    backend.on_exit = lambda: clock.__setitem__(0, 31)
    with patch("lingshu_gate.git_acquisition.time.monotonic", side_effect=lambda: clock[0]):
        with pytest.raises(TimeoutError):
            acquire(objects, backend)
    assert backend.cleanup == 1 and backend.materials == [{}]


@pytest.mark.parametrize("selection,material,code", [
    ({"mode": "profile", "profile_id": "fixture-profile", "version": 3}, {}, "network_material_missing"),
    ({"mode": "direct"}, {"proxy": "https://proxy.example.invalid:443"}, "network_material_missing"),
    ({"mode": "profile", "profile_id": "fixture-profile", "version": 3}, {"proxy": "socks5://proxy.example.invalid:1080"}, "proxy_scheme_unsupported"),
])
def test_pinned_proxy_material_missing_or_unsupported_never_falls_back(selection, material, code):
    objects, backend = source()
    prepared = request(objects.commit_sha)
    prepared["network"]["git"] = selection
    with pytest.raises(ToolExecutionError) as denied:
        acquire(objects, backend, prepared, material=material)
    assert denied.value.code == code and not backend.requests


def test_unknown_execution_fields_or_unpinned_profile_never_reach_backend():
    objects, backend = source()
    prepared = request(objects.commit_sha)
    prepared["command"] = ["sh", "-c", "fixture"]
    with pytest.raises(ToolExecutionError):
        acquire(objects, backend, prepared)
    del prepared["command"]
    prepared["network"]["git"] = {"mode": "profile", "profile_id": "fixture-profile"}
    with pytest.raises(ToolExecutionError):
        acquire(objects, backend, prepared)
    assert not backend.requests


def test_existing_zip_scan_streams_content_without_archive_read():
    objects, backend = source([("100644", "large.js", b"x" * (SNAPSHOT_CHUNK_BYTES * 2))])
    snapshot = acquire(objects, backend)
    with patch.object(zipfile.ZipFile, "read", side_effect=AssertionError("whole-entry reads are prohibited")):
        assert snapshot_inventory(snapshot.content, ".") == (snapshot.file_list_sha256, snapshot.inventory())


def test_valid_subdirectory_keeps_full_inventory_and_original_coordinate_root():
    objects = ObjectFixture()
    project = objects.tree([("100644", "index.js", objects.add("blob", b"export {};"))])
    objects.commit(objects.tree([("40000", "project", project), ("100644", "outside.txt", objects.add("blob", b"outside"))]))
    snapshot = acquire(objects, FixtureBackend(objects), request(objects.commit_sha, project_root="project"))
    assert [item["path"] for item in snapshot.inventory()] == ["outside.txt", "project/index.js"]
    assert snapshot_inventory(snapshot.content, "project") == (snapshot.file_list_sha256, snapshot.inventory())

from __future__ import annotations

import io
import importlib.util
import hashlib
import subprocess
import sys
import tarfile
import time
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest


_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "quality" / "check_repository_identity.py"
_SPEC = importlib.util.spec_from_file_location("repository_identity_policy", _MODULE_PATH)
assert _SPEC is not None and _SPEC.loader is not None
identity = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = identity
_SPEC.loader.exec_module(identity)


def _value(points: tuple[int, ...]) -> str:
    return "".join(chr(point) for point in points)


def _restricted_token() -> str:
    return _value((110, 101, 120, 117, 115))


def _external_token() -> str:
    return _value((73, 110, 102, 114, 97, 77, 67, 80))


def _short_external_token() -> str:
    return _value((100, 98, 120))


def _non_gate_environment_name() -> str:
    return _value((76, 73, 78, 71, 83, 72, 85, 95, 79, 84, 72, 69, 82, 95, 72, 79, 83, 84))


def _non_gate_kebab_name() -> str:
    return _value((108, 105, 110, 103, 115, 104, 117, 45, 119, 111, 114, 107, 101, 114))


def _prepare_repository(root: Path) -> None:
    skill = root / ".agents" / "skills" / "lingshu-gate-upload-build-start" / "SKILL.md"
    skill.parent.mkdir(parents=True)
    skill.write_text(
        "---\nname: lingshu-gate-upload-build-start\ndescription: Build and publish Lingshu Gate releases.\n---\n",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        "[project]\n"
        'name = "lingshu-gate"\n'
        "[project.scripts]\n"
        'lingshu-gate = "lingshu_gate.cli:main"\n',
        encoding="utf-8",
    )
    package = root / "src" / "lingshu_gate"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "cli.py").write_text("def main():\n    pass\n", encoding="utf-8")
    (package / "config.py").write_text(
        "class Settings:\n"
        '    auth_session_cookie_name: str = "lingshu_gate_session"\n'
        '    db_url: str = "sqlite:///gate.db"\n',
        encoding="utf-8",
    )


def _git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _add_tar_file(archive: tarfile.TarFile, name: str, data: bytes) -> None:
    member = tarfile.TarInfo(name)
    member.size = len(data)
    archive.addfile(member, io.BytesIO(data))


def test_clean_tree_with_one_authorized_skill(tmp_path: Path) -> None:
    _prepare_repository(tmp_path)
    (tmp_path / "README.md").write_text("# Lingshu Gate\n", encoding="utf-8")

    assert identity.audit_repository(tmp_path) == []


def test_restricted_text_is_reported_without_echo(
    tmp_path: Path,
    capsys,
) -> None:
    _prepare_repository(tmp_path)
    token = _restricted_token()
    (tmp_path / "README.md").write_text(f"safe\n{token}\n", encoding="utf-8")

    result = identity.main(["--root", str(tmp_path)])
    output = capsys.readouterr().out

    assert result == 1
    assert "TXT-001 README.md:2" in output
    assert token.casefold() not in output.casefold()


def test_nfkc_and_compact_normalization_cannot_bypass_policy(tmp_path: Path) -> None:
    _prepare_repository(tmp_path)
    token = _restricted_token()
    full_width = "".join(chr(ord(character) + 0xFEE0) for character in token)
    prefix = _value((109, 99, 112))
    fragmented = "-".join(token)
    (tmp_path / "README.md").write_text(
        f"{full_width}\n{prefix}-{token}\n{fragmented}\n",
        encoding="utf-8",
    )

    violations = identity.audit_repository(tmp_path)
    found = {(violation.rule_id, violation.line) for violation in violations}

    assert ("TXT-001", 1) in found
    assert ("TXT-002", 2) in found
    assert ("TXT-001", 3) in found


def test_long_compact_token_scans_the_middle_without_sampling(tmp_path: Path) -> None:
    _prepare_repository(tmp_path)
    token = _restricted_token()
    (tmp_path / "payload.unknown").write_text(
        "x" * 5000 + token + "x" * 5000,
        encoding="utf-8",
    )

    violations = identity.audit_repository(tmp_path)

    assert any(violation.rule_id == "TXT-001" for violation in violations)


def test_clean_long_minified_content_passes_without_budget_noise(tmp_path: Path) -> None:
    _prepare_repository(tmp_path)
    (tmp_path / "bundle.js").write_text(
        "let x='" + "a" * 200_000 + "';" + ",".join(f"v{i}=1" for i in range(30_000)),
        encoding="utf-8",
    )

    assert identity.audit_repository(tmp_path) == []


def test_unknown_extension_env_example_extensionless_and_binary_are_scanned(tmp_path: Path) -> None:
    _prepare_repository(tmp_path)
    token = _external_token()
    (tmp_path / ".env.example").write_text(token, encoding="utf-8")
    (tmp_path / "entrypoint").write_text(token, encoding="utf-8")
    (tmp_path / "payload.unknown").write_text(token, encoding="utf-8")
    (tmp_path / "payload.bin").write_bytes(b"\x00\xff" + token.encode("ascii") + b"\x00")

    locations = {
        violation.location
        for violation in identity.audit_repository(tmp_path)
        if violation.rule_id == "TXT-004"
    }

    assert {".env.example", "entrypoint", "payload.unknown", "payload.bin"}.issubset(locations)


def test_gate_positive_identity_contracts_fail_closed(tmp_path: Path) -> None:
    _prepare_repository(tmp_path)
    (tmp_path / "pyproject.toml").write_text(
        "[project]\n"
        'name = "other-hub"\n'
        "[project.scripts]\n"
        'other-hub = "other_hub.cli:main"\n',
        encoding="utf-8",
    )
    extra_package = tmp_path / "src" / "other_hub"
    extra_package.mkdir()
    (extra_package / "__init__.py").write_text("", encoding="utf-8")
    config = tmp_path / "src" / "lingshu_gate" / "config.py"
    config.write_text(
        "class Settings:\n"
        '    auth_session_cookie_name: str = "other_session"\n'
        '    db_url: str = "sqlite:///other.db"\n',
        encoding="utf-8",
    )
    (tmp_path / "src" / "lingshu_gate" / "identity_examples.py").write_text(
        f'ENVIRONMENT = "{_non_gate_environment_name()}"\n'
        f'PROCESS = "{_non_gate_kebab_name()}"\n'
        'log_event(logger, level, "other.started", "message")\n'
        'observability.emit_event("other.emitted")\n'
        '_definition("other_upload", "name", "description", Model)\n'
        'ToolDefinition(id="other_direct", name="name", description="description")\n',
        encoding="utf-8",
    )
    (tmp_path / "src" / "lingshu_gate" / "tool_files.py").write_text(
        'file_ref = f"other_file_{identifier}"\n',
        encoding="utf-8",
    )

    rule_ids = {violation.rule_id for violation in identity.audit_repository(tmp_path)}

    assert {
        "GATE-001",
        "GATE-002",
        "GATE-003",
        "GATE-004",
        "GATE-005",
        "GATE-006",
        "GATE-007",
        "GATE-008",
        "GATE-010",
        "GATE-011",
    }.issubset(rule_ids)


def test_unapproved_skill_is_rejected(tmp_path: Path) -> None:
    _prepare_repository(tmp_path)
    extra = tmp_path / ".agents" / "skills" / "extra" / "SKILL.md"
    extra.parent.mkdir(parents=True)
    extra.write_text("---\nname: extra\n---\n", encoding="utf-8")

    rule_ids = {violation.rule_id for violation in identity.audit_repository(tmp_path)}

    assert {"SKILL-001", "SKILL-003", "SKILL-004"}.issubset(rule_ids)


def test_restricted_feature_path_is_rejected(tmp_path: Path) -> None:
    _prepare_repository(tmp_path)
    component = _value((99, 108, 105, 101, 110, 116, 115))
    source = tmp_path / "src" / "lingshu_gate" / component / "item.py"
    source.parent.mkdir(parents=True)
    source.write_text("value = 1\n", encoding="utf-8")

    rule_ids = {violation.rule_id for violation in identity.audit_repository(tmp_path)}

    assert "PATH-001" in rule_ids


def test_console_release_and_archives_are_scanned(tmp_path: Path) -> None:
    _prepare_repository(tmp_path)
    token = _external_token()
    console = tmp_path / "src" / "lingshu_gate" / "static" / "console" / "index.js"
    console.parent.mkdir(parents=True)
    console.write_text(token, encoding="utf-8")
    release = tmp_path / "release"
    release.mkdir()
    (release / "README.md").write_text(token, encoding="utf-8")
    (release / "lingshu-gate").write_bytes(b"\x00" + token.encode("ascii") + b"\x00")
    with zipfile.ZipFile(release / "bundle.zip", mode="w") as archive:
        root = "lingshu-gate-v0-test"
        archive.writestr(f"{root}/docs/notes.md", token)
        archive.writestr(f"{root}/lingshu-gate", b"\x00" + token.encode("ascii") + b"\x00")

    source_locations = {
        violation.location for violation in identity.audit_repository(tmp_path) if violation.rule_id == "TXT-004"
    }
    artifact_locations = {
        violation.location
        for violation in identity.audit_repository(tmp_path, artifact_paths=[release])
        if violation.rule_id == "TXT-004"
    }

    assert source_locations == {"src/lingshu_gate/static/console/index.js"}
    assert "src/lingshu_gate/static/console/index.js" in artifact_locations
    assert "release/README.md" in artifact_locations
    assert "release/lingshu-gate" in artifact_locations
    assert f"release/bundle.zip!{root}/docs/notes.md" in artifact_locations
    assert f"release/bundle.zip!{root}/lingshu-gate" in artifact_locations


def test_binary_release_lockfiles_and_dependencies_do_not_create_noise(tmp_path: Path) -> None:
    _prepare_repository(tmp_path)
    token = _restricted_token()
    (tmp_path / "uv.lock").write_text(token, encoding="utf-8")
    cached = tmp_path / "node_modules" / "module" / "README.md"
    cached.parent.mkdir(parents=True)
    cached.write_text(token, encoding="utf-8")
    release = tmp_path / "release"
    release.mkdir()
    (release / "lingshu-gate").write_bytes(b"\x00\xff\x10\x80")

    assert identity.audit_repository(tmp_path) == []
    assert identity.audit_repository(tmp_path, artifact_paths=[release]) == []


def test_generated_intermediates_are_skipped_even_when_artifacts_are_requested(tmp_path: Path) -> None:
    _prepare_repository(tmp_path)
    token = _restricted_token()
    report = tmp_path / "build" / "release" / "linux" / "pyinstaller-work" / "xref.html"
    report.parent.mkdir(parents=True)
    report.write_text(token, encoding="utf-8")
    stale = tmp_path / "dist" / "cache" / "report.json"
    stale.parent.mkdir(parents=True)
    stale.write_text(token, encoding="utf-8")

    assert identity.audit_repository(tmp_path) == []
    assert identity.audit_repository(tmp_path, artifact_paths=[tmp_path / "build" / "release"]) == []


def test_artifact_archive_scans_first_party_content_but_not_runtime_dependencies(tmp_path: Path) -> None:
    _prepare_repository(tmp_path)
    restricted = _restricted_token()
    external = _external_token()
    archive_path = tmp_path / "release" / "bundle.zip"
    archive_path.parent.mkdir()
    root = "lingshu-gate-v0-test"
    with zipfile.ZipFile(archive_path, mode="w") as archive:
        archive.writestr(f"{root}/_internal/vendor/METADATA", "vendor metadata")
        archive.writestr(f"{root}/_internal/vendor/runtime.bin", b"\x00" + external.encode("ascii") + b"\x00")
        archive.writestr(f"{root}/licenses/vendor.txt", external)
        archive.writestr(f"{root}/_internal/lingshu_gate/module.py", external)
        archive.writestr(f"{root}/lingshu-gate", b"\x00" + restricted.encode("ascii") + b"\x00")

    violations = identity.audit_repository(tmp_path, artifact_paths=[archive_path])
    locations = {violation.location for violation in violations}

    assert f"release/bundle.zip!{root}/_internal/lingshu_gate/module.py" in locations
    assert f"release/bundle.zip!{root}/lingshu-gate" in locations
    assert not any("/_internal/vendor/" in location for location in locations)
    assert not any("/licenses/" in location for location in locations)


def test_native_tar_applies_the_same_first_party_boundary(tmp_path: Path) -> None:
    _prepare_repository(tmp_path)
    restricted = _restricted_token()
    external = _external_token()
    archive_path = tmp_path / "release" / "bundle.tar.gz"
    archive_path.parent.mkdir()
    root = "lingshu-gate-v0-test"
    with tarfile.open(archive_path, mode="w:gz") as archive:
        _add_tar_file(archive, f"{root}/_internal/vendor/METADATA", b"vendor metadata")
        _add_tar_file(archive, f"{root}/_internal/lingshu_gate/module.py", external.encode("ascii"))
        _add_tar_file(archive, f"{root}/lingshu-gate", b"\x00" + restricted.encode("ascii") + b"\x00")

    violations = identity.audit_repository(tmp_path, artifact_paths=[archive_path])
    locations = {violation.location for violation in violations}

    assert f"release/bundle.tar.gz!{root}/_internal/lingshu_gate/module.py" in locations
    assert f"release/bundle.tar.gz!{root}/lingshu-gate" in locations
    assert not any("/_internal/vendor/" in location for location in locations)


def test_artifact_archive_path_and_size_guards_cover_unscanned_members(tmp_path: Path, monkeypatch) -> None:
    _prepare_repository(tmp_path)
    archive_path = tmp_path / "release" / "bundle.zip"
    archive_path.parent.mkdir()
    with zipfile.ZipFile(archive_path, mode="w") as archive:
        archive.writestr("../escape.txt", "safe")
        archive.writestr("root/_internal/vendor/runtime.bin", b"0123456789")

    monkeypatch.setattr(identity, "_MAX_ARCHIVE_SCAN_BYTES", 8)
    rule_ids = {violation.rule_id for violation in identity.audit_repository(tmp_path, artifact_paths=[archive_path])}

    assert {"ARCHIVE-001", "ARCHIVE-002"}.issubset(rule_ids)


def test_large_invalid_binary_uses_bounded_printable_string_scanning() -> None:
    restricted = _restricted_token()
    external = _external_token()
    data = (
        b"A" * (6 * 1024 * 1024)
        + b"\xff\x00"
        + restricted.encode("ascii")
        + b"\x00\x01"
        + external.encode("utf-16-le")
        + b"\x01"
    )

    started = time.perf_counter()
    violations = identity._scan_bytes(data, "asset", strict_text=False)
    elapsed = time.perf_counter() - started

    assert {"TXT-001", "TXT-004"}.issubset({violation.rule_id for violation in violations})
    assert elapsed < 5


def test_opaque_binary_ignores_short_collision_without_weakening_text_policy() -> None:
    short_token = _short_external_token()
    assert "TXT-005" in {
        violation.rule_id for violation in identity._scan_text(short_token, "metadata.txt")
    }
    assert "TXT-005" in {
        violation.rule_id
        for violation in identity._scan_bytes(
            short_token.encode("ascii"), "unknown-text", strict_text=False
        )
    }

    payload = b"\x7fELF\x00" + f"{short_token}-{_restricted_token()}".encode("ascii") + b"\x00"
    rule_ids = {
        violation.rule_id for violation in identity._scan_bytes(payload, "executable", strict_text=False)
    }

    assert "TXT-005" not in rule_ids
    assert "TXT-001" in rule_ids


def test_invalid_source_text_fails_closed(tmp_path: Path) -> None:
    _prepare_repository(tmp_path)
    (tmp_path / "README.md").write_bytes(b"safe\xff")

    assert any(violation.rule_id == "FILE-002" for violation in identity.audit_repository(tmp_path))


def test_missing_artifact_path_fails_closed(tmp_path: Path) -> None:
    _prepare_repository(tmp_path)

    assert any(
        violation.rule_id == "ARTIFACT-001"
        for violation in identity.audit_repository(tmp_path, artifact_paths=[Path("missing-release")])
    )


def test_cli_artifact_option_scans_relative_release_path(tmp_path: Path, capsys) -> None:
    _prepare_repository(tmp_path)
    token = _restricted_token()
    release = tmp_path / "release"
    release.mkdir()
    (release / "README.md").write_text(token, encoding="utf-8")

    result = identity.main(["--root", str(tmp_path), "--artifacts", "release"])
    output = capsys.readouterr().out

    assert result == 1
    assert "TXT-001 release/README.md:1" in output
    assert token not in output


def test_repository_host_and_secret_signature_terms_remain_allowed(tmp_path: Path) -> None:
    _prepare_repository(tmp_path)
    signature = _value((103, 105, 116, 104, 117, 98, 95, 112, 97, 116, 95))
    (tmp_path / "security.md").write_text(signature, encoding="utf-8")

    assert identity.audit_repository(tmp_path) == []


def test_history_option_scans_messages_and_removed_blobs(tmp_path: Path) -> None:
    _prepare_repository(tmp_path)
    token = _restricted_token()
    tracked = tmp_path / "tracked_payload"
    tracked.write_text(token, encoding="utf-8")
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Identity Test")
    _git(tmp_path, "config", "user.email", "identity@example.invalid")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", token)
    tracked.write_text("clean\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked_payload")
    _git(tmp_path, "commit", "-m", "clean")

    assert identity.audit_repository(tmp_path) == []
    violations = identity.audit_repository(tmp_path, include_history=True)

    assert any(violation.rule_id == "TXT-001" and violation.location.count(":") == 1 for violation in violations)
    assert any(
        violation.rule_id == "TXT-001" and violation.location.endswith(":tracked_payload")
        for violation in violations
    )


def test_history_scans_tracked_generated_directories(tmp_path: Path) -> None:
    _prepare_repository(tmp_path)
    token = _restricted_token()
    tracked = tmp_path / "dist" / "release" / "payload"
    tracked.parent.mkdir(parents=True)
    tracked.write_text(token, encoding="utf-8")
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Identity Test")
    _git(tmp_path, "config", "user.email", "identity@example.invalid")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "release payload")

    assert identity.audit_repository(tmp_path) == []
    violations = identity.audit_repository(tmp_path, include_history=True)

    assert any(
        violation.rule_id == "TXT-001" and violation.location.endswith(":dist/release/payload")
        for violation in violations
    )


def _prepare_history_exception(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    payload: bytes | None = None,
    message: str = "Historical fixture",
):
    _prepare_repository(root)
    path = root / "fixtures" / "historical.txt"
    path.parent.mkdir()
    data = payload if payload is not None else f"{_restricted_token()}\n".encode()
    path.write_bytes(data)
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.name", "Identity Test")
    _git(root, "config", "user.email", "identity@example.invalid")
    _git(root, "add", ".")
    _git(root, "commit", "-m", message)
    relative = path.relative_to(root).as_posix()
    snapshot = identity.HistorySnapshotException(
        commits=frozenset({_git(root, "rev-parse", "HEAD")}),
        path=relative,
        blob=_git(root, "rev-parse", f"HEAD:{relative}"),
        sha256=hashlib.sha256(data).hexdigest(),
        findings=frozenset({("TXT-001", 1)}),
    )
    monkeypatch.setattr(identity, "_HISTORY_SNAPSHOT_EXCEPTIONS", (snapshot,))
    path.write_text("clean\n", encoding="utf-8")
    _git(root, "add", relative)
    _git(root, "commit", "-m", "Correct fixture")
    return path, data, snapshot


def test_pinned_historical_snapshot_passes_with_visible_policy_notice(tmp_path: Path, monkeypatch, capsys) -> None:
    _prepare_history_exception(tmp_path, monkeypatch)

    assert identity.audit_repository(tmp_path, include_history=True) == []
    assert identity.main(["--root", str(tmp_path), "--history"]) == 0
    output = capsys.readouterr().out
    assert "1 pinned legacy snapshot exception(s)" in output
    assert "repository identity check passed" in output
    assert _restricted_token() not in output.casefold()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("commits", frozenset({"0" * 40})),
        ("path", "fixtures/other.txt"),
        ("blob", "0" * 40),
        ("sha256", "0" * 64),
        ("findings", frozenset({("TXT-001", 2)})),
        ("findings", frozenset({("TXT-004", 1)})),
    ],
    ids=["commit", "path", "blob", "content-digest", "line", "rule"],
)
def test_history_exception_requires_every_pinned_dimension(tmp_path: Path, monkeypatch, field, value) -> None:
    _, _, snapshot = _prepare_history_exception(tmp_path, monkeypatch)
    monkeypatch.setattr(identity, "_HISTORY_SNAPSHOT_EXCEPTIONS", (replace(snapshot, **{field: value}),))

    violations = identity.audit_repository(tmp_path, include_history=True)

    assert any(item.rule_id == "TXT-001" and item.location.endswith(":fixtures/historical.txt") for item in violations)


@pytest.mark.parametrize("approve_first_occurrence", [True, False])
def test_reused_blob_is_rejected_in_either_commit_order(tmp_path: Path, monkeypatch, approve_first_occurrence) -> None:
    path, data, snapshot = _prepare_history_exception(tmp_path, monkeypatch)
    original = next(iter(snapshot.commits))
    path.write_bytes(data)
    _git(tmp_path, "add", snapshot.path)
    _git(tmp_path, "commit", "-m", "Reintroduce fixture")
    reused = _git(tmp_path, "rev-parse", "HEAD")
    path.write_text("clean again\n", encoding="utf-8")
    _git(tmp_path, "add", snapshot.path)
    _git(tmp_path, "commit", "-m", "Correct reintroduced fixture")
    if not approve_first_occurrence:
        snapshot = replace(snapshot, commits=frozenset({reused}))
        monkeypatch.setattr(identity, "_HISTORY_SNAPSHOT_EXCEPTIONS", (snapshot,))

    assert identity.audit_repository(tmp_path) == []
    violations = identity.audit_repository(tmp_path, include_history=True)

    rejected = reused if approve_first_occurrence else original
    assert identity.Violation("TXT-001", f"git:{rejected[:12]}:{snapshot.path}", 1) in violations


def test_pinned_blob_copied_to_another_path_still_fails(tmp_path: Path, monkeypatch) -> None:
    _, data, snapshot = _prepare_history_exception(tmp_path, monkeypatch)
    copied = tmp_path / "fixtures" / "copied.txt"
    copied.write_bytes(data)
    _git(tmp_path, "add", "fixtures/copied.txt")
    _git(tmp_path, "commit", "-m", "Copy fixture")
    copied_commit = _git(tmp_path, "rev-parse", "HEAD")
    snapshot = replace(snapshot, commits=snapshot.commits | {copied_commit})
    monkeypatch.setattr(identity, "_HISTORY_SNAPSHOT_EXCEPTIONS", (snapshot,))
    _git(tmp_path, "rm", "fixtures/copied.txt")
    _git(tmp_path, "commit", "-m", "Remove copied fixture")

    violations = identity.audit_repository(tmp_path, include_history=True)

    assert identity.Violation("TXT-001", f"git:{copied_commit[:12]}:fixtures/copied.txt", 1) in violations


def test_unapproved_findings_in_the_same_snapshot_still_fail(tmp_path: Path, monkeypatch) -> None:
    data = f"{_restricted_token()}\n{_restricted_token()}\n{_external_token()}\n".encode()
    _, _, snapshot = _prepare_history_exception(tmp_path, monkeypatch, payload=data)

    violations = identity.audit_repository(tmp_path, include_history=True)

    historical = [item for item in violations if item.location.endswith(":" + snapshot.path)]
    assert not any(item.rule_id == "TXT-001" and item.line == 1 for item in historical)
    assert any(item.rule_id == "TXT-001" and item.line == 2 for item in historical)
    assert any(item.rule_id != "TXT-001" and item.line == 3 for item in historical)


def test_history_exception_never_covers_commit_messages(tmp_path: Path, monkeypatch) -> None:
    _, _, snapshot = _prepare_history_exception(tmp_path, monkeypatch, message=_restricted_token())

    violations = identity.audit_repository(tmp_path, include_history=True)

    commit = next(iter(snapshot.commits))
    assert identity.Violation("TXT-001", f"git:{commit[:12]}", 1) in violations


def test_history_exception_never_covers_current_files(tmp_path: Path, monkeypatch) -> None:
    path, data, snapshot = _prepare_history_exception(tmp_path, monkeypatch)
    path.write_bytes(data)

    violations = identity.audit_repository(tmp_path, include_history=True)

    assert identity.Violation("TXT-001", snapshot.path, 1) in violations


def test_history_exception_never_covers_release_artifacts(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "source"
    _, data, _ = _prepare_history_exception(root, monkeypatch)
    artifact = tmp_path / "payload.txt"
    artifact.write_bytes(data)

    violations = identity.audit_repository(root, include_history=True, artifact_paths=[artifact])

    assert identity.Violation("TXT-001", "payload.txt", 1) in violations


def test_policy_source_does_not_embed_restricted_samples() -> None:
    source = Path(identity.__file__).read_text(encoding="utf-8").casefold()

    assert _restricted_token() not in source
    assert _external_token().casefold() not in source
    assert _short_external_token() not in source

from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

build_native = importlib.import_module("scripts.release.build_native")
collect_artifacts = importlib.import_module("scripts.release.collect_artifacts")
release_common = importlib.import_module("scripts.release.common")
generate_sbom = importlib.import_module("scripts.release.generate_sbom")
reconcile_release_assets = importlib.import_module("scripts.release.reconcile_release_assets")
smoke_native = importlib.import_module("scripts.release.smoke_native")
check_glibc = importlib.import_module("scripts.release.check_glibc")
compare_oci_indexes = importlib.import_module("scripts.release.compare_oci_indexes")
extract_native = importlib.import_module("scripts.release.extract_native")
frozen_inventory = importlib.import_module("scripts.release.frozen_inventory")
license_inventory = importlib.import_module("scripts.release.license_inventory")
list_release_assets = importlib.import_module("scripts.release.list_release_assets")
normalize_docker_archive = importlib.import_module("scripts.release.normalize_docker_archive")
TARGETS = build_native.TARGETS
verify_build_host = build_native.verify_build_host
collect = collect_artifacts.collect
expected_asset_names = collect_artifacts.expected_asset_names
create_tar_gz = release_common.create_tar_gz
create_zip = release_common.create_zip
is_prerelease = release_common.is_prerelease
reset_directory = release_common.reset_directory
sha256_file = release_common.sha256_file
validate_tree_symlinks = release_common.validate_tree_symlinks
write_checksums = release_common.write_checksums


def _native_fixture(root: Path, target: str) -> Path:
    version = release_common.read_version()
    bundle = root / f"lingshu-gate-v{version}-{target}"
    bundle.mkdir(parents=True)
    if target.startswith("windows-"):
        (bundle / "start.cmd").write_text("@echo off\r\n", encoding="utf-8")
    else:
        launcher = bundle / "start.sh"
        launcher.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        launcher.chmod(0o755)
    (bundle / "lingshu-gate.exe" if target.startswith("windows-") else bundle / "lingshu-gate").write_bytes(
        b"executable"
    )
    return bundle


def _fixture_tree(root: Path) -> Path:
    bundle = root / "bundle"
    (bundle / "empty").mkdir(parents=True)
    (bundle / "file.txt").write_text("stable\n", encoding="utf-8")
    return bundle


def test_windows_native_smoke_uses_cwd_relative_batch_launcher(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle = tmp_path / "bundle with spaces"
    bundle.mkdir()
    (bundle / "start.cmd").write_text("@exit /b 0\r\n", encoding="utf-8")
    command_processor = r"C:\Windows\System32\cmd.exe"
    monkeypatch.setenv("COMSPEC", command_processor)

    assert smoke_native._launcher_command(bundle, "windows-x86_64") == [
        command_processor,
        "/d",
        "/c",
        "start.cmd",
    ]


def test_windows_native_smoke_rejects_missing_launcher(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Native launcher is missing"):
        smoke_native._launcher_command(tmp_path, "windows-x86_64")


@pytest.mark.parametrize("archive_type", ["tar.gz", "zip"])
def test_archives_are_deterministic(tmp_path: Path, archive_type: str) -> None:
    source = _fixture_tree(tmp_path)
    first = tmp_path / f"first.{archive_type}"
    second = tmp_path / f"second.{archive_type}"
    writer = create_tar_gz if archive_type == "tar.gz" else create_zip

    writer(source, first, epoch=1_700_000_000)
    writer(source, second, epoch=1_700_000_000)

    assert sha256_file(first) == sha256_file(second)


@pytest.mark.parametrize(
    ("target", "archive_suffix"),
    [("linux-x86_64", "tar.gz"), ("windows-x86_64", "zip")],
)
def test_publishable_native_archive_is_validated_and_extracted(
    tmp_path: Path,
    target: str,
    archive_suffix: str,
) -> None:
    bundle = _native_fixture(tmp_path / "source", target)
    archive = tmp_path / f"{bundle.name}.{archive_suffix}"
    writer = create_zip if archive_suffix == "zip" else create_tar_gz
    writer(bundle, archive, epoch=1_700_000_000)
    allowed_parent = tmp_path / "release"
    extracted = extract_native.extract_archive(
        target,
        archive,
        allowed_parent / "extracted",
        allowed_parent=allowed_parent,
    )

    assert extracted.name == bundle.name
    launcher = extracted / ("start.cmd" if target.startswith("windows-") else "start.sh")
    assert launcher.is_file()
    if not target.startswith("windows-"):
        assert stat.S_IMODE(launcher.stat().st_mode) & 0o111 == 0o111


def test_tar_extractor_rejects_file_beneath_symlink_alias(tmp_path: Path) -> None:
    version = release_common.read_version()
    root = f"lingshu-gate-v{version}-linux-x86_64"
    archive = tmp_path / f"{root}.tar.gz"
    with tarfile.open(archive, mode="w:gz") as output:
        directory = tarfile.TarInfo(root)
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        output.addfile(directory)
        launcher_payload = b"#!/bin/sh\nexit 0\n"
        launcher = tarfile.TarInfo(f"{root}/start.sh")
        launcher.size = len(launcher_payload)
        launcher.mode = 0o755
        output.addfile(launcher, io.BytesIO(launcher_payload))
        alias = tarfile.TarInfo(f"{root}/alias")
        alias.type = tarfile.SYMTYPE
        alias.linkname = "."
        output.addfile(alias)
        replacement_payload = b"replaced\n"
        replacement = tarfile.TarInfo(f"{root}/alias/start.sh")
        replacement.size = len(replacement_payload)
        replacement.mode = 0o644
        output.addfile(replacement, io.BytesIO(replacement_payload))

    allowed_parent = tmp_path / "release"
    with pytest.raises(RuntimeError, match="ancestor is not a directory"):
        extract_native.extract_archive(
            "linux-x86_64",
            archive,
            allowed_parent / "extracted",
            allowed_parent=allowed_parent,
        )


@pytest.mark.parametrize("replacement_name", ["START.CMD", "start.cmd."])
def test_zip_extractor_rejects_windows_path_aliases(tmp_path: Path, replacement_name: str) -> None:
    version = release_common.read_version()
    root = f"lingshu-gate-v{version}-windows-x86_64"
    archive = tmp_path / f"{root}.zip"
    with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_DEFLATED) as output:
        output.writestr(f"{root}/", b"")
        output.writestr(f"{root}/start.cmd", b"@exit /b 0\r\n")
        output.writestr(f"{root}/{replacement_name}", b"@exit /b 1\r\n")

    allowed_parent = tmp_path / "release"
    with pytest.raises(RuntimeError, match="filesystem-colliding|trailing dot or space"):
        extract_native.extract_archive(
            "windows-x86_64",
            archive,
            allowed_parent / "extracted",
            allowed_parent=allowed_parent,
        )


def test_zip_extractor_rejects_member_over_resource_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    version = release_common.read_version()
    root = f"lingshu-gate-v{version}-windows-x86_64"
    archive = tmp_path / f"{root}.zip"
    with zipfile.ZipFile(archive, mode="w", compression=zipfile.ZIP_STORED) as output:
        output.writestr(f"{root}/", b"")
        output.writestr(f"{root}/start.cmd", b"12345")
    monkeypatch.setattr(extract_native, "MAX_ARCHIVE_MEMBER_BYTES", 4)

    allowed_parent = tmp_path / "release"
    with pytest.raises(RuntimeError, match="member exceeds the extraction size limit"):
        extract_native.extract_archive(
            "windows-x86_64",
            archive,
            allowed_parent / "extracted",
            allowed_parent=allowed_parent,
        )


def test_native_builder_recreates_console_from_lockfile(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[list[str], Path]] = []
    monkeypatch.setattr(build_native.shutil, "which", lambda command: "/opt/npm" if command == "npm" else None)

    def fake_run(command: list[str], *, cwd: Path, check: bool) -> None:
        assert check
        calls.append((command, cwd))

    monkeypatch.setattr(build_native.subprocess, "run", fake_run)
    build_native._build_console()

    assert calls == [
        (["/opt/npm", "ci", "--no-audit", "--no-fund"], REPOSITORY_ROOT / "web"),
        (["/opt/npm", "run", "build"], REPOSITORY_ROOT / "web"),
    ]


def test_docker_save_outer_archive_normalization_is_deterministic(tmp_path: Path) -> None:
    def write_fixture(path: Path, *, reverse: bool, mtime: int) -> None:
        entries = [("manifest.json", b"[]\n"), ("sha256/layer.tar", b"layer")]
        with tarfile.open(path, mode="w") as archive:
            for name, payload in reversed(entries) if reverse else entries:
                info = tarfile.TarInfo(name)
                info.size = len(payload)
                info.mtime = mtime
                info.uid = mtime
                archive.addfile(info, io.BytesIO(payload))

    first_source = tmp_path / "first-source.tar"
    second_source = tmp_path / "second-source.tar"
    first = tmp_path / "first.tar"
    second = tmp_path / "second.tar"
    write_fixture(first_source, reverse=False, mtime=1)
    write_fixture(second_source, reverse=True, mtime=2)
    normalize_docker_archive.normalize(first_source, first, epoch=1_700_000_000)
    normalize_docker_archive.normalize(second_source, second, epoch=1_700_000_000)
    assert sha256_file(first) == sha256_file(second)


def test_reset_directory_rejects_its_boundary(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="Refusing to reset"):
        reset_directory(tmp_path, allowed_parent=tmp_path)


def test_archive_rejects_an_escaping_symlink(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    link = bundle / "escape"
    try:
        link.symlink_to(Path("..") / "outside")
    except OSError:
        pytest.skip("symlinks are not available on this test host")

    with pytest.raises(RuntimeError, match="escaping symlink"):
        validate_tree_symlinks(bundle)


def test_zip_rejects_even_an_internal_symlink(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    target = bundle / "target.txt"
    target.write_text("target", encoding="utf-8")
    try:
        (bundle / "link.txt").symlink_to(target.name)
    except OSError:
        pytest.skip("symlinks are not available on this test host")

    with pytest.raises(RuntimeError, match="does not support symlinks"):
        create_zip(bundle, tmp_path / "bundle.zip", epoch=1_700_000_000)


def test_artifact_collection_validates_and_combines_checksums(tmp_path: Path) -> None:
    downloads = tmp_path / "downloads"
    first_job = downloads / "native-linux"
    second_job = downloads / "docker"
    first_job.mkdir(parents=True)
    second_job.mkdir(parents=True)
    expected_names = sorted(expected_asset_names("1.0.0"))
    first_assets = [first_job / name for name in expected_names[:5]]
    second_assets = [second_job / name for name in expected_names[5:]]
    for asset in [*first_assets, *second_assets]:
        asset.write_bytes(asset.name.encode("utf-8"))
    write_checksums(first_job, first_assets)
    write_checksums(second_job, second_assets)

    output = tmp_path / "release" / "assets"
    assets = collect(
        downloads,
        output,
        version="1.0.0",
        allowed_output_parent=tmp_path / "release",
    )

    assert [asset.name for asset in assets] == expected_names
    checksum_text = (output / "SHA256SUMS").read_text(encoding="utf-8")
    assert hashlib.sha256(expected_names[0].encode("utf-8")).hexdigest() in checksum_text
    assert hashlib.sha256(expected_names[-1].encode("utf-8")).hexdigest() in checksum_text


def test_artifact_collection_rejects_symlink_input(tmp_path: Path) -> None:
    downloads = tmp_path / "downloads" / "native"
    downloads.mkdir(parents=True)
    outside = tmp_path / "outside.tar.gz"
    outside.write_bytes(b"outside")
    asset = downloads / "lingshu-gate-v1.0.0-linux-x86_64.tar.gz"
    try:
        asset.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available on this test host")
    (downloads / "SHA256SUMS").write_text(
        f"{sha256_file(outside)}  {asset.name}\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="non-regular entry"):
        collect(
            tmp_path / "downloads",
            tmp_path / "output" / "release",
            version="1.0.0",
            allowed_output_parent=tmp_path / "output",
        )


def test_artifact_collection_rechecks_digest_after_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    downloads = tmp_path / "downloads" / "complete"
    downloads.mkdir(parents=True)
    assets = []
    for name in expected_asset_names("1.0.0"):
        asset = downloads / name
        asset.write_bytes(name.encode("utf-8"))
        assets.append(asset)
    write_checksums(downloads, assets)
    original_copy = collect_artifacts.shutil.copy2

    def corrupting_copy(source: Path, destination: Path) -> Path:
        copied = Path(original_copy(source, destination))
        copied.write_bytes(copied.read_bytes() + b"changed")
        return copied

    monkeypatch.setattr(collect_artifacts.shutil, "copy2", corrupting_copy)
    with pytest.raises(RuntimeError, match="Copied release asset checksum mismatch"):
        collect(
            tmp_path / "downloads",
            tmp_path / "output" / "release",
            version="1.0.0",
            allowed_output_parent=tmp_path / "output",
        )


def test_artifact_collection_rejects_foreign_asset_names(tmp_path: Path) -> None:
    downloads = tmp_path / "downloads" / "job"
    downloads.mkdir(parents=True)
    asset = downloads / "unrelated-v1.0.0-linux-x86_64.tar.gz"
    asset.write_bytes(b"unexpected")
    write_checksums(downloads, [asset])

    with pytest.raises(RuntimeError, match="Unexpected release asset name"):
        collect(
            tmp_path / "downloads",
            tmp_path / "release" / "assets",
            version="1.0.0",
            allowed_output_parent=tmp_path / "release",
        )


def test_artifact_collection_cannot_delete_an_arbitrary_output(tmp_path: Path) -> None:
    downloads = tmp_path / "downloads" / "job"
    downloads.mkdir(parents=True)
    asset = downloads / "lingshu-gate-v1.0.0-linux-x86_64.tar.gz"
    asset.write_bytes(b"asset")
    write_checksums(downloads, [asset])
    unsafe_output = tmp_path / "outside"
    unsafe_output.mkdir()
    sentinel = unsafe_output / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Refusing to reset"):
        collect(
            tmp_path / "downloads",
            unsafe_output,
            version="1.0.0",
            allowed_output_parent=tmp_path / "safe",
        )
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_release_asset_reconciliation_removes_only_stale_names() -> None:
    payload = {
        "assets": [
            {"name": "lingshu-gate-v1.0.0-linux-x86_64.tar.gz"},
            {"name": "obsolete-asset.zip"},
        ]
    }
    desired = {
        "lingshu-gate-v1.0.0-linux-x86_64.tar.gz",
        "SHA256SUMS",
    }

    assert reconcile_release_assets.release_asset_plan(payload, desired) == {
        "existing": ["lingshu-gate-v1.0.0-linux-x86_64.tar.gz"],
        "missing": ["SHA256SUMS"],
        "stale": ["obsolete-asset.zip"],
    }


def test_release_asset_reconciliation_rejects_duplicate_or_unsafe_names() -> None:
    with pytest.raises(RuntimeError, match="duplicate name"):
        reconcile_release_assets.release_asset_plan(
            {"assets": [{"name": "same.zip"}, {"name": "same.zip"}]},
            {"same.zip"},
        )
    with pytest.raises(RuntimeError, match="unsafe name"):
        reconcile_release_assets.release_asset_plan(
            {"assets": [{"name": "../escape.zip"}]},
            {"safe.zip"},
        )
    for unsafe_name in ("--repo=owner/other", "line\nbreak.zip", " leading.zip"):
        with pytest.raises(RuntimeError, match="unsafe name"):
            reconcile_release_assets.release_asset_plan(
                {"assets": [{"name": unsafe_name}]},
                {"safe.zip"},
            )


def test_native_target_matrix_covers_supported_downloads() -> None:
    assert set(TARGETS) == {
        "linux-x86_64",
        "linux-aarch64",
        "windows-x86_64",
        "macos-x86_64",
        "macos-arm64",
    }


def test_release_linux_builds_share_ubuntu_22_04_glibc_baseline() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "runner: ubuntu-22.04\n            target: linux-x86_64" in workflow
    assert "runner: ubuntu-22.04-arm\n            target: linux-aarch64" in workflow
    assert "--maximum 2.35" in workflow


def test_release_smokes_the_extracted_publishable_native_archive() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "Validate and extract the publishable native archive" in workflow
    assert "python -m scripts.release.extract_native" in workflow
    assert workflow.count("build/release/native-archive-${{ matrix.target }}") >= 3
    assert "build/release/${{ matrix.target }}/bundle/" not in workflow


def test_release_artifacts_receive_identity_validation_after_build() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "check_repository_identity.py --history" in workflow
    assert "Validate native archive identity" in workflow
    assert "Validate deployment artifacts identity" in workflow
    assert "Validate offline image archives identity" in workflow
    assert "Validate container metadata identity" in workflow
    assert "Validate final release identity" in workflow
    assert len(re.findall(r"check_repository_identity\.py\s+--artifacts", workflow)) >= 5


def test_release_examples_cover_browser_origin_policy() -> None:
    for relative_path in (
        "packaging/native/lingshu-gate.env.example",
        "packaging/docker/.env.example",
        "packaging/docker/.env.offline.example",
    ):
        example = (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")
        assert "LINGSHU_GATE_MCP_ALLOWED_ORIGINS=" in example
    deployment = (REPOSITORY_ROOT / "packaging" / "docker" / "README.md").read_text(encoding="utf-8")
    compose = (REPOSITORY_ROOT / "compose.prod.yaml").read_text(encoding="utf-8")
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "LINGSHU_GATE_MCP_ALLOWED_ORIGINS" in deployment
    assert "LINGSHU_GATE_MCP_ALLOWED_ORIGINS" in compose
    assert '--env-file "$bundle/.env.example"' in workflow
    assert '--env-file "$bundle/.env.offline-${architecture}.example"' in workflow
    assert '.services.core.environment.LINGSHU_GATE_MCP_ALLOWED_ORIGINS == ""' in workflow


def test_offline_compose_template_is_a_source_and_delivery_input() -> None:
    template = REPOSITORY_ROOT / "packaging" / "docker" / ".env.offline.example"
    assert template.is_file()
    assert not template.is_symlink()
    ignore_rules = (REPOSITORY_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    exception = "!packaging/docker/.env.offline.example"
    assert exception in ignore_rules
    assert ignore_rules.index(exception) > ignore_rules.index(".env.*")
    builder = (REPOSITORY_ROOT / "scripts" / "release" / "build_docker_bundle.py").read_text(
        encoding="utf-8"
    )
    assert '"docker" / ".env.offline.example"' in builder
    assert 'f".env.offline-{architecture}.example"' in builder


def test_docker_context_excludes_local_python_build_metadata() -> None:
    dockerignore = (REPOSITORY_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "*.egg-info/" in dockerignore
    dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY src ./src" in dockerfile


def test_docker_base_images_are_digest_pinned_and_release_values_match() -> None:
    dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    for argument, environment_name in (
        ("NODE_BASE_IMAGE", "LINGSHU_GATE_RELEASE_NODE_BASE_IMAGE"),
        ("PYTHON_BASE_IMAGE", "LINGSHU_GATE_RELEASE_PYTHON_BASE_IMAGE"),
    ):
        docker_match = re.search(rf"^ARG {argument}=(\S+@sha256:[0-9a-f]{{64}})$", dockerfile, re.MULTILINE)
        workflow_match = re.search(rf"^  {environment_name}: (\S+@sha256:[0-9a-f]{{64}})$", workflow, re.MULTILINE)
        assert docker_match is not None
        assert workflow_match is not None
        assert docker_match.group(1) == workflow_match.group(1)
        assert f"FROM ${{{argument}}}" in dockerfile


def test_container_identity_is_gate_specific_without_aliases() -> None:
    dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")
    docker_workflow = (
        REPOSITORY_ROOT / ".github" / "workflows" / "docker.yml"
    ).read_text(encoding="utf-8")
    release_workflow = (
        REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"
    ).read_text(encoding="utf-8")

    assert 'groupadd --gid "${APP_GID}" gate' in dockerfile
    assert '--home-dir /data/home --shell /usr/sbin/nologin gate' in dockerfile
    label_pattern = re.compile(r"io\.lingshu(?:\.[a-z]+)*\.image\.role")
    for content in (dockerfile, docker_workflow, release_workflow):
        assert set(label_pattern.findall(content)) == {"io.lingshu.gate.image.role"}
    password_path = re.search(
        r"LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE: (\S+)",
        docker_workflow,
    )
    assert password_path is not None
    assert password_path.group(1) == "/tmp/lingshu-gate-bootstrap-password"
    assert docker_workflow.count('grep --quiet "^gate:x:10001:') >= 2
    assert release_workflow.count('grep --quiet "^gate:x:10001:') >= 2


def test_release_toolchains_and_image_timestamps_are_pinned() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    offline_builder = (REPOSITORY_ROOT / "scripts" / "release" / "build_offline_images.sh").read_text(
        encoding="utf-8"
    )
    assert re.search(r"^  LINGSHU_GATE_RELEASE_NODE_VERSION: \d+\.\d+\.\d+$", workflow, re.MULTILINE)
    assert re.search(r"^  LINGSHU_GATE_RELEASE_PYTHON_VERSION: \d+\.\d+\.\d+$", workflow, re.MULTILINE)
    assert "LINGSHU_GATE_RELEASE_PYTHON_VERSION: 3.13.15" in workflow
    assert re.search(r"^  LINGSHU_GATE_RELEASE_BUILDX_VERSION: v\d+\.\d+\.\d+$", workflow, re.MULTILINE)
    assert re.search(
        r"^  LINGSHU_GATE_RELEASE_BUILDKIT_IMAGE: \S+@sha256:[0-9a-f]{64}$",
        workflow,
        re.MULTILINE,
    )
    assert re.search(
        r"^  LINGSHU_GATE_RELEASE_BINFMT_IMAGE: \S+@sha256:[0-9a-f]{64}$",
        workflow,
        re.MULTILINE,
    )
    assert "node-version: ${{ env.LINGSHU_GATE_RELEASE_NODE_VERSION }}" in workflow
    assert "python-version: ${{ env.LINGSHU_GATE_RELEASE_PYTHON_VERSION }}" in workflow
    assert "driver-opts: image=${{ env.LINGSHU_GATE_RELEASE_BUILDKIT_IMAGE }}" in workflow
    assert workflow.count("image: ${{ env.LINGSHU_GATE_RELEASE_BINFMT_IMAGE }}") == 2
    assert workflow.count("platforms: arm64") >= 2
    assert "rewrite-timestamp=true" in workflow
    assert "oci-mediatypes=true" in workflow
    assert "LINGSHU_GATE_RELEASE_SOURCE_DIGEST" in offline_builder
    assert "docker pull --platform" in offline_builder
    assert "docker save --output" in offline_builder
    assert "docker buildx build" not in offline_builder


def test_release_quality_uses_pinned_python_for_identity_validation() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    quality_job = workflow.split("\n  quality:\n", maxsplit=1)[1].split(
        "\n  native:\n", maxsplit=1
    )[0]
    assert quality_job.index("- name: Set up Python") < quality_job.index(
        "- name: Validate repository identity"
    )


def test_release_windows_matrix_smokes_delivery_skill_packager() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert '".agents/skills/lingshu-gate-upload-build-start/**"' in workflow
    assert "Parse and smoke-test the Delivery Skill packager" in workflow
    assert "if: runner.os == 'Windows'" in workflow
    assert "Language.Parser]::ParseFile" in workflow
    assert "New-LingshuGateProjectBundle.ps1" in workflow
    assert "file_list_sha256" in workflow
    assert "Non-deterministic Delivery Skill ZIP timestamp" in workflow


def test_release_build_backend_and_packager_are_exactly_pinned() -> None:
    project = (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'requires = ["setuptools==81.0.0"]' in project
    assert 'build-constraint-dependencies = ["setuptools==81.0.0"]' in project
    assert '"pyinstaller==6.22.2"' in project
    assert '"setuptools==81.0.0"' in project


def test_publishable_bundles_exclude_development_dependencies() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert workflow.count("uv sync --frozen --no-dev --group release") == 2
    assert "Install frozen quality and release dependencies\n        run: uv sync --frozen --group release" in workflow
    assert "uv sync --frozen --group release" in workflow


def test_release_is_the_only_version_tag_container_publisher() -> None:
    release_workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    container_workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "docker.yml").read_text(
        encoding="utf-8"
    )
    assert "docker-publish:" in release_workflow
    assert "- docker-publish" in release_workflow
    assert "platforms: linux/amd64,linux/arm64" in release_workflow
    assert "sbom: true" in release_workflow
    assert "provenance: mode=max" in release_workflow
    assert "release-candidate-${{ github.sha }}" in release_workflow
    assert "Promote version tag without replacing an existing digest" in release_workflow
    assert "Refusing to replace existing version tag" in release_workflow
    assert "Scan amd64 candidate payload for critical vulnerabilities" in release_workflow
    assert "Scan arm64 candidate payload for critical vulnerabilities" in release_workflow
    assert "steps.platforms.outputs.amd64_digest" in release_workflow
    assert "steps.platforms.outputs.arm64_digest" in release_workflow
    assert "lingshu-gate-v${VERSION}-container-image.txt" in release_workflow
    assert "LINGSHU_GATE_RELEASE_SOURCE_DIGEST" in release_workflow
    assert "needs.docker-publish.outputs.candidate_digest" in release_workflow
    assert 'DOCKER_BUILD_RECORD_UPLOAD: "false"' in release_workflow
    assert 'pattern: "!*.dockerbuild"' in release_workflow
    assert 'tags:\n      - "v*"' not in container_workflow
    assert "type=semver" not in container_workflow
    assert "github.ref == 'refs/heads/main'" in container_workflow


def test_manual_release_publication_is_version_checked_and_fail_closed() -> None:
    publish_workflow = (
        REPOSITORY_ROOT / ".github" / "workflows" / "publish-release.yml"
    ).read_text(encoding="utf-8")
    release_workflow = (
        REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"
    ).read_text(encoding="utf-8")

    assert "workflow_dispatch:" in publish_workflow
    assert "\n  push:" not in publish_workflow
    assert "contents: write" in publish_workflow
    assert "actions: write" in publish_workflow
    assert "cancel-in-progress: false" in publish_workflow
    assert "ref: ${{ github.sha }}" in publish_workflow
    assert "persist-credentials: false" in publish_workflow
    assert '[[ "$GITHUB_REF" != "refs/heads/main" ]]' in publish_workflow
    assert 'check_version --tag "$RELEASE_TAG"' in publish_workflow
    assert '-f ref="refs/tags/${RELEASE_TAG}"' in publish_workflow
    assert '-f sha="$GITHUB_SHA"' in publish_workflow
    assert "Release tag already points to a different revision" in publish_workflow
    assert "Release tag lookup failed" in publish_workflow
    assert "HTTP 404([^0-9]|$)" in publish_workflow
    assert "Release tag creation failed" in publish_workflow
    assert "Release tag was created concurrently at the verified revision" in publish_workflow
    assert "Release tag verification failed" in publish_workflow
    assert "actions/workflows/release.yml/dispatches" in publish_workflow
    assert '-f ref="$RELEASE_TAG"' in publish_workflow
    assert publish_workflow.count("X-GitHub-Api-Version: 2026-03-10") == 2
    assert ".workflow_run_id" in publish_workflow
    assert ".run_url" in publish_workflow
    assert ".html_url" in publish_workflow
    assert "Release workflow dispatch returned unexpected run metadata" in publish_workflow
    assert "--force" not in publish_workflow
    assert "delete" not in publish_workflow.casefold()

    tag_condition = (
        "if: github.ref_type == 'tag' && startsWith(github.ref, 'refs/tags/v') && "
        "(github.event_name == 'push' || github.event_name == 'workflow_dispatch')"
    )
    assert release_workflow.count(tag_condition) == 3
    assert "github.event_name == 'push' && startsWith(github.ref" not in release_workflow
    assert "Verify release tag still targets source revision before promotion" in release_workflow
    assert "Verify release tag still targets source revision before publication" in release_workflow
    assert release_workflow.count('.object.type == "commit" and .object.sha == $expected_sha') == 2
    assert release_workflow.count("Release tag no longer targets the verified source revision") == 2


def test_release_reconciliation_propagates_validation_failures() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "--emit \"$asset_set\" > \"/tmp/lingshu-gate-${asset_set}-assets.nul\"" in workflow
    assert "mapfile -d '' -t existing_assets < /tmp/lingshu-gate-existing-assets.nul" in workflow
    assert 'test "${#existing_assets[@]}" -eq 11' in workflow
    assert "< <(\n            python -m scripts.release.reconcile_release_assets" not in workflow
    assert "gh release upload" not in workflow
    assert "gh release delete-asset" not in workflow
    assert "gh release edit" not in workflow
    assert "if: steps.existing-release.outputs.exists != 'true'" in workflow
    assert "release not found[[:space:]]*$" in workflow
    assert "HTTP 404|not found" not in workflow
    assert "cat \"$release_error\" >&2" in workflow
    assert "Existing release does not exactly match the verified published artifact set" in workflow
    assert workflow.count("--json assets,isDraft,isImmutable,isPrerelease,tagName") == 2
    assert workflow.count(".tagName == $release_tag") == 2
    assert workflow.count(".isPrerelease == $expected_prerelease") == 2
    assert "Existing release tag, prerelease, draft, or immutability metadata is invalid" in workflow
    assert "Verify newly published immutable release" in workflow
    assert "for attempt in $(seq 1 10)" in workflow
    assert '[[ "$created_visible" != "true" ]]' in workflow
    assert "Published release tag, prerelease, draft, or immutability metadata is invalid" in workflow
    assert "created-existing-assets.nul" in workflow
    assert "New immutable release does not contain the exact verified artifact set" in workflow
    assert '(( ${#published_assets[@]} != 11 ))' in workflow
    assert workflow.count("cmp --silent") == 2
    assert "python -m scripts.release.list_release_assets" in workflow
    assert "mapfile -d '' -t assets < /tmp/lingshu-gate-release-assets.nul" in workflow
    assert "mapfile -t assets < <(" not in workflow


def test_release_verifies_all_asset_attestations_with_strict_identity() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "artifact-metadata: write" in workflow
    assert "Verify every release asset attestation" in workflow
    assert 'test "${#attested_assets[@]}" -eq 11' in workflow
    assert 'cert_identity="https://github.com/${GITHUB_REPOSITORY}/.github/workflows/release.yml@${GITHUB_REF}"' in workflow
    assert "--repo \"$GITHUB_REPOSITORY\"" in workflow
    assert "--cert-identity \"$cert_identity\"" in workflow
    assert "--source-ref \"$GITHUB_REF\"" in workflow
    assert "--source-digest \"$GITHUB_SHA\"" in workflow
    assert "--deny-self-hosted-runners" in workflow
    assert ".verificationResult.verifiedTimestamps | length > 0" in workflow


def test_release_asset_enumeration_rejects_non_regular_or_incomplete_sets(tmp_path: Path) -> None:
    version = release_common.read_version()
    release_dir = tmp_path / "release"
    release_dir.mkdir()
    with pytest.raises(RuntimeError, match="exact publishable file set"):
        list_release_assets.validated_asset_paths(release_dir, version)

    for name in expected_asset_names(version):
        (release_dir / name).write_bytes(name.encode("utf-8"))
    write_checksums(release_dir, [release_dir / name for name in expected_asset_names(version)])
    paths = list_release_assets.validated_asset_paths(release_dir, version)
    assert len(paths) == 11

    replaced = release_dir / next(iter(expected_asset_names(version)))
    replaced.unlink()
    try:
        replaced.symlink_to(release_dir / "SHA256SUMS")
    except OSError:
        pytest.skip("symlinks are not available on this test host")
    with pytest.raises(RuntimeError, match="non-regular entry"):
        list_release_assets.validated_asset_paths(release_dir, version)


def _platform_manifest(
    digest: str,
    architecture: str,
    *,
    size: int,
    variant: str | None = None,
    features: list[str] | None = None,
) -> dict[str, object]:
    platform: dict[str, object] = {"os": "linux", "architecture": architecture}
    if variant is not None:
        platform["variant"] = variant
    if features is not None:
        platform["os.features"] = features
    return {
        "mediaType": compare_oci_indexes.OCI_MANIFEST_MEDIA_TYPE,
        "digest": digest,
        "size": size,
        "platform": platform,
    }


def _attestation(digest_character: str, payload_digest: str, *, size: int) -> dict[str, object]:
    return {
        "mediaType": compare_oci_indexes.OCI_MANIFEST_MEDIA_TYPE,
        "digest": "sha256:" + digest_character * 64,
        "size": size,
        "platform": {"os": "unknown", "architecture": "unknown"},
        "annotations": {
            "vnd.docker.reference.type": "attestation-manifest",
            "vnd.docker.reference.digest": payload_digest,
        },
    }


def _oci_index(manifests: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schemaVersion": 2,
        "mediaType": compare_oci_indexes.OCI_INDEX_MEDIA_TYPE,
        "manifests": manifests,
    }


def test_oci_index_comparison_validates_attestations_and_platform_payloads() -> None:
    amd64 = "sha256:" + "a" * 64
    arm64 = "sha256:" + "b" * 64
    amd64_manifest = _platform_manifest(amd64, "amd64", size=100, features=["sse4"])
    arm64_manifest = _platform_manifest(arm64, "arm64", size=101, variant="v8")
    amd64_attestation = _attestation("c", amd64, size=102)
    arm64_attestation = _attestation("d", arm64, size=103)
    candidate = _oci_index(
        [amd64_manifest, arm64_manifest, amd64_attestation, arm64_attestation]
    )
    existing = _oci_index(
        [arm64_attestation, arm64_manifest, amd64_attestation, amd64_manifest]
    )
    compare_oci_indexes.assert_equivalent_indexes(candidate, existing)

    existing = json.loads(json.dumps(candidate))
    existing["manifests"][2]["size"] = 999
    with pytest.raises(RuntimeError, match="descriptor set differs"):
        compare_oci_indexes.assert_equivalent_indexes(candidate, existing)

    existing = json.loads(json.dumps(candidate))
    existing["manifests"][3]["digest"] = "sha256:" + "e" * 64
    with pytest.raises(RuntimeError, match="descriptor set differs"):
        compare_oci_indexes.assert_equivalent_indexes(candidate, existing)

    drifted_arm64 = "sha256:" + "9" * 64
    existing = json.loads(json.dumps(candidate))
    existing["manifests"][1]["digest"] = drifted_arm64
    existing["manifests"][3]["annotations"]["vnd.docker.reference.digest"] = drifted_arm64
    with pytest.raises(RuntimeError, match="payload differs"):
        compare_oci_indexes.assert_equivalent_indexes(candidate, existing)


def test_oci_index_rejects_unexpected_platform_or_malformed_attestation() -> None:
    amd64 = "sha256:" + "a" * 64
    arm64 = "sha256:" + "b" * 64
    manifests: list[dict[str, object]] = [
        _platform_manifest(amd64, "amd64", size=100),
        _platform_manifest(arm64, "arm64", size=101, variant="v8"),
        _attestation("c", amd64, size=102),
        _attestation("d", arm64, size=103),
    ]
    compare_oci_indexes.platform_payloads(_oci_index(manifests))

    with pytest.raises(RuntimeError, match="unexpected platform payload"):
        compare_oci_indexes.platform_payloads(
            _oci_index(
                [
                    *manifests,
                    _platform_manifest("sha256:" + "e" * 64, "s390x", size=104),
                ]
            )
        )

    malformed_attestation = _attestation("c", amd64, size=102)
    malformed_attestation["annotations"] = {}
    with pytest.raises(RuntimeError, match="not a BuildKit attestation"):
        compare_oci_indexes.platform_payloads(
            _oci_index([manifests[0], manifests[1], malformed_attestation, manifests[3]])
        )

    with pytest.raises(RuntimeError, match="exactly one BuildKit attestation"):
        compare_oci_indexes.platform_payloads(_oci_index(manifests[:-1]))

    invalid_schema = _oci_index(manifests)
    invalid_schema["schemaVersion"] = 1
    with pytest.raises(RuntimeError, match="schemaVersion 2"):
        compare_oci_indexes.platform_payloads(invalid_schema)

    invalid_variant = json.loads(json.dumps(_oci_index(manifests)))
    invalid_variant["manifests"][1]["platform"]["variant"] = "latest"
    with pytest.raises(RuntimeError, match="invalid platform variant"):
        compare_oci_indexes.platform_payloads(invalid_variant)


def test_release_validates_new_candidate_oci_index_before_promotion() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert "--index /tmp/lingshu-gate-image-index.json" in workflow
    assert workflow.count('[[ "$existing_digest" != "$CANDIDATE_DIGEST" ]]') == 2
    assert 'test "$EXPECTED_DIGEST" = "$CANDIDATE_DIGEST"' in workflow
    assert 'test "$source_digest" = "$candidate_digest"' in workflow
    assert "--index /tmp/lingshu-gate-offline-source-index.json" in workflow
    assert "--existing /tmp/lingshu-gate-promotion-final-index.json" in workflow


def test_frozen_inventory_maps_every_site_packages_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owned_file = tmp_path / "site-packages" / "example" / "module.py"
    owned_file.parent.mkdir(parents=True)
    owned_file.write_text("", encoding="utf-8")
    toc_path = tmp_path / "Analysis-00.toc"
    toc_path.write_text(repr(([('example.module', str(owned_file), 'PYMODULE')],)), encoding="utf-8")
    monkeypatch.setattr(frozen_inventory, "_installed_file_owners", lambda: {owned_file.resolve(): "example"})
    assert frozen_inventory.frozen_distribution_names(toc_path) == {"example"}

    monkeypatch.setattr(frozen_inventory, "_installed_file_owners", lambda: {})
    with pytest.raises(RuntimeError, match="no distribution owner"):
        frozen_inventory.frozen_distribution_names(toc_path)


def test_third_party_license_inventory_covers_production_console_closure(tmp_path: Path) -> None:
    npm_components, _npm_roots = generate_sbom.collect_npm_components()
    python_components = set(generate_sbom.collect_components("lingshu-gate")) - {"lingshu-gate"}
    records = license_inventory.stage_third_party_licenses(
        tmp_path / "licenses",
        frozen_distributions=python_components,
        npm_components=npm_components,
    )
    npm_records = [record for record in records if record["ecosystem"] == "npm"]
    assert len(npm_records) == len(npm_components)
    assert len([record for record in records if record["ecosystem"] == "pypi"]) == len(python_components)
    assert all(record["files"] for record in records)
    assert (tmp_path / "licenses" / "LICENSES.json").is_file()


def test_container_and_bundles_stage_complete_license_inventories() -> None:
    dockerfile = (REPOSITORY_ROOT / "Dockerfile").read_text(encoding="utf-8")
    docker_bundle = (REPOSITORY_ROOT / "scripts" / "release" / "build_docker_bundle.py").read_text(
        encoding="utf-8"
    )
    assert "stage_installed_python_licenses.py" in dockerfile
    assert "stage_npm_licenses.mjs" in dockerfile
    assert "COPY --from=console-builder /app/licenses/npm ./licenses/third-party/npm" in dockerfile
    assert "stage_third_party_licenses(" in docker_bundle


def test_container_ci_tracks_release_script_changes() -> None:
    workflow = (REPOSITORY_ROOT / ".github" / "workflows" / "docker.yml").read_text(
        encoding="utf-8"
    )
    assert workflow.count('- "scripts/release/**"') == 2


def test_npm_license_staging_creates_missing_output_parents(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to exercise the npm license staging script")

    package_root = tmp_path / "node_modules" / "example-package"
    package_root.mkdir(parents=True)
    (package_root / "package.json").write_text(
        json.dumps({"name": "example-package", "version": "1.0.0"}),
        encoding="utf-8",
    )
    (package_root / "LICENSE").write_text("Example license\n", encoding="utf-8")
    internal_working_directory = tmp_path / "node_modules" / ".vite-temp"
    internal_working_directory.mkdir()
    (internal_working_directory / "generated.js").write_text("export {};\n", encoding="utf-8")
    output_root = tmp_path / "missing-parent" / "licenses" / "npm"

    subprocess.run(
        [
            node,
            str(REPOSITORY_ROOT / "scripts" / "release" / "stage_npm_licenses.mjs"),
            str(tmp_path / "node_modules"),
            str(output_root),
            str(tmp_path / "overrides"),
        ],
        check=True,
    )

    inventory = json.loads((output_root / "LICENSES.json").read_text(encoding="utf-8"))
    assert [(item["name"], item["version"]) for item in inventory] == [
        ("example-package", "1.0.0")
    ]
    assert (output_root / inventory[0]["files"][0]).read_text(encoding="utf-8") == (
        "Example license\n"
    )


def test_npm_license_staging_rejects_visible_directory_without_metadata(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to exercise the npm license staging script")

    (tmp_path / "node_modules" / "unexpected-directory").mkdir(parents=True)
    result = subprocess.run(
        [
            node,
            str(REPOSITORY_ROOT / "scripts" / "release" / "stage_npm_licenses.mjs"),
            str(tmp_path / "node_modules"),
            str(tmp_path / "licenses" / "npm"),
            str(tmp_path / "overrides"),
        ],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode != 0
    assert "npm package metadata is missing" in result.stderr


def test_privileged_qemu_and_buildkit_images_are_immutable() -> None:
    for workflow_name, prefix in (
        ("release.yml", "LINGSHU_GATE_RELEASE"),
        ("docker.yml", "LINGSHU_GATE_CI"),
    ):
        workflow = (REPOSITORY_ROOT / ".github" / "workflows" / workflow_name).read_text(encoding="utf-8")
        qemu_steps = workflow.count("uses: docker/setup-qemu-action@")
        buildx_steps = workflow.count("uses: docker/setup-buildx-action@")
        assert qemu_steps > 0
        assert workflow.count(f"image: ${{{{ env.{prefix}_BINFMT_IMAGE }}}}") == qemu_steps
        assert workflow.count(f"driver-opts: image=${{{{ env.{prefix}_BUILDKIT_IMAGE }}}}") == buildx_steps
        assert re.search(
            rf"^  {prefix}_BINFMT_IMAGE: \S+@sha256:[0-9a-f]{{64}}$",
            workflow,
            re.MULTILINE,
        )
        assert re.search(
            rf"^  {prefix}_BUILDKIT_IMAGE: \S+@sha256:[0-9a-f]{{64}}$",
            workflow,
            re.MULTILINE,
        )


def test_all_github_actions_are_allowlisted_immutable_commit_pins() -> None:
    allowed_actions = {
        "actions/attest-build-provenance": ("4d101475d8b20a2381f78447822ac1eab6504dd8", "v4"),
        "actions/checkout": ("fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09", "v5"),
        "actions/download-artifact": ("37930b1c2abaa49bbe596cd826c3c89aef350131", "v7"),
        "actions/setup-node": ("a0853c24544627f65ddf259abe73b1d18a591444", "v5"),
        "actions/setup-python": ("ece7cb06caefa5fff74198d8649806c4678c61a1", "v6"),
        "actions/upload-artifact": ("b7c566a772e6b6bfb58ed0dc250532a479d7789f", "v6"),
        "aquasecurity/trivy-action": ("ed142fd0673e97e23eac54620cfb913e5ce36c25", "v0.36.0"),
        "astral-sh/setup-uv": ("37802adc94f370d6bfd71619e3f0bf239e1f3b78", "v7"),
        "docker/build-push-action": ("53b7df96c91f9c12dcc8a07bcb9ccacbed38856a", "v7"),
        "docker/login-action": ("dbcb813823bdd20940b903addbd779551569679f", "v4"),
        "docker/metadata-action": ("dc802804100637a589fabce1cb79ff13a1411302", "v6"),
        "docker/setup-buildx-action": ("37fe631027851001ddb9b187196cc803df7f5f0e", "v4"),
        "docker/setup-qemu-action": ("96fe6ef7f33517b61c61be40b68a1882f3264fb8", "v4"),
        "github/codeql-action/analyze": ("cdf488f595d80d6e07e03d4674febd5ab45fa938", "v4.37.9"),
        "github/codeql-action/init": ("cdf488f595d80d6e07e03d4674febd5ab45fa938", "v4.37.9"),
        "sigstore/cosign-installer": ("398d4b0eeef1380460a10c8013a76f728fb906ac", "v3"),
    }
    action_pattern = re.compile(
        r"^\s*uses:\s*([^\s@]+)@([0-9a-f]{40})\s+#\s+(\S+)\s*$"
    )
    observed_actions: set[str] = set()
    for workflow_path in sorted((REPOSITORY_ROOT / ".github" / "workflows").glob("*.yml")):
        for line_number, line in enumerate(workflow_path.read_text(encoding="utf-8").splitlines(), start=1):
            if "uses:" not in line or line.lstrip().startswith("#"):
                continue
            match = action_pattern.fullmatch(line)
            assert match, f"Unpinned action at {workflow_path}:{line_number}: {line}"
            action, commit, version = match.groups()
            assert action in allowed_actions, f"Unapproved action at {workflow_path}:{line_number}: {action}"
            assert (commit, version) == allowed_actions[action]
            observed_actions.add(action)
    assert observed_actions == set(allowed_actions)


def test_release_version_is_safe_for_oci_tags_and_marks_prereleases() -> None:
    assert not is_prerelease("1.2.3")
    assert is_prerelease("1.2.3-rc.1")
    for invalid_version in (
        "1.2.3+build.1",
        "1.2.3-alpha..1",
        "1.2.3-alpha.",
        "1.2.3-alpha.lock",
        "01.2.3",
        "1.2.3-01",
    ):
        with pytest.raises(RuntimeError, match="Invalid release version"):
            is_prerelease(invalid_version)


def test_glibc_version_parser_orders_numerically() -> None:
    versions = check_glibc.parse_versions("GLIBC_2.9 GLIBC_2.35 GLIBC_2.17 GLIBC_PRIVATE")
    assert max(versions) == (2, 35)


def test_release_launchers_are_executable_in_source_tree() -> None:
    if os.name != "posix":
        pytest.skip("POSIX executable mode is validated on the Linux CI runner")
    for relative_path in ("packaging/native/start.sh", "scripts/release/build_offline_images.sh"):
        mode = stat.S_IMODE((REPOSITORY_ROOT / relative_path).stat().st_mode)
        assert mode & 0o111 == 0o111


def test_spdx_includes_npm_production_closure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock_path = tmp_path / "package-lock.json"
    lock_path.write_text(
        json.dumps(
            {
                "lockfileVersion": 3,
                "packages": {
                    "": {
                        "dependencies": {"@scope/ui-runtime": "1.0.0"},
                        "devDependencies": {"build-only": "1.0.0"},
                    },
                    "node_modules/@scope/ui-runtime": {
                        "version": "1.0.0",
                        "license": "MIT",
                        "dependencies": {"shared-runtime": "2.0.0"},
                        "optionalDependencies": {"missing-platform-runtime": "1.0.0"},
                        "peerDependencies": {
                            "peer-runtime": "1.0.0",
                            "peer-types": "1.0.0",
                        },
                        "peerDependenciesMeta": {"peer-types": {"optional": True}},
                    },
                    "node_modules/shared-runtime": {"version": "2.0.0", "license": "Apache-2.0"},
                    "node_modules/peer-runtime": {"version": "1.0.0", "license": "ISC"},
                    "node_modules/peer-types": {"version": "1.0.0", "license": "MIT", "dev": True},
                    "node_modules/build-only": {"version": "1.0.0", "license": "MIT", "dev": True},
                },
            }
        ),
        encoding="utf-8",
    )
    python_root = generate_sbom.Component(
        name="lingshu-gate",
        version="1.0.0",
        license_declared="Apache-2.0",
        supplier="Organization: Lingshu Gate Contributors",
    )
    frozen_components = {
        "packaging": generate_sbom.Component(
            name="packaging",
            version="26.3",
            license_declared="Apache-2.0 OR BSD-2-Clause",
            supplier="NOASSERTION",
        ),
        "pyinstaller-hooks-contrib": generate_sbom.Component(
            name="pyinstaller-hooks-contrib",
            version="2026.3",
            license_declared="Apache-2.0 OR GPL-2.0-or-later",
            supplier="NOASSERTION",
        ),
        "setuptools": generate_sbom.Component(
            name="setuptools",
            version="81.0.0",
            license_declared="MIT",
            supplier="NOASSERTION",
        ),
    }
    monkeypatch.setattr(generate_sbom, "collect_components", lambda _name: {"lingshu-gate": python_root})
    monkeypatch.setattr(generate_sbom, "_installed_component", frozen_components.__getitem__)
    monkeypatch.setattr(generate_sbom, "read_version", lambda: "1.0.0")
    monkeypatch.setattr(generate_sbom, "source_revision", lambda: "a" * 40)
    monkeypatch.setattr(generate_sbom, "source_date_epoch", lambda: 1_700_000_000)
    monkeypatch.setattr(
        generate_sbom.importlib.metadata,
        "version",
        lambda name: "6.22.2" if name == "pyinstaller" else pytest.fail(f"unexpected distribution lookup: {name}"),
    )

    document = generate_sbom.build_spdx_document(
        "lingshu-gate",
        target="test-target",
        npm_lock_path=lock_path,
        frozen_runtime=True,
        frozen_distributions={"packaging", "setuptools", "pyinstaller-hooks-contrib"},
    )

    packages = document["packages"]
    npm_packages = [
        package for package in packages if str(package["SPDXID"]).startswith("SPDXRef-Package-npm-")
    ]
    assert {package["name"] for package in npm_packages} == {
        "@scope/ui-runtime",
        "shared-runtime",
        "peer-runtime",
    }
    assert all(package["licenseDeclared"] != "NOASSERTION" for package in npm_packages)
    assert all(
        str(package["externalRefs"][0]["referenceLocator"]).startswith("pkg:npm/")
        for package in npm_packages
    )
    relationships = document["relationships"]
    assert any(relationship["relationshipType"] == "CONTAINS" for relationship in relationships)
    assert any(
        relationship["spdxElementId"] == generate_sbom.CONSOLE_SPDX_ID
        and relationship["relationshipType"] == "DEPENDS_ON"
        for relationship in relationships
    )
    package_ids = {package["SPDXID"] for package in packages}
    assert generate_sbom.CPYTHON_SPDX_ID in package_ids
    assert generate_sbom.PYINSTALLER_SPDX_ID in package_ids
    python_packages = {
        canonical_name: package
        for package in packages
        if str(package["SPDXID"]).startswith("SPDXRef-Package-pypi-")
        for canonical_name in [str(package["name"]).lower()]
    }
    assert {
        name: python_packages[name]["versionInfo"] for name in frozen_components
    } == {
        "packaging": "26.3",
        "pyinstaller-hooks-contrib": "2026.3",
        "setuptools": "81.0.0",
    }
    root_id = generate_sbom._python_spdx_id("lingshu-gate")
    contained_ids = {
        relationship["relatedSpdxElement"]
        for relationship in relationships
        if relationship["spdxElementId"] == root_id
        and relationship["relationshipType"] == "CONTAINS"
    }
    assert {
        generate_sbom._python_spdx_id(component.name) for component in frozen_components.values()
    } <= contained_ids


def test_build_host_mismatch_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("scripts.release.build_native.platform.system", lambda: "Linux")
    monkeypatch.setattr("scripts.release.build_native.platform.machine", lambda: "x86_64")

    with pytest.raises(RuntimeError, match="requires Darwin"):
        verify_build_host("macos-arm64")

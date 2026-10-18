from __future__ import annotations

import hashlib
import importlib
import json
import re
import shutil
import sys
import tarfile
from pathlib import Path
from urllib.parse import unquote, urlsplit

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
build_docker_bundle = importlib.import_module("scripts.release.build_docker_bundle")
common = importlib.import_module("scripts.release.common")


@pytest.fixture
def public_source(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    files = ["README.md", "docs/guide.md", "docs/diagram.asset", "examples/public.json",
             ".agents/skills/lingshu-gate-upload-build-start/SKILL.md"]
    for name in [*files, "LICENSE"]:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"public documentation\n")
    (root / "packaging").mkdir()
    (root / "packaging/public-documentation.json").write_text(
        json.dumps({"schema_version": 1, "files": files}), encoding="utf-8"
    )
    monkeypatch.setattr(common, "REPOSITORY_ROOT", root)
    monkeypatch.setattr(common, "REQUIRED_DOCUMENTATION_FILES", (root / "README.md",))
    monkeypatch.setattr(common, "REQUIRED_LEGAL_FILES", (root / "LICENSE",))
    return root


def test_public_documentation_ignores_unlisted_runtime_files_without_git(public_source: Path, tmp_path: Path) -> None:
    private = ["docs/local-credentials.json", "examples/.env",
               ".agents/skills/lingshu-gate-upload-build-start/local.txt"]
    for name in private:
        (public_source / name).write_text("private runtime value", encoding="utf-8")
    assert not (public_source / ".git").exists()
    common.validate_release_inputs()
    destination = tmp_path / "bundle"
    common.copy_release_documentation(destination)
    assert all(not (destination / name).exists() for name in private)
    assert (destination / "docs/diagram.asset").read_bytes() == b"public documentation\n"
    assert {p.relative_to(destination).as_posix() for p in destination.rglob("*") if p.is_file()} == set(
        json.loads((public_source / "packaging/public-documentation.json").read_text())["files"]
    )


@pytest.mark.parametrize("name", ["../outside", "/tmp/outside", "docs/../../outside", "docs\\outside",
                                 "docs/./guide.md", "docs/\x00outside", ".env"])
def test_public_documentation_refuses_invalid_or_unapproved_paths(
    public_source: Path, tmp_path: Path, name: str
) -> None:
    manifest = public_source / "packaging/public-documentation.json"
    manifest.write_text(json.dumps({"schema_version": 1, "files": ["README.md", name]}))
    with pytest.raises(RuntimeError):
        common.copy_release_documentation(tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()


@pytest.mark.parametrize("name", ["README.md", "docs", "docs/guide.md", ".agents",
                                 "packaging/public-documentation.json", "LICENSE"])
def test_public_documentation_refuses_root_ancestor_and_file_links(
    public_source: Path, tmp_path: Path, name: str
) -> None:
    original = public_source / name
    outside = tmp_path / "outside"
    original.rename(outside)
    try:
        original.symlink_to(outside, target_is_directory=outside.is_dir())
    except OSError:
        pytest.skip("symlinks are not available on this test host")
    with pytest.raises(RuntimeError, match="symlinks"):
        common.validate_release_inputs()


@pytest.mark.parametrize("files", [["docs/guide.md"], ["README.md", "README.md"], ["README.md", "docs/missing.md"]])
def test_public_documentation_refuses_missing_required_duplicate_or_unavailable_files(
    public_source: Path, tmp_path: Path, files: list[str]
) -> None:
    manifest = public_source / "packaging/public-documentation.json"
    manifest.write_text(json.dumps({"schema_version": 1, "files": files}))
    with pytest.raises(RuntimeError):
        common.copy_release_documentation(tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()


@pytest.mark.parametrize("package", ["native", "docker"])
def test_package_readmes_replace_repository_entry_and_relocate_both_languages(
    public_source: Path, tmp_path: Path, package: str
) -> None:
    templates = public_source / "packaging" / package
    templates.mkdir()
    for suffix in ("", ".zh-CN"):
        (templates / f"package-README{suffix}.md").write_text(
            f"# {package}{suffix} @VERSION@\n[Guide](../../docs/guide.md)\n", encoding="utf-8"
        )
    destination = tmp_path / "bundle"
    common.copy_release_documentation(destination)
    common.copy_package_readmes(destination, package=package, version="2.3.4-rc.1")
    for suffix in ("", ".zh-CN"):
        assert (destination / f"README{suffix}.md").read_text(encoding="utf-8") == (
            f"# {package}{suffix} 2.3.4-rc.1\n[Guide](docs/guide.md)\n"
        )
    assert (destination / "docs/guide.md").is_file()


@pytest.mark.parametrize("package,version", [("../native", "1.2.3"), ("other", "1.2.3"),
                                           ("native", "../1.2.3"), ("docker", "01.2.3")])
def test_package_readmes_reject_invalid_target_without_writes(
    public_source: Path, tmp_path: Path, package: str, version: str
) -> None:
    destination = tmp_path / "bundle"
    destination.mkdir()
    with pytest.raises(RuntimeError, match="Invalid package documentation"):
        common.copy_package_readmes(destination, package=package, version=version)
    assert list(destination.iterdir()) == []


@pytest.mark.parametrize("failure", ["missing_translation", "invalid_translation", "linked_translation", "linked_ancestor"])
def test_package_readmes_resolve_and_read_both_templates_before_overwriting(
    public_source: Path, tmp_path: Path, failure: str
) -> None:
    templates = public_source / "packaging/native"
    templates.mkdir()
    (templates / "package-README.md").write_text("native @VERSION@", encoding="utf-8")
    translated = templates / "package-README.zh-CN.md"
    if failure == "invalid_translation":
        translated.write_bytes(b"\xff")
    elif failure != "missing_translation":
        translated.write_text("native zh-CN @VERSION@", encoding="utf-8")
    if failure in {"linked_translation", "linked_ancestor"}:
        original = translated if failure == "linked_translation" else templates
        outside = tmp_path / "outside"
        original.rename(outside)
        try:
            original.symlink_to(outside, target_is_directory=outside.is_dir())
        except OSError:
            pytest.skip("symlinks are not available on this test host")
    destination = tmp_path / "bundle"
    destination.mkdir()
    for suffix in ("", ".zh-CN"):
        (destination / f"README{suffix}.md").write_text("original entry", encoding="utf-8")
    with pytest.raises((RuntimeError, UnicodeError)):
        common.copy_package_readmes(destination, package="native", version="1.2.3")
    assert all(path.read_text(encoding="utf-8") == "original entry" for path in destination.iterdir())


def test_real_compose_archive_contains_rendered_onboarding_and_resolving_links(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Exercise real staging, rendering, inventory and tar; dependency SBOM has separate tests."""
    repository = common.REPOSITORY_ROOT
    source = tmp_path / "source"
    manifest = json.loads((repository / "packaging/public-documentation.json").read_text(encoding="utf-8"))
    names = set(manifest["files"]) | {
        "packaging/public-documentation.json", "compose.prod.yaml", "src/lingshu_gate/_version.py",
        *(path.relative_to(repository).as_posix() for path in common.REQUIRED_LEGAL_FILES),
        *(path.relative_to(repository).as_posix() for path in (repository / "packaging/docker").iterdir() if path.is_file()),
    }
    for name in names:
        destination = source / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(repository / name, destination)
    legal_files = tuple(source / path.relative_to(repository) for path in common.REQUIRED_LEGAL_FILES)
    documentation_files = tuple(source / path.relative_to(repository) for path in common.REQUIRED_DOCUMENTATION_FILES)
    monkeypatch.setattr(common, "REPOSITORY_ROOT", source)
    monkeypatch.setattr(common, "VERSION_FILE", source / "src/lingshu_gate/_version.py")
    monkeypatch.setattr(common, "REQUIRED_LEGAL_FILES", legal_files)
    monkeypatch.setattr(common, "REQUIRED_DOCUMENTATION_FILES", documentation_files)
    monkeypatch.setattr(build_docker_bundle, "REPOSITORY_ROOT", source)
    monkeypatch.setattr(build_docker_bundle, "REQUIRED_LEGAL_FILES", legal_files)
    # Package entry points must work independently of the test host's installed dependencies.
    monkeypatch.setattr(build_docker_bundle, "collect_components", lambda *_: {"lingshu-gate": {}})
    monkeypatch.setattr(build_docker_bundle, "collect_npm_components", lambda: ({}, {}))
    monkeypatch.setattr(build_docker_bundle, "stage_third_party_licenses", lambda path, **_: path.mkdir(parents=True))
    monkeypatch.setattr(build_docker_bundle, "build_spdx_document", lambda *_, **__: {"spdxVersion": "SPDX-2.3"})
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "0")
    version = common.read_version()
    archive = build_docker_bundle.build(tmp_path / "dist")
    extracted = tmp_path / "extracted"
    with tarfile.open(archive, "r:gz") as package:
        package.extractall(extracted, filter="data")
    bundle = extracted / f"lingshu-gate-v{version}-docker-compose"
    inventory = {entry["path"]: entry for entry in json.loads((bundle / "BUILD-INFO.json").read_bytes())["files"]}
    entries = ["README.md", "README.zh-CN.md", "DEPLOYMENT.md", "DEPLOYMENT.zh-CN.md",
               "compose.quickstart.yaml", ".env.quickstart.example", "examples/compose.demo.yaml",
               "docs/getting-started.md", "docs/zh-CN/getting-started.md",
               "docs/first-call.md", "docs/zh-CN/first-call.md"]
    for name in entries:
        path = bundle / name
        assert path.is_file(), name
        data = path.read_bytes()
        assert b"@VERSION@" not in data, name
        assert inventory[name]["sha256"] == hashlib.sha256(data).hexdigest(), name
        if path.suffix == ".md":
            for target in re.findall(r"\]\(([^\s)]+)\)", data.decode("utf-8")):
                link = urlsplit(target)
                if link.scheme or link.netloc or not link.path:
                    continue
                resolved = (path.parent / unquote(link.path)).resolve()
                assert resolved.is_relative_to(bundle.resolve()) and resolved.exists(), (name, target)
    for suffix in ("", ".zh-CN"):
        rendered = (repository / f"packaging/docker/package-README{suffix}.md").read_text(encoding="utf-8")
        rendered = rendered.replace("@VERSION@", version).replace("](../../", "](")
        assert (bundle / f"README{suffix}.md").read_text(encoding="utf-8") == rendered
        assert rendered != (repository / f"README{suffix}.md").read_text(encoding="utf-8")
    assert f"LINGSHU_GATE_IMAGE=ghcr.io/zhigege666/lingshu-gate:{version}" in (
        bundle / ".env.quickstart.example"
    ).read_text(encoding="utf-8")
    core = yaml.safe_load((bundle / "compose.quickstart.yaml").read_text(encoding="utf-8"))["services"]["core"]
    assert "build" not in core and core["ports"] == ["127.0.0.1:${LINGSHU_GATE_HTTP_PORT:-8000}:8000"]
    assert core["read_only"] is True and core["user"] == "10001:10001"
    assert core["environment"]["LINGSHU_GATE_AUTH_ENABLED"] == "true"
    assert core["environment"]["LINGSHU_GATE_AUTH_COOKIE_SECURE"] == "false"
    demo = yaml.safe_load((bundle / "examples/compose.demo.yaml").read_text(encoding="utf-8"))["services"]["demo"]
    assert demo["depends_on"]["core"]["condition"] == "service_healthy"
    assert demo["network_mode"] == "service:core" and "ports" not in demo
    assert demo["healthcheck"]["test"][0] == "CMD"
    for name in ("docs/images/console/en-US/v0.5.0-discovery.png", "docs/images/console/zh-CN/v0.5.0-discovery.png"):
        assert (bundle / name).read_bytes() == (repository / name).read_bytes()

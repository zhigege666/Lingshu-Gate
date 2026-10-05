from __future__ import annotations

import os
import base64
import csv
import hashlib
import io
import shutil
import subprocess
import sys
import sysconfig
import tarfile
import textwrap
import zipfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def _project(root: Path) -> Path:
    project = root / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(textwrap.dedent('''\
        [build-system]
        requires = ["setuptools==81.0.0"]
        build-backend = "setuptools.build_meta"
        [project]
        name = "lingshu-gate"
        version = "0.4.4"
        [tool.setuptools.packages.find]
        where = ["src"]
        [tool.setuptools.package-dir]
        "" = "src"
        scripts = "scripts"
        [tool.setuptools.cmdclass]
        build_py = "scripts.release.wheel_build.FreshBuildPy"
        bdist_wheel = "scripts.release.wheel_build.FreshBdistWheel"
        [tool.setuptools.package-data]
        lingshu_gate = ["static/console/**/*", "static/oauth/**/*"]
    '''))
    scripts = project / "scripts" / "release"
    scripts.mkdir(parents=True)
    for name in ("__init__.py", "wheel_build.py"):
        shutil.copyfile(REPOSITORY_ROOT / "scripts" / "release" / name, scripts / name)
    shutil.copyfile(REPOSITORY_ROOT / "MANIFEST.in", project / "MANIFEST.in")
    package = project / "src" / "lingshu_gate"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    for scope, entry in (("console", "index.html"), ("oauth", "oauth.html")):
        static = package / "static" / scope
        (static / "assets").mkdir(parents=True)
        (static / entry).write_text("synthetic entry")
        (static / "assets" / "current.js").write_text("synthetic current bundle")
    return project


def _build(project: Path, *, sdist: bool = False, successful: bool = True,
           config_settings: tuple[str, ...] = (), output_name: str = "output") -> Path | subprocess.CompletedProcess[str]:
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is required to exercise the standard isolated wheel build")
    output = project.parent / output_name
    result = subprocess.run(
        [uv, "build", "--sdist" if sdist else "--wheel", "--offline", "--python", sys.executable,
         "--out-dir", str(output), *("--config-setting=" + value for value in config_settings)],
        cwd=project, capture_output=True, text=True, timeout=30,
    )
    if not successful:
        assert result.returncode != 0
        assert not list(output.glob("*.whl"))
        return result
    assert result.returncode == 0, result.stdout + result.stderr
    return next(output.glob("*.tar.gz" if sdist else "*.whl"))


def _assert_assets(wheel: Path, package: Path) -> None:
    expected = {
        "lingshu_gate/" + path.relative_to(package).as_posix(): path.read_bytes()
        for path in (package / "static").rglob("*") if path.is_file()
    }
    with zipfile.ZipFile(wheel) as archive:
        actual = {name: archive.read(name) for name in archive.namelist() if name.startswith("lingshu_gate/static/")}
        assert actual == expected
        assert len(archive.namelist()) == len(set(archive.namelist()))
        record = next(name for name in archive.namelist() if name.endswith(".dist-info/RECORD"))
        rows = list(csv.reader(io.StringIO(archive.read(record).decode())))
        assert len(rows) == len(archive.namelist())
        assert {row[0] for row in rows} == set(archive.namelist())
        for name, digest, size in rows:
            if name == record:
                assert (digest, size) == ("", "")
            else:
                payload = archive.read(name)
                encoded = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).decode().rstrip("=")
                assert (digest, size) == ("sha256=" + encoded, str(len(payload)))


def test_standard_repeated_build_does_not_reuse_or_delete_old_build_lib(tmp_path: Path) -> None:
    project = _project(tmp_path)
    package = project / "src" / "lingshu_gate"
    first = _build(project)
    assert isinstance(first, Path)
    _assert_assets(first, package)
    cache = project / "build" / "lib" / "lingshu_gate"
    for scope in ("console", "oauth"):
        old = cache / "static" / scope / "assets" / "previous.js"
        old.parent.mkdir(parents=True)
        old.write_text("synthetic stale bundle")
        original = package / "static" / scope / "assets" / "current.js"
        original.rename(original.with_name("replacement.js"))
    removed = cache / "removed_module.py"
    removed.write_text("synthetic removed module")
    sources = project / "src" / "lingshu_gate.egg-info" / "SOURCES.txt"
    with sources.open("a") as output:
        output.write("src/lingshu_gate/static/console/assets/previous.js\n")
    second = _build(project)
    assert isinstance(second, Path)
    _assert_assets(second, package)
    with zipfile.ZipFile(second) as archive:
        assert "lingshu_gate/removed_module.py" not in archive.namelist()
    assert removed.read_text() == "synthetic removed module"
    assert (cache / "static/console/assets/previous.js").read_text() == "synthetic stale bundle"
    assert not list((project / "build").glob("lingshu-gate-wheel-*"))


def test_current_hash_wins_even_when_cache_file_is_newer(tmp_path: Path) -> None:
    project = _project(tmp_path)
    package = project / "src" / "lingshu_gate"
    stale = project / "build/lib/lingshu_gate/static/console/assets/current.js"
    stale.parent.mkdir(parents=True)
    stale.write_text("synthetic wrong bytes")
    os.utime(stale, (2_000_000_000, 2_000_000_000))
    wheel = _build(project)
    assert isinstance(wheel, Path)
    _assert_assets(wheel, package)
    assert stale.read_text() == "synthetic wrong bytes"


def test_sdist_keeps_build_hook_and_rebuilds_fresh_wheel(tmp_path: Path) -> None:
    project = _project(tmp_path)
    source = _build(project, sdist=True)
    assert isinstance(source, Path)
    extracted = tmp_path / "extracted"
    extracted.mkdir()
    with tarfile.open(source) as archive:
        assert any(member.name.endswith("scripts/release/wheel_build.py") for member in archive.getmembers())
        archive.extractall(extracted, filter="data")
    restored = next(extracted.iterdir())
    wheel = _build(restored)
    assert isinstance(wheel, Path)
    _assert_assets(wheel, restored / "src/lingshu_gate")


def test_source_symlink_refuses_build_without_reading_target(tmp_path: Path) -> None:
    project = _project(tmp_path)
    private = tmp_path / "private.txt"
    private.write_text("synthetic-never-copy")
    link = project / "src/lingshu_gate/static/console/assets/private.js"
    try:
        link.symlink_to(private)
    except OSError:
        pytest.skip("symlinks are not available on this test host")
    result = _build(project, successful=False)
    assert isinstance(result, subprocess.CompletedProcess)
    assert "Wheel static assets contain a symlink" in result.stderr
    assert "synthetic-never-copy" not in result.stdout + result.stderr


@pytest.mark.parametrize("relative", ["src", "src/lingshu_gate", "src/lingshu_gate/static"])
def test_source_ancestor_symlink_refuses_build(tmp_path: Path, relative: str) -> None:
    project = _project(tmp_path)
    original = project / relative
    outside = tmp_path / "outside"
    original.rename(outside)
    try:
        original.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not available on this test host")
    result = _build(project, successful=False)
    assert isinstance(result, subprocess.CompletedProcess)
    assert "Wheel static assets contain a symlink" in result.stderr
    assert outside.is_dir()


def test_staging_parent_symlink_refuses_build_and_preserves_target(tmp_path: Path) -> None:
    project = _project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "sentinel").write_text("synthetic preserved")
    try:
        (project / "build").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not available on this test host")
    result = _build(project, successful=False)
    assert isinstance(result, subprocess.CompletedProcess)
    assert "Wheel staging requires a regular project build directory" in result.stderr
    assert (outside / "sentinel").read_text() == "synthetic preserved"


@pytest.mark.parametrize("relative", ["console/index.html", "oauth/oauth.html"])
def test_missing_frontend_refuses_noneditable_wheel(tmp_path: Path, relative: str) -> None:
    project = _project(tmp_path)
    (project / "src/lingshu_gate/static" / relative).unlink()
    result = _build(project, successful=False)
    assert isinstance(result, subprocess.CompletedProcess)
    assert "Wheel Console/OAuth assets are missing" in result.stderr


def test_standard_editable_install_works_before_frontend_build(tmp_path: Path) -> None:
    project = _project(tmp_path)
    shutil.rmtree(project / "src/lingshu_gate/static")
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is required to exercise the standard editable build")
    environment = tmp_path / "editable-env"
    prepared = subprocess.run(
        [uv, "venv", "--offline", "--python", sys.executable, str(environment)],
        capture_output=True, text=True, timeout=30,
    )
    assert prepared.returncode == 0, prepared.stdout + prepared.stderr
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    installed = subprocess.run(
        [uv, "pip", "install", "--offline", "--python", str(python), "--no-deps", "--editable", str(project)],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    imported = subprocess.run(
        [str(python), "-I", "-c", "import lingshu_gate; print(lingshu_gate.__file__)"],
        cwd=tmp_path, capture_output=True, text=True, timeout=30,
    )
    assert imported.returncode == 0, imported.stdout + imported.stderr
    assert Path(imported.stdout.strip()).resolve() == project / "src/lingshu_gate/__init__.py"
    assert not (project / "build").exists()


@pytest.mark.parametrize("fault", ["missing", "extra", "changed"])
@pytest.mark.parametrize("scope", ["console", "oauth"])
def test_static_snapshot_validation_rejects_backend_copy_faults(tmp_path: Path, fault: str, scope: str) -> None:
    project = _project(tmp_path)
    module = project / "scripts/release/wheel_build.py"
    # Inject only a synthetic build-copy fault after the real superclass copy.
    # The real validation must prevent that altered payload becoming a wheel.
    operations = {
        "missing": '(Path(self.build_lib) / "lingshu_gate/static/console/assets/current.js").unlink()',
        "extra": '(Path(self.build_lib) / "lingshu_gate/static/console/assets/previous.js").write_text("synthetic extra")',
        "changed": '(Path(self.build_lib) / "lingshu_gate/static/console/assets/current.js").write_text("synthetic changed")',
    }
    operation = operations[fault].replace("static/console/", "static/" + scope + "/")
    code = module.read_text().replace("            super().run()\n            _verify_static_inventory", "            super().run()\n            " + operation + "\n            _verify_static_inventory")
    assert code != module.read_text()
    module.write_text(code)
    result = _build(project, successful=False)
    assert isinstance(result, subprocess.CompletedProcess)
    assert "Wheel static assets do not match the source snapshot" in result.stderr
    assert not list((project / "build").glob("lingshu-gate-wheel-*"))


def test_source_mutation_during_build_refuses_wheel(tmp_path: Path) -> None:
    project = _project(tmp_path)
    module = project / "scripts/release/wheel_build.py"
    code = module.read_text().replace(
        "            super().run()\n            _verify_static_inventory",
        '            super().run()\n            (source / "static/console/assets/current.js").write_text("synthetic mutation")\n'
        "            _verify_static_inventory",
    )
    assert code != module.read_text()
    module.write_text(code)
    result = _build(project, successful=False)
    assert isinstance(result, subprocess.CompletedProcess)
    assert "Wheel static source changed while building" in result.stderr
    assert not list((project / "build").glob("lingshu-gate-wheel-*"))


@pytest.mark.parametrize("custom", [False, True])
def test_wheel_ignores_and_preserves_previous_install_tree(tmp_path: Path, custom: bool) -> None:
    project = _project(tmp_path)
    if custom:
        stale_root = tmp_path / "user-selected-install"
        settings = ("--build-option=--bdist-dir=" + str(stale_root),)
    else:
        # Match setuptools' default on this host, including Windows/macOS.
        stale_root = project / "build" / ("bdist." + sysconfig.get_platform()) / "wheel"
        settings = ()
    stale = stale_root / "lingshu_gate"
    for scope in ("console", "oauth"):
        asset = stale / "static" / scope / "assets" / "previous-A.js"
        asset.parent.mkdir(parents=True)
        asset.write_text("synthetic old installed hash A")
    user_file = stale / "user_data.txt"
    user_file.write_text("synthetic preserved user data")
    wheel = _build(project, config_settings=settings)
    assert isinstance(wheel, Path)
    _assert_assets(wheel, project / "src/lingshu_gate")
    with zipfile.ZipFile(wheel) as archive:
        assert "lingshu_gate/user_data.txt" not in archive.namelist()
    assert user_file.read_text() == "synthetic preserved user data"
    for scope in ("console", "oauth"):
        assert (stale / "static" / scope / "assets/previous-A.js").read_text() == "synthetic old installed hash A"
    assert not list((project / "build").glob("lingshu-gate-wheel-*"))


def test_skip_build_cannot_bypass_clean_staging_checks(tmp_path: Path) -> None:
    project = _project(tmp_path)
    result = _build(project, successful=False, config_settings=("--build-option=--skip-build",))
    assert isinstance(result, subprocess.CompletedProcess)
    assert "cannot skip the fresh build" in result.stderr


@pytest.mark.parametrize("scope", ["console", "oauth"])
@pytest.mark.parametrize("fault", ["missing", "extra", "changed"])
def test_installed_payload_is_checked_before_wheel_archive(tmp_path: Path, scope: str, fault: str) -> None:
    project = _project(tmp_path)
    module = project / "scripts/release/wheel_build.py"
    asset = f'Path(self.bdist_dir) / "lingshu_gate/static/{scope}/assets/current.js"'
    operations = {
        "missing": f"({asset}).unlink()",
        "extra": f'({asset}).with_name("unexpected.js").write_text("synthetic extra")',
        "changed": f'({asset}).write_text("synthetic changed")',
    }
    marker = '            _verify_static_inventory(Path(self.bdist_dir)'
    code = module.read_text().replace(marker, "            " + operations[fault] + "\n" + marker)
    assert code != module.read_text()
    module.write_text(code)
    result = _build(project, successful=False)
    assert isinstance(result, subprocess.CompletedProcess)
    assert "Wheel static assets do not match the source snapshot" in result.stderr
    assert not list((project / "build").glob("lingshu-gate-wheel-*"))


def test_unknown_static_scope_refuses_build(tmp_path: Path) -> None:
    project = _project(tmp_path)
    extra = project / "src/lingshu_gate/static/unexpected"
    extra.mkdir()
    (extra / "private.txt").write_text("synthetic-never-copy")
    result = _build(project, successful=False)
    assert isinstance(result, subprocess.CompletedProcess)
    assert "unexpected entry outside Console/OAuth" in result.stderr
    assert "synthetic-never-copy" not in result.stdout + result.stderr


def test_staging_parent_file_is_preserved(tmp_path: Path) -> None:
    project = _project(tmp_path)
    existing = project / "build"
    existing.write_text("synthetic user file")
    result = _build(project, successful=False)
    assert isinstance(result, subprocess.CompletedProcess)
    assert "regular project build directory" in result.stderr
    assert existing.read_text() == "synthetic user file"


@pytest.mark.skipif(os.name != "posix", reason="POSIX special file boundary")
def test_static_fifo_refuses_build_without_opening_it(tmp_path: Path) -> None:
    project = _project(tmp_path)
    os.mkfifo(project / "src/lingshu_gate/static/oauth/assets/special.js")
    result = _build(project, successful=False)
    assert isinstance(result, subprocess.CompletedProcess)
    assert "special entry" in result.stderr


@pytest.mark.parametrize("fault", ["missing", "extra", "changed", "record", "record_hash", "record_size", "path"])
def test_final_archive_validation_rejects_corruption(tmp_path: Path, fault: str) -> None:
    project = _project(tmp_path)
    module = project / "scripts/release/wheel_build.py"
    operations = {
        "missing": 'files.pop("lingshu_gate/static/oauth/assets/current.js")',
        "extra": 'files["lingshu_gate/static/console/assets/previous-A.js"] = b"synthetic extra"',
        "changed": 'files["lingshu_gate/static/oauth/assets/current.js"] = b"synthetic changed"',
        "record": 'files[next(name for name in files if name.endswith(".dist-info/RECORD"))] = b"invalid,sha256=bad,0\\n"',
        "record_hash": 'key = next(name for name in files if name.endswith(".dist-info/RECORD")); '
                       'files[key] = files[key].replace(b"sha256=", b"sha256=bad", 1)',
        "record_size": 'key = next(name for name in files if name.endswith(".dist-info/RECORD")); '
                       'rows = list(csv.reader(io.StringIO(files[key].decode()))); rows[0][2] = str(int(rows[0][2]) + 1); '
                       'files[key] = ("\\n".join(",".join(row) for row in rows) + "\\n").encode()',
        "path": 'files["lingshu_gate/static/console/../../escape.js"] = b"synthetic escape"',
    }
    marker = "            _verify_wheel_archive(wheel, self._static_snapshot)"
    injected = (
        "            with ZipFile(wheel) as archive:\n"
        "                files = {name: archive.read(name) for name in archive.namelist()}\n"
        "            " + operations[fault] + "\n"
        '            with ZipFile(wheel, "w") as archive:\n'
        "                for name, payload in files.items():\n"
        "                    archive.writestr(name, payload)\n"
    )
    code = module.read_text().replace(marker, injected + marker)
    assert code != module.read_text()
    module.write_text(code)
    result = _build(project, successful=False)
    assert isinstance(result, subprocess.CompletedProcess)
    assert ("Wheel archive" in result.stderr or "Wheel RECORD" in result.stderr)
    assert not list((project / "build").glob("lingshu-gate-wheel-*"))


def test_failed_archive_then_retry_has_no_old_resources(tmp_path: Path) -> None:
    project = _project(tmp_path)
    module = project / "scripts/release/wheel_build.py"
    original = module.read_text()
    marker = "            _verify_wheel_archive(wheel, self._static_snapshot)"
    injection = (
        '            with ZipFile(wheel, "a") as archive:\n'
        '                archive.writestr("lingshu_gate/static/oauth/assets/previous-A.js", b"synthetic old A")\n'
    )
    module.write_text(original.replace(marker, injection + marker))
    failed = _build(project, successful=False)
    assert isinstance(failed, subprocess.CompletedProcess)
    assert "Wheel archive static assets do not match" in failed.stderr
    assert not list((project / "build").glob("lingshu-gate-wheel-*"))
    module.write_text(original)
    wheel = _build(project)
    assert isinstance(wheel, Path)
    _assert_assets(wheel, project / "src/lingshu_gate")
    assert not list((project / "build").glob("lingshu-gate-wheel-*"))


def test_concurrent_wheel_builds_have_private_copy_install_and_archive_trees(tmp_path: Path) -> None:
    project = _project(tmp_path)
    old = project / "build/lib/lingshu_gate/static/console/assets/previous-A.js"
    old.parent.mkdir(parents=True)
    old.write_text("synthetic preserved old A")
    with ThreadPoolExecutor(max_workers=2) as executor:
        jobs = [executor.submit(_build, project, output_name=name) for name in ("first-output", "second-output")]
        wheels = [job.result() for job in jobs]
    for wheel in wheels:
        assert isinstance(wheel, Path)
        _assert_assets(wheel, project / "src/lingshu_gate")
    assert old.read_text() == "synthetic preserved old A"
    assert not list((project / "build").glob("lingshu-gate-wheel-*"))


def test_output_replacement_preserves_a_symlinks_user_data_target(tmp_path: Path) -> None:
    project = _project(tmp_path)
    output = tmp_path / "output"
    output.mkdir()
    user_data = tmp_path / "user-data.txt"
    user_data.write_text("synthetic preserved output target")
    destination = output / "lingshu_gate-0.4.4-py3-none-any.whl"
    try:
        destination.symlink_to(user_data)
    except OSError:
        pytest.skip("symlinks are not available on this test host")
    wheel = _build(project)
    assert isinstance(wheel, Path)
    _assert_assets(wheel, project / "src/lingshu_gate")
    assert not destination.is_symlink()
    assert user_data.read_text() == "synthetic preserved output target"
    assert not list(output.glob(".lingshu-gate-wheel-*"))

"""Build one native, directly runnable Lingshu Gate release archive."""

from __future__ import annotations

import argparse
import importlib.metadata
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

from scripts.release.common import (
    REQUIRED_DOCUMENTATION_FILES,
    REQUIRED_LEGAL_FILES,
    REPOSITORY_ROOT,
    build_metadata,
    copy_release_file,
    create_tar_gz,
    create_zip,
    python_executable_name,
    read_version,
    reset_directory,
    source_date_epoch,
    validate_release_inputs,
    write_checksums,
    write_json,
)
from scripts.release.frozen_inventory import frozen_distribution_names
from scripts.release.generate_sbom import build_spdx_document, collect_npm_components
from scripts.release.license_inventory import stage_third_party_licenses

TARGETS = {
    "linux-x86_64": ("Linux", {"x86_64", "amd64"}, "tar.gz"),
    "linux-aarch64": ("Linux", {"aarch64", "arm64"}, "tar.gz"),
    "windows-x86_64": ("Windows", {"amd64", "x86_64"}, "zip"),
    "macos-x86_64": ("Darwin", {"x86_64", "amd64"}, "tar.gz"),
    "macos-arm64": ("Darwin", {"arm64", "aarch64"}, "tar.gz"),
}


def _command_version(*command: str) -> str:
    executable = shutil.which(command[0])
    if executable is None:
        return "unavailable"
    try:
        result = subprocess.run(
            [executable, *command[1:]],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"
    if result.returncode != 0:
        return "unavailable"
    return (result.stdout or result.stderr).strip().splitlines()[0]


def _packager_versions() -> dict[str, str]:
    tools = {
        "node": _command_version("node", "--version"),
        "npm": _command_version("npm", "--version"),
        "uv": _command_version("uv", "--version"),
    }
    for distribution_name in ("altgraph", "packaging", "pyinstaller", "pyinstaller-hooks-contrib"):
        tools[distribution_name] = importlib.metadata.version(distribution_name)
    return tools


def _cpython_license() -> Path:
    license_path = REPOSITORY_ROOT / "packaging" / "licenses" / "CPython-3.13.15-LICENSE.txt"
    if not license_path.is_file():
        raise RuntimeError(f"Vendored CPython license file is missing: {license_path}")
    return license_path


def _distribution_file(distribution_name: str, suffix: str) -> Path:
    distribution = importlib.metadata.distribution(distribution_name)
    for relative in distribution.files or ():
        if relative.as_posix().endswith(suffix):
            path = Path(distribution.locate_file(relative))
            if path.is_file():
                return path
    raise RuntimeError(f"{distribution_name} release file is missing: {suffix}")


def verify_build_host(target: str) -> None:
    expected_system, expected_machines, _archive_type = TARGETS[target]
    actual_system = platform.system()
    actual_machine = platform.machine().lower()
    if actual_system != expected_system or actual_machine not in expected_machines:
        raise RuntimeError(
            f"Target {target} requires {expected_system}/{sorted(expected_machines)}, "
            f"but this host is {actual_system}/{actual_machine}"
        )


def _run_pyinstaller(build_root: Path) -> tuple[Path, Path]:
    dist_path = build_root / "pyinstaller-dist"
    work_path = build_root / "pyinstaller-work"
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        str(dist_path),
        "--workpath",
        str(work_path),
        str(REPOSITORY_ROOT / "packaging" / "lingshu-gate.spec"),
    ]
    subprocess.run(command, cwd=REPOSITORY_ROOT, check=True)
    frozen_root = dist_path / "lingshu-gate"
    if not frozen_root.is_dir():
        raise RuntimeError(f"PyInstaller output is missing: {frozen_root}")
    analysis_toc = work_path / "lingshu-gate" / "Analysis-00.toc"
    if not analysis_toc.is_file():
        raise RuntimeError(f"PyInstaller analysis inventory is missing: {analysis_toc}")
    return frozen_root, analysis_toc


def _build_console() -> None:
    """Recreate Console assets from the lockfile before freezing any native bundle."""

    npm = shutil.which("npm")
    if npm is None:
        raise RuntimeError("npm is required to build fresh Console assets for a native release")
    subprocess.run(
        [npm, "ci", "--no-audit", "--no-fund"],
        cwd=REPOSITORY_ROOT / "web",
        check=True,
    )
    subprocess.run(
        [npm, "run", "build"],
        cwd=REPOSITORY_ROOT / "web",
        check=True,
    )


def _stage_bundle(
    *,
    target: str,
    version: str,
    build_root: Path,
    frozen_root: Path,
    frozen_distributions: set[str],
) -> Path:
    package_name = f"lingshu-gate-v{version}-{target}"
    stage_parent = build_root / "bundle"
    stage_parent.mkdir(parents=True, exist_ok=True)
    stage_root = stage_parent / package_name
    shutil.copytree(frozen_root, stage_root, symlinks=True)

    launcher_name = "start.cmd" if target.startswith("windows-") else "start.sh"
    copy_release_file(REPOSITORY_ROOT / "packaging" / "native" / launcher_name, stage_root)
    copy_release_file(
        REPOSITORY_ROOT / "packaging" / "native" / "lingshu-gate.env.example",
        stage_root,
        destination_name="lingshu-gate.env.example",
    )
    for required in (*REQUIRED_LEGAL_FILES, *REQUIRED_DOCUMENTATION_FILES):
        copy_release_file(required, stage_root)
    licenses_dir = stage_root / "licenses"
    licenses_dir.mkdir()
    copy_release_file(_cpython_license(), licenses_dir, destination_name="CPython-LICENSE.txt")
    copy_release_file(
        _distribution_file("pyinstaller", "/licenses/COPYING.txt"),
        licenses_dir,
        destination_name="PyInstaller-COPYING.txt",
    )
    npm_components, _npm_roots = collect_npm_components()
    stage_third_party_licenses(
        licenses_dir / "third-party",
        frozen_distributions=frozen_distributions,
        npm_components=npm_components,
    )

    for directory in (stage_root / "data", stage_root / "config" / "mcp.d", stage_root / "workspace"):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / ".keep").write_text("", encoding="utf-8")

    executable = stage_root / python_executable_name(target)
    if not executable.is_file():
        raise RuntimeError(f"Frozen executable is missing: {executable}")
    subprocess.run([str(executable), "--version"], cwd=stage_root, check=True, timeout=30)

    write_json(
        stage_root / "SBOM.spdx.json",
        build_spdx_document(
            "lingshu-gate",
            target=target,
            frozen_runtime=True,
            frozen_distributions=frozen_distributions,
        ),
    )
    metadata = build_metadata(
        root=stage_root,
        target=target,
        version=version,
        epoch=source_date_epoch(),
        tools=_packager_versions(),
    )
    write_json(stage_root / "BUILD-INFO.json", metadata)
    return stage_root


def build(target: str, output_dir: Path) -> Path:
    validate_release_inputs()
    verify_build_host(target)
    version = read_version()
    expected_python = os.environ.get("LINGSHU_GATE_RELEASE_PYTHON_VERSION", "3.13.15")
    actual_python = platform.python_version()
    if actual_python != expected_python:
        raise RuntimeError(f"CPython {expected_python} is required, but {actual_python} is running")
    expected_pyinstaller = os.environ.get("LINGSHU_GATE_RELEASE_PYINSTALLER_VERSION", "6.22.2")
    actual_pyinstaller = importlib.metadata.version("pyinstaller")
    if actual_pyinstaller != expected_pyinstaller:
        raise RuntimeError(
            f"PyInstaller {expected_pyinstaller} is required, but {actual_pyinstaller} is installed"
        )

    release_build_root = REPOSITORY_ROOT / "build" / "release"
    release_build_root.mkdir(parents=True, exist_ok=True)
    build_root = release_build_root / target
    reset_directory(build_root, allowed_parent=release_build_root)
    output_dir.mkdir(parents=True, exist_ok=True)

    _build_console()
    frozen_root, analysis_toc = _run_pyinstaller(build_root)
    frozen_distributions = frozen_distribution_names(analysis_toc)
    stage_root = _stage_bundle(
        target=target,
        version=version,
        build_root=build_root,
        frozen_root=frozen_root,
        frozen_distributions=frozen_distributions,
    )
    archive_type = TARGETS[target][2]
    if archive_type == "zip":
        archive = output_dir / f"{stage_root.name}.zip"
        create_zip(stage_root, archive, epoch=source_date_epoch())
    else:
        archive = output_dir / f"{stage_root.name}.tar.gz"
        create_tar_gz(stage_root, archive, epoch=source_date_epoch())
    write_checksums(output_dir, [archive])
    return archive


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", choices=sorted(TARGETS), required=True)
    parser.add_argument("--output-dir", type=Path, default=REPOSITORY_ROOT / "dist" / "release")
    args = parser.parse_args()
    archive = build(args.target, args.output_dir.resolve())
    print(archive)


if __name__ == "__main__":
    main()

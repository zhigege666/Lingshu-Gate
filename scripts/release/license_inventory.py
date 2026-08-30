"""Stage complete third-party license texts for binary release bundles."""

from __future__ import annotations

import hashlib
import importlib.metadata
import re
import shutil
from pathlib import Path

from packaging.utils import canonicalize_name

from scripts.release.common import REPOSITORY_ROOT, write_json
from scripts.release.generate_sbom import NpmComponent

LEGAL_FILE_PATTERN = re.compile(r"^(?:licen[cs]e|copying|copyright|notice)(?:[._-].*)?$", re.IGNORECASE)
NPM_OVERRIDE_ROOT = REPOSITORY_ROOT / "packaging" / "licenses" / "npm"


def _safe_relative(path: Path) -> Path:
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeError(f"Unsafe license path: {path}")
    return path


def _is_python_license_file(relative_path: Path) -> bool:
    if LEGAL_FILE_PATTERN.fullmatch(relative_path.name):
        return True
    parts = tuple(part.casefold() for part in relative_path.parts)
    return any(part.endswith(".dist-info") and parts[index + 1 : index + 2] == ("licenses",) for index, part in enumerate(parts))


def _python_license_files(distribution_name: str) -> tuple[str, list[tuple[Path, Path]]]:
    distribution = importlib.metadata.distribution(distribution_name)
    canonical_name = canonicalize_name(distribution.metadata.get("Name", distribution_name))
    files: list[tuple[Path, Path]] = []
    for relative in distribution.files or ():
        raw_path = Path(relative.as_posix())
        if raw_path.is_absolute() or any(part in {"", ".", ".."} for part in raw_path.parts):
            if _is_python_license_file(raw_path):
                raise RuntimeError(f"Python distribution contains an unsafe license path: {raw_path}")
            continue
        relative_path = _safe_relative(raw_path)
        if not _is_python_license_file(relative_path):
            continue
        source = Path(distribution.locate_file(relative))
        if source.is_file():
            files.append((relative_path, source))
    if not files:
        raise RuntimeError(f"Python distribution has no bundled license text: {canonical_name}")
    return distribution.version, sorted(files, key=lambda item: item[0].as_posix())


def _npm_license_files(component: NpmComponent) -> list[tuple[Path, Path]]:
    package_root = REPOSITORY_ROOT / "web" / component.package_path
    if not package_root.is_dir():
        raise RuntimeError(f"Installed npm package is missing for license collection: {component.package_path}")
    files: list[tuple[Path, Path]] = []
    for source in sorted(package_root.iterdir()):
        relative = source.relative_to(package_root)
        if not source.is_file():
            continue
        if LEGAL_FILE_PATTERN.fullmatch(source.name):
            files.append((_safe_relative(relative), source))
    if files:
        return files

    override_name = f"{re.sub(r'[^A-Za-z0-9._-]', '-', component.name)}-{component.version}"
    override_root = NPM_OVERRIDE_ROOT / override_name
    if override_root.is_dir():
        for source in sorted(override_root.rglob("*")):
            if source.is_file() and LEGAL_FILE_PATTERN.fullmatch(source.name):
                files.append((_safe_relative(source.relative_to(override_root)), source))
    if not files:
        raise RuntimeError(
            f"npm production package has no bundled or reviewed license text: "
            f"{component.name}@{component.version}"
        )
    return files


def stage_third_party_licenses(
    destination: Path,
    *,
    frozen_distributions: set[str],
    npm_components: dict[str, NpmComponent],
) -> list[dict[str, object]]:
    """Copy deterministic Python/npm license inventories and return their manifest."""

    destination.mkdir(parents=True, exist_ok=False)
    records: list[dict[str, object]] = []
    for distribution_name in sorted(frozen_distributions):
        version, license_files = _python_license_files(distribution_name)
        component_root = destination / "python" / f"{canonicalize_name(distribution_name)}-{version}"
        copied: list[str] = []
        for relative, source in license_files:
            target = component_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(target.relative_to(destination).as_posix())
        records.append(
            {
                "ecosystem": "pypi",
                "name": canonicalize_name(distribution_name),
                "version": version,
                "files": copied,
            }
        )

    for package_path, component in sorted(npm_components.items()):
        path_digest = hashlib.sha256(package_path.encode("utf-8")).hexdigest()[:10]
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "-", component.name).strip("-")
        component_root = destination / "npm" / f"{safe_name}-{component.version}-{path_digest}"
        copied = []
        for relative, source in _npm_license_files(component):
            target = component_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(target.relative_to(destination).as_posix())
        records.append(
            {
                "ecosystem": "npm",
                "name": component.name,
                "version": component.version,
                "package_lock_path": package_path,
                "files": copied,
            }
        )
    write_json(destination / "LICENSES.json", records)
    return records

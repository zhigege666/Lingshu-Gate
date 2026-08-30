"""Shared, deterministic release-asset helpers."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = REPOSITORY_ROOT / "src" / "lingshu_gate" / "_version.py"
REQUIRED_LEGAL_FILES = (
    REPOSITORY_ROOT / "LICENSE",
    REPOSITORY_ROOT / "NOTICE",
    REPOSITORY_ROOT / "THIRD_PARTY_NOTICES.md",
)
REQUIRED_DOCUMENTATION_FILES = (REPOSITORY_ROOT / "README.md",)
VERSION_PATTERN = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']\s*$', re.MULTILINE)
SEMVER_NUMBER = r"(?:0|[1-9][0-9]*)"
SEMVER_PRERELEASE_IDENTIFIER = r"(?:0|[1-9][0-9]*|[0-9A-Za-z-]*[A-Za-z-][0-9A-Za-z-]*)"
SAFE_VERSION_PATTERN = re.compile(
    rf"^{SEMVER_NUMBER}\.{SEMVER_NUMBER}\.{SEMVER_NUMBER}"
    rf"(?:-{SEMVER_PRERELEASE_IDENTIFIER}(?:\.{SEMVER_PRERELEASE_IDENTIFIER})*)?$"
)
MAX_RELEASE_VERSION_LENGTH = 96


def _valid_release_version(version: str) -> bool:
    return (
        len(version) <= MAX_RELEASE_VERSION_LENGTH
        and SAFE_VERSION_PATTERN.fullmatch(version) is not None
        and not version.casefold().endswith(".lock")
    )


def read_version() -> str:
    """Read and validate the single source version without importing the app."""

    try:
        source = VERSION_FILE.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise RuntimeError(f"Version source is missing: {VERSION_FILE}") from exc
    match = VERSION_PATTERN.search(source)
    if (
        match is None
        or not _valid_release_version(match.group(1))
    ):
        raise RuntimeError(f"Invalid version source: {VERSION_FILE}")
    return match.group(1)


def is_prerelease(version: str) -> bool:
    if not _valid_release_version(version):
        raise RuntimeError(f"Invalid release version: {version!r}")
    return "-" in version


def validate_release_inputs() -> None:
    """Fail closed when required legal or user documentation is absent."""

    missing = [path.relative_to(REPOSITORY_ROOT).as_posix() for path in (*REQUIRED_LEGAL_FILES, *REQUIRED_DOCUMENTATION_FILES) if not path.is_file()]
    if missing:
        raise RuntimeError("Required release file(s) are missing: " + ", ".join(missing))


def source_date_epoch() -> int:
    """Return the normalized source timestamp used for archive metadata."""

    raw = os.environ.get("SOURCE_DATE_EPOCH", "").strip()
    if raw:
        try:
            epoch = int(raw)
        except ValueError as exc:
            raise RuntimeError("SOURCE_DATE_EPOCH must be an integer") from exc
        if epoch < 0:
            raise RuntimeError("SOURCE_DATE_EPOCH must not be negative")
        return epoch
    return 0


def source_revision() -> str:
    """Return a non-secret source revision for traceability."""

    from_environment = os.environ.get("GITHUB_SHA", "").strip()
    if re.fullmatch(r"[0-9a-fA-F]{7,64}", from_environment):
        return from_environment.lower()
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    revision = result.stdout.strip()
    if result.returncode == 0 and re.fullmatch(r"[0-9a-fA-F]{40,64}", revision):
        return revision.lower()
    return "unknown"


def iso_timestamp(epoch: int) -> str:
    """Render an epoch in the stable UTC form used by metadata files."""

    return datetime.fromtimestamp(epoch, timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def iter_tree(root: Path) -> Iterable[Path]:
    """Yield a stable tree, including directories required by empty configs."""

    return sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix())


def build_file_manifest(root: Path, *, excluded: set[str] | None = None) -> list[dict[str, Any]]:
    """Describe every regular bundled file by relative path, size, and digest."""

    excluded = excluded or set()
    records: list[dict[str, Any]] = []
    for path in iter_tree(root):
        relative = path.relative_to(root).as_posix()
        if relative in excluded:
            continue
        if path.is_symlink():
            link_target = os.readlink(path)
            records.append(
                {
                    "path": relative,
                    "type": "symlink",
                    "target": link_target,
                    "sha256": hashlib.sha256(link_target.encode("utf-8")).hexdigest(),
                }
            )
            continue
        if not path.is_file():
            continue
        records.append(
            {
                "path": relative,
                "type": "file",
                "sha256": sha256_file(path),
                "size": path.stat().st_size,
            }
        )
    return records


def validate_tree_symlinks(root: Path) -> None:
    """Reject absolute or escaping symlinks before an archive is produced."""

    resolved_root = root.resolve()
    for path in iter_tree(root):
        if not path.is_symlink():
            continue
        raw_target = Path(os.readlink(path))
        if raw_target.is_absolute():
            raise RuntimeError(f"Release tree contains an absolute symlink: {path}")
        resolved_target = (path.parent / raw_target).resolve(strict=False)
        if not resolved_target.is_relative_to(resolved_root):
            raise RuntimeError(f"Release tree contains an escaping symlink: {path}")


def validate_tree_entries(root: Path, *, allow_symlinks: bool) -> None:
    """Allow only archive-safe entries and enforce the requested symlink policy."""

    validate_tree_symlinks(root)
    for path in iter_tree(root):
        if path.is_symlink():
            if not allow_symlinks:
                raise RuntimeError(f"This release archive does not support symlinks: {path}")
            continue
        if not path.is_file() and not path.is_dir():
            raise RuntimeError(f"Release tree contains a special filesystem entry: {path}")


def build_metadata(*, root: Path, target: str, version: str, epoch: int, tools: dict[str, str]) -> dict[str, Any]:
    return {
        "application": "Lingshu Gate",
        "version": version,
        "target": target,
        "source_revision": source_revision(),
        "source_date_epoch": epoch,
        "created": iso_timestamp(epoch),
        "builder": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "system": platform.system(),
            "machine": platform.machine(),
            **tools,
        },
        "files": build_file_manifest(root, excluded={"BUILD-INFO.json"}),
    }


def _normalized_mode(path: Path) -> int:
    if path.is_dir():
        return 0o755
    existing = stat.S_IMODE(path.stat().st_mode)
    return 0o755 if existing & 0o111 else 0o644


def create_tar_gz(source: Path, destination: Path, *, epoch: int) -> None:
    """Create a stable gzip-compressed POSIX archive from one directory."""

    validate_tree_entries(source, allow_symlinks=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as raw_stream:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw_stream, compresslevel=9, mtime=epoch) as gzip_stream:
            with tarfile.open(fileobj=gzip_stream, mode="w", format=tarfile.PAX_FORMAT) as archive:
                paths = [source, *iter_tree(source)]
                for path in paths:
                    relative = Path(source.name) if path == source else Path(source.name) / path.relative_to(source)
                    info = archive.gettarinfo(str(path), arcname=relative.as_posix())
                    info.uid = 0
                    info.gid = 0
                    info.uname = "root"
                    info.gname = "root"
                    info.mtime = epoch
                    info.mode = _normalized_mode(path)
                    if info.isfile():
                        with path.open("rb") as stream:
                            archive.addfile(info, stream)
                    else:
                        archive.addfile(info)


def create_zip(source: Path, destination: Path, *, epoch: int) -> None:
    """Create a stable Windows-friendly ZIP archive from one directory."""

    validate_tree_entries(source, allow_symlinks=False)
    destination.parent.mkdir(parents=True, exist_ok=True)
    zip_epoch = max(epoch, 315532800)  # ZIP timestamps start at 1980-01-01.
    timestamp = datetime.fromtimestamp(zip_epoch, timezone.utc).timetuple()[:6]
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in [source, *iter_tree(source)]:
            relative = Path(source.name) if path == source else Path(source.name) / path.relative_to(source)
            is_directory = path.is_dir()
            name = relative.as_posix() + ("/" if is_directory else "")
            info = zipfile.ZipInfo(name, date_time=timestamp)
            info.create_system = 3
            info.external_attr = (_normalized_mode(path) | (stat.S_IFDIR if is_directory else stat.S_IFREG)) << 16
            if is_directory:
                archive.writestr(info, b"")
            else:
                info.compress_type = zipfile.ZIP_DEFLATED
                with path.open("rb") as stream:
                    archive.writestr(info, stream.read())


def write_checksums(output_dir: Path, assets: Iterable[Path]) -> Path:
    assets = sorted(assets, key=lambda path: path.name)
    checksum_path = output_dir / "SHA256SUMS"
    checksum_path.write_text(
        "".join(f"{sha256_file(asset)}  {asset.name}\n" for asset in assets),
        encoding="utf-8",
    )
    return checksum_path


def reset_directory(path: Path, *, allowed_parent: Path) -> None:
    """Recreate one narrow build directory after verifying its boundary."""

    resolved = path.resolve()
    parent = allowed_parent.resolve()
    if resolved == parent or not resolved.is_relative_to(parent):
        raise RuntimeError(f"Refusing to reset path outside {parent}: {resolved}")
    if resolved.exists():
        shutil.rmtree(resolved)
    resolved.mkdir(parents=True)


def copy_release_file(source: Path, destination_dir: Path, *, destination_name: str | None = None) -> Path:
    destination = destination_dir / (destination_name or source.name)
    shutil.copy2(source, destination)
    return destination


def python_executable_name(target: str) -> str:
    return "lingshu-gate.exe" if target.startswith("windows-") else "lingshu-gate"


def current_python() -> str:
    return sys.executable

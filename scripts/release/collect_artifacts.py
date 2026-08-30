"""Validate per-job checksums and assemble one collision-free release directory."""

from __future__ import annotations

import argparse
import re
import shutil
import stat
from pathlib import Path

from scripts.release.common import REPOSITORY_ROOT, reset_directory, sha256_file, write_checksums

VERSION_FRAGMENT = r"(?P<version>[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z][0-9A-Za-z.-]*)?)"
ASSET_PATTERNS = (
    re.compile(rf"^lingshu-gate-v{VERSION_FRAGMENT}-linux-(?:x86_64|aarch64)\.tar\.gz$"),
    re.compile(rf"^lingshu-gate-v{VERSION_FRAGMENT}-windows-x86_64\.zip$"),
    re.compile(rf"^lingshu-gate-v{VERSION_FRAGMENT}-macos-(?:x86_64|arm64)\.tar\.gz$"),
    re.compile(rf"^lingshu-gate-v{VERSION_FRAGMENT}-docker-compose\.tar\.gz$"),
    re.compile(rf"^lingshu-gate-v{VERSION_FRAGMENT}-docker-core-linux-(?:amd64|arm64)\.tar\.gz$"),
    re.compile(rf"^lingshu-gate-v{VERSION_FRAGMENT}-application-sbom\.spdx\.json$"),
    re.compile(rf"^lingshu-gate-v{VERSION_FRAGMENT}-container-image\.txt$"),
)


def _asset_version(name: str) -> str:
    for pattern in ASSET_PATTERNS:
        match = pattern.fullmatch(name)
        if match is not None:
            return match.group("version")
    raise RuntimeError(f"Unexpected release asset name: {name}")


def expected_asset_names(version: str) -> set[str]:
    return {
        f"lingshu-gate-v{version}-linux-x86_64.tar.gz",
        f"lingshu-gate-v{version}-linux-aarch64.tar.gz",
        f"lingshu-gate-v{version}-windows-x86_64.zip",
        f"lingshu-gate-v{version}-macos-x86_64.tar.gz",
        f"lingshu-gate-v{version}-macos-arm64.tar.gz",
        f"lingshu-gate-v{version}-docker-compose.tar.gz",
        f"lingshu-gate-v{version}-docker-core-linux-amd64.tar.gz",
        f"lingshu-gate-v{version}-docker-core-linux-arm64.tar.gz",
        f"lingshu-gate-v{version}-application-sbom.spdx.json",
        f"lingshu-gate-v{version}-container-image.txt",
    }


def _read_checksum_file(path: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise RuntimeError(f"Invalid checksum line in {path}: {line!r}")
        digest, raw_name = parts
        name = raw_name.lstrip("* ")
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest.lower()):
            raise RuntimeError(f"Invalid SHA-256 digest in {path}: {digest!r}")
        if Path(name).name != name:
            raise RuntimeError(f"Checksum entry must be a base name in {path}: {name!r}")
        if name in checksums:
            raise RuntimeError(f"Duplicate checksum entry in {path}: {name}")
        checksums[name] = digest.lower()
    if not checksums:
        raise RuntimeError(f"Checksum file is empty: {path}")
    return checksums


def collect(
    input_dir: Path,
    output_dir: Path,
    *,
    version: str,
    allowed_output_parent: Path,
) -> list[Path]:
    checksum_files = sorted(input_dir.rglob("SHA256SUMS"))
    if not checksum_files:
        raise RuntimeError(f"No SHA256SUMS files found under {input_dir}")
    allowed_output_parent.mkdir(parents=True, exist_ok=True)
    reset_directory(output_dir, allowed_parent=allowed_output_parent)

    assets: list[Path] = []
    seen_names: set[str] = set()
    for checksum_file in checksum_files:
        if not stat.S_ISREG(checksum_file.lstat().st_mode):
            raise RuntimeError(f"Checksum inventory is not a regular file: {checksum_file}")
        declared = _read_checksum_file(checksum_file)
        actual: set[str] = set()
        for path in checksum_file.parent.iterdir():
            if path.name == "SHA256SUMS":
                continue
            if not stat.S_ISREG(path.lstat().st_mode):
                raise RuntimeError(f"Artifact directory contains a non-regular entry: {path}")
            actual.add(path.name)
        if set(declared) != actual:
            raise RuntimeError(
                f"Artifact directory checksum coverage mismatch in {checksum_file.parent}: "
                f"declared={sorted(declared)}, actual={sorted(actual)}"
            )
        for name, expected_digest in declared.items():
            source = checksum_file.parent / name
            if not source.is_file() or not stat.S_ISREG(source.lstat().st_mode):
                raise RuntimeError(f"Checksummed asset is missing: {source}")
            asset_version = _asset_version(source.name)
            if asset_version != version:
                raise RuntimeError(f"Expected release version {version!r}, found {asset_version!r}")
            if sha256_file(source) != expected_digest:
                raise RuntimeError(f"Checksum mismatch: {source}")
            if source.name in seen_names:
                raise RuntimeError(f"Duplicate release asset name: {source.name}")
            seen_names.add(source.name)
            destination = output_dir / source.name
            shutil.copy2(source, destination)
            if sha256_file(destination) != expected_digest:
                raise RuntimeError(f"Copied release asset checksum mismatch: {destination}")
            assets.append(destination)
    expected = expected_asset_names(version)
    if seen_names != expected:
        raise RuntimeError(
            f"Release asset set is incomplete or unexpected: "
            f"missing={sorted(expected - seen_names)}, extra={sorted(seen_names - expected)}"
        )
    write_checksums(output_dir, assets)
    return sorted(assets, key=lambda path: path.name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    assets = collect(
        args.input_dir.resolve(),
        args.output_dir.resolve(),
        version=args.version,
        allowed_output_parent=REPOSITORY_ROOT / "dist",
    )
    for asset in assets:
        print(asset)


if __name__ == "__main__":
    main()

"""Fail closed while enumerating the exact files passed to GitHub Release creation."""

from __future__ import annotations

import argparse
import stat
import sys
from pathlib import Path

from scripts.release.collect_artifacts import _read_checksum_file, expected_asset_names
from scripts.release.common import sha256_file


def validated_asset_paths(release_dir: Path, version: str) -> list[Path]:
    if not release_dir.is_dir() or release_dir.is_symlink():
        raise RuntimeError(f"Release directory is missing or unsafe: {release_dir}")
    expected_assets = expected_asset_names(version)
    expected_files = expected_assets | {"SHA256SUMS"}
    actual_files: set[str] = set()
    for path in release_dir.iterdir():
        mode = path.lstat().st_mode
        if not stat.S_ISREG(mode):
            raise RuntimeError(f"Release directory contains a non-regular entry: {path.name}")
        actual_files.add(path.name)
    if actual_files != expected_files:
        raise RuntimeError(
            "Release directory does not contain the exact publishable file set: "
            f"missing={sorted(expected_files - actual_files)}, "
            f"extra={sorted(actual_files - expected_files)}"
        )
    checksums = _read_checksum_file(release_dir / "SHA256SUMS")
    if set(checksums) != expected_assets:
        raise RuntimeError("Aggregate SHA256SUMS does not cover the exact release asset set")
    for name, digest in checksums.items():
        if sha256_file(release_dir / name) != digest:
            raise RuntimeError(f"Aggregate release checksum mismatch: {name}")
    return [release_dir / name for name in sorted(expected_files)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    paths = validated_asset_paths(args.release_dir.resolve(), args.version)
    sys.stdout.buffer.write(b"".join(str(path).encode("utf-8") + b"\0" for path in paths))


if __name__ == "__main__":
    main()

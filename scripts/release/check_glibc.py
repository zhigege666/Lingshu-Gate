"""Fail when a Linux native bundle exceeds the documented glibc baseline."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
from pathlib import Path

GLIBC_PATTERN = re.compile(r"\bGLIBC_(\d+)\.(\d+)\b")


def parse_versions(output: str) -> set[tuple[int, int]]:
    return {(int(major), int(minor)) for major, minor in GLIBC_PATTERN.findall(output)}


def check_bundle(bundle_dir: Path, maximum: tuple[int, int]) -> tuple[int, int]:
    readelf = shutil.which("readelf")
    if readelf is None:
        raise RuntimeError("readelf is required for the Linux compatibility check")
    discovered: set[tuple[int, int]] = set()
    for path in sorted(bundle_dir.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open("rb") as stream:
            if stream.read(4) != b"\x7fELF":
                continue
        result = subprocess.run(
            [readelf, "--version-info", "--wide", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"readelf failed for bundled ELF file: {path}\n{result.stderr}")
        discovered.update(parse_versions(result.stdout))
    if not discovered:
        raise RuntimeError(f"No glibc symbol versions were found under {bundle_dir}")
    highest = max(discovered)
    if highest > maximum:
        raise RuntimeError(
            f"Bundle requires GLIBC_{highest[0]}.{highest[1]}, exceeding "
            f"GLIBC_{maximum[0]}.{maximum[1]}"
        )
    return highest


def _version(value: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)", value)
    if match is None:
        raise argparse.ArgumentTypeError("glibc version must use MAJOR.MINOR")
    return int(match.group(1)), int(match.group(2))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--maximum", type=_version, default=(2, 35))
    args = parser.parse_args()
    highest = check_bundle(args.bundle_dir.resolve(), args.maximum)
    print(f"maximum required glibc: {highest[0]}.{highest[1]}")


if __name__ == "__main__":
    main()

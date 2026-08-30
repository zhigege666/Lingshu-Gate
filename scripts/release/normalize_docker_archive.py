"""Normalize the outer tar metadata of a Docker save archive."""

from __future__ import annotations

import argparse
import os
import tarfile
from pathlib import Path, PurePosixPath

from scripts.release.common import source_date_epoch


def _safe_name(raw_name: str) -> str:
    name = raw_name.rstrip("/")
    path = PurePosixPath(name)
    if not name or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeError(f"Docker archive contains an unsafe path: {raw_name!r}")
    return path.as_posix()


def normalize(source: Path, destination: Path, *, epoch: int) -> None:
    if source.resolve() == destination.resolve():
        raise RuntimeError("Docker archive normalization requires distinct source and destination paths")
    if epoch < 0:
        raise RuntimeError("Docker archive timestamp must not be negative")
    seen: set[str] = set()
    with tarfile.open(source, mode="r:") as input_archive:
        members = sorted(input_archive.getmembers(), key=lambda member: _safe_name(member.name))
        if not members:
            raise RuntimeError("Docker archive is empty")
        with tarfile.open(destination, mode="w", format=tarfile.PAX_FORMAT) as output_archive:
            for member in members:
                normalized_name = _safe_name(member.name)
                if normalized_name in seen:
                    raise RuntimeError(f"Docker archive contains a duplicate path: {normalized_name}")
                seen.add(normalized_name)
                if not (member.isdir() or member.isfile()):
                    raise RuntimeError(f"Docker archive contains an unsupported entry: {normalized_name}")
                member.name = normalized_name
                member.uid = 0
                member.gid = 0
                member.uname = "root"
                member.gname = "root"
                member.mtime = epoch
                member.mode = 0o755 if member.isdir() else 0o644
                member.pax_headers = {}
                if member.isfile():
                    stream = input_archive.extractfile(member)
                    if stream is None:
                        raise RuntimeError(f"Unable to read Docker archive member: {normalized_name}")
                    output_archive.addfile(member, stream)
                else:
                    output_archive.addfile(member)


def normalize_in_place(path: Path, *, epoch: int) -> None:
    temporary = path.with_name(f".{path.name}.normalized")
    if temporary.exists():
        raise RuntimeError(f"Refusing to replace an existing normalization temporary file: {temporary}")
    try:
        normalize(path, temporary, epoch=epoch)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    normalize_in_place(args.archive.resolve(), epoch=source_date_epoch())


if __name__ == "__main__":
    main()

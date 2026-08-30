"""Validate and extract the exact native archive that will be published."""

from __future__ import annotations

import argparse
import os
import stat
import struct
import tarfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import IO

from scripts.release.common import REPOSITORY_ROOT, read_version, reset_directory


def _safe_member_path(raw_name: str, expected_root: str) -> PurePosixPath:
    name = raw_name.rstrip("/")
    path = PurePosixPath(name)
    if not name or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeError(f"Native archive contains an unsafe path: {raw_name!r}")
    if path.parts[0] != expected_root:
        raise RuntimeError(f"Native archive contains an unexpected top-level path: {raw_name!r}")
    return path


WINDOWS_INVALID_CHARACTERS = frozenset('<>:"\\|?*')
WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{number}" for number in range(1, 10)}
    | {f"LPT{number}" for number in range(1, 10)}
)
MAX_ARCHIVE_MEMBERS = 100_000
MAX_ARCHIVE_MEMBER_BYTES = 1024 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 4 * 1024 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 500
MAX_ARCHIVE_COMPRESSED_BYTES = 1024 * 1024 * 1024
MAX_ZIP_CENTRAL_DIRECTORY_BYTES = 128 * 1024 * 1024
ZIP_EOCD_SIGNATURE = b"PK\x05\x06"
ZIP_EOCD_STRUCT = struct.Struct("<4s4H2LH")


def _validate_link(member_path: PurePosixPath, raw_target: str, expected_root: str) -> PurePosixPath:
    target = PurePosixPath(raw_target)
    if target.is_absolute():
        raise RuntimeError(f"Native archive contains an absolute symlink: {member_path}")
    resolved_parts: list[str] = list(member_path.parent.parts)
    for part in target.parts:
        if part in {"", "."}:
            continue
        if part == "..":
            if not resolved_parts:
                raise RuntimeError(f"Native archive contains an escaping symlink: {member_path}")
            resolved_parts.pop()
        else:
            resolved_parts.append(part)
    if not resolved_parts or resolved_parts[0] != expected_root:
        raise RuntimeError(f"Native archive contains an escaping symlink: {member_path}")
    return PurePosixPath(*resolved_parts)


def _filesystem_part(part: str, *, case_insensitive: bool) -> str:
    normalized = unicodedata.normalize("NFC", part)
    return normalized.casefold() if case_insensitive else normalized


def _validate_filesystem_paths(paths: list[PurePosixPath], *, case_insensitive: bool) -> None:
    """Reject archive names that alias on the destination filesystem."""

    spellings: dict[tuple[str, ...], tuple[str, ...]] = {}
    for path in paths:
        parts = path.parts
        for length in range(1, len(parts) + 1):
            raw_prefix = parts[:length]
            key = tuple(
                _filesystem_part(part, case_insensitive=case_insensitive) for part in raw_prefix
            )
            previous = spellings.get(key)
            if previous is not None and previous != raw_prefix:
                raise RuntimeError(
                    "Native archive contains filesystem-colliding paths: "
                    f"{PurePosixPath(*previous)} and {PurePosixPath(*raw_prefix)}"
                )
            spellings[key] = raw_prefix


def _validate_member_ancestors(
    member_paths: set[PurePosixPath],
    directory_paths: set[PurePosixPath],
) -> None:
    for path in member_paths:
        for ancestor in path.parents:
            if ancestor == PurePosixPath("."):
                continue
            if ancestor in member_paths and ancestor not in directory_paths:
                raise RuntimeError(
                    f"Native archive member ancestor is not a directory: {ancestor} -> {path}"
                )


def _destination(output_dir: Path, path: PurePosixPath) -> Path:
    return output_dir.joinpath(*path.parts)


def _validate_resource_budget(sizes: list[int]) -> None:
    if len(sizes) > MAX_ARCHIVE_MEMBERS:
        raise RuntimeError("Native archive contains too many members")
    if any(size < 0 or size > MAX_ARCHIVE_MEMBER_BYTES for size in sizes):
        raise RuntimeError("Native archive member exceeds the extraction size limit")
    if sum(sizes) > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
        raise RuntimeError("Native archive exceeds the total extraction size limit")


def _validate_archive_file_size(archive: Path) -> None:
    if archive.stat().st_size > MAX_ARCHIVE_COMPRESSED_BYTES:
        raise RuntimeError("Native archive exceeds the compressed size limit")


def _preflight_zip_directory(archive: Path) -> None:
    """Bound ZIP central-directory work before ZipFile allocates its member list."""

    archive_size = archive.stat().st_size
    tail_size = min(archive_size, 65_557)
    with archive.open("rb") as stream:
        stream.seek(archive_size - tail_size)
        tail = stream.read(tail_size)
    search_end = len(tail)
    end_record: tuple[int, ...] | None = None
    while True:
        position = tail.rfind(ZIP_EOCD_SIGNATURE, 0, search_end)
        if position < 0:
            break
        if position + ZIP_EOCD_STRUCT.size <= len(tail):
            candidate = ZIP_EOCD_STRUCT.unpack_from(tail, position)
            comment_length = candidate[-1]
            if position + ZIP_EOCD_STRUCT.size + comment_length == len(tail):
                end_record = candidate[1:]
                break
        search_end = position
    if end_record is None:
        raise RuntimeError("Native ZIP archive has no valid end-of-central-directory record")
    disk_number, central_disk, disk_entries, total_entries, central_size, central_offset, _comment = end_record
    if disk_number != 0 or central_disk != 0 or disk_entries != total_entries:
        raise RuntimeError("Native ZIP archive uses unsupported multi-disk storage")
    if total_entries == 0xFFFF or central_size == 0xFFFFFFFF or central_offset == 0xFFFFFFFF:
        raise RuntimeError("Native ZIP archive uses unsupported ZIP64 directory metadata")
    if total_entries > MAX_ARCHIVE_MEMBERS:
        raise RuntimeError("Native archive contains too many members")
    if central_size > MAX_ZIP_CENTRAL_DIRECTORY_BYTES:
        raise RuntimeError("Native ZIP archive central directory exceeds the size limit")
    if central_offset + central_size > archive_size:
        raise RuntimeError("Native ZIP archive central directory is outside the archive")


def _copy_member(source: IO[bytes], destination: Path, expected_size: int) -> None:
    written = 0
    with destination.open("xb") as target:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > expected_size:
                raise RuntimeError(f"Native archive member exceeds its declared size: {destination}")
            target.write(chunk)
    if written != expected_size:
        raise RuntimeError(f"Native archive member size does not match its declaration: {destination}")


def _extract_tar(archive: Path, output_dir: Path, expected_root: str, *, case_insensitive: bool) -> None:
    _validate_archive_file_size(archive)
    with tarfile.open(archive, mode="r:gz") as source:
        members: dict[PurePosixPath, tarfile.TarInfo] = {}
        symlink_paths: set[PurePosixPath] = set()
        total_size = 0
        for member in source:
            if len(members) >= MAX_ARCHIVE_MEMBERS:
                raise RuntimeError("Native archive contains too many members")
            member_size = member.size if member.isfile() else 0
            if member_size < 0 or member_size > MAX_ARCHIVE_MEMBER_BYTES:
                raise RuntimeError("Native archive member exceeds the extraction size limit")
            total_size += member_size
            if total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise RuntimeError("Native archive exceeds the total extraction size limit")
            member_path = _safe_member_path(member.name, expected_root)
            if member_path in members:
                raise RuntimeError(f"Native archive contains a duplicate path: {member_path}")
            if not (member.isdir() or member.isfile() or member.issym()):
                raise RuntimeError(f"Native archive contains an unsupported entry: {member_path}")
            if member.issym():
                _validate_link(
                    member_path,
                    member.linkname,
                    expected_root,
                )
                symlink_paths.add(member_path)
            members[member_path] = member

        if not members:
            raise RuntimeError("Native archive is empty")
        root_member = members.get(PurePosixPath(expected_root))
        if root_member is None or not root_member.isdir():
            raise RuntimeError("Native archive root entry is missing or is not a directory")
        _validate_filesystem_paths(list(members), case_insensitive=case_insensitive)
        _validate_member_ancestors(
            set(members),
            {path for path, member in members.items() if member.isdir()},
        )
        launcher = members.get(PurePosixPath(expected_root) / "start.sh")
        if launcher is None or not launcher.isfile() or launcher.mode & 0o111 != 0o111:
            raise RuntimeError("Native archive launcher is missing or not executable")

        for path, member in sorted(members.items(), key=lambda item: (len(item[0].parts), item[0].as_posix())):
            if not member.isdir():
                continue
            destination = _destination(output_dir, path)
            destination.mkdir(mode=member.mode & 0o777, parents=True, exist_ok=True)
        for path, member in sorted(members.items(), key=lambda item: item[1].offset_data):
            if not member.isfile():
                continue
            destination = _destination(output_dir, path)
            destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            stream = source.extractfile(member)
            if stream is None:
                raise RuntimeError(f"Unable to read native archive member: {path}")
            with stream:
                _copy_member(stream, destination, member.size)
            destination.chmod(member.mode & 0o777)
        for path, member in sorted(members.items(), key=lambda item: item[0].as_posix()):
            if not member.issym():
                continue
            destination = _destination(output_dir, path)
            destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            destination.symlink_to(member.linkname)

        resolved_output = output_dir.resolve()
        for path in symlink_paths:
            destination = _destination(output_dir, path)
            try:
                resolved_target = destination.resolve(strict=True)
            except (FileNotFoundError, RuntimeError) as error:
                raise RuntimeError(f"Native archive contains a dangling or cyclic symlink: {path}") from error
            if not resolved_target.is_relative_to(resolved_output):
                raise RuntimeError(f"Native archive symlink resolves outside the bundle: {path}")


def _validate_windows_path(path: PurePosixPath, raw_name: str) -> None:
    if "\\" in raw_name:
        raise RuntimeError(f"Native ZIP archive contains a backslash path: {raw_name!r}")
    for part in path.parts:
        if part.endswith((".", " ")):
            raise RuntimeError(f"Native ZIP archive contains a trailing dot or space: {raw_name!r}")
        if any(character in WINDOWS_INVALID_CHARACTERS or ord(character) < 32 for character in part):
            raise RuntimeError(f"Native ZIP archive contains an invalid Windows name: {raw_name!r}")
        if part.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
            raise RuntimeError(f"Native ZIP archive contains a reserved Windows name: {raw_name!r}")


def _extract_zip(archive: Path, output_dir: Path, expected_root: str) -> None:
    _validate_archive_file_size(archive)
    _preflight_zip_directory(archive)
    with zipfile.ZipFile(archive) as source:
        archive_members = source.infolist()
        if not archive_members:
            raise RuntimeError("Native archive is empty")
        members: dict[PurePosixPath, zipfile.ZipInfo] = {}
        for member in archive_members:
            member_path = _safe_member_path(member.filename, expected_root)
            _validate_windows_path(member_path, member.filename)
            if member_path in members:
                raise RuntimeError(f"Native archive contains a duplicate path: {member_path}")
            if member.flag_bits & 0x1:
                raise RuntimeError(f"Native ZIP archive contains an encrypted member: {member_path}")
            unix_mode = member.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                raise RuntimeError(f"Native ZIP archive contains a symlink: {member_path}")
            file_type = stat.S_IFMT(unix_mode)
            if file_type not in {0, stat.S_IFREG, stat.S_IFDIR}:
                raise RuntimeError(f"Native ZIP archive contains an unsupported entry: {member_path}")
            if member.file_size and (
                member.compress_size == 0
                or member.file_size / member.compress_size > MAX_ZIP_COMPRESSION_RATIO
            ):
                raise RuntimeError(f"Native ZIP archive member exceeds the compression ratio limit: {member_path}")
            members[member_path] = member

        _validate_resource_budget([member.file_size if not member.is_dir() else 0 for member in members.values()])
        root_member = members.get(PurePosixPath(expected_root))
        if root_member is None or not root_member.is_dir():
            raise RuntimeError("Native ZIP archive root entry is missing or is not a directory")
        _validate_filesystem_paths(list(members), case_insensitive=True)
        _validate_member_ancestors(
            set(members),
            {path for path, member in members.items() if member.is_dir()},
        )
        launcher = members.get(PurePosixPath(expected_root) / "start.cmd")
        if launcher is None or launcher.is_dir():
            raise RuntimeError("Native archive launcher is missing")

        for path, member in sorted(members.items(), key=lambda item: (len(item[0].parts), item[0].as_posix())):
            if not member.is_dir():
                continue
            _destination(output_dir, path).mkdir(mode=0o755, parents=True, exist_ok=True)
        for path, member in sorted(members.items(), key=lambda item: item[0].as_posix()):
            if member.is_dir():
                continue
            destination = _destination(output_dir, path)
            destination.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
            with source.open(member, mode="r") as stream:
                _copy_member(stream, destination, member.file_size)


def extract_archive(target: str, archive: Path, output_dir: Path, *, allowed_parent: Path) -> Path:
    version = read_version()
    expected_root = f"lingshu-gate-v{version}-{target}"
    expected_archive = f"{expected_root}.zip" if target.startswith("windows-") else f"{expected_root}.tar.gz"
    if archive.name != expected_archive:
        raise RuntimeError(f"Unexpected native archive name: {archive.name}")
    if not archive.is_file() or archive.is_symlink():
        raise RuntimeError(f"Native archive is missing or unsafe: {archive}")

    allowed_parent.mkdir(parents=True, exist_ok=True)
    reset_directory(output_dir, allowed_parent=allowed_parent)
    if target.startswith("windows-"):
        _extract_zip(archive, output_dir, expected_root)
    else:
        _extract_tar(
            archive,
            output_dir,
            expected_root,
            case_insensitive=target.startswith("macos-"),
        )
    bundle_dir = output_dir / expected_root
    if not bundle_dir.is_dir() or bundle_dir.is_symlink():
        raise RuntimeError("Native archive did not extract to exactly one bundle directory")
    top_level_entries = sorted(path.name for path in output_dir.iterdir())
    if top_level_entries != [expected_root]:
        raise RuntimeError(f"Native archive has an unexpected top-level layout: {top_level_entries}")
    launcher_name = "start.cmd" if target.startswith("windows-") else "start.sh"
    launcher = bundle_dir / launcher_name
    launcher_mode = launcher.lstat().st_mode
    if not stat.S_ISREG(launcher_mode):
        raise RuntimeError("Extracted native archive launcher is not a regular file")
    if not target.startswith("windows-") and stat.S_IMODE(launcher_mode) & 0o111 != 0o111:
        raise RuntimeError("Extracted native archive launcher is not executable")
    return bundle_dir


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    bundle_dir = extract_archive(
        args.target,
        args.archive.resolve(),
        output_dir,
        allowed_parent=REPOSITORY_ROOT / "build" / "release",
    )
    print(os.fspath(bundle_dir))


if __name__ == "__main__":
    main()

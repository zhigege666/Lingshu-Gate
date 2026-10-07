"""Descriptor-based reads for frozen untrusted executor output."""
from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO


@contextmanager
def open_regular_file(path: Path, *, maximum: int) -> Iterator[tuple[BinaryIO, os.stat_result]]:
    descriptor: int | None = None
    reader: BinaryIO | None = None
    try:
        if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_NONBLOCK"):
            raise ValueError("safe_regular_file_platform_unsupported")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= maximum:
            raise ValueError("safe_regular_file_rejected")
        reader = os.fdopen(descriptor, "rb")
        descriptor = None
        yield reader, before
        after = os.fstat(reader.fileno())
        named = os.stat(path, follow_symlinks=False)
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) or not stat.S_ISREG(named.st_mode) or (named.st_dev, named.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("safe_regular_file_changed")
    finally:
        if reader is not None:
            reader.close()
        if descriptor is not None:
            os.close(descriptor)

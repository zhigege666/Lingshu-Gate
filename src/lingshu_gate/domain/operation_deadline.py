"""Cancellation and deadline checks for bounded connection operations."""
from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Protocol


class TimedLock(Protocol):
    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool: ...
    def release(self) -> None: ...


def check_operation(cancel: threading.Event | None, deadline: float) -> None:
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Connection operation cancelled")
    if time.monotonic() >= deadline:
        raise TimeoutError("Connection operation deadline exceeded")


@contextmanager
def operation_lock(lock: TimedLock, *, cancel: threading.Event | None, deadline: float) -> Iterator[None]:
    """Bound contention as well as I/O; cancellation never forces a lock open."""
    while True:
        check_operation(cancel, deadline)
        if lock.acquire(timeout=min(.05, max(deadline - time.monotonic(), .001))):
            break
    try:
        check_operation(cancel, deadline)
        yield
    finally:
        lock.release()

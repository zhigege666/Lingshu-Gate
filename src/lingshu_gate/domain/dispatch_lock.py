"""Reentrant shared dispatch leases with exclusive, deadline-capable mutations."""
from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from types import TracebackType


class DispatchLock:
    """Acquire/release users are writers; shared dispatch leases run together.

    Waiting writers stop new readers; nested reads by an existing holder remain
    possible. Read-to-write upgrades fail instead of deadlocking. Neither lease
    grants authority: policy is rechecked after acquiring the leases.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition(threading.RLock())
        self._writer: int | None = None
        self._depth = 0
        self._readers: dict[int, int] = {}
        self._waiting_writers = 0

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        if not blocking and timeout != -1:
            raise ValueError("Non-blocking acquisition cannot specify a timeout")
        if timeout < 0 and timeout != -1:
            raise ValueError("Invalid lock timeout")
        owner = threading.get_ident()
        deadline = time.monotonic() + timeout if timeout >= 0 else None
        with self._condition:
            if self._writer == owner:
                self._depth += 1
                return True
            if owner in self._readers:
                raise RuntimeError("A dispatch read lease cannot be upgraded to a mutation")
            self._waiting_writers += 1
            try:
                while self._writer is not None or self._readers:
                    remaining = None if deadline is None else deadline - time.monotonic()
                    if not blocking or remaining is not None and remaining <= 0:
                        return False
                    self._condition.wait(remaining)
                self._writer, self._depth = owner, 1
                return True
            finally:
                self._waiting_writers -= 1
                self._condition.notify_all()

    def release(self) -> None:
        with self._condition:
            if self._writer != threading.get_ident():
                raise RuntimeError("Mutation lock is not owned by this thread")
            self._depth -= 1
            if self._depth == 0:
                self._writer = None
                self._condition.notify_all()

    def _is_owned(self) -> bool:
        """Preserve the runtime's existing lock-ownership diagnostic contract."""
        with self._condition:
            owner = threading.get_ident()
            return self._writer == owner or owner in self._readers

    def __enter__(self) -> DispatchLock:
        self.acquire()
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 traceback: TracebackType | None) -> None:
        self.release()

    @contextmanager
    def read_lock(self) -> Iterator[None]:
        owner = threading.get_ident()
        with self._condition:
            while (self._writer not in {None, owner}
                   or self._waiting_writers and owner not in self._readers and self._writer != owner):
                self._condition.wait()
            self._readers[owner] = self._readers.get(owner, 0) + 1
        try:
            yield
        finally:
            with self._condition:
                count = self._readers[owner] - 1
                if count:
                    self._readers[owner] = count
                else:
                    del self._readers[owner]
                self._condition.notify_all()

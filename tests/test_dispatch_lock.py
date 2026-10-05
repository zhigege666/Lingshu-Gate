"""Shared dispatch safety: concurrent readers, reentrancy and bounded writers."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Thread

import pytest

from lingshu_gate.domain.dispatch_lock import DispatchLock


def test_readers_overlap_and_writer_timeout_preserves_lease():
    lock, barrier = DispatchLock(), Barrier(2)
    def reader():
        with lock.read_lock(), lock.read_lock():
            barrier.wait(timeout=2)
            with pytest.raises(RuntimeError, match="upgraded"):
                lock.acquire(blocking=False)
    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(lambda _: reader(), range(2)))
    with lock.read_lock():
        with ThreadPoolExecutor(max_workers=1) as executor:
            assert executor.submit(lock.acquire, timeout=.05).result(timeout=1) is False
    assert lock.acquire(timeout=.05)
    with lock, lock.read_lock():
        pass
    lock.release()


def test_writer_excludes_readers_and_releases_after_exception():
    lock, started, entered = DispatchLock(), Event(), Event()
    def reader():
        started.set()
        with lock.read_lock():
            entered.set()
    with pytest.raises(ValueError):
        with lock:
            thread = Thread(target=reader)
            thread.start()
            assert started.wait(1) and not entered.wait(.05)
            raise ValueError("Synthetic mutation failure")
    thread.join(timeout=1)
    assert entered.is_set()
    with pytest.raises(RuntimeError, match="owned"):
        lock.release()

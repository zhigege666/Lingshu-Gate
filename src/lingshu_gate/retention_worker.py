"""Opt-in lifespan worker. Work is bounded and SQLite leases fence processes."""
from __future__ import annotations

import asyncio
import logging
import time
from uuid import uuid4

from lingshu_gate.retention_store import RetentionConflict, RetentionStore


class RetentionWorker:
    def __init__(self, store: RetentionStore, *, enabled: bool = False, interval_seconds: int = 3600) -> None:
        self.store = store
        self.enabled = enabled
        self.interval_seconds = interval_seconds
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self.owner = uuid4().hex

    def start(self) -> None:
        if self.enabled and self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None

    def _scheduled_job(self) -> None:
        preview = self.store.preview()
        try:
            self.store.enqueue(preview["preview_id"], preview["revision"], "retention-worker")
        except RetentionConflict:
            pass  # Another confirmed/scheduled job already owns the queue.

    async def _run(self) -> None:
        # Enabling starts the scheduler, not an immediate destructive startup sweep.
        next_sweep = time.monotonic() + self.interval_seconds
        while not self._stop.is_set():
            try:
                if time.monotonic() >= next_sweep:
                    await asyncio.to_thread(self._scheduled_job)
                    next_sweep = time.monotonic() + self.interval_seconds
                await asyncio.to_thread(self.store.run_batch, self.owner)
            except Exception:
                logging.getLogger(__name__).warning("Retention batch failed; bounded retry scheduled")
                try:
                    await asyncio.to_thread(self.store.retry_failure, self.owner)
                except Exception:
                    logging.getLogger(__name__).warning("Retention retry state unavailable; lease will expire")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=1)
            except TimeoutError:
                pass

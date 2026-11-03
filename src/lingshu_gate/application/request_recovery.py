"""Bounded, process-local references to late MCP responses.

Receipts are not task records or authorization grants. Callers must revalidate
current authority and the tool before and after reading through a receipt.
"""

from __future__ import annotations

import math
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from lingshu_gate.auth import AuthPrincipal

MAX_RECOVERY_ENTRIES = 128
MAX_RECOVERY_ENTRIES_PER_PRINCIPAL = 16
MAX_RECOVERY_TTL_SECONDS = 300.0

ResponseReader = Callable[[], dict[str, Any] | None]


class RequestRecoveryCapacityError(RuntimeError):
    """No recovery receipt can be retained without evicting a live receipt."""


@dataclass(frozen=True, slots=True)
class RecoveryReceipt:
    handle: str = field(repr=False)
    principal: AuthPrincipal = field(repr=False)
    tool_id: str
    definition_revision: str
    reader: ResponseReader = field(repr=False)
    created_at: float
    expires_at: float


class RequestRecoveryStore:
    """Retain callbacks without invoking them or storing their response data.

    Times use the injected clock's domain (monotonic seconds by default).
    Expiry is absolute, never extended by reads, and cleaned up lazily.
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._entries: dict[str, RecoveryReceipt] = {}
        self._lock = threading.Lock()

    def retain(
        self,
        principal: AuthPrincipal,
        tool_id: str,
        definition_revision: str,
        reader: ResponseReader,
        ttl_seconds: float = MAX_RECOVERY_TTL_SECONDS,
    ) -> str:
        if isinstance(ttl_seconds, bool) or not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("Request recovery TTL must be a finite positive duration")
        ttl = min(float(ttl_seconds), MAX_RECOVERY_TTL_SECONDS)
        with self._lock:
            now = self._clock()
            self._expire(now)
            if len(self._entries) >= MAX_RECOVERY_ENTRIES:
                raise RequestRecoveryCapacityError("Request recovery capacity reached")
            if sum(entry.principal == principal for entry in self._entries.values()) >= MAX_RECOVERY_ENTRIES_PER_PRINCIPAL:
                raise RequestRecoveryCapacityError("Request recovery identity capacity reached")
            for _ in range(3):
                handle = secrets.token_urlsafe(32)
                if handle not in self._entries:
                    self._entries[handle] = RecoveryReceipt(
                        handle, principal, tool_id, definition_revision, reader, now, now + ttl,
                    )
                    return handle
            raise RuntimeError("Request recovery identifier allocation failed")

    def get(self, handle: str, principal: AuthPrincipal) -> RecoveryReceipt | None:
        with self._lock:
            self._expire(self._clock())
            receipt = self._entries.get(handle)
            return receipt if receipt is not None and receipt.principal == principal else None

    def discard(self, handle: str) -> None:
        with self._lock:
            self._entries.pop(handle, None)

    def _expire(self, now: float) -> None:
        for handle in [key for key, receipt in self._entries.items() if receipt.expires_at <= now]:
            del self._entries[handle]

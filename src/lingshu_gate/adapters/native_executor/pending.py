"""Exact resolver handle attached to an uncertain trusted DNS outcome."""
from __future__ import annotations

import threading


class PendingDNS(InterruptedError):
    def __init__(self, worker: threading.Thread) -> None:
        super().__init__("trusted_dns_termination_unknown")
        self.worker = worker

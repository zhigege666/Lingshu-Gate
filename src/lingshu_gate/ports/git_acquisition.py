"""Trusted Git object transport contract; no shell, checkout or project code."""

from __future__ import annotations

import threading
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any, BinaryIO, Protocol

from lingshu_gate.ports.safe_network_executor import ExecutorReadiness


@dataclass(frozen=True)
class GitObject:
    kind: str
    size_bytes: int
    stream: BinaryIO


class GitObjectReader(Protocol):
    object_format: str
    commit_sha: str

    def open_object(self, oid: str) -> AbstractContextManager[GitObject]:
        """Bound header/read time and producer chunks; close streams on all paths.

        Object bytes are untrusted even after transport completes. No working
        tree, revision expression, arbitrary path or command may be accepted.
        """
        ...


class TrustedGitBackend(Protocol):
    proxy_schemes: frozenset[str]

    def readiness(self) -> ExecutorReadiness:
        ...

    def resolve_commit(self, request: dict[str, Any], *, material: dict[str, Any], timeout_seconds: int) -> str:
        """Resolve/peel the exact safe ref to a SHA-1 commit, not a tag object.

        Enforce HTTPS verification, pinned DNS/host policy, zero redirects and
        the selected immutable proxy revision. Never fall back to direct or
        another protocol. Credentials belong only to this acquisition layer.
        """
        ...

    def fetch_exact(self, request: dict[str, Any], *, material: dict[str, Any], cancel: threading.Event, deadline: float) -> AbstractContextManager[GitObjectReader]:
        """Fetch only confirmed commit/tree/blob content, never a moving ref.

        Apply request limits while receiving/decoding, including compressed
        transfer_bytes, object count/bytes and absolute monotonic deadline.
        Collision-aware Git object decoding/verification is required from the
        reviewed backend; plain SHA-1 comparison is not collision detection.
        No host subprocess fallback, Git pack parser or transport is supplied
        by this Protocol. A future reviewed backend must disable all inherited
        config/hooks/filters/helpers and submodule/LFS acquisition. Secrets must
        never enter project/script env, argv, output or exported objects.

        Context exit must clean material/workspace. SafeExecutionCancelled is
        allowed only after confirmed whole-group termination; uncertain exit
        raises InterruptedError and must not be replayed automatically.
        """
        ...

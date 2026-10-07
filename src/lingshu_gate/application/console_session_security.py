"""Console session binding shared by OAuth consent and configuration writes."""
from __future__ import annotations

import hmac
import secrets
import time
from typing import Any

from lingshu_gate.auth import AuthPrincipal, AuthStore, hash_secret

CSRF_TTL = 300
MAX_SESSION_CSRF = 16
MAX_CONSOLE_CSRF = 4096


def session_binding(principal: AuthPrincipal, session: str) -> dict[str, str]:
    return {"user_id": principal.id, "session_hash": hash_secret(session)}


def session_binding_matches(binding: dict[str, Any], principal: AuthPrincipal, session: str) -> bool:
    return (binding.get("user_id") == principal.id and isinstance(binding.get("session_hash"), str)
            and hmac.compare_digest(binding["session_hash"], hash_secret(session)))


def live_console_session(auth: AuthStore, principal: AuthPrincipal, session: str) -> AuthPrincipal | None:
    current = auth._principal_from_session(session)
    if (principal.auth_type != "session" or current is None or current.id != principal.id
            or current.must_change_password or (principal.session_id is not None and principal.session_id != current.session_id)):
        return None
    return current


class ConsoleCsrfError(Exception):
    def __init__(self, code: str, status: int = 403) -> None:
        self.code, self.status = code, status
        super().__init__(code)


class ConsoleSessionCsrf:
    """Short-lived, single-use synchronizer tickets; no new signing key."""
    def __init__(self, auth: AuthStore) -> None:
        self.auth = auth

    def _current(self, principal: AuthPrincipal, session: str) -> AuthPrincipal:
        current = live_console_session(self.auth, principal, session)
        if current is None or not current.session_id:
            raise ConsoleCsrfError("session_required")
        return current

    def issue(self, principal: AuthPrincipal, session: str, target: str, request_digest: str) -> dict[str, Any]:
        current = self._current(principal, session)
        binding = session_binding(current, session)
        token, now = secrets.token_urlsafe(32), int(time.time())
        with self.auth.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM console_csrf_tickets WHERE expires_at<=?", (now,))
            counts = connection.execute("SELECT COUNT(*),SUM(session_id=?) FROM console_csrf_tickets", (current.session_id,)).fetchone()
            if counts[0] >= MAX_CONSOLE_CSRF or (counts[1] or 0) >= MAX_SESSION_CSRF:
                raise ConsoleCsrfError("csrf_capacity", 429)
            connection.execute("INSERT INTO console_csrf_tickets VALUES(?,?,?,?,?,?,?)",
                (hash_secret(token), current.session_id, binding["user_id"], binding["session_hash"], target, request_digest, now + CSRF_TTL))
        return {"csrf": token, "expires_at": now + CSRF_TTL}

    def consume(self, principal: AuthPrincipal, session: str, token: str, target: str, request_digest: str) -> None:
        current = self._current(principal, session)
        if len(token) != 43:
            raise ConsoleCsrfError("invalid_csrf")
        binding = session_binding(current, session)
        with self.auth.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            deleted = connection.execute("DELETE FROM console_csrf_tickets WHERE token_hash=? AND session_id=? AND user_id=? "
                "AND session_hash=? AND target=? AND request_digest=? AND expires_at>?",
                (hash_secret(token), current.session_id, binding["user_id"], binding["session_hash"], target, request_digest, int(time.time())))
            if deleted.rowcount != 1:
                raise ConsoleCsrfError("invalid_csrf")

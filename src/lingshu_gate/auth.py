"""Authentication, API token, and RBAC helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, cast
from uuid import uuid4

from fastapi import HTTPException, Request, status

from lingshu_gate.config import Settings
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.logging import log_event


USER_STATUSES = {"pending", "active", "disabled"}
INITIAL_ADMIN_CREDENTIALS_FILE = "initial-admin-credentials.json"
BOOTSTRAP_PASSWORD_FILE_ENV = "LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE"
MAX_BOOTSTRAP_SECRET_BYTES = 16 * 1024
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AuthPrincipal:
    id: str
    username: str
    role: str
    auth_type: str = "session"
    status: str = "active"
    display_name: str = ""
    roles: tuple[str, ...] = ()
    permissions: tuple[str, ...] = ()
    must_change_password: bool = False
    token_id: str | None = None
    scopes: tuple[str, ...] = ()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


def hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def hash_password(password: str, *, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200_000)
    return f"pbkdf2_sha256${salt}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, salt, digest = stored_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hash_password(password, salt=salt)
    return hmac.compare_digest(candidate, stored_hash)


class AuthStore:
    def __init__(self, settings: Settings, database: SQLiteDatabase) -> None:
        self.settings = settings
        self.database = database
        self.cookie_name = settings.auth_session_cookie_name
        self.session_ttl_hours = settings.auth_session_ttl_hours
        self.enabled = settings.auth_enabled
        self.initial_admin_credentials_path = (
            settings.data_dir / INITIAL_ADMIN_CREDENTIALS_FILE
        )
        self.bootstrap_from_env()

    def bootstrap_from_env(self) -> None:
        if not self.enabled:
            return

        connection = self.database.connect()
        local_credentials = False
        try:
            # 首次启动可能有多个进程同时进入。写锁必须覆盖“空库检查 +
            # user/role 插入”，否则两个进程都可能观察到空库并创建管理员。
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT COUNT(*) AS total FROM users").fetchone()
            if row and int(row["total"]) > 0:
                connection.commit()
                return

            configured = self._configured_bootstrap_credentials()
            if configured is None:
                # 空库不再暴露共享的 admin/admin。一次性随机凭据只写入
                # 本机 data_dir，日志也只记录文件路径。
                username, password = self._load_or_create_initial_admin_credentials()
                local_credentials = True
            else:
                username, password = configured

            self._insert_user(
                connection,
                username=username,
                password=password,
                role="admin",
                must_change_password=True,
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

        if local_credentials:
            log_event(
                logger,
                logging.WARNING,
                "gate.auth.initial_admin_credentials_created",
                "Initial admin credentials are available in a local protected file",
                path=str(self.initial_admin_credentials_path),
                username=username,
            )
        else:
            # 清理曾在提交前崩溃留下的随机凭据；配置式 bootstrap 从不需要它。
            self.initial_admin_credentials_path.unlink(missing_ok=True)

    def _configured_bootstrap_credentials(self) -> tuple[str, str] | None:
        username = os.getenv("LINGSHU_GATE_ADMIN_USERNAME", "").strip()
        inline_password = os.getenv("LINGSHU_GATE_ADMIN_PASSWORD", "")
        password_file = os.getenv(BOOTSTRAP_PASSWORD_FILE_ENV, "").strip()

        if inline_password and password_file:
            raise ValueError(
                "LINGSHU_GATE_ADMIN_PASSWORD and "
                f"{BOOTSTRAP_PASSWORD_FILE_ENV} are mutually exclusive"
            )
        password_configured = bool(inline_password or password_file)
        if bool(username) != password_configured:
            raise ValueError(
                "LINGSHU_GATE_ADMIN_USERNAME must be configured together with "
                "exactly one of LINGSHU_GATE_ADMIN_PASSWORD or "
                f"{BOOTSTRAP_PASSWORD_FILE_ENV}"
            )
        if not username:
            return None
        password = (
            self._read_bootstrap_password_file(Path(password_file))
            if password_file
            else inline_password
        )
        return username, password

    @staticmethod
    def _read_bootstrap_password_file(path: Path) -> str:
        if not path.is_absolute():
            raise ValueError(f"{BOOTSTRAP_PASSWORD_FILE_ENV} must be an absolute path")
        flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise ValueError(f"cannot open bootstrap password file: {path}") from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError(f"bootstrap password file is not a regular file: {path}")
            if metadata.st_size > MAX_BOOTSTRAP_SECRET_BYTES:
                raise ValueError("bootstrap password file is too large")
            if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o022:
                raise ValueError("bootstrap password file must not be group/world writable")
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                payload = stream.read(MAX_BOOTSTRAP_SECRET_BYTES + 1)
        finally:
            if descriptor >= 0:
                os.close(descriptor)

        if len(payload) > MAX_BOOTSTRAP_SECRET_BYTES:
            raise ValueError("bootstrap password file is too large")
        try:
            password = payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("bootstrap password file must contain UTF-8 text") from exc
        if password.endswith("\r\n"):
            password = password[:-2]
        elif password.endswith("\n"):
            password = password[:-1]
        if not password or any(character in password for character in ("\x00", "\r", "\n")):
            raise ValueError("bootstrap password file must contain exactly one non-empty line")
        if len(password) < 8:
            raise ValueError("bootstrap password must be at least 8 characters")
        return password

    def _load_or_create_initial_admin_credentials(self) -> tuple[str, str]:
        """Return crash-recoverable local bootstrap credentials.

        A pre-existing file is reused only while the database is still empty. This
        handles a process crash between the protected file write and user creation.
        """

        path = self.initial_admin_credentials_path
        if path.exists():
            try:
                payload = json.loads(self._read_private_credentials_file(path))
                username = str(payload["username"]).strip()
                password = str(payload["password"])
            except (OSError, ValueError, TypeError, KeyError) as exc:
                raise RuntimeError(
                    f"initial admin credentials file is invalid: {path}"
                ) from exc
            if not username or len(password) < 8:
                raise RuntimeError(f"initial admin credentials file is invalid: {path}")
            return username, password

        username = "admin"
        password = secrets.token_urlsafe(24)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary_path, flags, 0o600)
        published = False
        try:
            payload = (
                json.dumps(
                    {"username": username, "password": password},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n"
            ).encode("utf-8")
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("failed to write initial admin credentials")
                view = view[written:]
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(temporary_path, path)
            published = True
            self._fsync_directory(path.parent)
        except BaseException:
            if descriptor >= 0:
                os.close(descriptor)
            if not published:
                temporary_path.unlink(missing_ok=True)
            raise
        return username, password

    @staticmethod
    def _read_private_credentials_file(path: Path) -> str:
        flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode):
                raise RuntimeError(f"initial admin credentials file is invalid: {path}")
            if os.name == "posix" and stat.S_IMODE(metadata.st_mode) & 0o077:
                raise RuntimeError(
                    f"initial admin credentials file permissions are not 0600: {path}"
                )
            with os.fdopen(descriptor, "r", encoding="utf-8") as stream:
                descriptor = -1
                return stream.read(MAX_BOOTSTRAP_SECRET_BYTES + 1)
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        if os.name != "posix":
            return
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        descriptor = os.open(path, flags)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def has_users(self) -> bool:
        row = self.database.query_one("SELECT COUNT(*) AS total FROM users")
        return bool(row and row["total"] > 0)

    def create_user(
        self,
        *,
        username: str,
        password: str,
        role: str,
        status_value: str = "active",
        display_name: str = "",
        must_change_password: bool = False,
        allow_weak_password: bool = False,
    ) -> dict[str, object]:
        connection = self.database.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            user_id = self._insert_user(
                connection,
                username=username,
                password=password,
                role=role,
                status_value=status_value,
                display_name=display_name,
                must_change_password=must_change_password,
                allow_weak_password=allow_weak_password,
            )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
        return self.get_user(user_id)

    @staticmethod
    def _insert_user(
        connection: sqlite3.Connection,
        *,
        username: str,
        password: str,
        role: str,
        status_value: str = "active",
        display_name: str = "",
        must_change_password: bool = False,
        allow_weak_password: bool = False,
    ) -> str:
        username = username.strip()
        if not username:
            raise ValueError("username is required")
        if len(password) < 8 and not allow_weak_password:
            raise ValueError("password must be at least 8 characters")
        if status_value not in USER_STATUSES:
            raise ValueError(f"invalid user status: {status_value}")
        user_id = str(uuid4())
        now = iso_now()
        connection.execute(
            """
            INSERT INTO users
                (id, username, password_hash, display_name, status,
                 must_change_password, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                username,
                hash_password(password),
                display_name.strip(),
                status_value,
                int(must_change_password),
                now,
                now,
            ),
        )
        assignment = connection.execute(
            """
            INSERT INTO user_roles (user_id, role_id)
            SELECT ?, id FROM roles WHERE code = ?
            """,
            (user_id, role),
        )
        if assignment.rowcount != 1:
            raise RuntimeError(f"role is not initialized: {role}")
        return user_id

    def register_user(self, *, username: str, password: str, display_name: str = "") -> dict[str, object]:
        return self.create_user(
            username=username,
            password=password,
            role="viewer",
            status_value="pending",
            display_name=display_name,
        )

    def login(self, *, username: str, password: str) -> tuple[AuthPrincipal, str, str]:
        row = self.database.query_one("SELECT * FROM users WHERE username = ?", (username.strip(),))
        if not row or not verify_password(password, row["password_hash"]):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid username or password")
        if row["status"] == "pending":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="registration is pending approval")
        if row["status"] != "active":
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="user is disabled")
        token = secrets.token_urlsafe(32)
        session_id = str(uuid4())
        expires_at = (utc_now() + timedelta(hours=self.session_ttl_hours)).isoformat()
        self.database.execute(
            "INSERT INTO auth_sessions (id, user_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, row["id"], hash_secret(token), expires_at, iso_now()),
        )
        return self._build_principal(row, auth_type="session"), token, expires_at

    def logout(self, token: str | None) -> None:
        if not token:
            return
        self.database.execute("DELETE FROM auth_sessions WHERE token_hash = ?", (hash_secret(token),))

    def me(self, principal: AuthPrincipal) -> dict[str, object]:
        return {
            "id": principal.id,
            "username": principal.username,
            "display_name": principal.display_name,
            "role": principal.role,
            "roles": list(principal.roles or (principal.role,)),
            "permissions": list(principal.permissions),
            "status": principal.status,
            "must_change_password": principal.must_change_password,
            "auth_type": principal.auth_type,
            "token_id": principal.token_id,
            "scopes": list(principal.scopes),
        }

    def create_api_token(self, *, principal: AuthPrincipal, name: str, scopes: list[str], expires_at: str | None = None) -> dict[str, object]:
        name = name.strip() or "API Token"
        requested_scopes = self._normalize_api_token_scopes(
            principal=principal,
            scopes=scopes,
            allow_default=True,
        )
        token = f"lgt_{secrets.token_urlsafe(32)}"
        token_id = str(uuid4())
        created_at = iso_now()
        self.database.execute(
            """
            INSERT INTO api_tokens
                (id, user_id, name, token_hash, token_prefix, scopes_json,
                 expires_at, revoked_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """,
            (
                token_id,
                principal.id,
                name,
                hash_secret(token),
                f"{token[:9]}…",
                json.dumps(requested_scopes),
                expires_at,
                created_at,
            ),
        )
        return {
            "id": token_id,
            "name": name,
            "username": principal.username,
            "token_prefix": f"{token[:9]}…",
            "scopes": requested_scopes,
            "expires_at": expires_at,
            "revoked_at": None,
            "last_used_at": None,
            "created_at": created_at,
            "token": token,
        }

    def update_api_token_scopes(
        self,
        token_id: str,
        *,
        principal: AuthPrincipal,
        scopes: list[str],
    ) -> tuple[dict[str, object], list[str]]:
        row = self.database.query_one(
            """
            SELECT api_tokens.*, users.username
            FROM api_tokens
            JOIN users ON users.id = api_tokens.user_id
            WHERE api_tokens.id = ?
            """,
            (token_id,),
        )
        if not row or row["user_id"] != principal.id:
            raise KeyError(f"API token not found: {token_id}")
        if row["revoked_at"]:
            raise ValueError("revoked API token scopes cannot be updated")
        if _is_expired(row["expires_at"]):
            raise ValueError("expired API token scopes cannot be updated")

        requested_scopes = self._normalize_api_token_scopes(
            principal=principal,
            scopes=scopes,
            allow_default=False,
        )
        previous_scopes = list(json.loads(row["scopes_json"] or "[]"))
        self.database.execute(
            "UPDATE api_tokens SET scopes_json = ? WHERE id = ?",
            (json.dumps(requested_scopes), token_id),
        )
        return (
            {
                "id": row["id"],
                "name": row["name"],
                "username": row["username"],
                "token_prefix": row["token_prefix"],
                "scopes": requested_scopes,
                "expires_at": row["expires_at"],
                "revoked_at": row["revoked_at"],
                "last_used_at": row["last_used_at"],
                "created_at": row["created_at"],
            },
            previous_scopes,
        )

    @staticmethod
    def _normalize_api_token_scopes(
        *,
        principal: AuthPrincipal,
        scopes: list[str],
        allow_default: bool,
    ) -> list[str]:
        requested_scopes = sorted({scope.strip() for scope in scopes if scope.strip()})
        if not requested_scopes:
            if allow_default:
                requested_scopes = ["tools.read"]
            else:
                raise ValueError("at least one scope is required")
        allowed_scopes = set(principal.permissions)
        if principal.auth_type == "token":
            parent_scopes = set(principal.scopes)
            if "*" not in parent_scopes:
                allowed_scopes &= parent_scopes
            else:
                allowed_scopes.add("*")
        elif principal.role == "admin" or "admin" in principal.roles:
            allowed_scopes.add("*")
        invalid_scopes = set(requested_scopes) - allowed_scopes
        if invalid_scopes:
            raise ValueError(f"scope exceeds user permissions: {', '.join(sorted(invalid_scopes))}")
        return requested_scopes

    def list_api_tokens(self, *, user_id: str | None = None) -> list[dict[str, object]]:
        where = "WHERE api_tokens.user_id = ?" if user_id else ""
        parameters = (user_id,) if user_id else ()
        rows = self.database.query_all(
            f"""
            SELECT api_tokens.id, api_tokens.name, api_tokens.token_prefix,
                   api_tokens.scopes_json, api_tokens.expires_at, api_tokens.revoked_at,
                   api_tokens.last_used_at, api_tokens.created_at, users.username
            FROM api_tokens
            JOIN users ON users.id = api_tokens.user_id
            {where}
            ORDER BY api_tokens.created_at DESC
            """,
            parameters,
        )
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "username": row["username"],
                "token_prefix": row["token_prefix"],
                "scopes": json.loads(row["scopes_json"] or "[]"),
                "expires_at": row["expires_at"],
                "revoked_at": row["revoked_at"],
                "last_used_at": row["last_used_at"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def revoke_api_token(self, token_id: str, *, user_id: str | None = None) -> dict[str, object]:
        row = self.database.query_one("SELECT * FROM api_tokens WHERE id = ?", (token_id,))
        if not row:
            raise KeyError(f"API token not found: {token_id}")
        if user_id and row["user_id"] != user_id:
            raise KeyError(f"API token not found: {token_id}")
        revoked_at = iso_now()
        self.database.execute("UPDATE api_tokens SET revoked_at = ? WHERE id = ?", (revoked_at, token_id))
        return {
            "id": row["id"],
            "name": row["name"],
            "token_prefix": row["token_prefix"],
            "scopes": json.loads(row["scopes_json"] or "[]"),
            "expires_at": row["expires_at"],
            "revoked_at": revoked_at,
            "last_used_at": row["last_used_at"],
            "created_at": row["created_at"],
        }

    def list_users(self) -> list[dict[str, object]]:
        rows = self.database.query_all("SELECT * FROM users ORDER BY created_at DESC")
        return [self._user_row_to_dict(row) for row in rows]

    def get_user(self, user_id: str) -> dict[str, object]:
        row = self.database.query_one("SELECT * FROM users WHERE id = ?", (user_id,))
        if not row:
            raise KeyError(f"user not found: {user_id}")
        return self._user_row_to_dict(row)

    def update_user(
        self,
        user_id: str,
        *,
        display_name: str | None = None,
        status_value: str | None = None,
    ) -> dict[str, object]:
        row = self.database.query_one("SELECT * FROM users WHERE id = ?", (user_id,))
        if not row:
            raise KeyError(f"user not found: {user_id}")
        if status_value is not None and status_value not in USER_STATUSES:
            raise ValueError(f"invalid user status: {status_value}")
        next_display_name = row["display_name"] if display_name is None else display_name.strip()
        next_status = row["status"] if status_value is None else status_value
        self.database.execute(
            "UPDATE users SET display_name = ?, status = ?, updated_at = ? WHERE id = ?",
            (next_display_name, next_status, iso_now(), user_id),
        )
        if next_status != "active":
            self.database.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
        return self.get_user(user_id)

    def validate_admin_transition(
        self,
        user_id: str,
        *,
        status_value: str | None,
        roles: Iterable[str] | None,
    ) -> None:
        user = self.get_user(user_id)
        current_roles = set(cast(Iterable[str], user["roles"]))
        next_roles = current_roles if roles is None else {str(role) for role in roles}
        next_status = str(user["status"]) if status_value is None else status_value
        if "admin" not in current_roles or (next_status == "active" and "admin" in next_roles):
            return
        row = self.database.query_one(
            """
            SELECT COUNT(DISTINCT users.id) AS total
            FROM users
            JOIN user_roles ON user_roles.user_id = users.id
            JOIN roles ON roles.id = user_roles.role_id
            WHERE users.status = 'active' AND roles.code = 'admin' AND users.id <> ?
            """,
            (user_id,),
        )
        if not row or int(row["total"]) == 0:
            raise ValueError("the last active admin cannot be disabled or lose the admin role")

    def change_password(self, user_id: str, password: str) -> None:
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters")
        row = self.database.query_one(
            "SELECT id, username, must_change_password FROM users WHERE id = ?",
            (user_id,),
        )
        if not row:
            raise KeyError(f"user not found: {user_id}")
        self.database.execute(
            """
            UPDATE users
            SET password_hash = ?, must_change_password = 0, updated_at = ?
            WHERE id = ?
            """,
            (hash_password(password), iso_now(), user_id),
        )
        # 改密后撤销已有会话，要求使用新密码重新登录。
        self.database.execute("DELETE FROM auth_sessions WHERE user_id = ?", (user_id,))
        if row["username"] == "admin" and bool(row["must_change_password"]):
            self.initial_admin_credentials_path.unlink(missing_ok=True)

    def authenticate_request(self, request: Request) -> AuthPrincipal:
        if not self.enabled:
            return AuthPrincipal(
                id="system",
                username="auth-disabled",
                role="admin",
                auth_type="disabled",
                roles=("admin",),
                permissions=("*",),
            )
        if not self.has_users():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="authentication state is unavailable",
            )

        bearer = self._bearer_token(request)
        if bearer:
            principal = self._principal_from_api_token(bearer)
            if principal:
                return self._enforce_password_change(principal, request)

        session_token = request.cookies.get(self.cookie_name)
        if session_token:
            principal = self._principal_from_session(session_token)
            if principal:
                return self._enforce_password_change(principal, request)

        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required")

    @staticmethod
    def _enforce_password_change(principal: AuthPrincipal, request: Request) -> AuthPrincipal:
        allowed_paths = {"/v1/auth/me", "/v1/auth/password", "/v1/auth/logout"}
        if principal.must_change_password and request.url.path not in allowed_paths:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="password change required",
            )
        return principal

    def _principal_from_session(self, token: str) -> AuthPrincipal | None:
        row = self.database.query_one(
            """
            SELECT users.*, auth_sessions.expires_at AS session_expires_at
            FROM auth_sessions
            JOIN users ON users.id = auth_sessions.user_id
            WHERE auth_sessions.token_hash = ?
            """,
            (hash_secret(token),),
        )
        if not row or row["status"] != "active" or _is_expired(row["session_expires_at"]):
            return None
        return self._build_principal(row, auth_type="session")

    def _principal_from_api_token(self, token: str) -> AuthPrincipal | None:
        row = self.database.query_one(
            """
            SELECT users.*, api_tokens.id AS token_id, api_tokens.scopes_json,
                   api_tokens.expires_at AS token_expires_at, api_tokens.revoked_at
            FROM api_tokens
            JOIN users ON users.id = api_tokens.user_id
            WHERE api_tokens.token_hash = ?
            """,
            (hash_secret(token),),
        )
        if not row or row["status"] != "active" or row["revoked_at"] or _is_expired(row["token_expires_at"]):
            return None
        self.database.execute("UPDATE api_tokens SET last_used_at = ? WHERE id = ?", (iso_now(), row["token_id"]))
        return self._build_principal(
            row,
            auth_type="token",
            token_id=row["token_id"],
            scopes=tuple(json.loads(row["scopes_json"] or "[]")),
        )

    def _build_principal(
        self,
        row: object,
        *,
        auth_type: str,
        token_id: str | None = None,
        scopes: tuple[str, ...] = (),
    ) -> AuthPrincipal:
        user_id = row["id"]  # type: ignore[index]
        roles = tuple(self._roles_for_user(user_id))
        if not roles:
            raise RuntimeError(f"user has no enabled role: {user_id}")
        permissions = tuple(self._permissions_for_user(user_id))
        return AuthPrincipal(
            id=user_id,
            username=row["username"],  # type: ignore[index]
            display_name=row["display_name"],  # type: ignore[index]
            role=roles[0],
            status=row["status"],  # type: ignore[index]
            auth_type=auth_type,
            roles=roles,
            permissions=permissions,
            must_change_password=bool(row["must_change_password"]),  # type: ignore[index]
            token_id=token_id,
            scopes=scopes,
        )

    def _user_row_to_dict(self, row: object) -> dict[str, object]:
        user_id = row["id"]  # type: ignore[index]
        roles = self._roles_for_user(user_id)
        if not roles:
            raise RuntimeError(f"user has no enabled role: {user_id}")
        return {
            "id": user_id,
            "username": row["username"],  # type: ignore[index]
            "display_name": row["display_name"],  # type: ignore[index]
            "role": roles[0],
            "roles": roles,
            "status": row["status"],  # type: ignore[index]
            "must_change_password": bool(row["must_change_password"]),  # type: ignore[index]
            "created_at": row["created_at"],  # type: ignore[index]
            "updated_at": row["updated_at"],  # type: ignore[index]
        }

    def _roles_for_user(self, user_id: str) -> list[str]:
        rows = self.database.query_all(
            """
            SELECT roles.code
            FROM user_roles
            JOIN roles ON roles.id = user_roles.role_id
            WHERE user_roles.user_id = ? AND roles.enabled = 1
            ORDER BY roles.is_system DESC, roles.code
            """,
            (user_id,),
        )
        return [str(row["code"]) for row in rows]

    def _permissions_for_user(self, user_id: str) -> list[str]:
        rows = self.database.query_all(
            """
            SELECT DISTINCT control_permissions.code
            FROM user_roles
            JOIN roles ON roles.id = user_roles.role_id AND roles.enabled = 1
            JOIN role_permissions ON role_permissions.role_id = roles.id
            JOIN control_permissions ON control_permissions.id = role_permissions.permission_id
            WHERE user_roles.user_id = ?
            ORDER BY control_permissions.code
            """,
            (user_id,),
        )
        return [str(row["code"]) for row in rows]

    def _bearer_token(self, request: Request) -> str | None:
        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return None
        return header.split(" ", 1)[1].strip() or None


def _is_expired(value: str | None) -> bool:
    if not value:
        return False
    try:
        expires_at = datetime.fromisoformat(value)
    except ValueError:
        return True
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= utc_now()

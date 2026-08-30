"""Gate 通用工具文件中转存储。"""

from __future__ import annotations

import hashlib
import os
import shutil
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from lingshu_gate.database import SQLiteDatabase

MAX_TOOL_FILE_BYTES = 4 * 1024 * 1024
MAX_TOOL_FILE_CHUNK_BYTES = 512 * 1024
TRANSFER_TTL = timedelta(hours=2)
FILE_TTL = timedelta(minutes=30)


class ToolFileError(RuntimeError):
    """带稳定错误码的通用文件错误。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _parse(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _safe_filename(filename: str) -> str:
    value = filename.strip()
    if not value or value in {".", ".."} or len(value) > 255:
        raise ToolFileError("invalid_filename", "filename 必须是 1 到 255 个字符的纯文件名")
    if Path(value).name != value or "/" in value or "\\" in value or "\x00" in value:
        raise ToolFileError("invalid_filename", "filename 不能包含路径或空字符")
    return value


class ToolFileStore:
    """持久化分块上传状态，并将已提交文件绑定到调用用户。"""

    def __init__(self, database: SQLiteDatabase, data_dir: Path) -> None:
        self.database = database
        self.root = (data_dir / "tool-files").resolve()
        self.transfer_root = self.root / "transfers"
        self.file_root = self.root / "files"
        self.transfer_root.mkdir(parents=True, exist_ok=True)
        self.file_root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    def _initialize(self) -> None:
        with self.database.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tool_file_transfers (
                    id TEXT PRIMARY KEY,
                    actor_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    received_bytes INTEGER NOT NULL DEFAULT 0,
                    status TEXT NOT NULL,
                    begin_idempotency_key TEXT NOT NULL,
                    commit_idempotency_key TEXT,
                    file_ref TEXT,
                    temp_path TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(actor_id, begin_idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS tool_file_chunks (
                    transfer_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    offset_bytes INTEGER NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(transfer_id, idempotency_key)
                );
                CREATE TABLE IF NOT EXISTS tool_files (
                    file_ref TEXT PRIMARY KEY,
                    actor_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    sha256 TEXT NOT NULL,
                    file_path TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tool_files_actor
                    ON tool_files(actor_id, expires_at);
                """
            )

    def cleanup_expired(self) -> None:
        now = _now()
        with self._lock, self.database.connect() as connection:
            transfers = connection.execute(
                "SELECT id, temp_path FROM tool_file_transfers WHERE expires_at <= ?",
                (_iso(now),),
            ).fetchall()
            files = connection.execute(
                "SELECT file_ref, file_path FROM tool_files WHERE expires_at <= ?",
                (_iso(now),),
            ).fetchall()
            for row in transfers:
                Path(row["temp_path"]).unlink(missing_ok=True)
                connection.execute("DELETE FROM tool_file_chunks WHERE transfer_id = ?", (row["id"],))
                connection.execute("DELETE FROM tool_file_transfers WHERE id = ?", (row["id"],))
            for row in files:
                file_path = Path(row["file_path"])
                file_path.unlink(missing_ok=True)
                shutil.rmtree(file_path.parent, ignore_errors=True)
                connection.execute("DELETE FROM tool_files WHERE file_ref = ?", (row["file_ref"],))

    def begin(
        self,
        *,
        actor_id: str,
        filename: str,
        size_bytes: int,
        sha256: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        filename = _safe_filename(filename)
        digest = sha256.lower()
        if size_bytes < 1 or size_bytes > MAX_TOOL_FILE_BYTES:
            raise ToolFileError("file_too_large", f"文件大小必须在 1 到 {MAX_TOOL_FILE_BYTES} 字节之间")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ToolFileError("invalid_sha256", "sha256 必须是 64 位十六进制字符串")
        self.cleanup_expired()
        with self._lock, self.database.connect() as connection:
            existing = connection.execute(
                "SELECT * FROM tool_file_transfers WHERE actor_id = ? AND begin_idempotency_key = ?",
                (actor_id, idempotency_key),
            ).fetchone()
            if existing:
                if (existing["filename"], existing["size_bytes"], existing["sha256"]) != (
                    filename,
                    size_bytes,
                    digest,
                ):
                    raise ToolFileError("idempotency_conflict", "幂等键已用于不同的上传请求")
                return self._transfer_result(existing)

            transfer_id = uuid4().hex
            now = _now()
            temp_path = (self.transfer_root / f"{transfer_id}.part").resolve()
            temp_path.touch(exist_ok=False)
            connection.execute(
                """
                INSERT INTO tool_file_transfers(
                    id, actor_id, filename, size_bytes, sha256, received_bytes, status,
                    begin_idempotency_key, temp_path, expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 0, 'uploading', ?, ?, ?, ?, ?)
                """,
                (
                    transfer_id,
                    actor_id,
                    filename,
                    size_bytes,
                    digest,
                    idempotency_key,
                    str(temp_path),
                    _iso(now + TRANSFER_TTL),
                    _iso(now),
                    _iso(now),
                ),
            )
            row = connection.execute("SELECT * FROM tool_file_transfers WHERE id = ?", (transfer_id,)).fetchone()
            return self._transfer_result(row)

    def append_chunk(
        self,
        *,
        actor_id: str,
        transfer_id: str,
        offset: int,
        data: bytes,
        chunk_sha256: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        if not data or len(data) > MAX_TOOL_FILE_CHUNK_BYTES:
            raise ToolFileError("invalid_chunk_size", f"分块大小必须在 1 到 {MAX_TOOL_FILE_CHUNK_BYTES} 字节之间")
        actual_digest = hashlib.sha256(data).hexdigest()
        if actual_digest != chunk_sha256.lower():
            raise ToolFileError("chunk_sha256_mismatch", "分块 SHA-256 校验失败")
        with self._lock, self.database.connect() as connection:
            row = self._owned_transfer(connection, transfer_id, actor_id)
            previous = connection.execute(
                "SELECT * FROM tool_file_chunks WHERE transfer_id = ? AND idempotency_key = ?",
                (transfer_id, idempotency_key),
            ).fetchone()
            if previous:
                if (previous["offset_bytes"], previous["size_bytes"], previous["sha256"]) != (
                    offset,
                    len(data),
                    actual_digest,
                ):
                    raise ToolFileError("idempotency_conflict", "幂等键已用于不同的文件分块")
                return self._transfer_result(row)
            if row["status"] != "uploading":
                raise ToolFileError("transfer_not_uploading", "上传会话已不处于可写状态")
            if offset != row["received_bytes"]:
                raise ToolFileError("offset_mismatch", f"offset 必须等于当前已接收字节数 {row['received_bytes']}")
            if offset + len(data) > row["size_bytes"]:
                raise ToolFileError("chunk_overflow", "分块会超过声明的文件大小")
            with Path(row["temp_path"]).open("ab") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            now = _iso(_now())
            connection.execute(
                "INSERT INTO tool_file_chunks VALUES (?, ?, ?, ?, ?, ?)",
                (transfer_id, idempotency_key, offset, len(data), actual_digest, now),
            )
            connection.execute(
                "UPDATE tool_file_transfers SET received_bytes = ?, updated_at = ? WHERE id = ?",
                (offset + len(data), now, transfer_id),
            )
            updated = connection.execute("SELECT * FROM tool_file_transfers WHERE id = ?", (transfer_id,)).fetchone()
            return self._transfer_result(updated)

    def commit(self, *, actor_id: str, transfer_id: str, idempotency_key: str) -> dict[str, object]:
        with self._lock, self.database.connect() as connection:
            row = self._owned_transfer(connection, transfer_id, actor_id)
            if row["status"] == "committed":
                if row["commit_idempotency_key"] != idempotency_key:
                    raise ToolFileError("idempotency_conflict", "上传已使用其他幂等键提交")
                return self._file_result(connection, row["file_ref"])
            if row["status"] != "uploading" or row["received_bytes"] != row["size_bytes"]:
                raise ToolFileError("upload_incomplete", "文件尚未完整上传")
            temp_path = Path(row["temp_path"])
            digest = hashlib.sha256(temp_path.read_bytes()).hexdigest()
            if digest != row["sha256"]:
                raise ToolFileError("file_sha256_mismatch", "完整文件 SHA-256 校验失败")
            file_ref = f"gate_file_{uuid4().hex}"
            target_dir = (self.file_root / file_ref).resolve()
            target_dir.mkdir(parents=True, exist_ok=False)
            target_path = target_dir / row["filename"]
            temp_path.replace(target_path)
            now = _now()
            expires_at = now + FILE_TTL
            connection.execute(
                "INSERT INTO tool_files VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    file_ref,
                    actor_id,
                    row["filename"],
                    row["size_bytes"],
                    row["sha256"],
                    str(target_path),
                    _iso(expires_at),
                    _iso(now),
                ),
            )
            connection.execute(
                """UPDATE tool_file_transfers
                   SET status = 'committed', commit_idempotency_key = ?, file_ref = ?, updated_at = ?
                   WHERE id = ?""",
                (idempotency_key, file_ref, _iso(now), transfer_id),
            )
            return self._file_result(connection, file_ref)

    def abort(self, *, actor_id: str, transfer_id: str) -> dict[str, object]:
        with self._lock, self.database.connect() as connection:
            row = self._owned_transfer(connection, transfer_id, actor_id)
            if row["status"] == "committed":
                raise ToolFileError("transfer_committed", "已提交文件不能通过 abort 删除")
            Path(row["temp_path"]).unlink(missing_ok=True)
            if row["status"] == "aborted":
                return {"status": "aborted", "transfer_id": transfer_id}
            connection.execute("DELETE FROM tool_file_chunks WHERE transfer_id = ?", (transfer_id,))
            connection.execute(
                "UPDATE tool_file_transfers SET status = 'aborted', updated_at = ? WHERE id = ?",
                (_iso(_now()), transfer_id),
            )
            return {"status": "aborted", "transfer_id": transfer_id}

    def resolve(self, *, actor_id: str, file_ref: str) -> Path:
        self.cleanup_expired()
        with self._lock, self.database.connect() as connection:
            row = connection.execute("SELECT * FROM tool_files WHERE file_ref = ?", (file_ref,)).fetchone()
            if not row:
                raise ToolFileError("file_ref_not_found", "fileRef 不存在或已过期")
            if row["actor_id"] != actor_id:
                raise ToolFileError("file_ref_forbidden", "fileRef 不属于当前用户")
            if _parse(row["expires_at"]) <= _now():
                raise ToolFileError("file_ref_expired", "fileRef 已过期")
            file_path = Path(row["file_path"]).resolve()
            try:
                file_path.relative_to(self.file_root)
            except ValueError as exc:
                raise ToolFileError("file_ref_invalid_path", "fileRef 对应路径超出 Gate 受控目录") from exc
            if not file_path.is_file() or file_path.is_symlink():
                raise ToolFileError("file_ref_unavailable", "fileRef 对应文件不可用")
            return file_path

    def prepare_tool_arguments(self, *, actor_id: str, arguments: dict[str, object]) -> dict[str, object]:
        if "fileRef" not in arguments:
            return arguments
        if "filePath" in arguments:
            raise ToolFileError("file_source_conflict", "fileRef 与 filePath 不能同时传入")
        file_ref = arguments.get("fileRef")
        if not isinstance(file_ref, str) or not file_ref.strip():
            raise ToolFileError("invalid_file_ref", "fileRef 必须是非空字符串")
        prepared = dict(arguments)
        prepared.pop("fileRef")
        prepared["filePath"] = str(self.resolve(actor_id=actor_id, file_ref=file_ref))
        return prepared

    def _owned_transfer(self, connection, transfer_id: str, actor_id: str):
        row = connection.execute("SELECT * FROM tool_file_transfers WHERE id = ?", (transfer_id,)).fetchone()
        if not row or _parse(row["expires_at"]) <= _now():
            raise ToolFileError("transfer_not_found", "上传会话不存在或已过期")
        if row["actor_id"] != actor_id:
            raise ToolFileError("transfer_forbidden", "上传会话不属于当前用户")
        return row

    @staticmethod
    def _transfer_result(row) -> dict[str, object]:
        return {
            "status": row["status"],
            "transfer_id": row["id"],
            "filename": row["filename"],
            "size_bytes": row["size_bytes"],
            "received_bytes": row["received_bytes"],
            "expires_at": row["expires_at"],
            **({"fileRef": row["file_ref"]} if row["file_ref"] else {}),
        }

    @staticmethod
    def _file_result(connection, file_ref: str) -> dict[str, object]:
        row = connection.execute("SELECT * FROM tool_files WHERE file_ref = ?", (file_ref,)).fetchone()
        return {
            "status": "committed",
            "fileRef": row["file_ref"],
            "filename": row["filename"],
            "size_bytes": row["size_bytes"],
            "sha256": row["sha256"],
            "expires_at": row["expires_at"],
        }

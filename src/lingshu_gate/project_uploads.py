"""ZIP upload and project analyzer service."""

from __future__ import annotations

import io
import json
import shutil
import stat
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO
from uuid import uuid4

from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.models import ResourceDeleteConflict

MAX_ZIP_BYTES = 50 * 1024 * 1024
MAX_FILES = 3_000
MAX_EXTRACTED_BYTES = 200 * 1024 * 1024
IGNORED_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "target", "__pycache__"}
PROJECT_MARKERS = {"package.json", "pyproject.toml", "requirements.txt", "Dockerfile"}
UPLOAD_CHUNK_BYTES = 1024 * 1024
_WINDOWS_RESERVED_NAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}


class ProjectUploadTooLarge(ValueError):
    """Raised as soon as an upload exceeds the compressed archive budget."""


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectUploadStore:
    def __init__(self, database: SQLiteDatabase, data_dir: Path) -> None:
        self.database = database
        self.data_dir = data_dir
        self.root = data_dir / "uploads"
        self.root.mkdir(parents=True, exist_ok=True)

    def save_zip(self, *, filename: str, content: bytes) -> dict[str, Any]:
        return self.save_zip_stream(filename=filename, source=io.BytesIO(content))

    def save_zip_stream(self, *, filename: str, source: BinaryIO) -> dict[str, Any]:
        """Stage a ZIP from a bounded stream before validating and extracting it."""

        _validate_upload_filename(filename)
        upload_id = str(uuid4())
        upload_dir = self.root / upload_id
        upload_dir.mkdir(parents=True, exist_ok=False)
        try:
            zip_path = upload_dir / "source.zip"
            total_compressed = 0
            with zip_path.open("xb") as destination:
                while chunk := source.read(UPLOAD_CHUNK_BYTES):
                    total_compressed += len(chunk)
                    if total_compressed > MAX_ZIP_BYTES:
                        raise ProjectUploadTooLarge(
                            f"zip too large: exceeds {MAX_ZIP_BYTES} bytes"
                        )
                    destination.write(chunk)
            extract_dir = upload_dir / "extracted"
            extract_dir.mkdir(parents=True, exist_ok=True)
            try:
                _safe_extract(zip_path, extract_dir)
            except zipfile.BadZipFile as exc:
                raise ValueError("invalid zip archive") from exc
            analysis = analyze_project(extract_dir)
            project_root = Path(str(analysis.get("project_root_dir") or extract_dir))
            now = iso_now()
            record = {"id": upload_id, "filename": filename, "status": "analyzed", "root_dir": str(project_root), "detected_runtime": analysis["detected_runtime"], "analysis": analysis, "created_at": now, "updated_at": now}
            self.database.execute(
                """
                INSERT INTO project_uploads (id, filename, status, root_dir, detected_runtime, analysis_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (record["id"], record["filename"], record["status"], record["root_dir"], record["detected_runtime"], json.dumps(record["analysis"], ensure_ascii=False), record["created_at"], record["updated_at"]),
            )
            return record
        except Exception:
            # ZIP 校验、解压或落库失败时清理本次受控目录，避免留下不可见孤儿上传。
            shutil.rmtree(upload_dir, ignore_errors=True)
            raise

    def list_uploads(self) -> list[dict[str, Any]]:
        rows = self.database.query_all("SELECT * FROM project_uploads ORDER BY created_at DESC LIMIT 100")
        return [_row_to_dict(row) for row in rows]

    def get_upload(self, upload_id: str) -> dict[str, Any]:
        row = self.database.query_one("SELECT * FROM project_uploads WHERE id = ?", (upload_id,))
        if not row:
            raise KeyError(f"upload not found: {upload_id}")
        return _row_to_dict(row)

    def analyze_upload(self, upload_id: str) -> dict[str, Any]:
        record = self.get_upload(upload_id)
        root = Path(record["root_dir"])
        analysis = analyze_project(root)
        project_root = Path(str(analysis.get("project_root_dir") or root))
        now = iso_now()
        self.database.execute("UPDATE project_uploads SET status = ?, root_dir = ?, detected_runtime = ?, analysis_json = ?, updated_at = ? WHERE id = ?", ("analyzed", str(project_root), analysis["detected_runtime"], json.dumps(analysis, ensure_ascii=False), now, upload_id))
        record.update({"status": "analyzed", "root_dir": str(project_root), "detected_runtime": analysis["detected_runtime"], "analysis": analysis, "updated_at": now})
        return record

    def draft_manifest(self, upload_id: str) -> dict[str, Any]:
        """Generate a deterministic manifest draft from the uploaded project."""

        return self._draft_manifest_heuristic(upload_id)

    def delete_upload(self, upload_id: str) -> dict[str, Any]:
        record = self.get_upload(upload_id)
        build_rows = self.database.query_all(
            "SELECT id, status FROM builds WHERE upload_id = ? ORDER BY created_at DESC",
            (upload_id,),
        )
        if build_rows:
            build_ids = [str(row["id"]) for row in build_rows]
            active_build_ids = [str(row["id"]) for row in build_rows if str(row["status"]) in {"queued", "running", "cancel_requested"}]
            raise ResourceDeleteConflict(
                code="project_upload_has_builds",
                message=f"项目上传仍关联 {len(build_ids)} 条构建记录，请先删除这些构建记录。",
                resource_type="project_upload",
                resource_id=upload_id,
                dependencies={"build_count": len(build_ids), "build_ids": build_ids, "active_build_ids": active_build_ids},
            )

        # 上传分析得到的 root_dir 可能位于 extracted 的任意子目录，删除路径必须始终
        # 从受控 uploads 根目录和 upload_id 推导，不能再依赖 root_dir.parent。
        uploads_root = self.root.resolve()
        upload_dir = (self.root / upload_id).resolve()
        if upload_dir.parent != uploads_root:
            raise ValueError(f"unsafe upload directory: {upload_dir}")

        trash_dir: Path | None = None
        if upload_dir.exists():
            if not upload_dir.is_dir():
                raise ValueError(f"upload path is not a directory: {upload_dir}")
            trash_root = self.root / ".trash"
            trash_root.mkdir(parents=True, exist_ok=True)
            trash_dir = trash_root / f"{upload_id}-{uuid4().hex}"
            upload_dir.replace(trash_dir)

        try:
            # 缓存没有独立业务价值，和上传记录在同一事务内清理。
            with self.database.connect() as connection:
                connection.execute("DELETE FROM preflight_cache WHERE upload_id = ?", (upload_id,))
                connection.execute("DELETE FROM project_uploads WHERE id = ?", (upload_id,))
                connection.commit()
        except Exception:
            if trash_dir is not None and trash_dir.exists() and not upload_dir.exists():
                trash_dir.replace(upload_dir)
            raise

        if trash_dir is not None:
            # 数据库删除已提交；垃圾目录清理失败不应让调用方误以为记录仍然存在。
            shutil.rmtree(trash_dir, ignore_errors=True)
        return record

    def _draft_manifest_heuristic(self, upload_id: str) -> dict[str, Any]:
        record = self.get_upload(upload_id)
        analysis = record["analysis"]
        server_id = _safe_id(Path(record["filename"]).stem or "uploaded-mcp")
        runtime = analysis.get("detected_runtime", "unknown")
        command = "python"
        args: list[str] = ["server.py"]
        cwd = record["root_dir"]
        if runtime == "node":
            command = "npm"
            scripts = analysis.get("package_json", {}).get("scripts", {}) if isinstance(analysis.get("package_json"), dict) else {}
            args = ["run", "start"] if "start" in scripts else ["exec", "node", "index.js"]
        elif runtime == "python":
            entry = analysis.get("python_entrypoint") or "server.py"
            command = "python"
            args = [entry]
        elif runtime == "docker":
            return {
                "id": server_id,
                "name": f"Uploaded {server_id}",
                "enabled": True,
                "launch": {
                    "type": "managed_container",
                    # Project contents do not prove an immutable registry image.
                    # The operator must supply and review a digest-pinned reference.
                    "image": None,
                },
                "transport": {"type": "stdio"},
                "timeout_seconds": 120,
                "auto_start": False,
                "analysis": {
                    "detected_runtime": runtime,
                    "upload_id": upload_id,
                    "draft_source": "heuristic",
                    "requires_digest_pinned_image": True,
                },
            }
        return {"id": server_id, "name": f"Uploaded {server_id}", "enabled": True, "launch": {"type": "managed_process", "command": command, "args": args, "cwd": cwd}, "transport": {"type": "stdio"}, "timeout_seconds": 120, "auto_start": False, "analysis": {"detected_runtime": runtime, "upload_id": upload_id, "draft_source": "heuristic"}}


def analyze_project(root: Path) -> dict[str, Any]:
    scan_root = _find_project_root(root)
    files = _scan_files(scan_root)
    names = {item["path"] for item in files}
    detected = "unknown"
    package_json: dict[str, Any] = {}
    pyproject: dict[str, Any] = {}
    python_entrypoint = ""
    if "package.json" in names:
        detected = "node"
        try:
            package_json = json.loads((scan_root / "package.json").read_text(encoding="utf-8"))
        except Exception:
            package_json = {}
    elif "pyproject.toml" in names or "requirements.txt" in names:
        detected = "python"
        for candidate in ["server.py", "main.py", "app.py"]:
            if candidate in names:
                python_entrypoint = candidate
                break
    elif "Dockerfile" in names:
        detected = "docker"
    readme = ""
    for candidate in ["README.md", "readme.md", "README.txt"]:
        path = scan_root / candidate
        if path.exists():
            readme = path.read_text(encoding="utf-8", errors="ignore")[:8000]
            break
    project_root = ""
    try:
        project_root = scan_root.relative_to(root).as_posix()
    except ValueError:
        project_root = ""
    return {"detected_runtime": detected, "project_root": project_root, "project_root_dir": str(scan_root), "files": files[:500], "file_count": len(files), "has_package_json": "package.json" in names, "has_pyproject": "pyproject.toml" in names, "has_requirements": "requirements.txt" in names, "has_dockerfile": "Dockerfile" in names, "package_json": package_json, "pyproject": pyproject, "python_entrypoint": python_entrypoint, "readme_excerpt": readme}


def _find_project_root(root: Path) -> Path:
    """Locate the project root: the shallowest directory containing a marker.

    Markers (package.json/pyproject.toml/requirements.txt/Dockerfile) are matched
    at any depth, so archives that nest the project under one or more wrapper
    directories (e.g. nested-project/server/package.json) resolve to the directory that
    actually holds the marker. Ties break by marker score then path.
    """

    files = _scan_files(root)
    best_key: tuple[int, int, str] | None = None
    best_parent: PurePosixPath | None = None
    for item in files:
        path = PurePosixPath(item["path"])
        if path.name not in PROJECT_MARKERS:
            continue
        parent = path.parent
        depth = len(parent.parts)
        score = 3 if path.name == "package.json" else 2 if path.name in {"pyproject.toml", "requirements.txt"} else 1
        key = (depth, -score, str(parent))
        if best_key is None or key < best_key:
            best_key = key
            best_parent = parent
    if best_parent is not None:
        if not best_parent.parts:
            return root
        candidate = root / Path(*best_parent.parts)
        if candidate.exists() and candidate.is_dir():
            return candidate
    top_dirs = {PurePosixPath(item["path"]).parts[0] for item in files if PurePosixPath(item["path"]).parts}
    if len(top_dirs) == 1:
        candidate = root / next(iter(top_dirs))
        if candidate.exists() and candidate.is_dir():
            return candidate
    return root


def _scan_files(root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if any(part in IGNORED_DIRS for part in rel.parts):
            continue
        if path.is_file():
            result.append({"path": rel.as_posix(), "size": path.stat().st_size})
    return sorted(result, key=lambda item: item["path"])


def _safe_extract(zip_path: Path, target: Path) -> None:
    target_root = target.resolve()
    total_size = 0
    with zipfile.ZipFile(zip_path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_FILES:
            raise ValueError(f"too many files in zip: {len(infos)}")
        planned: list[tuple[zipfile.ZipInfo, tuple[str, ...], str, bool]] = []
        entries: dict[str, bool] = {}
        for info in infos:
            parts, alias = _validated_zip_member(info)
            is_directory = info.is_dir()
            if alias in entries:
                raise ValueError(f"duplicate or aliased zip path: {info.filename}")
            for offset in range(1, len(parts)):
                ancestor = "/".join(
                    unicodedata.normalize("NFC", part).casefold()
                    for part in parts[:offset]
                )
                if entries.get(ancestor) is False:
                    raise ValueError(f"zip path has a file ancestor: {info.filename}")
            if not is_directory and any(
                existing.startswith(f"{alias}/") for existing in entries
            ):
                raise ValueError(f"zip file collides with a directory: {info.filename}")
            entries[alias] = is_directory
            planned.append((info, parts, alias, is_directory))
            if is_directory:
                continue
            total_size += info.file_size
            if total_size > MAX_EXTRACTED_BYTES:
                raise ValueError("extracted content too large")

        ignored = {item.casefold() for item in IGNORED_DIRS}
        for info, parts, _alias, is_directory in planned:
            if is_directory or any(part.casefold() in ignored for part in parts):
                continue
            destination = (target_root / Path(*parts)).resolve()
            try:
                destination.relative_to(target_root)
            except ValueError as exc:
                raise ValueError(f"unsafe zip path: {info.filename}") from exc
            if destination == target_root:
                raise ValueError(f"unsafe zip path: {info.filename}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                destination.parent.resolve().relative_to(target_root)
            except ValueError as exc:
                raise ValueError(f"unsafe zip path: {info.filename}") from exc
            with archive.open(info) as source, destination.open("wb") as dest:
                remaining = info.file_size
                while chunk := source.read(min(UPLOAD_CHUNK_BYTES, remaining + 1)):
                    remaining -= len(chunk)
                    if remaining < 0:
                        raise ValueError(f"zip member exceeds declared size: {info.filename}")
                    dest.write(chunk)
                if remaining != 0:
                    raise ValueError(f"zip member size mismatch: {info.filename}")


def _validated_zip_member(info: zipfile.ZipInfo) -> tuple[tuple[str, ...], str]:
    raw_name = info.filename
    if (
        not raw_name
        or "\\" in raw_name
        or "//" in raw_name
        or raw_name.startswith("/")
        or any(ord(character) < 32 or ord(character) == 127 for character in raw_name)
    ):
        raise ValueError(f"unsafe zip path: {raw_name}")
    mode = info.external_attr >> 16
    file_type = stat.S_IFMT(mode)
    if file_type not in {0, stat.S_IFREG, stat.S_IFDIR} or info.flag_bits & 0x1:
        raise ValueError(f"unsupported zip entry: {raw_name}")

    path = PurePosixPath(raw_name)
    raw_parts = tuple(part for part in path.parts if part != "")
    if (
        path.is_absolute()
        or not raw_parts
        or len(raw_parts) > 128
        or len(raw_name) > 4096
        or any(part in {".", ".."} for part in raw_parts)
    ):
        raise ValueError(f"unsafe zip path: {raw_name}")
    parts: list[str] = []
    for part in raw_parts:
        normalized = unicodedata.normalize("NFC", part)
        if (
            part != normalized
            or len(part) > 255
            or part.rstrip(" .") != part
            or any(character in '<>:"|?*' for character in part)
            or not part
            or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_NAMES
        ):
            raise ValueError(f"unsafe zip path: {raw_name}")
        parts.append(part)
    return tuple(parts), "/".join(part.casefold() for part in parts)


def _validate_upload_filename(filename: str) -> None:
    if (
        not filename
        or len(filename) > 255
        or not filename.casefold().endswith(".zip")
        or any(ord(character) < 32 or ord(character) == 127 for character in filename)
    ):
        raise ValueError("upload filename must be a valid .zip name")


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {"id": row["id"], "filename": row["filename"], "status": row["status"], "root_dir": row["root_dir"], "detected_runtime": row["detected_runtime"], "analysis": json.loads(row["analysis_json"] or "{}"), "created_at": row["created_at"], "updated_at": row["updated_at"]}


def _safe_id(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in value).strip("-._")
    return cleaned or "uploaded-mcp"

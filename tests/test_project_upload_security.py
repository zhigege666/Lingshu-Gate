from __future__ import annotations

import io
import stat
import unicodedata
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.interfaces.control_api.project_routes import register_project_routes
from lingshu_gate.project_uploads import ProjectUploadStore, ProjectUploadTooLarge


class _ObservabilityStub:
    def emit_event(self, *_args: object, **_kwargs: object) -> None:
        pass


def _zip_bytes(*entries: tuple[str, bytes]) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return stream.getvalue()


@pytest.mark.parametrize(
    "member_name",
    [
        "../extracted-evil/payload.txt",
        "folder\\..\\payload.txt",
        "C:/payload.txt",
        "//host/share/payload.txt",
        "folder//payload.txt",
        "folder/payload.txt.",
        "folder/payload.txt ",
        "folder/payload?.txt",
        "folder/con.txt",
        "folder/control\x1f.txt",
    ],
)
def test_zip_rejects_cross_platform_unsafe_paths(tmp_path: Path, member_name: str) -> None:
    store = ProjectUploadStore(SQLiteDatabase("", tmp_path), tmp_path)

    with pytest.raises(ValueError, match="unsafe zip path"):
        store.save_zip(filename="unsafe.zip", content=_zip_bytes((member_name, b"payload")))

    assert list(store.root.iterdir()) == []


def test_zip_rejects_casefold_and_file_ancestor_aliases(tmp_path: Path) -> None:
    store = ProjectUploadStore(SQLiteDatabase("", tmp_path), tmp_path)

    for archive in (
        _zip_bytes(("Readme.md", b"one"), ("README.md", b"two")),
        _zip_bytes(("folder", b"file"), ("folder/item.txt", b"child")),
    ):
        with pytest.raises(ValueError, match="duplicate|ancestor"):
            store.save_zip(filename="aliases.zip", content=archive)


def test_zip_rejects_non_normalized_unicode_name(tmp_path: Path) -> None:
    store = ProjectUploadStore(SQLiteDatabase("", tmp_path), tmp_path)
    decomposed = unicodedata.normalize("NFD", "café.txt")
    assert decomposed != unicodedata.normalize("NFC", decomposed)

    with pytest.raises(ValueError, match="unsafe zip path"):
        store.save_zip(filename="unicode.zip", content=_zip_bytes((decomposed, b"payload")))


def test_zip_rejects_link_entries(tmp_path: Path) -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        member = zipfile.ZipInfo("link")
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(member, "target")
    store = ProjectUploadStore(SQLiteDatabase("", tmp_path), tmp_path)

    with pytest.raises(ValueError, match="unsupported zip entry"):
        store.save_zip(filename="link.zip", content=stream.getvalue())


def test_streaming_upload_stops_at_compressed_budget_and_cleans_up(tmp_path: Path) -> None:
    store = ProjectUploadStore(SQLiteDatabase("", tmp_path), tmp_path)

    with (
        patch("lingshu_gate.project_uploads.MAX_ZIP_BYTES", 8),
        patch("lingshu_gate.project_uploads.UPLOAD_CHUNK_BYTES", 4),
        pytest.raises(ProjectUploadTooLarge),
    ):
        store.save_zip_stream(filename="large.zip", source=io.BytesIO(b"123456789"))

    assert list(store.root.iterdir()) == []


def test_upload_route_returns_payload_too_large_without_full_body_read(tmp_path: Path) -> None:
    database = SQLiteDatabase("", tmp_path)
    app = FastAPI()
    register_project_routes(
        app,
        project_upload_store=ProjectUploadStore(database, tmp_path),
        observability_store=_ObservabilityStub(),  # type: ignore[arg-type]
        require_operations_manager=lambda: None,
    )

    with patch("lingshu_gate.project_uploads.MAX_ZIP_BYTES", 8):
        response = TestClient(app).post(
            "/v1/projects/upload",
            files={"file": ("large.zip", b"123456789", "application/zip")},
        )

    assert response.status_code == 413
    assert list((tmp_path / "uploads").iterdir()) == []


def test_valid_zip_extracts_inside_controlled_upload_root(tmp_path: Path) -> None:
    store = ProjectUploadStore(SQLiteDatabase("", tmp_path), tmp_path)

    record = store.save_zip(
        filename="project.zip",
        content=_zip_bytes(("project/pyproject.toml", b"[project]\nname='demo'\n")),
    )

    root = Path(record["root_dir"])
    root.relative_to(store.root.resolve())
    assert (root / "pyproject.toml").read_text(encoding="utf-8") == "[project]\nname='demo'\n"

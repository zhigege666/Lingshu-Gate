"""Build and install wheels in private staging, with exact static inventories."""

from __future__ import annotations

import atexit
import base64
import csv
import hashlib
import io
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

from setuptools.command.build_py import build_py
from setuptools.command.bdist_wheel import bdist_wheel


def _static_inventory(package: Path) -> dict[str, str]:
    static = (package / "static").absolute()
    for directory in (static, *static.parents):
        if directory.is_symlink():
            raise RuntimeError(f"Wheel static assets contain a symlink: {directory}")
    if static.is_dir() and any(path.name not in {"console", "oauth"} for path in static.iterdir()):
        raise RuntimeError("Wheel static assets contain an unexpected entry outside Console/OAuth")
    inventory: dict[str, str] = {}
    for name, entry in (("console", "index.html"), ("oauth", "oauth.html")):
        root = package / "static" / name
        if root.is_symlink():
            raise RuntimeError(f"Wheel static assets contain a symlink: static/{name}")
        if not root.is_dir() or not (root / entry).is_file():
            raise RuntimeError(
                "Wheel Console/OAuth assets are missing; run npm --prefix web ci "
                "and npm --prefix web run build before building the wheel"
            )
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(package).as_posix()
            if path.is_symlink():
                raise RuntimeError(f"Wheel static assets contain a symlink: {relative}")
            if path.is_dir():
                continue
            if not path.is_file():
                raise RuntimeError(f"Wheel static assets contain a special entry: {relative}")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            inventory[relative] = digest.hexdigest()
    return inventory


def _verify_static_inventory(package: Path, expected: dict[str, str]) -> None:
    actual = _static_inventory(package)
    if actual != expected:
        missing = len(expected.keys() - actual.keys())
        extra = len(actual.keys() - expected.keys())
        changed = sum(actual[path] != expected[path] for path in actual.keys() & expected.keys())
        raise RuntimeError(
            f"Wheel static assets do not match the source snapshot: "
            f"{missing} missing, {extra} extra, {changed} changed"
        )


def _verify_wheel_archive(wheel: Path, expected: dict[str, str]) -> None:
    """Check the final zip and RECORD before exposing it as a build result."""
    with ZipFile(wheel) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or any(
            name.startswith("/") or "\\" in name or ":" in name
            or ".." in PurePosixPath(name).parts or str(PurePosixPath(name)) != name
            for name in names
        ):
            raise RuntimeError("Wheel archive contains duplicate or unsafe paths")
        actual = {
            name.removeprefix("lingshu_gate/"): hashlib.sha256(archive.read(name)).hexdigest()
            for name in names if name.startswith("lingshu_gate/static/")
        }
        if actual != expected:
            raise RuntimeError("Wheel archive static assets do not match the source snapshot")
        records = [name for name in names if name.endswith(".dist-info/RECORD")]
        if len(records) != 1:
            raise RuntimeError("Wheel archive must contain exactly one RECORD")
        rows = list(csv.reader(io.StringIO(archive.read(records[0]).decode("utf-8"))))
        if any(len(row) != 3 for row in rows) or len(rows) != len(names) or {row[0] for row in rows} != set(names):
            raise RuntimeError("Wheel RECORD file list does not match the archive")
        for name, digest, size in rows:
            if name == records[0]:
                expected_digest, expected_size = "", ""
            else:
                payload = archive.read(name)
                encoded = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).decode().rstrip("=")
                expected_digest, expected_size = "sha256=" + encoded, str(len(payload))
            if (digest, size) != (expected_digest, expected_size):
                raise RuntimeError("Wheel RECORD hash or size does not match the archive")


def _new_staging(project: Path) -> Path:
    parent = project / "build"
    if parent.is_symlink() or (parent.exists() and not parent.is_dir()):
        raise RuntimeError("Wheel staging requires a regular project build directory")
    parent.mkdir(exist_ok=True)
    # This directory is created by this invocation. Existing build/lib,
    # native artifacts and user-selected build paths are never deleted.
    stage = Path(tempfile.mkdtemp(prefix="lingshu-gate-wheel-", dir=parent))
    atexit.register(shutil.rmtree, stage, ignore_errors=True)
    return stage


class FreshBuildPy(build_py):
    """Build wheel package files into a private directory, then check assets."""

    def run(self) -> None:
        # Editable installs must still point at the live checkout and remain
        # usable before the frontend is built. They do not assemble a wheel
        # containing copied Console/OAuth package data.
        if self.editable_mode or self.dry_run:
            super().run()
            return

        source = Path(self.get_package_dir("lingshu_gate"))
        expected = _static_inventory(source)
        stage = _new_staging(Path.cwd())
        self.build_lib = str(stage / "lib")
        # bdist_wheel's later install_lib step obtains this same directory
        # from the finalized build command, rather than copying old build/lib.
        self.get_finalized_command("build").build_lib = self.build_lib
        try:
            super().run()
            _verify_static_inventory(Path(self.build_lib) / "lingshu_gate", expected)
            if _static_inventory(source) != expected:
                raise RuntimeError("Wheel static source changed while building; finish the frontend build and retry")
        except BaseException:
            shutil.rmtree(stage, ignore_errors=True)
            raise


class FreshBdistWheel(bdist_wheel):
    """Prevent a previous failed wheel's install tree from entering an archive."""

    def run(self) -> None:
        if self.dry_run:
            super().run()
            return
        if self.skip_build:
            raise RuntimeError("Wheel builds cannot skip the fresh build and static inventory checks")
        self._static_source = Path(self.get_finalized_command("build_py").get_package_dir("lingshu_gate"))
        self._static_snapshot = _static_inventory(self._static_source)
        stage = _new_staging(Path.cwd())
        destination = Path(self.dist_dir)
        before = len(self.distribution.dist_files)
        # The default bdist directory may survive a failed install/archive.
        # Override even a custom --bdist-dir; never reset or delete that path.
        self.bdist_dir = str(stage / "wheel")
        self.dist_dir = str(stage / "dist")
        try:
            super().run()
            wheels = list((stage / "dist").glob("*.whl"))
            if len(wheels) != 1:
                raise RuntimeError("Wheel build must produce exactly one staged archive")
            wheel = wheels[0]
            _verify_wheel_archive(wheel, self._static_snapshot)
            if _static_inventory(self._static_source) != self._static_snapshot:
                raise RuntimeError("Wheel static source changed while archiving; finish the frontend build and retry")
            destination.mkdir(parents=True, exist_ok=True)
            # Publish only verified bytes. The random file belongs to this
            # invocation; replace does not follow a preexisting output symlink.
            descriptor, temporary_name = tempfile.mkstemp(prefix=".lingshu-gate-wheel-", dir=destination)
            os.close(descriptor)
            temporary = Path(temporary_name)
            published = destination / wheel.name
            try:
                shutil.copyfile(wheel, temporary)
                os.replace(temporary, published)
            finally:
                temporary.unlink(missing_ok=True)
            self.distribution.dist_files[before:] = [
                (command, version, str(published)) for command, version, _path in self.distribution.dist_files[before:]
            ]
        finally:
            self.dist_dir = str(destination)
            shutil.rmtree(stage, ignore_errors=True)

    def write_wheelfile(self, wheelfile_base: str, **kwargs: str) -> None:
        # setuptools' editable_wheel uses this method only to write metadata;
        # it does not run bdist_wheel or copy static files from a checkout.
        if "editable_wheel" in self.distribution.command_obj and not hasattr(self, "_static_snapshot"):
            super().write_wheelfile(wheelfile_base, **kwargs)
            return
        # This hook runs after install_lib and before WheelFile writes RECORD
        # and the archive. Check the actual installed payload as well as lib.
        if not self.dry_run:
            _verify_static_inventory(Path(self.bdist_dir) / "lingshu_gate", self._static_snapshot)
            if _static_inventory(self._static_source) != self._static_snapshot:
                raise RuntimeError("Wheel static source changed while installing; finish the frontend build and retry")
        super().write_wheelfile(wheelfile_base, **kwargs)

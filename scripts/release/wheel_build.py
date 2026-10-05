"""Keep ordinary setuptools wheel builds independent of old build/lib data."""

from __future__ import annotations

import atexit
import hashlib
import shutil
import tempfile
from pathlib import Path

from setuptools.command.build_py import build_py


def _static_inventory(package: Path) -> dict[str, str]:
    static = (package / "static").absolute()
    for directory in (static, *static.parents):
        if directory.is_symlink():
            raise RuntimeError(f"Wheel static assets contain a symlink: {directory}")
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

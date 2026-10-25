"""Regression floors for the reviewed 2026-10 frontend security patches."""
from pathlib import Path
import json

import pytest
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name,minimum", [("vite", "8.3.3"), ("fast-uri", "3.1.9")])
def test_frontend_lock_contains_reviewed_security_fixes(name: str, minimum: str) -> None:
    lock = json.loads((ROOT / "web/package-lock.json").read_text())
    packages = [item for path, item in lock["packages"].items()
                if path == "node_modules/" + name or path.endswith("/node_modules/" + name)]
    assert packages
    for package in packages:
        assert Version(package["version"]) >= Version(minimum)
        assert package["integrity"].startswith("sha512-")
        assert package["resolved"].startswith("https://registry.npmjs.org/")


def test_direct_vite_requirement_and_lock_have_the_same_safe_floor() -> None:
    manifest = json.loads((ROOT / "web/package.json").read_text())
    lock = json.loads((ROOT / "web/package-lock.json").read_text())
    requirement = manifest["devDependencies"]["vite"]
    assert Version(requirement.lstrip("^~")) >= Version("8.3.3")
    assert lock["packages"][""]["devDependencies"]["vite"] == requirement

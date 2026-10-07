"""Keep the JWT dependency floor and lock files on patched releases.

RSA keys are generated locally for tests; no provider or network is involved.
"""
from importlib.metadata import version
from pathlib import Path
import re
import tomllib

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from packaging.requirements import Requirement
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
MINIMUM_SAFE_VERSION = Version("2.14.0")


def test_pyjwt_requirement_rejects_vulnerable_releases():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    requirements = [Requirement(value) for value in project["project"]["dependencies"]]
    requirement = next(value for value in requirements if value.name.lower() == "pyjwt")
    assert "crypto" in requirement.extras
    for vulnerable in ("2.10.0", "2.10.1", "2.12.1", "2.13.0"):
        assert vulnerable not in requirement.specifier
    assert str(MINIMUM_SAFE_VERSION) in requirement.specifier
    assert version("PyJWT") in requirement.specifier


def test_pyjwt_lock_export_and_installed_versions_match():
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    package = next(value for value in lock["package"] if value["name"] == "pyjwt")
    export = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    match = re.search(r"^pyjwt==([^\s]+)", export, re.MULTILINE)
    assert match is not None
    assert package["version"] == match.group(1) == version("PyJWT")
    assert Version(package["version"]) >= MINIMUM_SAFE_VERSION
    block = export[match.start():].split("\npython-", 1)[0]
    for artifact in [package["sdist"], *package["wheels"]]:
        assert f'--hash={artifact["hash"]}' in block
    assert "#   lingshu-gate" in block


@pytest.fixture(scope="module")
def public_pem():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


@pytest.mark.parametrize("mutation", ["indented-end", "cr-only", "single-line"])
def test_hmac_rejects_mutated_asymmetric_public_keys(public_pem, mutation):
    """Regression for CVE-2026-102268 / GHSA-ffc3-869f-jxw9."""
    if mutation == "indented-end":
        public_pem = public_pem.replace(b"-----END", b"\t-----END")
    elif mutation == "cr-only":
        public_pem = public_pem.replace(b"\n", b"\r")
    else:
        public_pem = b" ".join(public_pem.splitlines())
    algorithm = jwt.algorithms.HMACAlgorithm(jwt.algorithms.HMACAlgorithm.SHA256)
    with pytest.raises(jwt.InvalidKeyError):
        algorithm.prepare_key(public_pem)

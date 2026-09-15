"""Copy a verified OCI index to Docker Hub without rebuilding or replacing versions."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess

from scripts.release.common import is_prerelease
from scripts.release.compare_oci_indexes import assert_equivalent_indexes, platform_payloads

SOURCE_PATTERN = re.compile(r"^ghcr\.io/[a-z0-9-]+/lingshu-gate@sha256:[0-9a-f]{64}$")


def inspect(ref: str, *, allow_missing: bool = False) -> object | None:
    result = subprocess.run(
        ["docker", "buildx", "imagetools", "inspect", "--raw", ref],
        capture_output=True, text=True, timeout=120, check=False,
    )
    if result.returncode:
        # Authentication, rate limits and network errors must never authorize a write.
        error = result.stderr.lower()
        denied = any(word in error for word in ("unauthorized", "denied", "forbidden", "429"))
        missing = "manifest unknown" in error or f"{ref.lower()}: not found" in error
        if allow_missing and not denied and missing:
            return None
        raise RuntimeError(f"Cannot inspect registry reference: {ref}")
    payload = json.loads(result.stdout)
    platform_payloads(payload)
    return payload


def copy(source: str, target: str) -> None:
    result = subprocess.run(
        ["docker", "buildx", "imagetools", "create", "--tag", target, source],
        capture_output=True, text=True, timeout=1800, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Registry copy failed: {target}")


def mirror(source: str, version: str, *, latest: bool = False) -> None:
    prerelease = is_prerelease(version)
    username = os.environ.get("DOCKERHUB_USERNAME", "")
    if re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,29}", username) is None:
        raise RuntimeError("Configure a valid DOCKERHUB_USERNAME")
    destination = f"docker.io/{username}/lingshu-gate"
    if SOURCE_PATTERN.fullmatch(source) is None:
        raise RuntimeError("Source must be a digest-pinned Lingshu Gate GHCR image")
    if latest and prerelease:
        raise RuntimeError("Prereleases cannot update latest")
    candidate = inspect(source)
    target = f"{destination}:{version}"
    existing = inspect(target, allow_missing=True)
    if existing is not None:
        assert_equivalent_indexes(candidate, existing)
    elif latest:
        raise RuntimeError("Verify the version mirror before updating latest")
    else:
        copy(source, target)
    assert_equivalent_indexes(candidate, inspect(target))
    if latest:
        copy(source, f"{destination}:latest")
        assert_equivalent_indexes(candidate, inspect(f"{destination}:latest"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--latest", action="store_true")
    args = parser.parse_args()
    mirror(args.source, args.version, latest=args.latest)


if __name__ == "__main__":
    main()

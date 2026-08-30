"""Plan an immutable GitHub Release asset reconciliation."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SAFE_ASSET_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")


def _is_safe_asset_name(name: str) -> bool:
    return SAFE_ASSET_NAME.fullmatch(name) is not None and Path(name).name == name and name not in {".", ".."}


def _existing_asset_names(existing_payload: object) -> set[str]:
    if not isinstance(existing_payload, dict) or not isinstance(existing_payload.get("assets"), list):
        raise RuntimeError("Release asset response has an unexpected shape")
    existing_names: set[str] = set()
    for asset in existing_payload["assets"]:
        if not isinstance(asset, dict) or not isinstance(asset.get("name"), str):
            raise RuntimeError("Release asset response contains an invalid name")
        name = asset["name"]
        if not _is_safe_asset_name(name):
            raise RuntimeError("Release asset response contains an unsafe name")
        if name in existing_names:
            raise RuntimeError(f"Release asset response contains a duplicate name: {name}")
        existing_names.add(name)
    return existing_names


def release_asset_plan(existing_payload: object, desired_names: set[str]) -> dict[str, list[str]]:
    """Return stable asset sets without allowing same-name content replacement."""

    if not desired_names:
        raise RuntimeError("Desired release asset set is empty")
    if any(not _is_safe_asset_name(name) for name in desired_names):
        raise RuntimeError("Desired release asset set contains an unsafe name")
    existing_names = _existing_asset_names(existing_payload)
    return {
        "existing": sorted(existing_names & desired_names),
        "missing": sorted(desired_names - existing_names),
        "stale": sorted(existing_names - desired_names),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--existing-json", type=Path, required=True)
    parser.add_argument("--desired-dir", type=Path, required=True)
    parser.add_argument("--emit", choices=("existing", "missing", "stale"), required=True)
    args = parser.parse_args()
    payload = json.loads(args.existing_json.read_text(encoding="utf-8"))
    desired_names = {path.name for path in args.desired_dir.iterdir() if path.is_file()}
    plan = release_asset_plan(payload, desired_names)
    sys.stdout.buffer.write(b"".join(name.encode("utf-8") + b"\0" for name in plan[args.emit]))


if __name__ == "__main__":
    main()

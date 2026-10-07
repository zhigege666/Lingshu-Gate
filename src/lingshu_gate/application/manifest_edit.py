"""Restore explicitly masked container sources only for their original target."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


def restore_masked_mounts(candidate: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(candidate)
    launch = result.get("launch")
    if not isinstance(launch, dict) or not isinstance(launch.get("mounts"), list):
        return result
    old_launch = previous.get("launch") or {}
    old_mounts = old_launch.get("mounts") or []
    for mount in launch["mounts"]:
        if not isinstance(mount, dict) or mount.get("source") != "***":
            continue
        matches = [old for old in old_mounts if old.get("target") == mount.get("target")]
        if result.get("id") != previous.get("id") or len(matches) != 1 or not matches[0].get("source"):
            raise ValueError("Masked mount source requires the original server and mount target")
        mount["source"] = matches[0]["source"]
    return result

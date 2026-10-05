"""Administrator-only Native executor provisioning; no project-supplied options."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from lingshu_gate.network_settings import GitHostRule

IMAGE = re.compile(r"^[a-z0-9][a-z0-9./:_-]*@sha256:[0-9a-f]{64}$")


@dataclass(frozen=True)
class NativeExecutorConfig:
    enabled: bool = False
    root: Path | None = None
    image: str = ""
    podman_bin: str = "/usr/bin/podman"
    proxy_hosts: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool or not Path(self.podman_bin).is_absolute() or any(ord(ch) < 32 for ch in self.podman_bin):
            raise ValueError("Native executor requires an administrator-reviewed absolute Podman binary")
        if self.enabled and (not self.root or not self.root.is_absolute() or not IMAGE.fullmatch(self.image)):
            raise ValueError("Enabled Native executor requires an absolute provisioned root and digest-pinned image")
        if len(self.proxy_hosts) > 32:
            raise ValueError("Too many reviewed proxy hosts")
        for rule in self.proxy_hosts:
            GitHostRule.model_validate(rule)

    @classmethod
    def parse(cls, value: dict[str, Any]) -> NativeExecutorConfig:
        if not isinstance(value, dict) or set(value) - {"enabled", "root", "image", "podman_bin", "proxy_hosts"}:
            raise ValueError("Invalid Native executor configuration")
        raw = dict(value)
        if raw.get("root") is not None:
            raw["root"] = Path(raw["root"])
        if "proxy_hosts" in raw:
            raw["proxy_hosts"] = tuple(GitHostRule.model_validate(item).model_dump() for item in raw["proxy_hosts"])
        return cls(**raw)

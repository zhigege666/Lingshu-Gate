"""Platform/role composition, before importing any Linux engine implementation."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from lingshu_gate.ports.safe_network_executor import SafeNetworkExecutor


def create_safe_network_executor(settings: Any) -> SafeNetworkExecutor | None:
    config = settings.native_executor
    if settings.runtime_role != "local" or not config.enabled or sys.platform != "linux":
        return None
    if config.root and any(config.root.resolve().is_relative_to(Path(path).resolve()) or Path(path).resolve().is_relative_to(config.root.resolve()) for path in (settings.data_dir, settings.config_dir, settings.allowed_root)):
        raise ValueError("Executor root must be separate from Gate data/config/workspace")
    from lingshu_gate.adapters.native_executor.executor import NativeNetworkExecutor
    return NativeNetworkExecutor(config, settings.data_dir / "builds")


def unavailable_readiness(settings: Any) -> dict[str, Any]:
    missing = ["core_gateway_only_native_delivery_disabled"] if settings.runtime_role != "local" else ["unsupported_platform_linux_required"] if sys.platform != "linux" else ["native_executor_not_configured"]
    return {"available": False, "code": "safe_executor_unavailable", "missing": missing}

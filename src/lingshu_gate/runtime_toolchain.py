"""Verify an installed local startup tool; never bootstrap or borrow build caches."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import subprocess
import tempfile
import threading
import time

from lingshu_gate.config import Settings
from lingshu_gate.mcp_manifest import LaunchConfig
from lingshu_gate.node_toolchain import VERSION, node_requirement, node_version_supported
from lingshu_gate.subprocess_environment import build_subprocess_environment

NO_TOOL_DOWNLOADS = {
    "COREPACK_ENABLE_NETWORK": "0", "COREPACK_ENABLE_AUTO_PIN": "0",
    "COREPACK_ENABLE_PROJECT_SPEC": "0", "COREPACK_DEFAULT_TO_LATEST": "0",
    "npm_config_manage_package_manager_versions": "false",
    "npm_config_package_manager_strict": "false", "YARN_IGNORE_PATH": "1",
    "PNPM_DISABLE_SELF_UPDATE_CHECK": "1", "NPM_CONFIG_UPDATE_NOTIFIER": "false",
}
VERSION_TIMEOUT_SECONDS = 5.0
MAX_VERSION_BYTES = 128


class RuntimeToolchainError(RuntimeError):
    def __init__(self, code: str, manager: str, version: str) -> None:
        self.code = code
        super().__init__(f"{code}: The local runtime requires administrator-registered {manager}@{version} and Node through service-owned LINGSHU_GATE_RUNTIME_TOOLCHAIN_PATHS. Exact versions are checked only during authorized startup. Project paths/PATH and build caches cannot supply tools. Register reviewed installed tools and confirm startup, or review a direct Node entrypoint. No automatic installation or fallback.")


def _read_version(binary: str | list[str], environment: dict[str, str]) -> str:
    """Probe outside the project with bounded output and no project credentials."""
    with tempfile.TemporaryDirectory(prefix="gate-runtime-tool-probe-") as directory:
        return _probe_version(binary, environment, directory)


def _probe_version(binary: str | list[str], environment: dict[str, str], directory: str) -> str:
    started = time.monotonic()
    command = [binary] if isinstance(binary, str) else binary
    process = subprocess.Popen([*command, "--version"], env=environment, cwd=directory, stdin=subprocess.DEVNULL,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               start_new_session=os.name != "nt")
    finished = threading.Event()
    output: list[bytes] = []

    def read() -> None:
        try:
            assert process.stdout is not None
            output.append(process.stdout.read(MAX_VERSION_BYTES + 1))
        except Exception:
            pass
        finally:
            finished.set()

    reader = threading.Thread(target=read, name="gate-runtime-tool-version", daemon=True)
    reader.start()
    try:
        if not finished.wait(VERSION_TIMEOUT_SECONDS):
            raise ValueError("version probe timed out")
        process.wait(timeout=max(0.001, VERSION_TIMEOUT_SECONDS - (time.monotonic() - started)))
        if process.returncode != 0 or not output or len(output[0]) > MAX_VERSION_BYTES:
            raise ValueError("version probe failed")
        version = output[0].decode("ascii").strip().removeprefix("v")
        if not VERSION.fullmatch(version):
            raise ValueError("version probe returned an invalid version")
        return version
    finally:
        if process.poll() is None or reader.is_alive():
            try:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                pass
        reader.join(timeout=0.2)
        if process.stdout is not None and not reader.is_alive():
            process.stdout.close()


def inspect_runtime_toolchain(launch: LaunchConfig, settings: Settings) -> dict[str, str]:
    """Read administrator registrations and file metadata; never spawn or probe."""
    pin = launch.toolchain
    if pin is None:
        raise ValueError("A runtime toolchain pin is required")
    if settings.runtime_role != "local":
        raise RuntimeToolchainError("runtime_role_execution_blocked", pin.manager, pin.version)
    if launch.command != pin.manager:
        raise RuntimeToolchainError("runtime_toolchain_untrusted", pin.manager, pin.version)
    paths = {}
    for name in ("node", pin.manager):
        registered = settings.runtime_toolchain_paths.get(name)
        if not registered:
            raise RuntimeToolchainError("runtime_toolchain_unregistered", pin.manager, pin.version)
        try:
            declared = Path(registered)
            binary = declared.resolve(strict=True)
            declared_location = declared.parent.resolve(strict=True) / declared.name
            protected = (settings.allowed_root, settings.data_dir, settings.config_dir)
            if any(declared.is_relative_to(root.absolute()) or binary.is_relative_to(root.resolve()) or declared_location.is_relative_to(root.resolve()) for root in protected):
                raise RuntimeToolchainError("runtime_toolchain_untrusted", pin.manager, pin.version)
            if not binary.is_file() or not os.access(binary, os.X_OK if name == "node" else os.R_OK):
                raise OSError
            if name == "node" and binary.name.lower() not in {"node", "node.exe"}:
                raise RuntimeToolchainError("runtime_toolchain_untrusted", pin.manager, pin.version)
            if name != "node" and binary.suffix.lower() not in {".js", ".cjs", ".mjs"}:
                raise RuntimeToolchainError("runtime_toolchain_untrusted", pin.manager, pin.version)
            paths[name] = str(binary)
        except RuntimeToolchainError:
            raise
        except (OSError, ValueError, RuntimeError):
            raise RuntimeToolchainError("runtime_toolchain_unavailable", pin.manager, pin.version) from None
    return paths


def resolve_runtime_toolchain(launch: LaunchConfig, environment: dict[str, str], *, settings: Settings) -> list[str]:
    """Called only by existing clients after their authorized startup boundary."""
    command = [launch.command or "", *launch.args]
    pin = launch.toolchain
    if pin is None:
        return command
    paths = inspect_runtime_toolchain(launch, settings)
    # Neither initial executable nor its Node interpreter comes from project
    # env/PATH. Only administrator-controlled registered binary directories.
    trusted_path = os.pathsep.join(dict.fromkeys(str(Path(path).parent) for path in paths.values()))
    for name in list(environment):
        if name.upper() == "PATH":
            environment.pop(name)
    environment["PATH"] = trusted_path
    environment.update(NO_TOOL_DOWNLOADS)
    # Invoke the reviewed JS CLI using the registered Node directly; shell/
    # Corepack launcher shebangs cannot select another interpreter through PATH.
    tool_command = [paths["node"], paths[pin.manager]]
    probe_environment = build_subprocess_environment({**NO_TOOL_DOWNLOADS, "PATH": trusted_path})
    try:
        actual = _read_version(tool_command, probe_environment)
        if actual != pin.version:
            raise RuntimeToolchainError("runtime_toolchain_version_mismatch", pin.manager, pin.version)
        if node_requirement(pin.manager, pin.version) == ">=22.13":
            if not node_version_supported(pin.manager, pin.version, _read_version(paths["node"], probe_environment)):
                raise RuntimeToolchainError("runtime_toolchain_node_incompatible", pin.manager, pin.version)
    except RuntimeToolchainError:
        raise
    except Exception:
        raise RuntimeToolchainError("runtime_toolchain_unverified", pin.manager, pin.version) from None
    return [*tool_command, *launch.args]

"""Exercise the frozen native application through its readiness endpoint."""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from scripts.release.common import python_executable_name

CONSOLE_ASSET_PATTERN = re.compile(r'(?:src|href)="(/console/[^"?#]+\.(?:js|css))"')


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _verify_http_surface(port: int) -> None:
    origin = f"http://127.0.0.1:{port}"
    with urllib.request.urlopen(f"{origin}/", timeout=5) as response:
        metadata = json.loads(response.read())
        if response.status != 200 or metadata.get("service") != "Lingshu Gate":
            raise RuntimeError("Frozen root metadata response is invalid")
    with urllib.request.urlopen(f"{origin}/console", timeout=5) as response:
        console_html = response.read().decode("utf-8")
        if response.status != 200:
            raise RuntimeError("Frozen Console entry point is unavailable")
    assets = sorted(set(CONSOLE_ASSET_PATTERN.findall(console_html)))
    if not assets or not any(asset.endswith(".js") for asset in assets):
        raise RuntimeError("Frozen Console does not reference a JavaScript asset")
    for asset in assets:
        with urllib.request.urlopen(f"{origin}{asset}", timeout=5) as response:
            content = response.read()
            if response.status != 200 or not content:
                raise RuntimeError(f"Frozen Console asset is unavailable: {asset}")


def _launcher_command(bundle_dir: Path, target: str) -> list[str]:
    if target.startswith("windows-"):
        launcher = bundle_dir / "start.cmd"
        if not launcher.is_file():
            raise RuntimeError(f"Native launcher is missing: {launcher}")
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", f'call "{launcher}"']
    launcher = bundle_dir / "start.sh"
    if not launcher.is_file():
        raise RuntimeError(f"Native launcher is missing: {launcher}")
    return [str(launcher)]


def _stop_process_tree(process: subprocess.Popen[bytes], *, windows: bool) -> None:
    if process.poll() is not None:
        return
    if windows:
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            capture_output=True,
            timeout=15,
        )
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def smoke(bundle_dir: Path, target: str, timeout_seconds: int) -> None:
    executable = bundle_dir / python_executable_name(target)
    if not executable.is_file():
        raise RuntimeError(f"Frozen executable is missing: {executable}")

    port = _free_loopback_port()
    with tempfile.TemporaryDirectory(prefix="lingshu-gate-smoke-") as temp_dir:
        runtime_root = Path(temp_dir)
        data_dir = runtime_root / "data"
        config_dir = runtime_root / "config"
        workspace_dir = runtime_root / "workspace"
        data_dir.mkdir()
        config_dir.mkdir()
        workspace_dir.mkdir()
        environment = os.environ.copy()
        environment.update(
            {
                "LINGSHU_GATE_HOST": "127.0.0.1",
                "LINGSHU_GATE_PORT": str(port),
                "LINGSHU_GATE_DATA_DIR": str(data_dir),
                "LINGSHU_GATE_CONFIG_DIR": str(config_dir),
                "LINGSHU_GATE_ALLOWED_ROOT": str(workspace_dir),
                "LINGSHU_GATE_RUNTIME_ROLE": "local",
                "LINGSHU_GATE_LOG_LEVEL": "WARNING",
                # The CLI must preserve the single-process SQLite/Core contract
                # even when a host injects Uvicorn's conventional worker hint.
                "WEB_CONCURRENCY": "2",
            }
        )
        log_path = runtime_root / "server.log"
        with log_path.open("wb") as log:
            windows_target = target.startswith("windows-")
            process = subprocess.Popen(
                _launcher_command(bundle_dir, target),
                cwd=bundle_dir,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if windows_target else 0,
            )
            deadline = time.monotonic() + timeout_seconds
            try:
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        break
                    try:
                        with urllib.request.urlopen(f"http://127.0.0.1:{port}/readyz", timeout=2) as response:
                            if response.status == 200:
                                _verify_http_surface(port)
                                return
                    except (urllib.error.URLError, TimeoutError):
                        time.sleep(0.5)
                log.flush()
                details = log_path.read_text(encoding="utf-8", errors="replace")
                raise RuntimeError(f"Native readiness smoke test failed\n{details}")
            finally:
                _stop_process_tree(process, windows=windows_target)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-dir", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()
    smoke(args.bundle_dir.resolve(), args.target, args.timeout)
    print("native readiness smoke test passed")


if __name__ == "__main__":
    main()

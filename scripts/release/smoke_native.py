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

CONSOLE_ASSET_PATTERN = re.compile(r'(?:src|href)="(/assets/[^"?#]+\.(?:js|css))"')


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class _ConsoleRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, expected_url: str) -> None:
        self.expected_url = expected_url
        self.redirects: list[int] = []

    def redirect_request(self, request, fp, code, message, headers, new_url):
        if code != 307 or new_url != self.expected_url or self.redirects:
            raise RuntimeError("Frozen Console entry point has an unexpected redirect")
        self.redirects.append(code)
        return super().redirect_request(request, fp, code, message, headers, new_url)


def _read_console_entry(url: str, *, expected_url: str) -> str:
    redirects = _ConsoleRedirectHandler(expected_url)
    opener = urllib.request.build_opener(redirects)
    request = urllib.request.Request(url, headers={"Accept": "text/html"})
    try:
        with opener.open(request, timeout=5) as response:
            if (response.status != 200 or response.geturl() != expected_url
                    or response.headers.get_content_type() != "text/html"
                    or redirects.redirects != ([307] if url != expected_url else [])):
                raise RuntimeError("Frozen Console entry point is unavailable")
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        raise RuntimeError("Frozen Console entry point is unavailable") from error


def _read_console_asset(origin: str, asset: str) -> bytes:
    expected_types = {"text/javascript", "application/javascript"} if asset.endswith(".js") else {"text/css"}
    url = f"{origin}{asset}"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            content = response.read()
            if (response.status != 200 or response.geturl() != url or not content
                    or response.headers.get_content_type() not in expected_types):
                raise RuntimeError(f"Frozen Console asset is unavailable: {asset}")
            return content
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"Frozen Console asset is unavailable: {asset}") from error


def _verify_http_surface(port: int) -> None:
    origin = f"http://127.0.0.1:{port}"
    with urllib.request.urlopen(f"{origin}/", timeout=5) as response:
        metadata = json.loads(response.read())
        if (response.status != 200 or metadata.get("service") != "Lingshu Gate"
                or response.headers.get_content_type() != "application/json"):
            raise RuntimeError("Frozen root metadata response is invalid")
    console_html = _read_console_entry(f"{origin}/", expected_url=f"{origin}/")
    query = "?native_smoke=one&native_smoke=two"
    for entry in ("/console", "/console/", "/console/index.html"):
        legacy_html = _read_console_entry(f"{origin}{entry}{query}", expected_url=f"{origin}/{query}")
        if legacy_html != console_html:
            raise RuntimeError("Frozen legacy Console entry does not match the root Console")
    assets = sorted(set(CONSOLE_ASSET_PATTERN.findall(console_html)))
    if not assets or not any(asset.endswith(".js") for asset in assets):
        raise RuntimeError("Frozen Console does not reference a JavaScript asset")
    if not any(asset.endswith(".css") for asset in assets):
        raise RuntimeError("Frozen Console does not reference a CSS asset")
    for asset in assets:
        content = _read_console_asset(origin, asset)
        if _read_console_asset(origin, f"/console{asset}") != content:
            raise RuntimeError(f"Frozen legacy Console asset does not match the root asset: {asset}")


def _launcher_command(bundle_dir: Path, target: str) -> list[str]:
    if target.startswith("windows-"):
        launcher = bundle_dir / "start.cmd"
        if not launcher.is_file():
            raise RuntimeError(f"Native launcher is missing: {launcher}")
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", launcher.name]
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

"""Reviewable, run-owned Gate browser launcher. Preparation never starts Gate.

The explicit run switch is for a later, separately approved nx5 fixture scope.
This module imports no Gate code. Detailed runtime identities stay private.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
from urllib.parse import urlsplit
import uuid

SOURCE_SHA = "9f8fddd9709e400517fc2e342ed9889a35751c96"
ACCOUNT_TEST_SHA256 = "e438b49735506590b5b7d503b97caba97acc2887b0b0238a88594f46c0e97797"
DESKTOPS = [(1600, 900, "en-US"), (1920, 1080, "zh-CN"), (2560, 1080, "en-US"), (2560, 1440, "zh-CN")]
PROTECTED_PID = 117063


class BoundaryError(RuntimeError):
    """A boundary was not established; no broad fallback is permitted."""


def reject_injected_flags(ambient: dict[str, str], fixture_root: Path | None = None) -> None:
    for key, value in ambient.items():
        if not key.startswith("GATE_E2E_"):
            continue
        if key == "GATE_E2E_TEMP_ROOT" and fixture_root is not None:
            if value == str(fixture_root):
                continue
        # In particular, even an empty/zero catalog switch is not accepted.
        # Do not print the injected value or inherited environment.
        raise BoundaryError("Unapproved E2E environment parameter: " + key)


def _json_write(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as handle:
        os.chmod(path, 0o600)
        handle.write(json.dumps(value, indent=2) + "\n")


def new_layout(parent: Path) -> dict[str, object]:
    parent = parent.resolve(strict=True)
    root = Path(tempfile.mkdtemp(prefix="gate-account-focus-", dir=parent))
    token = uuid.uuid4().hex
    fixture = root / "tmp" / ("gate-e2e-" + token)
    paths = {
        "root": root,
        "home": root / "home",
        "tmp": root / "tmp",
        "cache": root / "cache",
        "artifacts": root / "artifacts",
        "fixture": fixture,
        "tests": root / "tests",
    }
    for name, path in paths.items():
        if name != "root":
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
    metadata = root.stat()
    layout: dict[str, object] = {
        **{key: str(path) for key, path in paths.items()},
        "token": token,
        "uid": os.getuid(),
        "device": metadata.st_dev,
        "inode": metadata.st_ino,
        "source_sha": SOURCE_SHA,
    }
    _json_write(root / "owner.json", layout)
    return layout


def validate_owner(layout: dict[str, object], token: str) -> Path:
    root = Path(str(layout["root"]))
    metadata = root.lstat()
    if (
        root.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or metadata.st_dev != layout["device"]
        or metadata.st_ino != layout["inode"]
        or layout["token"] != token
        or not root.name.startswith("gate-account-focus-")
    ):
        raise BoundaryError("Owned directory identity mismatch")
    marker = root / "owner.json"
    if marker.is_symlink() or not marker.is_file():
        raise BoundaryError("Owned marker is not a regular file")
    if json.loads(marker.read_text()) != layout:
        raise BoundaryError("Owned marker changed")
    for key in ["home", "tmp", "cache", "artifacts", "fixture", "tests"]:
        path = Path(str(layout[key]))
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise BoundaryError("Owned output boundary mismatch")
    return root


def clean_environment(
    layout: dict[str, object],
    ambient: dict[str, str],
    python: Path,
    node: Path,
    browsers: Path,
    *,
    fixture_child: bool = False,
) -> dict[str, str]:
    fixture = Path(str(layout["fixture"]))
    reject_injected_flags(ambient, fixture if fixture_child else None)
    root = validate_owner(layout, str(layout["token"]))
    home_path, tmp_path, cache_path = (Path(str(layout[k])) for k in ["home", "tmp", "cache"])
    # Construct a new dictionary. Never copy HOME, proxies, secrets, loader
    # options, Gate settings, E2E flags, Git settings or npm options from ambient.
    environment = {
        "PATH": os.pathsep.join([str(python.parent), str(node.parent), "/usr/bin", "/bin"]),
        "HOME": str(home_path),
        "TMPDIR": str(tmp_path),
        "TMP": str(tmp_path),
        "TEMP": str(tmp_path),
        "XDG_CONFIG_HOME": str(home_path / "config"),
        "XDG_STATE_HOME": str(home_path / "state"),
        "XDG_CACHE_HOME": str(cache_path),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TZ": "UTC",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "GATE_E2E_TEMP_ROOT": str(fixture),
        "PLAYWRIGHT_BROWSERS_PATH": str(browsers),
        "PLAYWRIGHT_JSON_OUTPUT_NAME": str(root / "artifacts" / "results.json"),
        "PLAYWRIGHT_HTML_OUTPUT_DIR": str(root / "artifacts" / "html"),
        "PLAYWRIGHT_HTML_OPEN": "never",
        "npm_config_cache": str(cache_path / "npm"),
        "npm_config_audit": "false",
        "npm_config_fund": "false",
        "npm_config_update_notifier": "false",
    }
    assert "GATE_E2E_OAUTH_CATALOG_SCALE" not in environment
    return environment


def _inventory(source: Path) -> dict[str, dict[str, str]]:
    inventory = {}
    for directory in ["console", "oauth"]:
        root = source / "src" / "lingshu_gate" / "static" / directory
        if not root.is_dir() or root.is_symlink():
            raise BoundaryError("Built static directory missing")
        files = {}
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise BoundaryError("Built static symlink rejected")
            if path.is_file():
                files[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
        if ("index.html" if directory == "console" else "oauth.html") not in files:
            raise BoundaryError("Built static entry missing")
        inventory[directory] = files
    return inventory


def _source_check(source: Path) -> None:
    safe_git_env = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "HOME": "/nonexistent",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
    }
    head = subprocess.check_output(
        ["/usr/bin/git", "-C", str(source), "rev-parse", "HEAD"], env=safe_git_env, text=True
    ).strip()
    dirty = subprocess.check_output(
        ["/usr/bin/git", "-C", str(source), "status", "--porcelain"], env=safe_git_env, text=True
    )
    if head != SOURCE_SHA or dirty:
        raise BoundaryError("The reviewed source head is not a clean exact checkout")


def _write_config(layout: dict[str, object], source: Path, python: Path) -> None:
    root = Path(str(layout["root"]))
    # Match the source helpers' ESM boundary in this separate owned directory.
    (root / "package.json").write_text(json.dumps({"private": True, "type": "module"}) + "\n")
    original = (source / "web" / "e2e" / "account-menu.spec.ts").read_bytes()
    if hashlib.sha256(original).hexdigest() != ACCOUNT_TEST_SHA256:
        raise BoundaryError("Reviewed account test bytes differ")
    text = original.decode()
    helper = text.split("// Actual isolated sign-in;", 1)[0]
    helper = helper.replace(
        "'@playwright/test'", json.dumps(str(source / "web/node_modules/@playwright/test/index.mjs"))
    )
    helper = helper.replace("'./helpers'", json.dumps(str(source / "web/e2e/helpers.ts")))
    anchor = "for (const locale of ['en-US', 'zh-CN'] as const) {\n  for (const width of [1280, 640])"
    section = text[text.index(anchor) :]
    body = section[section.index("      test(") :]
    tail = "    }\n  }\n}\n"
    if not body.endswith(tail):
        raise BoundaryError("Reviewed account test shape changed")
    body = body[: -len(tail)].replace("{ width, height: 720 }", "{ width, height }")
    focus = helper + "\nconst targets = " + json.dumps(DESKTOPS) + " as const\n"
    focus += "for (const [width, height, locale] of targets) {\nconst openFrames = 0\n" + body + "}\n"
    (root / "tests" / "account-focus-targets.spec.ts").write_text(focus)
    (root / "defer-cleanup.ts").write_text("export default async function () {}\n")
    projects = []
    for width, height, _ in DESKTOPS:
        project = {
            "name": f"desktop-{width}x{height}",
            "testDir": str(source / "web/e2e"),
            "testMatch": "root-entry.spec.ts",
            "use": {"viewport": {"width": width, "height": height}},
        }
        projects.append(
            json.dumps(project)[:-1]
            + ', "grep": new RegExp("root entry zh-CN / preserves|root entry en-US /console preserves")}'
        )
    projects.append(
        json.dumps(
            {
                "name": "desktop-account-focus",
                "testDir": str(root / "tests"),
                "testMatch": "account-focus-targets.spec.ts",
            }
        )
    )
    project = {
        "name": "permissions-once",
        "testDir": str(source / "web/e2e"),
        "testMatch": "real-backend.spec.ts",
        "use": {"viewport": {"width": 1600, "height": 900}},
    }
    projects.append(json.dumps(project)[:-1] + ', "grep": new RegExp("E2E-00[246] ")}')
    fixture_command = shlex.join([str(python), str(Path(__file__).resolve()), "fixture", "--root", str(root)])
    config = (
        "import { defineConfig } from " + json.dumps(str(source / "web/node_modules/@playwright/test/index.mjs")) + "\n"
    )
    config += "import base from " + json.dumps(str(source / "web/playwright.config.ts")) + "\n"
    config += "export default defineConfig({ ...base, workers: 1, retries: 0, globalTeardown: " + json.dumps(
        str(root / "defer-cleanup.ts")
    )
    config += ", outputDir: " + json.dumps(str(root / "artifacts/test-results"))
    config += (
        ", reporter: [['list'], ['json', { outputFile: "
        + json.dumps(str(root / "artifacts/results.json"))
        + " }], ['html', { outputFolder: "
        + json.dumps(str(root / "artifacts/html"))
        + ", open: 'never' }]],"
    )
    config += (
        " use: { ...base.use, trace: 'retain-on-failure', screenshot: 'only-on-failure' }, projects: ["
        + ",".join(projects)
        + "],"
    )
    config += (
        " webServer: { ...base.webServer, command: "
        + json.dumps(fixture_command)
        + ", cwd: "
        + json.dumps(str(source / "web"))
        + ", reuseExistingServer: false } })\n"
    )
    (root / "owned.config.ts").write_text(config)


def prepare(
    parent: Path, source: Path, python: Path, node: Path, browsers: Path, ambient: dict[str, str]
) -> dict[str, object]:
    reject_injected_flags(ambient)
    source = source.resolve(strict=True)
    _source_check(source)
    # Keep the venv executable's lexical path; resolving its symlink loses venv discovery.
    python, node, browsers = [Path(os.path.abspath(p)) for p in [python, node, browsers]]
    if not all(path.is_file() and os.access(path, os.X_OK) for path in [python, node]) or not browsers.is_dir():
        raise BoundaryError("Explicit runtime paths are not usable")
    inventory = _inventory(source)
    # Browser binaries are input material. Copy them into this run's cache so
    # even browser-registry writes cannot touch the previous shared cache.
    for path in browsers.rglob("*"):
        if path.is_symlink() and not path.resolve().is_relative_to(browsers.resolve()):
            raise BoundaryError("Browser input symlink escapes its reviewed input")
    layout = new_layout(parent)
    owned_browsers = Path(str(layout["cache"])) / "browser-binaries"
    shutil.copytree(browsers, owned_browsers, ignore=shutil.ignore_patterns(".links"))
    layout.update(
        {
            "source": str(source),
            "python": str(python),
            "node": str(node),
            "browsers": str(owned_browsers),
            "static_inventory": inventory,
            "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        }
    )
    marker = Path(str(layout["root"])) / "owner.json"
    marker.unlink()
    _json_write(marker, layout)
    _write_config(layout, source, python)
    layout["prepared_files"] = {
        name: hashlib.sha256((Path(str(layout["root"])) / name).read_bytes()).hexdigest()
        for name in [
            "owned.config.ts",
            "defer-cleanup.ts",
            "tests/account-focus-targets.spec.ts",
            "package.json",
        ]
    }
    marker.unlink()
    _json_write(marker, layout)
    return layout


def read_layout(root: Path) -> dict[str, object]:
    if root.is_symlink() or (root / "owner.json").is_symlink():
        raise BoundaryError("Owned root/marker symlink rejected")
    layout = json.loads((root / "owner.json").read_text())
    if str(root) != layout["root"]:
        raise BoundaryError("Owned root path mismatch")
    validate_owner(layout, str(layout["token"]))
    return layout


def process_identity(pid: int) -> dict[str, int | str] | None:
    try:
        text = Path(f"/proc/{pid}/stat").read_text()
        fields = text.rsplit(") ", 1)[1].split()
        return {"pid": pid, "state": fields[0], "ppid": int(fields[1]), "start_ticks": int(fields[19])}
    except (FileNotFoundError, ProcessLookupError):
        return None
    except (OSError, ValueError, IndexError) as error:
        raise BoundaryError("Process identity cannot be established") from error


def observe_owned(known: dict[int, dict[str, int | str]], manager_pid: int) -> None:
    snapshot = {}
    for path in Path("/proc").iterdir():
        if path.name.isdigit():
            try:
                snapshot[int(path.name)] = process_identity(int(path.name))
            except BoundaryError:
                # An unreadable identity might be an unobserved descendant;
                # never convert that uncertainty into deletion permission.
                raise
    parents = {manager_pid, *known}
    while True:
        added = False
        for pid, identity in snapshot.items():
            if identity and identity["ppid"] in parents and pid not in parents:
                if pid == PROTECTED_PID:
                    raise BoundaryError("Protected original-service PID encountered")
                known[pid] = identity
                parents.add(pid)
                added = True
        if not added:
            return


def _live_or_uncertain(identity: dict[str, int | str]) -> bool:
    current = process_identity(int(identity["pid"]))
    if current is None:
        return False
    if current["start_ticks"] != identity["start_ticks"]:
        raise BoundaryError("PID identity changed; do not signal or delete")
    return current["state"] != "Z"


def _gone(identity: dict[str, int | str]) -> bool:
    current = process_identity(int(identity["pid"]))
    if current is None:
        return True
    if current["start_ticks"] != identity["start_ticks"]:
        raise BoundaryError("PID identity changed; retain owned state")
    # A zombie has exited but has not been reaped. It is not deletion proof.
    return False


def signal_owned(identity: dict[str, int | str], sig: int) -> None:
    if identity["pid"] == PROTECTED_PID:
        raise BoundaryError("Original service is protected")
    if _live_or_uncertain(identity):
        try:
            os.kill(int(identity["pid"]), sig)
        except ProcessLookupError:
            pass


def _reap() -> None:
    while True:
        try:
            pid, _ = os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            return
        if pid == 0:
            return


def reap_owned(known: dict[int, dict[str, int | str]], grace_seconds: float = 3) -> bool:
    for sig in [signal.SIGTERM, signal.SIGKILL]:
        observe_owned(known, os.getpid())
        for identity in list(known.values()):
            signal_owned(identity, sig)
        deadline = time.monotonic() + grace_seconds
        while time.monotonic() < deadline:
            _reap()
            observe_owned(known, os.getpid())
            if all(_gone(identity) for identity in known.values()):
                return True
            time.sleep(0.05)
    return False


def listener_closed(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def peer_port(layout: dict[str, object]) -> int:
    path = Path(str(layout["fixture"])) / "http-peer.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        raise BoundaryError("Peer listener identity is unavailable; retain owned state")
    endpoint = urlsplit(json.loads(path.read_text())["endpoint"])
    port = endpoint.port
    if (
        endpoint.scheme != "http"
        or endpoint.hostname != "127.0.0.1"
        or endpoint.path != "/mcp"
        or not port
        or port == 18763
    ):
        raise BoundaryError("Unexpected peer listener identity")
    return port


def remove_after_exit(
    layout: dict[str, object], token: str, identities: list[dict[str, int | str]], ports: list[int]
) -> bool:
    root = validate_owner(layout, token)
    if any(not _gone(identity) for identity in identities):
        return False
    if not all(listener_closed(port) for port in ports):
        return False
    # Exactly the recorded directory. shutil's fd-based implementation does
    # not follow nested symlinks; no scanning, prefix deletion or broad rm.
    if not shutil.rmtree.avoids_symlink_attacks:
        raise BoundaryError("Safe owned deletion is unavailable")
    shutil.rmtree(root)
    return not root.exists()


def _require_execution_approval(root: Path, layout: dict[str, object]) -> None:
    path = root / "execution-approved.private.json"
    if path.is_symlink() or not path.is_file():
        raise BoundaryError("Fixture scope was not separately approved for this run")
    approval = json.loads(path.read_text())
    if approval != {"token": layout["token"], "source_sha": SOURCE_SHA, "fixture_scope_approved": True}:
        raise BoundaryError("Fixture execution approval does not match owned run")


class HeldAppDirectory:
    """Only the reviewed serve module's app directory; retain until owned reap.

    This changes no global tempfile behavior. Browser/other Python temporary
    directories keep their standard behavior under the run-owned TMPDIR.
    """

    def __init__(self, *, prefix: str, dir: str) -> None:
        expected = Path(os.environ["GATE_E2E_TEMP_ROOT"])
        if Path(dir) != expected or prefix != "gate-browser-synthetic-":
            raise BoundaryError("Unexpected fixture application directory request")
        self.name = tempfile.mkdtemp(prefix=prefix, dir=dir)

    def __enter__(self) -> str:
        return self.name

    def __exit__(self, *_args: object) -> None:
        # PBKDF2/role/session/grant rows persist until exact root deletion.
        return None


def fixture(root: Path, ambient: dict[str, str], *, entry: bool = False) -> None:
    # Reject catalog/other injected flags before any Gate import or initialization.
    reject_injected_flags(ambient, root / "tmp" / ("gate-e2e-" + read_layout(root)["token"]))
    layout = read_layout(root)
    _require_execution_approval(root, layout)
    environment = clean_environment(
        layout,
        ambient,
        Path(str(layout["python"])),
        Path(str(layout["node"])),
        Path(str(layout["browsers"])),
        fixture_child=True,
    )
    python = str(layout["python"])
    if not entry:
        command = [python, str(Path(__file__).resolve()), "fixture-entry", "--root", str(root)]
        os.execve(python, command, environment)
    # Only a clean child can reach the real reviewed fixture. This path is
    # intentionally unexecuted by the pure negative tests.
    os.environ.clear()
    os.environ.update(environment)
    _json_write(root / "fixture-launch-intent.json", {"fixture_start_requested": True})
    source = Path(str(layout["source"]))
    sys.path.insert(0, str(source / "scripts/e2e"))
    specification = importlib.util.spec_from_file_location("owned_reviewed_fixture", source / "scripts/e2e/serve.py")
    if specification is None or specification.loader is None:
        raise BoundaryError("Reviewed fixture cannot be loaded")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    module.tempfile = SimpleNamespace(TemporaryDirectory=HeldAppDirectory)
    os.chdir(source / "web")
    module.main()


def run(layout: dict[str, object], ambient: dict[str, str], *, fixture_scope_approved: bool) -> dict[str, object]:
    if not fixture_scope_approved:
        raise BoundaryError("Separate nx5 temporary identity/policy scope approval is required")
    root = validate_owner(layout, str(layout["token"]))
    environment = clean_environment(
        layout, ambient, Path(str(layout["python"])), Path(str(layout["node"])), Path(str(layout["browsers"]))
    )
    _source_check(Path(str(layout["source"])))
    if _inventory(Path(str(layout["source"]))) != layout["static_inventory"]:
        raise BoundaryError("Prepared source static inventory changed")
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != layout["adapter_sha256"]:
        raise BoundaryError("Prepared launcher changed")
    for name, digest in layout["prepared_files"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise BoundaryError("Prepared test/report configuration changed")
    if not listener_closed(18763):
        raise BoundaryError("Existing listener must not be reused or stopped")
    _json_write(
        root / "execution-approved.private.json",
        {"token": layout["token"], "source_sha": SOURCE_SHA, "fixture_scope_approved": True},
    )
    # Subreaping changes only this launcher process, not host permissions or
    # system configuration. It captures orphaned descendants across sessions.
    if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
        raise BoundaryError("Owned descendant reaping unavailable")
    command = [
        str(layout["node"]),
        str(Path(str(layout["source"])) / "web/node_modules/playwright/cli.js"),
        "test",
        "--config=" + str(root / "owned.config.ts"),
    ]
    known: dict[int, dict[str, int | str]] = {}
    receipt: dict[str, object] = {
        "source_sha": SOURCE_SHA,
        "adapter_sha256": layout["adapter_sha256"],
        "desktop_targets": DESKTOPS,
        "temporary_persistent_state": "retained",
    }
    result_path = root / "artifacts/results.json"
    if result_path.exists() or result_path.is_symlink():
        if result_path.is_symlink() or not result_path.is_file():
            raise BoundaryError("Owned JSON report is not a regular file")
        # A preparation-only --list receipt cannot stand in for a real run.
        result_path.unlink()
    try:
        with (root / "artifacts/run.log").open("w") as log:
            process = subprocess.Popen(
                command,
                cwd=Path(str(layout["source"])) / "web",
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            leader = process_identity(process.pid)
            if leader is None or leader["pid"] == PROTECTED_PID:
                raise BoundaryError("Owned launcher identity cannot be established")
            known[process.pid] = leader
            deadline = time.monotonic() + 180
            while process.poll() is None and time.monotonic() < deadline:
                observe_owned(known, os.getpid())
                time.sleep(0.05)
            if process.poll() is None:
                receipt["command_timed_out"] = True
                observe_owned(known, os.getpid())
                for identity in list(known.values()):
                    signal_owned(identity, signal.SIGTERM)
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    signal_owned(leader, signal.SIGKILL)
                    process.wait(timeout=3)
            receipt["command_exit_code"] = process.returncode
    except Exception as error:
        receipt["execution_error"] = type(error).__name__
    try:
        reaped = reap_owned(known)
    except BoundaryError:
        reaped = False
        receipt["cleanup_uncertain"] = True
    validate_owner(layout, str(layout["token"]))
    _json_write(root / "lifecycle.private.json", {"owned_identities": list(known.values()), "reaped": reaped})
    if result_path.exists():
        results = json.loads(result_path.read_text())
        receipt["browser_stats"] = results["stats"]
        receipt["fifteen_sample_subphase_passed"] = (
            receipt.get("command_exit_code") == 0
            and results["stats"]["expected"] == 15
            and results["stats"]["skipped"] == 0
            and results["stats"]["unexpected"] == 0
            and results["stats"]["flaky"] == 0
        )
    receipt["entire_gate7_gate9_tickets_closed"] = False
    try:
        port = peer_port(layout)
        receipt["two_listeners_closed"] = listener_closed(18763) and listener_closed(port)
        receipt["owned_descendants_reaped"] = reaped
        if reaped and remove_after_exit(layout, str(layout["token"]), list(known.values()), [18763, port]):
            receipt["temporary_persistent_state"] = "destroyed_with_exact_owned_root"
    except BoundaryError:
        receipt["cleanup_uncertain"] = True
    # Product assertions only. No PID, namespace, environment, cookies, keys,
    # database contents or original-service secret arguments are exported.
    receipt_path = root.parent / (root.name + "-acceptance.json")
    _json_write(receipt_path, receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "fixture", "fixture-entry", "run"])
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--node", type=Path)
    parser.add_argument("--browsers", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--fixture-scope-approved", action="store_true")
    args = parser.parse_args()
    required = ["parent", "source", "python", "node", "browsers"] if args.mode == "prepare" else ["root"]
    if any(getattr(args, name) is None for name in required):
        parser.error("This mode requires: " + ", ".join("--" + name for name in required))
    try:
        if args.mode == "prepare":
            layout = prepare(args.parent, args.source, args.python, args.node, args.browsers, dict(os.environ))
            print(json.dumps({"prepared_only": True, "owned_root": layout["root"], "source_sha": SOURCE_SHA}))
        elif args.mode in {"fixture", "fixture-entry"}:
            fixture(args.root, dict(os.environ), entry=args.mode == "fixture-entry")
        else:
            print(
                json.dumps(
                    run(read_layout(args.root), dict(os.environ), fixture_scope_approved=args.fixture_scope_approved)
                )
            )
        return 0
    except (BoundaryError, OSError, ValueError, KeyError, TypeError) as error:
        # Do not print inherited values, commands, configuration, paths or
        # exception representations containing private runtime details.
        print(
            json.dumps(
                {
                    "boundary_error": type(error).__name__,
                    "mode": args.mode,
                    "state": "not_started" if args.mode == "prepare" else "unestablished_or_retained",
                }
            ),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

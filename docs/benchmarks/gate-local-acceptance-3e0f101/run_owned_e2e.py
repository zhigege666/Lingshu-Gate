"""Reviewable, run-owned Gate browser launcher. Preparation never starts Gate.

The explicit run switch requires authorization for a regenerable local fixture.
This module imports no Gate code. Detailed runtime identities stay private.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import importlib.abc
import importlib.machinery
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
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from urllib.parse import urlsplit
import uuid

SOURCE_SHA = "3e0f101ed858c94841a1f75b3ef23ee4d52e2e1b"
SOURCE_TREE = "d3d6bef164400732b18ea19be3f8a942b8d00815"
WEB_TREE = "11cc8d5aeaf7b14da0b5568f4a34c73a8c61d176"
STATIC_MANIFEST_SHA256 = "dd3f5e2d2a236100963f3109d4355812fbdaff58a2f6a5af65fa2726b557c7fa"
STATIC_MANIFEST_NAME = "gate-local-acceptance-static-3e0f101.json"
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
    if "source_binding" in layout:
        source_path = Path(str(layout["source"])) / "src"
        if layout["source_binding"]["source_sha"] != SOURCE_SHA or source_path.resolve(strict=True) != source_path:
            raise BoundaryError("Worker source import boundary is unavailable")
        # Product-created Python workers inherit this generated value. The
        # parent's PYTHONPATH is never accepted, including an old wheel/venv.
        environment["PYTHONPATH"] = str(source_path)
    assert "GATE_E2E_OAUTH_CATALOG_SCALE" not in environment
    return environment


def _inventory(source: Path) -> dict[str, dict[str, str]]:
    inventory = {}
    for directory in ["console", "oauth"]:
        root = source / "src" / "lingshu_gate" / "static" / directory
        if not root.is_dir() or root.is_symlink() or root.resolve(strict=True) != root:
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


def _verified_static(source: Path) -> dict[str, dict[str, str]]:
    # This is the already-published exact-head build receipt, not a new baseline
    # captured from whichever ignored static directory happens to be present.
    proof = Path(__file__).resolve().parents[1] / STATIC_MANIFEST_NAME
    if proof.is_symlink() or not proof.is_file():
        raise BoundaryError("Pinned static build evidence is unavailable")
    raw = proof.read_bytes()
    if hashlib.sha256(raw).hexdigest() != STATIC_MANIFEST_SHA256:
        raise BoundaryError("Pinned static build evidence changed")
    receipt = json.loads(raw)
    if receipt["source_sha"] != SOURCE_SHA or receipt["build_command"] != "npm --prefix web run build":
        raise BoundaryError("Static build evidence is not bound to the reviewed head")
    expected = {}
    if set(receipt["directories"]) != {"console", "oauth"}:
        raise BoundaryError("Static build evidence is incomplete")
    for name, record in receipt["directories"].items():
        files = record["files"]
        digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if len(files) != record["file_count"] or digest != record["inventory_sha256"]:
            raise BoundaryError("Static build evidence inventory is inconsistent")
        expected[name] = files
    if _inventory(source) != expected:
        raise BoundaryError("Static files differ from the pinned exact-head build")
    return expected


def _source_check(source: Path) -> dict[str, object]:
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
    tree = subprocess.check_output(
        ["/usr/bin/git", "-C", str(source), "rev-parse", "HEAD^{tree}", "HEAD:web"],
        env=safe_git_env,
        text=True,
    ).splitlines()
    if tree != [SOURCE_TREE, WEB_TREE]:
        raise BoundaryError("Reviewed source tree identity differs")
    entries = subprocess.check_output(
        ["/usr/bin/git", "-C", str(source), "ls-tree", "-rz", "HEAD", "--", "src/lingshu_gate", "scripts/e2e", "web", "tests/test_real_delivery_journey.py"],
        env=safe_git_env,
    )
    files = {}
    for entry in entries.split(b"\0"):
        if not entry:
            continue
        metadata, relative_raw = entry.split(b"\t", 1)
        mode, kind, object_id = metadata.decode().split()
        relative = relative_raw.decode()
        path = source / relative
        if mode not in {"100644", "100755"} or kind != "blob" or not path.is_file():
            raise BoundaryError("Reviewed input is not a regular source file")
        for ancestor in [path, *path.parents]:
            if ancestor == source:
                break
            if ancestor.is_symlink():
                raise BoundaryError("Reviewed input has a symlink boundary")
        raw = path.read_bytes()
        git_digest = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if git_digest != object_id:
            raise BoundaryError("Working input bytes differ from the exact Git blob")
        files[relative] = hashlib.sha256(raw).hexdigest()
    return {"source_sha": head, "tree_sha": tree[0], "web_tree_sha": tree[1], "files": files}


def _product_location(source: Path, binding: dict[str, object], name: str) -> tuple[Path, str, bool]:
    if name == "http_peer":
        relative = "scripts/e2e/http_peer.py"
        if relative not in binding["files"]:
            raise BoundaryError("Reviewed peer helper is absent from the Git source binding")
        return source / relative, binding["files"][relative], False
    if name != "lingshu_gate" and not name.startswith("lingshu_gate."):
        raise BoundaryError("Unexpected product module name")
    stem = "src/" + name.replace(".", "/")
    for relative, package in [(stem + "/__init__.py", True), (stem + ".py", False)]:
        if relative in binding["files"]:
            return source / relative, binding["files"][relative], package
    raise BoundaryError("Product module is absent from the reviewed Git tree")


def _is_reviewed_module(name: str) -> bool:
    # Only the product package and this exact fixture dependency are intercepted.
    return name == "http_peer" or name == "lingshu_gate" or name.startswith("lingshu_gate.")


def _check_module_origin(source: Path, binding: dict[str, object], name: str, origin: str | None) -> None:
    expected, digest, _ = _product_location(source, binding, name)
    if origin is None or Path(origin) != expected or expected.is_symlink() or expected.resolve(strict=True) != expected:
        raise BoundaryError("Product module resolved outside the exact source tree")
    if hashlib.sha256(expected.read_bytes()).hexdigest() != digest:
        raise BoundaryError("Product module bytes changed")


class ReviewedSourceLoader(importlib.machinery.SourceFileLoader):
    def __init__(self, name: str, path: Path, digest: str) -> None:
        super().__init__(name, str(path))
        self.digest = digest

    def get_code(self, fullname: str):
        # Never execute an ignored/stale __pycache__ with matching mtime/size.
        raw = Path(self.path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != self.digest:
            raise BoundaryError("Product import bytes changed")
        return self.source_to_code(raw, self.path)


class ReviewedProductFinder(importlib.abc.MetaPathFinder):
    def __init__(self, source: Path, binding: dict[str, object]) -> None:
        self.source, self.binding = source, binding

    def find_spec(self, fullname: str, path=None, target=None):
        if not _is_reviewed_module(fullname):
            return None
        location, digest, package = _product_location(self.source, self.binding, fullname)
        _check_module_origin(self.source, self.binding, fullname, str(location))
        return importlib.util.spec_from_file_location(
            fullname,
            location,
            loader=ReviewedSourceLoader(fullname, location, digest),
            submodule_search_locations=[str(location.parent)] if package else None,
        )


def _bind_product_source(source: Path, binding: dict[str, object]) -> None:
    if any(_is_reviewed_module(name) for name in sys.modules):
        raise BoundaryError("Product or peer helper was loaded before the source boundary")
    sys.path.insert(0, str(source / "src"))
    specification = importlib.util.find_spec("lingshu_gate")
    _check_module_origin(source, binding, "lingshu_gate", None if specification is None else specification.origin)
    sys.meta_path.insert(0, ReviewedProductFinder(source, binding))
    sys.path.insert(1, str(source / "scripts/e2e"))
    specification = importlib.util.find_spec("http_peer")
    _check_module_origin(source, binding, "http_peer", None if specification is None else specification.origin)


def _check_loaded_product(source: Path, binding: dict[str, object]) -> None:
    for name, module in list(sys.modules.items()):
        if _is_reviewed_module(name):
            _check_module_origin(source, binding, name, getattr(module, "__file__", None))
            _check_module_origin(source, binding, name, getattr(getattr(module, "__spec__", None), "origin", None))


def _prepared_inputs(layout: dict[str, object]) -> Path:
    source = Path(str(layout["source"]))
    if _source_check(source) != layout["source_binding"]:
        raise BoundaryError("Prepared source binding changed")
    if (
        layout["static_manifest_sha256"] != STATIC_MANIFEST_SHA256
        or _verified_static(source) != layout["static_inventory"]
    ):
        raise BoundaryError("Prepared exact-head static binding changed")
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != layout["adapter_sha256"]:
        raise BoundaryError("Prepared launcher changed")
    root = validate_owner(layout, str(layout["token"]))
    for name, digest in layout["prepared_files"].items():
        path = root / name
        if path.is_symlink() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise BoundaryError("Prepared test/report configuration changed")
    return source


def _write_config(layout: dict[str, object], source: Path, python: Path) -> None:
    root = Path(str(layout["root"]))
    helper = Path(__file__).with_name("local_http_acceptance.py")
    if helper.is_symlink() or not helper.is_file():
        raise BoundaryError("Reviewed HTTP acceptance helper unavailable")
    (root / "local_http_acceptance.py").write_bytes(helper.read_bytes())
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
    (root / "verify-static.ts").write_text(
        "import { execFileSync } from 'node:child_process'\n"
        + "export default async function () { execFileSync("
        + json.dumps(str(python))
        + ", "
        + json.dumps([str(Path(__file__).resolve()), "verify-served", "--root", str(root)])
        + ", { env: process.env, timeout: 30000, stdio: 'pipe' }) }\n"
    )
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
            + "}"
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
    projects.append(json.dumps({
        "name": "local-delivery",
        "testDir": str(source / "web/e2e"),
        "testMatch": "delivery-real.spec.ts",
        "use": {"viewport": {"width": 1600, "height": 900}},
    }))
    fixture_command = shlex.join(
        [str(python), "-I", "-B", str(Path(__file__).resolve()), "fixture", "--root", str(root)]
    )
    config = (
        "import { defineConfig } from " + json.dumps(str(source / "web/node_modules/@playwright/test/index.mjs")) + "\n"
    )
    config += "import base from " + json.dumps(str(source / "web/playwright.config.ts")) + "\n"
    config += "export default defineConfig({ ...base, workers: 1, retries: 0, globalTeardown: " + json.dumps(
        str(root / "defer-cleanup.ts")
    )
    config += ", outputDir: " + json.dumps(str(root / "artifacts/test-results"))
    config += ", globalSetup: " + json.dumps(str(root / "verify-static.ts"))
    config += (
        ", reporter: [['list'], ['json', { outputFile: "
        + json.dumps(str(root / "artifacts/results.json"))
        + " }], ['html', { outputFolder: "
        + json.dumps(str(root / "artifacts/html"))
        + ", open: 'never' }]],"
    )
    config += (
        " use: { ...base.use, launchOptions: { ...base.use.launchOptions, chromiumSandbox: true }, "
        "trace: 'retain-on-failure', screenshot: 'only-on-failure' }, projects: ["
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
    binding = _source_check(source)
    # Keep the venv executable's lexical path; resolving its symlink loses venv discovery.
    python, node, browsers = [Path(os.path.abspath(p)) for p in [python, node, browsers]]
    if not all(path.is_file() and os.access(path, os.X_OK) for path in [python, node]) or not browsers.is_dir():
        raise BoundaryError("Explicit runtime paths are not usable")
    inventory = _verified_static(source)
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
            "static_manifest_sha256": STATIC_MANIFEST_SHA256,
            "source_binding": binding,
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
            "verify-static.ts",
            "local_http_acceptance.py",
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
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise BoundaryError("Invalid loopback listener port")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        try:
            result = sock.connect_ex(("127.0.0.1", port))
        except OSError as error:
            raise BoundaryError("Loopback listener state is uncertain") from error
    if result == 0:
        return False
    if result == errno.ECONNREFUSED:
        return True
    raise BoundaryError("Loopback listener state is uncertain")


class OwnedRunSignals:
    """Interrupt execution once, then defer further signals through owned reap."""

    def __init__(self, receipt: dict[str, object]) -> None:
        self.receipt = receipt
        self.cleaning = False
        self.previous: dict[int, object] = {}

    def interrupt(self, signum: int, _frame: object) -> None:
        self.receipt.setdefault("interrupted_signal", signum)
        if self.cleaning:
            self.receipt["signal_deferred_during_cleanup"] = True
        else:
            raise KeyboardInterrupt

    def __enter__(self):
        for signum in [signal.SIGINT, signal.SIGTERM]:
            self.previous[signum] = signal.getsignal(signum)
            signal.signal(signum, self.interrupt)
        return self

    def __exit__(self, *_args: object) -> None:
        for signum, handler in self.previous.items():
            signal.signal(signum, handler)


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


def _check_app_static_routes(app, source: Path) -> None:
    meta = sys.modules.get("lingshu_gate.interfaces.control_api.meta_routes")
    if getattr(meta, "STATIC_DIR", None) != source / "src/lingshu_gate/static":
        raise BoundaryError("Actual Console route static directory differs")
    expected = source / "src/lingshu_gate/static/oauth"
    paths = {"/oauth/consent", "/oauth/assets/{asset_path:path}"}
    found = set()
    for route in app.routes:
        if getattr(route, "path", None) in paths:
            endpoint = route.endpoint
            cells = dict(zip(endpoint.__code__.co_freevars, endpoint.__closure__ or ()))
            if "static" not in cells or cells["static"].cell_contents != expected:
                raise BoundaryError("Actual OAuth route static directory differs")
            found.add(route.path)
    if found != paths:
        raise BoundaryError("Expected OAuth static routes are missing")


class RejectRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        raise BoundaryError("Static verification cannot follow redirects")


def _http_bytes(path: str) -> tuple[int, bytes]:
    if not path.startswith("/") or ".." in path.split("/") or "\\" in path or "?" in path or "#" in path:
        raise BoundaryError("Unexpected served asset path")
    opener = build_opener(ProxyHandler({}), RejectRedirect())
    request = Request("http://127.0.0.1:18763" + path, headers={"Accept": "text/html", "Accept-Encoding": "identity"})
    try:
        with opener.open(request, timeout=3) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


def _check_served_inventory(inventory: dict[str, dict[str, str]], fetch=_http_bytes) -> dict[str, object]:
    for relative, digest in inventory["console"].items():
        path = "/" if relative == "index.html" else "/" + relative
        status_code, raw = fetch(path)
        if status_code != 200 or hashlib.sha256(raw).hexdigest() != digest:
            raise BoundaryError("Actual served Console bytes differ from the exact-head build")
    for relative in inventory["oauth"]:
        path = "/oauth/consent" if relative == "oauth.html" else "/oauth/" + relative
        status_code, raw = fetch(path)
        # This scope does not enable OAuth or mint its owner/config/keys. Its
        # real disabled routes must remain closed; do not pretend these bytes
        # were served successfully or bypass ready_config for a hash check.
        if status_code != 404 or json.loads(raw) != {"error": "oauth_disabled"}:
            raise BoundaryError("OAuth routes are not in the approved disabled state")
    return {
        "source_sha": SOURCE_SHA,
        "static_manifest_sha256": STATIC_MANIFEST_SHA256,
        "console_served_assets_verified": len(inventory["console"]),
        "oauth_disk_assets_verified": len(inventory["oauth"]),
        "oauth_routes_disabled": True,
        "oauth_ui_served_bytes_verified": False,
    }


def verify_served(root: Path) -> dict[str, object]:
    layout = read_layout(root)
    _require_execution_approval(root, layout)
    _prepared_inputs(layout)
    product = root / "artifacts/product-binding.private.json"
    if product.is_symlink() or not product.is_file():
        raise BoundaryError("Actual fixture product binding is unavailable")
    if json.loads(product.read_text()) != {
        "source_sha": SOURCE_SHA,
        "product_modules_bound_before_initialization": True,
        "actual_console_and_oauth_route_directories_bound": True,
        "static_manifest_sha256": STATIC_MANIFEST_SHA256,
    }:
        raise BoundaryError("Actual fixture product binding differs")
    receipt = _check_served_inventory(layout["static_inventory"])
    _json_write(root / "artifacts/served-static.json", receipt)
    return receipt


def fixture(root: Path, ambient: dict[str, str], *, entry: bool = False) -> None:
    # Reject catalog/other injected flags before any Gate import or initialization.
    reject_injected_flags(ambient, root / "tmp" / ("gate-e2e-" + read_layout(root)["token"]))
    layout = read_layout(root)
    _require_execution_approval(root, layout)
    source = _prepared_inputs(layout)
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
        command = [python, "-I", "-B", str(Path(__file__).resolve()), "fixture-entry", "--root", str(root)]
        os.execve(python, command, environment)
    # Only a clean child can reach the real reviewed fixture. This path is
    # intentionally unexecuted by the pure negative tests.
    os.environ.clear()
    os.environ.update(environment)
    _bind_product_source(source, layout["source_binding"])
    _json_write(root / "fixture-launch-intent.json", {"fixture_start_requested": True})
    # Validate the actual helper before create_app can initialize any state.
    # serve.main's normal import then reuses this exact source-loaded module.
    importlib.import_module("http_peer")
    _check_loaded_product(source, layout["source_binding"])
    gate_main = importlib.import_module("lingshu_gate.main")
    _check_loaded_product(source, layout["source_binding"])
    original_create_app = gate_main.create_app

    def checked_create_app():
        _prepared_inputs(layout)
        _check_loaded_product(source, layout["source_binding"])
        app = original_create_app()
        _check_loaded_product(source, layout["source_binding"])
        _check_app_static_routes(app, source)
        _json_write(
            root / "artifacts/product-binding.private.json",
            {
                "source_sha": SOURCE_SHA,
                "product_modules_bound_before_initialization": True,
                "actual_console_and_oauth_route_directories_bound": True,
                "static_manifest_sha256": STATIC_MANIFEST_SHA256,
            },
        )
        return app

    gate_main.create_app = checked_create_app
    specification = importlib.util.spec_from_file_location(
        "owned_reviewed_fixture",
        source / "scripts/e2e/serve.py",
        loader=ReviewedSourceLoader(
            "owned_reviewed_fixture",
            source / "scripts/e2e/serve.py",
            layout["source_binding"]["files"]["scripts/e2e/serve.py"],
        ),
    )
    if specification is None or specification.loader is None:
        raise BoundaryError("Reviewed fixture cannot be loaded")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    module.tempfile = SimpleNamespace(TemporaryDirectory=HeldAppDirectory)
    os.chdir(source / "web")
    module.main()


def run(layout: dict[str, object], ambient: dict[str, str], *, fixture_scope_approved: bool,
        acceptance_kind: str = "browser") -> dict[str, object]:
    if not fixture_scope_approved:
        raise BoundaryError("Regenerable local fixture scope approval is required")
    if acceptance_kind not in {"browser", "http"}:
        raise BoundaryError("Unknown acceptance kind")
    root = validate_owner(layout, str(layout["token"]))
    environment = clean_environment(
        layout, ambient, Path(str(layout["python"])), Path(str(layout["node"])), Path(str(layout["browsers"]))
    )
    _prepared_inputs(layout)
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
    if acceptance_kind == "http":
        command = [str(layout["python"]), "-I", "-B", str(root / "local_http_acceptance.py"),
                   str(Path(__file__).resolve().parent), str(root)]
    known: dict[int, dict[str, int | str]] = {}
    receipt: dict[str, object] = {
        "source_sha": SOURCE_SHA,
        "adapter_sha256": layout["adapter_sha256"],
        "desktop_targets": DESKTOPS,
        "temporary_persistent_state": "retained",
        "acceptance_kind": acceptance_kind,
    }
    result_path = root / "artifacts/results.json"
    if result_path.exists() or result_path.is_symlink():
        if result_path.is_symlink() or not result_path.is_file():
            raise BoundaryError("Owned JSON report is not a regular file")
        # A preparation-only --list receipt cannot stand in for a real run.
        result_path.unlink()
    with OwnedRunSignals(receipt) as signals:
        try:
            execute_owned_command(layout, environment, command, known, receipt)
        except KeyboardInterrupt:
            receipt["execution_interrupted"] = True
            receipt["command_exit_code"] = 128 + int(receipt.get("interrupted_signal", signal.SIGINT))
        except Exception as error:
            receipt["execution_error"] = type(error).__name__
        finally:
            signals.cleaning = True
            try:
                reaped = reap_owned(known)
            except (BoundaryError, OSError):
                reaped = False
                receipt["cleanup_uncertain"] = True
        return finish_owned_run(layout, known, receipt, reaped)


def execute_owned_command(layout, environment, command, known, receipt) -> None:
    root = Path(str(layout["root"]))
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
    finally:
        # Discover an owned child even if interruption landed immediately after
        # Popen returned, before its leader identity was recorded.
        observe_owned(known, os.getpid())


def finish_owned_run(layout, known, receipt, reaped: bool) -> dict[str, object]:
    root = Path(str(layout["root"]))
    result_path = root / "artifacts/results.json"
    validate_owner(layout, str(layout["token"]))
    _json_write(root / "lifecycle.private.json", {"owned_identities": list(known.values()), "reaped": reaped})
    private_receipts = root.parent / (root.name + "-private")
    private_receipts.mkdir(mode=0o700)
    for name in ["run.log", "lifecycle.private.json"]:
        source = root / ("artifacts" if name == "run.log" else "") / name
        if source.is_symlink() or not source.is_file():
            raise BoundaryError("Owned private receipt is not a regular file")
        target = private_receipts / name
        with target.open("xb") as handle:
            os.chmod(target, 0o600)
            handle.write(source.read_bytes())
    if result_path.exists():
        results = json.loads(result_path.read_text())
        receipt["browser_stats"] = results["stats"]
        receipt["local_browser_subphase_passed"] = (
            receipt.get("command_exit_code") == 0
            and results["stats"]["expected"] == 48
            and results["stats"]["skipped"] == 0
            and results["stats"]["unexpected"] == 0
            and results["stats"]["flaky"] == 0
            and (root / "artifacts/served-static.json").is_file()
        )
    served = root / "artifacts/served-static.json"
    if served.is_file() and not served.is_symlink():
        receipt["static_source_and_serving_binding"] = json.loads(served.read_text())
    http_result = root / "artifacts/http-acceptance.json"
    if receipt.get("acceptance_kind") == "http" and http_result.is_file() and not http_result.is_symlink():
        receipt["http_acceptance"] = json.loads(http_result.read_text())
        receipt["local_http_subphase_passed"] = (
            receipt.get("command_exit_code") == 0 and receipt["http_acceptance"].get("passed") is True
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
    parser.add_argument("mode", choices=["prepare", "fixture", "fixture-entry", "verify-served", "run"])
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--node", type=Path)
    parser.add_argument("--browsers", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--fixture-scope-approved", action="store_true")
    parser.add_argument("--acceptance-kind", choices=["browser", "http"], default="browser")
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
        elif args.mode == "verify-served":
            print(json.dumps(verify_served(args.root)))
        else:
            receipt = run(read_layout(args.root), dict(os.environ), fixture_scope_approved=args.fixture_scope_approved,
                          acceptance_kind=args.acceptance_kind)
            print(json.dumps(receipt))
            if receipt.get("execution_interrupted"):
                return int(receipt["command_exit_code"])
            if not (receipt.get("local_http_subphase_passed") or receipt.get("local_browser_subphase_passed")):
                return 1
            if receipt.get("temporary_persistent_state") != "destroyed_with_exact_owned_root":
                return 2
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

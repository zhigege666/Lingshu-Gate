"""Official tool cache and bounded npm lock tarball acquisition, without scripts."""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import re
import shutil
import stat
import tarfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import urlsplit
from uuid import uuid4

from lingshu_gate.adapters.native_executor.controller import PodmanController, reject
from lingshu_gate.adapters.native_executor.https import PinnedHTTPS
from lingshu_gate.git_source import digest_json
from lingshu_gate.node_toolchain import node_version_supported, tool_preparation
from lingshu_gate.offline_build_contract import DependencyNode, verify_dependency_content
from lingshu_gate.ports.safe_network_executor import SafeExecutionCancelled

OFFICIAL = "https://registry.npmjs.org/"
BINARIES = {"npm": "bin/npm-cli.js", "pnpm": "bin/pnpm.cjs", "yarn": "bin/yarn.js"}


def chunks(data: bytes):
    for offset in range(0, len(data), 64 * 1024):
        yield data[offset:offset + 64 * 1024]


def engine_satisfies(version: str, expression: str) -> bool:
    """Conservative stable Node range evaluator; unknown syntax fails closed."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", version) or not isinstance(expression, str) or len(expression) > 256:
        return False
    current = tuple(int(value) for value in version.split("."))
    for option in expression.split("||"):
        comparators = re.findall(r"(?:>=|<=|>|<|\^|~|=)?\s*\d+(?:\.\d+){0,2}", option)
        if not comparators or "".join(comparators).replace(" ", "") != option.replace(" ", ""):
            return False
        matches = True
        for item in comparators:
            matched = re.fullmatch(r"(>=|<=|>|<|\^|~|=)?\s*(\d+(?:\.\d+){0,2})", item)
            if not matched:
                return False
            operator, raw = matched.groups()
            parts = tuple(int(value) for value in raw.split("."))
            target = parts + (0,) * (3 - len(parts))
            if operator in {"^", "~"}:
                upper = (target[0] + 1, 0, 0) if operator == "^" and target[0] else (target[0], target[1] + 1, 0)
                matches &= target <= current < upper
            elif operator == ">=":
                matches &= current >= target
            elif operator == ">":
                matches &= current > target
            elif operator == "<=":
                matches &= current <= target
            elif operator == "<":
                matches &= current < target
            else:
                matches &= current[:len(parts)] == parts
        if matches:
            return True
    return False


def extract_official(content: bytes, target: Path, limits: dict[str, int]) -> None:
    total = count = 0
    seen: set[str] = set()
    deadline = time.monotonic() + 30
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            count += 1
            total += member.size
            if count > limits["files"] or total > limits["expanded_bytes"] or time.monotonic() > deadline or member.size < 0:
                reject("package_manager_archive_limit", "Official distribution exceeds extraction limits")
            if path.is_absolute() or path.as_posix().rstrip("/") != member.name.rstrip("/") or not path.parts or path.parts[0] != "package" or any(part in {".", ".."} for part in path.parts) or "\\" in member.name or ":" in member.name or any(ord(ch) < 32 for ch in member.name) or not (member.isdir() or member.isfile()):
                reject("package_manager_archive_rejected", "Official distribution contains unsupported paths, links or types")
            key = path.as_posix().casefold()
            if key in seen:
                reject("package_manager_archive_rejected", "Official distribution contains ambiguous entries")
            seen.add(key)
            output = target / path
            if member.isdir():
                output.mkdir(parents=True, exist_ok=True)
            else:
                output.parent.mkdir(parents=True, exist_ok=True)
                reader = archive.extractfile(member)
                if reader is None:
                    reject("package_manager_archive_rejected", "Official distribution has a missing regular entry")
                with reader, output.open("xb") as writer:
                    shutil.copyfileobj(reader, writer, 64 * 1024)
                if output.stat().st_size != member.size:
                    reject("package_manager_archive_rejected", "Official distribution entry size changed")
                output.chmod(0o555 if member.mode & 0o111 else 0o444)


def checked_json(path: Path, maximum: int = 4 * 1024 * 1024) -> dict[str, Any]:
    if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode) or path.stat().st_size > maximum:
        reject("executor_project_metadata_rejected", "Project metadata is linked, non-regular or oversized")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        reject("executor_project_metadata_rejected", "Project metadata must be an object")
    return value


def project_policy(root: Path, manager: dict[str, Any], *, install: bool) -> None:
    # Applies to uploads as well as Git imports, before exposing content to a
    # verified manager. Alternate hooks/rc/cache selectors need separate review.
    for path in root.rglob("*"):
        if path.name.lower() in {".npmrc", ".yarnrc", ".yarnrc.yml", ".pnpmfile.cjs", "pnpm-workspace.yaml", "pip.conf", ".pypirc", ".netrc"}:
            reject("dependency_configuration_unsupported", "Project tool/network configuration requires a separately reviewed cache workflow")
    package = checked_json(root / "package.json")
    if install and package.get("workspaces"):
        reject("dependency_cache_workflow_unsupported", "npm workspace/link cache closure is not supported in this adapter")
    if install:
        lockfile = manager.get("lockfile")
        if lockfile not in {"package-lock.json", "npm-shrinkwrap.json"} or manager.get("name") != "npm":
            reject("dependency_cache_workflow_unsupported", "Only registry-only npm lock v2/v3 frozen installs are reviewed; no manager substitution is permitted")
        if lockfile == "package-lock.json" and (root / "npm-shrinkwrap.json").exists():
            reject("dependency_lock_changed", "npm shrinkwrap precedence conflicts with the confirmed selection")
        path = root / str(lockfile)
        content = path.read_bytes() if not path.is_symlink() and path.stat().st_size <= 4 * 1024 * 1024 else b""
        if hashlib.sha256(content).hexdigest() != manager.get("lockfile_sha256"):
            reject("dependency_lock_changed", "Dependency lock differs from the confirmed plan")


class ToolCache:
    def __init__(self, controller: PodmanController, https: PinnedHTTPS) -> None:
        self.controller, self.https = controller, https
        self.root = controller.root / "tools"

    @staticmethod
    def _rule(url: str) -> dict[str, Any]:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or "\\" in url or any(ord(ch) <= 32 for ch in url):
            reject("dependency_origin_rejected", "Tool/dependency source is not an approved HTTPS endpoint")
        return {"host": parsed.hostname, "port": parsed.port or 443, "private_cidrs": []}

    def _fetch(self, url: str, *, network: dict[str, Any], material: dict[str, Any], deadline: float, maximum: int, cancelled: Callable[[], bool], official: bool = False) -> bytes:
        credential = None
        if not official and urlsplit(url).netloc == urlsplit(network["npm_registry"]).netloc:
            credential = material.get("npm_credential")
        try:
            return self.https.request(url, rule=self._rule(url), material=material, deadline=deadline, maximum=maximum, credential=credential, cancelled=cancelled)[1]
        except InterruptedError:
            if cancelled():
                raise SafeExecutionCancelled("trusted_tool_fetch_closed") from None
            raise

    def prepare(self, specification: dict[str, Any], *, network: dict[str, Any], material: dict[str, Any], deadline: float, cancelled: Callable[[], bool], key: str) -> dict[str, Any]:
        self.controller.require_ready()
        name, version = specification.get("name"), specification.get("version")
        if specification != tool_preparation(str(name), str(version), specification.get("declared_integrity")):
            reject("package_manager_specification_rejected", "Tool preparation is not the generated fixed official specification")
        self.root.mkdir(mode=0o700, exist_ok=True)
        pointer = self.root / f"{name}-{version}.json"
        if pointer.exists():
            metadata = checked_json(pointer, 8192)
        else:
            metadata = json.loads(self._fetch(specification["official_metadata_url"], network=network, material=material, deadline=deadline, maximum=specification["limits"]["metadata_bytes"], cancelled=cancelled, official=True))
            metadata = {"name": metadata.get("name"), "version": metadata.get("version"), "engines": metadata.get("engines"), "dist": {field: (metadata.get("dist") or {}).get(field) for field in ("integrity", "tarball")}}
        integrity = metadata.get("dist", {}).get("integrity", "")
        if metadata.get("name") != name or metadata.get("version") != version or not isinstance(integrity, str) or not re.fullmatch(r"sha512-[A-Za-z0-9+/]{86}==", integrity):
            reject("package_manager_metadata_rejected", "Official exact-version metadata or SHA-512 integrity is missing")
        engines = (metadata.get("engines") or {}).get("node", "")
        if not engine_satisfies(self.controller.node_version, engines) or not node_version_supported(str(name), str(version), self.controller.node_version):
            reject("package_manager_node_incompatible", "Pinned image Node does not satisfy the exact official engines; automatic Node downloads are disabled")
        cache_key = digest_json({"name": name, "version": version, "integrity": integrity})
        target = self.root / cache_key
        if not target.exists():
            url = metadata["dist"]["tarball"]
            if not isinstance(url, str) or not url.startswith(OFFICIAL + str(name) + "/-/") or self._rule(url)["port"] != 443:
                reject("package_manager_metadata_rejected", "Official tool tarball source is outside the fixed registry/package origin")
            registry = network["npm_registry"].rstrip("/") + "/"
            self._rule(registry)
            content = self._fetch(registry + url.removeprefix(OFFICIAL), network=network, material=material, deadline=deadline, maximum=specification["limits"]["archive_bytes"], cancelled=cancelled)
            verify_dependency_content(DependencyNode(str(name), url, integrity), chunks(content), max_bytes=specification["limits"]["archive_bytes"])
            declared = specification.get("declared_integrity")
            if declared:
                algorithm, expected = declared.split(".", 1)
                if not hmac.compare_digest(hashlib.new(algorithm, content).hexdigest().lower(), expected.lower()):
                    reject("package_manager_integrity_unverified", "Distribution does not match the declared integrity pin")
            temporary = self.root / ("prepare-" + uuid4().hex)
            temporary.mkdir(mode=0o700)
            try:
                extract_official(content, temporary, specification["limits"])
                package = checked_json(temporary / "package" / "package.json", 1024 * 1024)
                if package.get("name") != name or package.get("version") != version or (package.get("engines") or {}).get("node") != engines or not (temporary / "package" / BINARIES[str(name)]).is_file():
                    reject("package_manager_archive_rejected", "Official archive does not match its exact metadata or reviewed CLI")
                fingerprint = self.controller._inventory(temporary)
                temporary.rename(target)
                metadata["fingerprint"] = fingerprint
                metadata["declared_verified"] = declared
                pointer.write_text(json.dumps(metadata))
                pointer.chmod(0o400)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        if not metadata.get("fingerprint") or self.controller._inventory(target) != metadata["fingerprint"] or specification.get("declared_integrity") != metadata.get("declared_verified"):
            reject("package_manager_cache_changed", "Verified tool cache changed or does not satisfy the declared integrity pin")
        result = self.controller.run(key + ":tool_probe", {"kind": "tool_probe", "manager": name, "binding": network.get("execution", {})}, mounts={"/tool": target}, timeout=max(1, min(10, int(deadline - time.monotonic()))), cancelled=cancelled)
        try:
            if result["returncode"] or result.get("package_manager_version") != version or result.get("node_version") != self.controller.node_version:
                reject("package_manager_version_changed", "Verified CLI or Node version differs from the prepared tool pin")
            return {"returncode": 0, "package_manager_version": version, "node_version": result["node_version"], "source_integrity": integrity, "cache_path": target, "duration_ms": result["duration_ms"]}
        finally:
            self.controller.release_output(result)

    def prepared(self, manager: dict[str, Any]) -> Path:
        name, version = manager.get("name"), manager.get("version")
        if name not in BINARIES or not re.fullmatch(r"\d+\.\d+\.\d+", str(version)):
            reject("package_manager_specification_rejected", "Manager version is not an exact generated pin")
        metadata = checked_json(self.root / f"{name}-{version}.json", 8192)
        target = self.root / digest_json({"name": name, "version": version, "integrity": metadata["dist"]["integrity"]})
        if self.controller._inventory(target) != metadata.get("fingerprint") or metadata.get("declared_verified") != manager.get("declared_integrity"):
            reject("package_manager_cache_changed", "Prepared tool is missing, changed or has a different integrity pin")
        return target

    def npm_dependencies(self, root: Path, manager: dict[str, Any], *, network: dict[str, Any], material: dict[str, Any], deadline: float, cancelled: Callable[[], bool]) -> Path:
        project_policy(root, manager, install=True)
        lock = checked_json(root / manager["lockfile"])
        if lock.get("lockfileVersion") not in {2, 3} or not isinstance(lock.get("packages"), dict) or "" not in lock["packages"] or len(lock["packages"]) > 5000:
            reject("dependency_cache_workflow_unsupported", "npm cache requires a complete bounded v2/v3 packages table")
        registry = network["npm_registry"].rstrip("/") + "/"
        self._rule(registry)
        temporary = self.controller.root / ("dependencies-" + uuid4().hex)
        temporary.mkdir(mode=0o700)
        index: list[dict[str, str]] = []
        total = 0
        try:
            for path, entry in lock["packages"].items():
                if path == "":
                    continue
                if not isinstance(path, str) or not path.startswith("node_modules/") or PurePosixPath(path).as_posix() != path or ".." in PurePosixPath(path).parts or not isinstance(entry, dict) or entry.get("link") or entry.get("inBundle"):
                    reject("dependency_cache_workflow_unsupported", "npm linked, workspace or bundled cache entries are unsupported")
                url, integrity = entry.get("resolved"), entry.get("integrity")
                if not isinstance(url, str) or not isinstance(integrity, str) or not url.startswith((OFFICIAL, registry)):
                    reject("dependency_origin_rejected", "Every npm package requires a pinned approved registry tarball and integrity; Git/file/link sources are unsupported")
                self._rule(url)
                if "/-/" not in url or not url.endswith(".tgz"):
                    reject("dependency_origin_rejected", "npm content source must be a fixed registry tarball")
                source = registry + url.removeprefix(OFFICIAL) if url.startswith(OFFICIAL) else url
                content = self._fetch(source, network=network, material=material, deadline=deadline, maximum=50 * 1024 * 1024, cancelled=cancelled)
                verify_dependency_content(DependencyNode("npm", url, integrity), chunks(content), max_bytes=50 * 1024 * 1024)
                total += len(content)
                if total > 200 * 1024 * 1024 or time.monotonic() >= deadline:
                    reject("dependency_cache_limit", "Dependency tarballs exceed the bounded download budget")
                filename = hashlib.sha256(content).hexdigest() + ".tgz"
                (temporary / filename).write_bytes(content)
                index.append({"file": filename, "integrity": integrity})
            (temporary / "index.json").write_text(json.dumps(index))
            return temporary
        except BaseException:
            shutil.rmtree(temporary)
            raise

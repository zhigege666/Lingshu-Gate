"""Official tools and bounded registry lock content acquisition, without scripts."""
from __future__ import annotations

import hashlib
import hmac
import base64
import gzip
import io
import json
import re
import shutil
import tarfile
import time
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import urlsplit
from uuid import uuid4

from lingshu_gate.adapters.native_executor.controller import PodmanController, reject
from lingshu_gate.adapters.native_executor.https import PinnedHTTPS
from lingshu_gate.adapters.native_executor.locked_dependencies import NAME, pnpm_tarballs, yarn_tarballs
from lingshu_gate.git_source import digest_json
from lingshu_gate.node_toolchain import node_version_supported, tool_preparation
from lingshu_gate.offline_build_contract import DependencyNode, verify_dependency_content
from lingshu_gate.adapters.native_executor.shims import SHIM_REVISION, install_shims
from lingshu_gate.safe_files import open_regular_file

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
    compressed = gzip.GzipFile(fileobj=io.BytesIO(content))
    class BoundedDecodedArchive(io.RawIOBase):
        consumed = 0
        def read(self, size: int = -1) -> bytes:
            if size < 0 or self.consumed + size > limits["expanded_bytes"] + limits["files"] * 4096 + 1024 * 1024 or time.monotonic() > deadline:
                reject("package_manager_archive_limit", "Official distribution metadata/decompression exceeds limits")
            value = compressed.read(size)
            self.consumed += len(value)
            return value
    with compressed, tarfile.open(fileobj=BoundedDecodedArchive(), mode="r|") as archive:
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


def checked_content(path: Path, maximum: int = 4 * 1024 * 1024) -> bytes:
    try:
        with open_regular_file(path, maximum=maximum) as (reader, info):
            content = reader.read(maximum + 1)
            if len(content) != info.st_size:
                raise ValueError
        return content
    except (OSError, ValueError):
        reject("executor_project_metadata_rejected", "Project metadata is not unchanged bounded regular content")


def checked_json(path: Path, maximum: int = 4 * 1024 * 1024) -> dict[str, Any]:
    try:
        value = json.loads(checked_content(path, maximum))
    except (ValueError, RecursionError):
        reject("executor_project_metadata_rejected", "Project metadata has invalid bounded JSON")
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
    if install and any(package.get(field) for field in ("workspaces", "resolutions", "overrides", "pnpm", "installConfig", "bundleDependencies", "bundledDependencies", "dependenciesMeta")):
        reject("dependency_cache_workflow_unsupported", "Workspace, patch, override, PnP and bundled workflows require separate cache review")
    if install:
        cache_manager_supported(manager)
        lockfile = manager.get("lockfile")
        accepted = {"npm": {"package-lock.json", "npm-shrinkwrap.json"}, "pnpm": {"pnpm-lock.yaml"}, "yarn": {"yarn.lock"}}
        if lockfile not in accepted[manager["name"]]:
            reject("dependency_cache_workflow_unsupported", "Frozen installation requires the selected manager's native lockfile")
        if lockfile == "package-lock.json" and (root / "npm-shrinkwrap.json").exists():
            reject("dependency_lock_changed", "npm shrinkwrap precedence conflicts with the confirmed selection")
        content = checked_content(root / str(lockfile))
        if hashlib.sha256(content).hexdigest() != manager.get("lockfile_sha256"):
            reject("dependency_lock_changed", "Dependency lock differs from the confirmed plan")
        seed_manifest(package)


def cache_manager_supported(manager: dict[str, Any]) -> None:
    name, version = manager.get("name"), str(manager.get("version", ""))
    if name not in BINARIES or not re.fullmatch(r"\d+\.\d+\.\d+", version):
        reject("dependency_cache_workflow_unsupported", "Cache installation requires a selected exact official manager")
    major = int(version.split(".")[0])
    if name == "pnpm" and major not in {8, 9}:
        reject("pnpm_cache_format_unsupported", "pnpm 10/11 package-ID-dependent stores require a separately reviewed cache adapter")
    if name == "yarn" and not version.startswith("1.22."):
        reject("dependency_cache_workflow_unsupported", "Only Yarn Classic 1.22 registry mirrors are supported")


def seed_manifest(package: dict[str, Any]) -> dict[str, Any]:
    """Carry dependency requests only; never project scripts, bin or hooks."""
    value: dict[str, Any] = {"name": "gate-cache-seed", "version": "0.0.0", "private": True}
    for field in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        entries = package.get(field, {})
        if not isinstance(entries, dict) or len(entries) > 5000 or any(not isinstance(key, str) or not NAME.fullmatch(key) or not isinstance(request, str) or not re.fullmatch(r"[A-Za-z0-9*<>=~^| .+-]{1,256}", request) for key, request in entries.items()):
            reject("dependency_cache_workflow_unsupported", "Project dependency requests require bounded registry ranges/tags; Git/file/link/alias protocols are unsupported")
        if entries:
            value[field] = entries
    meta = package.get("peerDependenciesMeta", {})
    if not isinstance(meta, dict) or len(meta) > 5000 or any(not isinstance(key, str) or not NAME.fullmatch(key) or not isinstance(options, dict) or set(options) != {"optional"} or type(options["optional"]) is not bool for key, options in meta.items()):
        reject("dependency_cache_workflow_unsupported", "Peer metadata supports only bounded optional boolean declarations")
    if meta:
        value["peerDependenciesMeta"] = meta
    return value


class ToolCache:
    def __init__(self, controller: PodmanController, https: PinnedHTTPS) -> None:
        self.controller, self.https = controller, https
        self.root = controller.root / "tools"

    @staticmethod
    def _validate_pin(metadata: dict[str, Any], declared: str | None) -> None:
        if not declared:
            return
        matched = re.fullmatch(r"(sha224|sha256|sha384|sha512)\.([a-fA-F0-9]+)", declared)
        if not matched:
            reject("package_manager_integrity_unverified", "Request integrity pin is invalid")
        algorithm, expected = matched.groups()
        actual = (metadata.get("archive_hashes") or {}).get(algorithm)
        if actual is None and algorithm == "sha512":
            actual = base64.b64decode(metadata["dist"]["integrity"].removeprefix("sha512-"), validate=True).hex()
        if not isinstance(actual, str) or not hmac.compare_digest(actual.lower(), expected.lower()):
            reject("package_manager_integrity_unverified", "Verified distribution bytes do not satisfy this request's integrity pin")

    @staticmethod
    def _write_metadata(pointer: Path, metadata: dict[str, Any]) -> None:
        temporary = pointer.with_name("metadata-" + uuid4().hex)
        try:
            temporary.write_text(json.dumps(metadata))
            temporary.chmod(0o400)
            temporary.replace(pointer)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _rule(url: str) -> dict[str, Any]:
        parsed = urlsplit(url)
        if len(url) > 2048 or parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment or "\\" in url or any(ord(ch) <= 32 for ch in url):
            reject("dependency_origin_rejected", "Tool/dependency source is not an approved HTTPS endpoint")
        return {"host": parsed.hostname, "port": parsed.port or 443, "private_cidrs": []}

    def _fetch(self, url: str, *, network: dict[str, Any], material: dict[str, Any], deadline: float, maximum: int, cancelled: Callable[[], bool], official: bool = False) -> bytes:
        credential = None
        if not official and urlsplit(url).netloc == urlsplit(network["npm_registry"]).netloc:
            credential = material.get("npm_credential")
        return self.https.request(url, rule=self._rule(url), material=material, deadline=deadline, maximum=maximum, credential=credential, cancelled=cancelled)[1]

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
            if sum(path.is_dir() for path in self.root.iterdir()) >= 4:
                reject("package_manager_cache_capacity", "The four-distribution verified tool cache is full; administrator eviction is required")
            url = metadata["dist"]["tarball"]
            if not isinstance(url, str) or not url.startswith(OFFICIAL + str(name) + "/-/") or self._rule(url)["port"] != 443:
                reject("package_manager_metadata_rejected", "Official tool tarball source is outside the fixed registry/package origin")
            registry = network["npm_registry"].rstrip("/") + "/"
            self._rule(registry)
            content = self._fetch(registry + url.removeprefix(OFFICIAL), network=network, material=material, deadline=deadline, maximum=specification["limits"]["archive_bytes"], cancelled=cancelled)
            verify_dependency_content(DependencyNode(str(name), url, integrity), chunks(content), max_bytes=specification["limits"]["archive_bytes"])
            metadata["archive_hashes"] = {algorithm: hashlib.new(algorithm, content).hexdigest() for algorithm in ("sha224", "sha256", "sha384", "sha512")}
            self._validate_pin(metadata, specification.get("declared_integrity"))
            temporary = self.root / ("prepare-" + uuid4().hex)
            temporary.mkdir(mode=0o700)
            try:
                extract_official(content, temporary, specification["limits"])
                package = checked_json(temporary / "package" / "package.json", 1024 * 1024)
                if package.get("name") != name or package.get("version") != version or (package.get("engines") or {}).get("node") != engines or not (temporary / "package" / BINARIES[str(name)]).is_file():
                    reject("package_manager_archive_rejected", "Official archive does not match its exact metadata or reviewed CLI")
                install_shims(temporary, str(name))
                metadata["shim_revision"] = SHIM_REVISION
                fingerprint = self.controller._inventory(temporary)
                temporary.rename(target)
                metadata["fingerprint"] = fingerprint
                self._write_metadata(pointer, metadata)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        if not metadata.get("fingerprint") or self.controller._inventory(target) != metadata["fingerprint"]:
            reject("package_manager_cache_changed", "Verified tool cache changed")
        if metadata.get("shim_revision") != SHIM_REVISION:
            if (target / "shims").exists():
                reject("package_manager_shims_unprepared", "Cached launchers require a reviewed preparation migration")
            install_shims(target, str(name))
            metadata["shim_revision"] = SHIM_REVISION
            metadata["fingerprint"] = self.controller._inventory(target)
            self._write_metadata(pointer, metadata)
        if not metadata.get("archive_hashes"):
            # Upgrade old pointers only by fetching and re-verifying the same
            # official archive. Never derive an unrelated hash from extraction.
            url = metadata["dist"]["tarball"]
            if not isinstance(url, str) or not url.startswith(OFFICIAL + str(name) + "/-/") or self._rule(url)["port"] != 443:
                reject("package_manager_metadata_rejected", "Cached official archive origin is invalid")
            registry = network["npm_registry"].rstrip("/") + "/"
            self._rule(registry)
            content = self._fetch(registry + url.removeprefix(OFFICIAL), network=network, material=material, deadline=deadline, maximum=specification["limits"]["archive_bytes"], cancelled=cancelled)
            verify_dependency_content(DependencyNode(str(name), url, integrity), chunks(content), max_bytes=specification["limits"]["archive_bytes"])
            metadata["archive_hashes"] = {algorithm: hashlib.new(algorithm, content).hexdigest() for algorithm in ("sha224", "sha256", "sha384", "sha512")}
            metadata.pop("declared_verified", None)
            self._write_metadata(pointer, metadata)
        self._validate_pin(metadata, specification.get("declared_integrity"))
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
        if self.controller._inventory(target) != metadata.get("fingerprint") or metadata.get("shim_revision") != SHIM_REVISION:
            reject("package_manager_cache_changed", "Prepared tool is missing or changed")
        self._validate_pin(metadata, manager.get("declared_integrity"))
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

    def dependencies(self, root: Path, manager: dict[str, Any], *, network: dict[str, Any], material: dict[str, Any], deadline: float, cancelled: Callable[[], bool]) -> Path:
        if manager["name"] == "npm":
            return self.npm_dependencies(root, manager, network=network, material=material, deadline=deadline, cancelled=cancelled)
        project_policy(root, manager, install=True)
        registry = network["npm_registry"].rstrip("/")
        self._rule(registry + "/")
        lock = checked_content(root / manager["lockfile"])
        records = yarn_tarballs(lock, registry) if manager["name"] == "yarn" else pnpm_tarballs(lock, registry, manager["version"])
        temporary = self.controller.root / ("dependencies-" + uuid4().hex)
        temporary.mkdir(mode=0o700)
        total = 0
        seen: dict[str, str] = {}
        index: list[dict[str, str]] = []
        try:
            (temporary / "mirror").mkdir()
            for item in records:
                if cancelled():
                    from lingshu_gate.ports.safe_network_executor import SafeExecutionCancelled
                    raise SafeExecutionCancelled("dependency_acquisition_cancelled")
                if item.filename in seen:
                    if seen[item.filename] != item.integrity:
                        reject("dependency_lock_unsupported", "Conflicting content hashes share a registry mirror filename")
                    continue
                content = self._fetch(item.source, network=network, material=material, deadline=deadline, maximum=50 * 1024 * 1024, cancelled=cancelled)
                verify_dependency_content(DependencyNode(manager["name"], item.source, item.integrity), chunks(content), max_bytes=50 * 1024 * 1024)
                if item.legacy_sha1 and hashlib.sha1(content).hexdigest() != item.legacy_sha1:
                    reject("dependency_integrity_unverified", "Yarn legacy tarball hash disagrees with its strong verified content")
                total += len(content)
                if total > 200 * 1024 * 1024 or time.monotonic() >= deadline:
                    reject("dependency_cache_limit", "Dependency tarballs exceed the bounded download budget")
                seen[item.filename] = item.integrity
                (temporary / "mirror" / item.filename).write_bytes(content)
                index.append({"file": "mirror/" + item.filename, "integrity": item.integrity})
            (temporary / "index.json").write_text(json.dumps(index))
            (temporary / manager["lockfile"]).write_bytes(lock)
            (temporary / "package.json").write_text(json.dumps(seed_manifest(checked_json(root / "package.json"))))
            return temporary
        except BaseException:
            shutil.rmtree(temporary)
            raise

"""Bounded registry-content lists; selected official CLI proves frozen closure."""
from __future__ import annotations

import json
import csv
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import yaml

from lingshu_gate.adapters.native_executor.controller import reject
from lingshu_gate.offline_build_contract import parse_strong_sri

NAME = re.compile(r"(?:@[a-z0-9][a-z0-9._-]*/)?[a-z0-9][a-z0-9._-]*")
VERSION = re.compile(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?")
OFFICIAL_ORIGINS = {"registry.npmjs.org", "registry.yarnpkg.com"}
REGISTRY_REQUEST = re.compile(r"[A-Za-z0-9*<>=~^| .+-]{1,256}")


@dataclass(frozen=True)
class LockedTarball:
    source: str
    integrity: str
    filename: str
    legacy_sha1: str | None = None


def registry_tarball(url: str, integrity: str, registry: str) -> LockedTarball:
    parse_strong_sri(integrity)
    try:
        parsed, chosen = urlsplit(url), urlsplit(registry)
        origin = (parsed.hostname, parsed.port or 443)
        selected_origin = (chosen.hostname, chosen.port or 443)
    except ValueError:
        reject("dependency_origin_rejected", "Lock tarball origin/port is invalid")
    if chosen.scheme != "https" or chosen.path not in {"", "/"} or parsed.scheme != "https" or parsed.username or parsed.password or parsed.query or origin not in {(host, 443) for host in OFFICIAL_ORIGINS} | {selected_origin} or len(url) > 2048:
        reject("dependency_origin_rejected", "Lock content must use the official or selected HTTPS registry origin")
    matched = re.fullmatch(r"/(?:(@[a-z0-9][a-z0-9._-]*)/)?([a-z0-9][a-z0-9._-]*)/-/([A-Za-z0-9._+-]+\.tgz)", parsed.path)
    if not matched or any(ord(ch) < 33 for ch in url) or parsed.fragment and not re.fullmatch(r"[a-f0-9]{40}", parsed.fragment):
        reject("dependency_origin_rejected", "Lock tarball path/hash is unsupported")
    scope, _, basename = matched.groups()
    filename = (scope + "-" if scope else "") + basename
    canonical_path = parsed.path.lstrip("/")
    source = registry.rstrip("/") + "/" + canonical_path
    # The selected registry is the acquisition origin; original lock bytes
    # remain unchanged for the manager's own offline/frozen verification.
    return LockedTarball(source, integrity, filename, parsed.fragment or None)


def yarn_tarballs(content: bytes, registry: str) -> tuple[LockedTarball, ...]:
    if len(content) > 4 * 1024 * 1024 or b"# yarn lockfile v1" not in content[:2048] or b"__metadata:" in content:
        reject("dependency_lock_unsupported", "Only bounded Yarn Classic v1 locks are supported")
    records: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    nested = False
    edges = 0
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeError:
        reject("dependency_lock_unsupported", "Yarn lock requires UTF-8 data")
    for line in lines:
        if not line.strip() or line.startswith("#"):
            continue
        if len(line) > 8192 or "\t" in line:
            reject("dependency_lock_unsupported", "Yarn lock line exceeds its grammar bounds")
        if not line.startswith(" "):
            if not line.endswith(":") or len(records) >= 5000:
                reject("dependency_lock_unsupported", "Yarn lock requires bounded top-level entries")
            try:
                selectors = next(csv.reader([line[:-1]], skipinitialspace=True, strict=True))
            except (csv.Error, StopIteration):
                reject("dependency_lock_unsupported", "Yarn lock selectors are malformed")
            for selector in selectors:
                name, separator, request = selector.rpartition("@")
                if not separator or not NAME.fullmatch(name) or not REGISTRY_REQUEST.fullmatch(request):
                    reject("dependency_cache_workflow_unsupported", "Yarn selectors require registry ranges/tags without aliases or Git/file protocols")
            current = {}
            records.append(current)
            nested = False
        elif line.startswith("    "):
            matched = re.fullmatch(r'    ("(?:[^"\\]|\\.)+"|[A-Za-z0-9@._/-]+) (.+)', line)
            if not nested or not matched:
                reject("dependency_lock_unsupported", "Unsupported nested Yarn lock grammar")
            try:
                dependency, raw = matched.groups()
                name = json.loads(dependency) if dependency.startswith('"') else dependency
                request = json.loads(raw) if raw.startswith('"') else raw
            except ValueError:
                reject("dependency_lock_unsupported", "Invalid nested Yarn dependency scalar")
            edges += 1
            if edges > 20000 or not isinstance(name, str) or not NAME.fullmatch(name) or not isinstance(request, str) or not REGISTRY_REQUEST.fullmatch(request):
                reject("dependency_cache_workflow_unsupported", "Yarn dependency edges exceed bounds or require an unreviewed non-registry workflow")
        elif current is None or not line.startswith("  "):
            reject("dependency_lock_unsupported", "Unsupported Yarn lock indentation")
        elif line in {"  dependencies:", "  optionalDependencies:"}:
            nested = True
        else:
            matched = re.fullmatch(r"  (version|resolved|integrity) (.+)", line)
            if not matched or matched[1] in current:
                reject("dependency_lock_unsupported", "Yarn lock has unsupported or duplicate fields")
            field, raw = matched.groups()
            try:
                value = json.loads(raw) if raw.startswith('"') else raw
            except ValueError:
                reject("dependency_lock_unsupported", "Invalid Yarn lock scalar")
            if not isinstance(value, str):
                reject("dependency_lock_unsupported", "Yarn lock requires scalar pin fields")
            current[field] = value
            nested = False
    result = []
    for entry in records:
        if set(entry) != {"version", "resolved", "integrity"} or not VERSION.fullmatch(entry["version"]):
            reject("dependency_lock_unsupported", "Every Yarn entry requires exact version, registry tarball and strong SRI")
        result.append(registry_tarball(entry["resolved"], entry["integrity"], registry))
    return tuple(result)


def strict_yaml(content: bytes) -> dict[str, Any]:
    if len(content) > 4 * 1024 * 1024:
        reject("dependency_lock_unsupported", "pnpm lock exceeds the byte limit")
    count = depth = 0
    try:
        events = yaml.parse(content)
        for event in events:
            count += 1
            if isinstance(event, yaml.AliasEvent) or getattr(event, "anchor", None) or getattr(event, "tag", None):
                reject("dependency_lock_unsupported", "pnpm aliases, anchors and explicit tags are unsupported")
            if isinstance(event, (yaml.MappingStartEvent, yaml.SequenceStartEvent)):
                depth += 1
            if isinstance(event, (yaml.MappingEndEvent, yaml.SequenceEndEvent)):
                depth -= 1
            if count > 100000 or depth > 32:
                reject("dependency_lock_unsupported", "pnpm lock exceeds structural bounds")
    except (yaml.YAMLError, UnicodeError):
        reject("dependency_lock_unsupported", "pnpm lock has invalid YAML encoding/grammar")
    class Loader(yaml.SafeLoader):
        def construct_mapping(self, node, deep=False):
            keys = [self.construct_object(key, deep=deep) for key, _ in node.value]
            if any(not isinstance(key, str) for key in keys) or len(keys) != len(set(keys)):
                reject("dependency_lock_unsupported", "pnpm lock has non-string or duplicate keys")
            return super().construct_mapping(node, deep=deep)
    try:
        value = yaml.load(content, Loader=Loader)
    except (yaml.YAMLError, UnicodeError):
        reject("dependency_lock_unsupported", "pnpm lock has invalid scalar/map data")
    if not isinstance(value, dict):
        reject("dependency_lock_unsupported", "pnpm lock must be a mapping")
    return value


def pnpm_tarballs(content: bytes, registry: str, version: str) -> tuple[LockedTarball, ...]:
    major = int(version.split(".")[0])
    if major not in {8, 9}:
        reject("pnpm_cache_format_unsupported", "This cache adapter supports the reviewed pnpm 8/9 v3 store only")
    lock = strict_yaml(content)
    if str(lock.get("lockfileVersion")) not in ({"6", "6.0"} if major == 8 else {"9", "9.0"}) or not isinstance(lock.get("packages", {}), dict) or len(lock.get("packages", {})) > 5000 or lock.get("patchedDependencies") or lock.get("overrides") or lock.get("importers") and (not isinstance(lock["importers"], dict) or set(lock["importers"]) != {"."}):
        reject("dependency_lock_unsupported", "pnpm requires a complete single-project matching registry lock without patches/overrides")
    result = []
    edge_count = 0
    for table in (lock.get("packages", {}), lock.get("snapshots", {})):
        if not isinstance(table, dict) or len(table) > 5000:
            reject("dependency_lock_unsupported", "pnpm snapshot/package table exceeds bounds")
        for entry in table.values():
            if not isinstance(entry, dict) or entry.get("bundledDependencies") or entry.get("bundleDependencies"):
                reject("dependency_lock_unsupported", "pnpm package/snapshot requires unbundled mapping data")
            for field in ("dependencies", "optionalDependencies"):
                edges_map = entry.get(field, {})
                if not isinstance(edges_map, dict):
                    reject("dependency_lock_unsupported", "pnpm dependency edges require mappings")
                edge_count += len(edges_map)
                if edge_count > 20000 or any(not NAME.fullmatch(name) or not isinstance(pin, str) or ":" in pin or len(pin) > 2048 for name, pin in edges_map.items()):
                    reject("dependency_cache_workflow_unsupported", "pnpm edges exceed bounds or require Git/file/link/alias protocols")
    for key, entry in lock.get("packages", {}).items():
        base = key.lstrip("/").split("(", 1)[0]
        name, separator, exact = base.rpartition("@")
        if not separator or not NAME.fullmatch(name) or not VERSION.fullmatch(exact) or not isinstance(entry, dict) or not isinstance(entry.get("resolution"), dict):
            reject("dependency_lock_unsupported", "pnpm packages require exact registry name/version resolutions")
        resolution = entry["resolution"]
        if set(resolution) - {"integrity", "tarball"} or not isinstance(resolution.get("integrity"), str):
            reject("dependency_cache_workflow_unsupported", "pnpm Git/link/file/directory/variant resolutions are unsupported")
        if not resolution["integrity"].startswith("sha512-"):
            reject("pnpm_cache_format_unsupported", "pnpm local tarball seeding requires the lock's canonical SHA-512 CAFS content address")
        url = resolution.get("tarball", "https://registry.npmjs.org/" + name + "/-/" + name.rsplit("/", 1)[-1] + "-" + exact + ".tgz")
        if not isinstance(url, str):
            reject("dependency_origin_rejected", "pnpm tarball requires an exact registry URL")
        result.append(registry_tarball(url, resolution["integrity"], registry))
    return tuple(result)

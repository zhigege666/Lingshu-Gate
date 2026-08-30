"""Generate a deterministic SPDX 2.3 inventory of the frozen backend and Console."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import re
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from scripts.release.common import (
    REPOSITORY_ROOT,
    iso_timestamp,
    read_version,
    source_date_epoch,
    source_revision,
    write_json,
)

NPM_LOCK_FILE = REPOSITORY_ROOT / "web" / "package-lock.json"
CONSOLE_SPDX_ID = "SPDXRef-Package-application-lingshu-gate-console"
CPYTHON_SPDX_ID = "SPDXRef-Package-runtime-cpython"
PYINSTALLER_SPDX_ID = "SPDXRef-Package-build-pyinstaller-embedded-runtime"


@dataclass
class Component:
    name: str
    version: str
    license_declared: str
    supplier: str
    dependencies: set[str] = field(default_factory=set)


@dataclass
class NpmComponent:
    package_path: str
    name: str
    version: str
    license_declared: str
    dependencies: set[str] = field(default_factory=set)


def _python_spdx_id(name: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9.-]", "-", canonicalize_name(name))
    return f"SPDXRef-Package-pypi-{safe}"


def _npm_spdx_id(component: NpmComponent) -> str:
    safe_name = re.sub(r"[^A-Za-z0-9.-]", "-", component.name).strip("-")
    safe_version = re.sub(r"[^A-Za-z0-9.-]", "-", component.version).strip("-")
    path_digest = hashlib.sha256(component.package_path.encode("utf-8")).hexdigest()[:10]
    return f"SPDXRef-Package-npm-{safe_name}-{safe_version}-{path_digest}"


def _metadata_value(metadata: importlib.metadata.PackageMetadata, *names: str) -> str:
    for name in names:
        value = metadata.get(name, "").strip()
        if value:
            return value
    return ""


def collect_components(root_name: str) -> dict[str, Component]:
    """Walk only the installed runtime dependency closure of the application."""

    queue: deque[tuple[str, frozenset[str]]] = deque([(root_name, frozenset())])
    requested_extras: dict[str, set[str]] = {}
    components: dict[str, Component] = {}
    while queue:
        requested_name, extras = queue.popleft()
        normalized = canonicalize_name(requested_name)
        known_extras = requested_extras.setdefault(normalized, set())
        new_extras = set(extras) - known_extras
        if normalized in components and not new_extras:
            continue
        known_extras.update(extras)
        try:
            distribution = importlib.metadata.distribution(requested_name)
        except importlib.metadata.PackageNotFoundError as exc:
            raise RuntimeError(f"Installed release dependency is missing: {requested_name}") from exc

        metadata = distribution.metadata
        name = metadata.get("Name", requested_name)
        author = _metadata_value(metadata, "Author-email", "Author", "Maintainer-email", "Maintainer")
        component = components.setdefault(
            normalized,
            Component(
                name=name,
                version=distribution.version,
                # Core Metadata 2.4 License-Expression is SPDX-compatible. Older
                # free-form License values are not safe to place in this field.
                license_declared=_metadata_value(metadata, "License-Expression") or "NOASSERTION",
                supplier=f"Organization: {author}" if author else "NOASSERTION",
            ),
        )

        active_extras = known_extras or {""}
        for raw_requirement in distribution.requires or ():
            requirement = Requirement(raw_requirement)
            if requirement.marker is not None and not any(
                requirement.marker.evaluate({"extra": extra}) for extra in active_extras
            ):
                continue
            dependency_name = canonicalize_name(requirement.name)
            component.dependencies.add(dependency_name)
            queue.append((requirement.name, frozenset(requirement.extras)))
    return components


def _installed_component(distribution_name: str) -> Component:
    try:
        distribution = importlib.metadata.distribution(distribution_name)
    except importlib.metadata.PackageNotFoundError as exc:
        raise RuntimeError(f"Frozen release distribution is missing: {distribution_name}") from exc
    metadata = distribution.metadata
    name = metadata.get("Name", distribution_name)
    author = _metadata_value(metadata, "Author-email", "Author", "Maintainer-email", "Maintainer")
    return Component(
        name=name,
        version=distribution.version,
        license_declared=_metadata_value(metadata, "License-Expression") or "NOASSERTION",
        supplier=f"Organization: {author}" if author else "NOASSERTION",
    )


def _npm_name_from_path(package_path: str) -> str:
    marker = "node_modules/"
    if marker not in package_path:
        raise RuntimeError(f"Invalid npm package-lock path: {package_path!r}")
    return package_path.rsplit(marker, 1)[1]


def _resolve_npm_dependency(packages: dict[str, object], parent_path: str, dependency_name: str) -> str | None:
    prefix = parent_path
    while True:
        candidate = f"{prefix}/node_modules/{dependency_name}" if prefix else f"node_modules/{dependency_name}"
        if candidate in packages:
            return candidate
        if not prefix:
            return None
        prefix = prefix.rpartition("/")[0]


def _dependency_names(entry: dict[str, object]) -> dict[str, bool]:
    """Return dependency names mapped to whether a missing lock entry is allowed."""

    dependencies: dict[str, bool] = {}
    required = entry.get("dependencies", {})
    optional = entry.get("optionalDependencies", {})
    peers = entry.get("peerDependencies", {})
    peer_metadata = entry.get("peerDependenciesMeta", {})
    for label, value in (
        ("dependencies", required),
        ("optionalDependencies", optional),
        ("peerDependencies", peers),
        ("peerDependenciesMeta", peer_metadata),
    ):
        if not isinstance(value, dict):
            raise RuntimeError(f"package-lock entry {label} must be an object")

    for name in required:
        dependencies[str(name)] = False
    for name in optional:
        dependencies.setdefault(str(name), True)
    for name in peers:
        peer_name = str(name)
        metadata = peer_metadata.get(peer_name, {})
        if not isinstance(metadata, dict):
            raise RuntimeError(f"package-lock peer metadata for {peer_name!r} must be an object")
        if metadata.get("optional") is True:
            continue
        dependencies.setdefault(peer_name, False)
    return dependencies


def collect_npm_components(lock_path: Path = NPM_LOCK_FILE) -> tuple[dict[str, NpmComponent], set[str]]:
    """Walk the npm production dependency closure using lockfile node resolution."""

    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to read npm lockfile: {lock_path}") from exc
    if not isinstance(payload, dict) or payload.get("lockfileVersion") not in {2, 3}:
        raise RuntimeError(f"Unsupported npm lockfile format: {lock_path}")
    raw_packages = payload.get("packages")
    if not isinstance(raw_packages, dict):
        raise RuntimeError(f"npm lockfile does not contain a packages object: {lock_path}")
    packages: dict[str, object] = {str(key): value for key, value in raw_packages.items()}
    root_entry = packages.get("")
    if not isinstance(root_entry, dict):
        raise RuntimeError(f"npm lockfile does not contain a root package: {lock_path}")

    root_dependencies: set[str] = set()
    for dependency_name in _dependency_names({"dependencies": root_entry.get("dependencies", {})}):
        resolved = _resolve_npm_dependency(packages, "", dependency_name)
        if resolved is None:
            raise RuntimeError(f"npm production dependency is missing from the lockfile: {dependency_name}")
        root_dependencies.add(resolved)

    components: dict[str, NpmComponent] = {}
    queue: deque[str] = deque(sorted(root_dependencies))
    while queue:
        package_path = queue.popleft()
        if package_path in components:
            continue
        entry = packages.get(package_path)
        if not isinstance(entry, dict):
            raise RuntimeError(f"npm package entry must be an object: {package_path}")
        version = entry.get("version")
        if not isinstance(version, str) or not version:
            raise RuntimeError(f"npm package version is missing: {package_path}")
        license_value = entry.get("license")
        component = NpmComponent(
            package_path=package_path,
            name=_npm_name_from_path(package_path),
            version=version,
            license_declared=license_value if isinstance(license_value, str) and license_value else "NOASSERTION",
        )
        components[package_path] = component
        for dependency_name, missing_allowed in sorted(_dependency_names(entry).items()):
            resolved = _resolve_npm_dependency(packages, package_path, dependency_name)
            if resolved is None:
                if missing_allowed:
                    continue
                raise RuntimeError(
                    f"npm dependency {dependency_name!r} required by {package_path!r} is missing from the lockfile"
                )
            component.dependencies.add(resolved)
            queue.append(resolved)
    return components, root_dependencies


def build_spdx_document(
    root_name: str,
    *,
    target: str,
    npm_lock_path: Path = NPM_LOCK_FILE,
    frozen_runtime: bool = False,
    frozen_distributions: set[str] | None = None,
) -> dict[str, object]:
    components = collect_components(root_name)
    application_component_keys = set(components)
    frozen_component_keys: set[str] = set()
    for distribution_name in sorted(frozen_distributions or set()):
        key = canonicalize_name(distribution_name)
        if key in {canonicalize_name(root_name), "pyinstaller"} or key in components:
            continue
        component = _installed_component(distribution_name)
        component_key = canonicalize_name(component.name)
        components[component_key] = component
        frozen_component_keys.add(component_key)
    npm_components, npm_root_dependencies = collect_npm_components(npm_lock_path)
    root_key = canonicalize_name(root_name)
    if root_key not in components:
        raise RuntimeError(f"Root package was not discovered: {root_name}")
    version = read_version()
    revision = source_revision()
    fingerprint_lines = [
        *(f"pypi:{key}=={component.version}" for key, component in sorted(components.items())),
        *(
            f"npm:{path}:{component.name}=={component.version}"
            for path, component in sorted(npm_components.items())
        ),
    ]
    if frozen_runtime:
        fingerprint_lines.extend(
            (
                f"runtime:cpython=={platform.python_version()}",
                f"build:pyinstaller=={importlib.metadata.version('pyinstaller')}",
            )
        )
    fingerprint = hashlib.sha256(
        (revision + "\n" + "\n".join(fingerprint_lines)).encode("utf-8")
    ).hexdigest()[:20]
    packages: list[dict[str, object]] = []
    relationships: list[dict[str, str]] = [
        {
            "spdxElementId": "SPDXRef-DOCUMENT",
            "relationshipType": "DESCRIBES",
            "relatedSpdxElement": _python_spdx_id(root_name),
        }
    ]
    for key, component in sorted(components.items()):
        packages.append(
            {
                "SPDXID": _python_spdx_id(component.name),
                "name": component.name,
                "versionInfo": component.version,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": component.license_declared,
                "copyrightText": "NOASSERTION",
                "supplier": component.supplier,
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": f"pkg:pypi/{quote(canonicalize_name(component.name))}@{quote(component.version)}",
                    }
                ],
            }
        )
        for dependency in sorted(component.dependencies):
            if dependency in components:
                relationships.append(
                    {
                        "spdxElementId": _python_spdx_id(component.name),
                        "relationshipType": "DEPENDS_ON",
                        "relatedSpdxElement": _python_spdx_id(components[dependency].name),
                    }
                )
        if key in frozen_component_keys and key not in application_component_keys:
            relationships.append(
                {
                    "spdxElementId": _python_spdx_id(root_name),
                    "relationshipType": "CONTAINS",
                    "relatedSpdxElement": _python_spdx_id(component.name),
                }
            )
    packages.append(
        {
            "SPDXID": CONSOLE_SPDX_ID,
            "name": "Lingshu Gate Console",
            "versionInfo": version,
            "downloadLocation": "NOASSERTION",
            "filesAnalyzed": False,
            "licenseConcluded": "NOASSERTION",
            "licenseDeclared": "Apache-2.0",
            "copyrightText": "NOASSERTION",
            "supplier": "Organization: Lingshu Gate Contributors",
            "primaryPackagePurpose": "APPLICATION",
        }
    )
    relationships.append(
        {
            "spdxElementId": _python_spdx_id(root_name),
            "relationshipType": "CONTAINS",
            "relatedSpdxElement": CONSOLE_SPDX_ID,
        }
    )
    for package_path, component in sorted(npm_components.items()):
        packages.append(
            {
                "SPDXID": _npm_spdx_id(component),
                "name": component.name,
                "versionInfo": component.version,
                "downloadLocation": "NOASSERTION",
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": component.license_declared,
                "copyrightText": "NOASSERTION",
                "supplier": "NOASSERTION",
                "primaryPackagePurpose": "LIBRARY",
                "comment": f"Resolved production dependency at web/{package_path}",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceType": "purl",
                        "referenceLocator": f"pkg:npm/{quote(component.name, safe='/')}@{quote(component.version)}",
                    }
                ],
            }
        )
        for dependency_path in sorted(component.dependencies):
            if dependency_path in npm_components:
                relationships.append(
                    {
                        "spdxElementId": _npm_spdx_id(component),
                        "relationshipType": "DEPENDS_ON",
                        "relatedSpdxElement": _npm_spdx_id(npm_components[dependency_path]),
                    }
                )
    for dependency_path in sorted(npm_root_dependencies):
        relationships.append(
            {
                "spdxElementId": CONSOLE_SPDX_ID,
                "relationshipType": "DEPENDS_ON",
                "relatedSpdxElement": _npm_spdx_id(npm_components[dependency_path]),
            }
        )
    if frozen_runtime:
        pyinstaller_version = importlib.metadata.version("pyinstaller")
        packages.extend(
            (
                {
                    "SPDXID": CPYTHON_SPDX_ID,
                    "name": "CPython runtime",
                    "versionInfo": platform.python_version(),
                    "downloadLocation": "NOASSERTION",
                    "filesAnalyzed": False,
                    "licenseConcluded": "NOASSERTION",
                    "licenseDeclared": "PSF-2.0",
                    "copyrightText": "NOASSERTION",
                    "supplier": "Organization: Python Software Foundation",
                    "primaryPackagePurpose": "APPLICATION",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": f"pkg:generic/cpython@{quote(platform.python_version())}",
                        }
                    ],
                },
                {
                    "SPDXID": PYINSTALLER_SPDX_ID,
                    "name": "PyInstaller embedded bootloader and runtime hooks",
                    "versionInfo": pyinstaller_version,
                    "downloadLocation": "NOASSERTION",
                    "filesAnalyzed": False,
                    "licenseConcluded": "NOASSERTION",
                    "licenseDeclared": "(GPL-2.0-or-later WITH Bootloader-exception) AND Apache-2.0",
                    "copyrightText": "NOASSERTION",
                    "supplier": "Organization: PyInstaller Development Team",
                    "primaryPackagePurpose": "LIBRARY",
                    "externalRefs": [
                        {
                            "referenceCategory": "PACKAGE-MANAGER",
                            "referenceType": "purl",
                            "referenceLocator": f"pkg:pypi/pyinstaller@{quote(pyinstaller_version)}",
                        }
                    ],
                },
            )
        )
        for contained_id in (CPYTHON_SPDX_ID, PYINSTALLER_SPDX_ID):
            relationships.append(
                {
                    "spdxElementId": _python_spdx_id(root_name),
                    "relationshipType": "CONTAINS",
                    "relatedSpdxElement": contained_id,
                }
            )
    return {
        "spdxVersion": "SPDX-2.3",
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"Lingshu-Gate-{version}-{target}",
        "documentNamespace": f"https://spdx.org/spdxdocs/lingshu-gate-{version}-{target}-{fingerprint}",
        "creationInfo": {
            "created": iso_timestamp(source_date_epoch()),
            "creators": ["Tool: Lingshu-Gate-release-engineering"],
            "comment": f"Source revision: {revision}",
        },
        "packages": packages,
        "relationships": relationships,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--root-package", default="lingshu-gate")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, build_spdx_document(args.root_package, target=args.target))


if __name__ == "__main__":
    main()

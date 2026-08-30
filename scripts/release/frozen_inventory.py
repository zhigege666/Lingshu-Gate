"""Map PyInstaller's analyzed files back to installed Python distributions."""

from __future__ import annotations

import ast
import importlib.metadata
from collections.abc import Iterator
from pathlib import Path

from packaging.utils import canonicalize_name


def _installed_file_owners() -> dict[Path, str]:
    owners: dict[Path, str] = {}
    for distribution in importlib.metadata.distributions():
        distribution_name = distribution.metadata.get("Name", "").strip()
        if not distribution_name:
            continue
        normalized_name = canonicalize_name(distribution_name)
        for relative_path in distribution.files or ():
            path = Path(distribution.locate_file(relative_path)).resolve()
            previous = owners.setdefault(path, normalized_name)
            if previous != normalized_name:
                raise RuntimeError(f"Installed file has multiple distribution owners: {path}")
    return owners


def _source_paths(value: object) -> Iterator[Path]:
    if isinstance(value, (list, tuple)):
        if len(value) >= 2 and isinstance(value[1], str):
            candidate = Path(value[1])
            if candidate.is_absolute():
                yield candidate
        for item in value:
            yield from _source_paths(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from _source_paths(item)


def frozen_distribution_names(toc_path: Path) -> set[str]:
    """Return every installed distribution contributing a file to Analysis TOC."""

    try:
        payload = ast.literal_eval(toc_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, SyntaxError, ValueError) as exc:
        raise RuntimeError(f"Unable to read PyInstaller analysis inventory: {toc_path}") from exc
    owners = _installed_file_owners()
    distributions: set[str] = set()
    unowned_site_packages: set[Path] = set()
    for source_path in _source_paths(payload):
        resolved = source_path.resolve()
        owner = owners.get(resolved)
        if owner is not None:
            distributions.add(owner)
        elif "site-packages" in {part.casefold() for part in resolved.parts}:
            unowned_site_packages.add(resolved)
    if unowned_site_packages:
        preview = ", ".join(str(path) for path in sorted(unowned_site_packages)[:5])
        raise RuntimeError(f"Frozen third-party files have no distribution owner: {preview}")
    if not distributions:
        raise RuntimeError(f"No frozen Python distributions were discovered in {toc_path}")
    return distributions

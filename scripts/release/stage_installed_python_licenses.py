"""Copy license texts for every Python distribution installed in an image stage."""

from __future__ import annotations

import importlib.metadata
import json
import re
import shutil
import sys
from pathlib import Path

LEGAL_FILE_PATTERN = re.compile(r"^(?:licen[cs]e|copying|copyright|notice)(?:[._-].*)?$", re.IGNORECASE)


def is_license_file(relative_path: Path) -> bool:
    if LEGAL_FILE_PATTERN.fullmatch(relative_path.name):
        return True
    parts = tuple(part.casefold() for part in relative_path.parts)
    return any(part.endswith(".dist-info") and parts[index + 1 : index + 2] == ("licenses",) for index, part in enumerate(parts))


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: stage_installed_python_licenses.py OUTPUT_DIR")
    output_dir = Path(sys.argv[1])
    output_dir.mkdir(parents=True, exist_ok=False)
    records: list[dict[str, object]] = []
    for distribution in sorted(
        importlib.metadata.distributions(),
        key=lambda item: item.metadata.get("Name", "").casefold(),
    ):
        name = distribution.metadata.get("Name", "").strip()
        if not name:
            continue
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "-", name).strip("-").lower()
        component_root = output_dir / f"{safe_name}-{distribution.version}"
        copied: list[str] = []
        for relative in sorted(distribution.files or (), key=lambda item: item.as_posix()):
            relative_path = Path(relative.as_posix())
            if relative_path.is_absolute() or ".." in relative_path.parts or not is_license_file(relative_path):
                continue
            source = Path(distribution.locate_file(relative))
            if not source.is_file():
                continue
            target = component_root / relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            copied.append(target.relative_to(output_dir).as_posix())
        if not copied:
            raise RuntimeError(f"Installed Python distribution has no license text: {name}=={distribution.version}")
        records.append({"name": name, "version": distribution.version, "files": copied})
    (output_dir / "LICENSES.json").write_text(
        json.dumps(records, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()

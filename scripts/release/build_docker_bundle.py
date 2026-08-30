"""Build a deterministic, Core-only Docker Compose deployment bundle."""

from __future__ import annotations

import argparse
from pathlib import Path

from scripts.release.common import (
    REQUIRED_DOCUMENTATION_FILES,
    REQUIRED_LEGAL_FILES,
    REPOSITORY_ROOT,
    build_metadata,
    copy_release_file,
    create_tar_gz,
    read_version,
    reset_directory,
    source_date_epoch,
    validate_release_inputs,
    write_checksums,
    write_json,
)
from scripts.release.generate_sbom import build_spdx_document, collect_components, collect_npm_components
from scripts.release.license_inventory import stage_third_party_licenses


def build(output_dir: Path) -> Path:
    validate_release_inputs()
    version = read_version()
    release_build_root = REPOSITORY_ROOT / "build" / "release"
    release_build_root.mkdir(parents=True, exist_ok=True)
    build_root = release_build_root / "docker-compose"
    reset_directory(build_root, allowed_parent=release_build_root)
    stage_root = build_root / f"lingshu-gate-v{version}-docker-compose"
    stage_root.mkdir()

    copy_release_file(REPOSITORY_ROOT / "compose.prod.yaml", stage_root, destination_name="compose.yaml")
    copy_release_file(
        REPOSITORY_ROOT / "packaging" / "docker" / "README.md",
        stage_root,
        destination_name="DEPLOYMENT.md",
    )
    env_template = (REPOSITORY_ROOT / "packaging" / "docker" / ".env.example").read_text(encoding="utf-8")
    (stage_root / ".env.example").write_text(env_template.replace("@VERSION@", version), encoding="utf-8")
    offline_env_template = (
        REPOSITORY_ROOT / "packaging" / "docker" / ".env.offline.example"
    ).read_text(encoding="utf-8")
    for architecture in ("amd64", "arm64"):
        rendered = offline_env_template.replace("@VERSION@", version).replace("@ARCH@", architecture)
        (stage_root / f".env.offline-{architecture}.example").write_text(rendered, encoding="utf-8")
    for required in (*REQUIRED_LEGAL_FILES, *REQUIRED_DOCUMENTATION_FILES):
        copy_release_file(required, stage_root)

    python_components = set(collect_components("lingshu-gate")) - {"lingshu-gate"}
    npm_components, _npm_roots = collect_npm_components()
    stage_third_party_licenses(
        stage_root / "licenses" / "third-party",
        frozen_distributions=python_components,
        npm_components=npm_components,
    )

    (stage_root / "workspace").mkdir()
    (stage_root / "workspace" / ".keep").write_text("", encoding="utf-8")
    (stage_root / "secrets").mkdir()
    (stage_root / "secrets" / ".keep").write_text("", encoding="utf-8")
    sbom = build_spdx_document("lingshu-gate", target="application-bundle")
    write_json(stage_root / "SBOM.spdx.json", sbom)
    metadata = build_metadata(
        root=stage_root,
        target="docker-compose",
        version=version,
        epoch=source_date_epoch(),
        tools={},
    )
    write_json(stage_root / "BUILD-INFO.json", metadata)

    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"{stage_root.name}.tar.gz"
    sbom_asset = output_dir / f"lingshu-gate-v{version}-application-sbom.spdx.json"
    write_json(sbom_asset, sbom)
    create_tar_gz(stage_root, archive, epoch=source_date_epoch())
    write_checksums(output_dir, [archive, sbom_asset])
    return archive


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=REPOSITORY_ROOT / "dist" / "release")
    args = parser.parse_args()
    archive = build(args.output_dir.resolve())
    print(archive)


if __name__ == "__main__":
    main()

"""Validate and compare complete release OCI indexes."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
PLATFORM_VARIANT_PATTERN = re.compile(r"^v[0-9]+(?:\.[0-9]+)?$")
REQUIRED_PLATFORMS = {("linux", "amd64"), ("linux", "arm64")}
ATTESTATION_PLATFORM = ("unknown", "unknown")
REFERENCE_TYPE_ANNOTATION = "vnd.docker.reference.type"
REFERENCE_DIGEST_ANNOTATION = "vnd.docker.reference.digest"
ATTESTATION_MANIFEST_TYPE = "attestation-manifest"
OCI_INDEX_MEDIA_TYPE = "application/vnd.oci.image.index.v1+json"
OCI_MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"
INDEX_KEYS = frozenset({"schemaVersion", "mediaType", "manifests", "annotations"})
DESCRIPTOR_KEYS = frozenset({"mediaType", "digest", "size", "annotations", "platform"})
PLATFORM_KEYS = frozenset({"architecture", "os", "os.version", "os.features", "variant"})


@dataclass(frozen=True)
class ManifestDescriptor:
    digest: str
    media_type: str
    size: int
    platform: tuple[tuple[str, object], ...]
    annotations: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ValidatedIndex:
    annotations: tuple[tuple[str, str], ...]
    platforms: tuple[tuple[tuple[str, str], ManifestDescriptor], ...]
    attestations: tuple[tuple[str, ManifestDescriptor], ...]


def _validated_string_map(value: object, description: str) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{description} must be an object")
    entries: list[tuple[str, str]] = []
    for key, item in value.items():
        if not isinstance(key, str) or not key or not isinstance(item, str):
            raise RuntimeError(f"{description} must contain only non-empty string keys and string values")
        entries.append((key, item))
    return tuple(sorted(entries))


def _descriptor_digest(manifest: dict[str, object], description: str) -> str:
    digest = manifest.get("digest")
    if not isinstance(digest, str) or DIGEST_PATTERN.fullmatch(digest) is None:
        raise RuntimeError(f"{description} has an invalid digest")
    return digest


def _validated_platform(value: object, description: str) -> tuple[tuple[str, object], ...]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{description} has an invalid platform")
    unexpected_keys = set(value) - PLATFORM_KEYS
    if unexpected_keys:
        raise RuntimeError(f"{description} has unexpected platform fields: {sorted(unexpected_keys)}")
    operating_system = value.get("os")
    architecture = value.get("architecture")
    if not isinstance(operating_system, str) or not isinstance(architecture, str):
        raise RuntimeError(f"{description} has invalid operating system or architecture fields")
    if (operating_system, architecture) == ATTESTATION_PLATFORM:
        if set(value) != {"os", "architecture"}:
            raise RuntimeError(f"{description} has unexpected attestation platform metadata")
    else:
        variant = value.get("variant")
        if variant is not None and (
            not isinstance(variant, str) or PLATFORM_VARIANT_PATTERN.fullmatch(variant) is None
        ):
            raise RuntimeError(f"{description} has an invalid platform variant")
        os_version = value.get("os.version")
        if os_version is not None and (not isinstance(os_version, str) or not os_version):
            raise RuntimeError(f"{description} has an invalid platform OS version")
        os_features = value.get("os.features")
        if os_features is not None:
            if (
                not isinstance(os_features, list)
                or not os_features
                or any(not isinstance(feature, str) or not feature for feature in os_features)
                or len(set(os_features)) != len(os_features)
            ):
                raise RuntimeError(f"{description} has invalid platform OS features")
    normalized: list[tuple[str, object]] = []
    for key, item in value.items():
        if isinstance(item, list):
            normalized.append((key, tuple(item)))
        else:
            normalized.append((key, item))
    return tuple(sorted(normalized))


def _validated_descriptor(value: object, description: str) -> ManifestDescriptor:
    if not isinstance(value, dict):
        raise RuntimeError("OCI index contains an invalid manifest descriptor")
    unexpected_keys = set(value) - DESCRIPTOR_KEYS
    if unexpected_keys:
        raise RuntimeError(f"{description} has unexpected descriptor fields: {sorted(unexpected_keys)}")
    if value.get("mediaType") != OCI_MANIFEST_MEDIA_TYPE:
        raise RuntimeError(f"{description} has an invalid media type")
    size = value.get("size")
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise RuntimeError(f"{description} has an invalid descriptor size")
    annotations_value = value.get("annotations", {})
    return ManifestDescriptor(
        digest=_descriptor_digest(value, description),
        media_type=OCI_MANIFEST_MEDIA_TYPE,
        size=size,
        platform=_validated_platform(value.get("platform"), description),
        annotations=_validated_string_map(annotations_value, f"{description} annotations"),
    )


def _validated_index(payload: object) -> ValidatedIndex:
    if not isinstance(payload, dict):
        raise RuntimeError("OCI index has an unexpected shape")
    unexpected_keys = set(payload) - INDEX_KEYS
    if unexpected_keys:
        raise RuntimeError(f"OCI index has unexpected fields: {sorted(unexpected_keys)}")
    if payload.get("schemaVersion") != 2:
        raise RuntimeError("OCI index must use schemaVersion 2")
    if payload.get("mediaType") != OCI_INDEX_MEDIA_TYPE:
        raise RuntimeError("OCI index has an invalid media type")
    manifests = payload.get("manifests")
    if not isinstance(manifests, list):
        raise RuntimeError("OCI index has an unexpected shape")

    platforms: dict[tuple[str, str], ManifestDescriptor] = {}
    attestations: dict[str, ManifestDescriptor] = {}
    for manifest in manifests:
        if not isinstance(manifest, dict) or not isinstance(manifest.get("platform"), dict):
            raise RuntimeError("OCI index contains an invalid manifest descriptor")
        platform = manifest["platform"]
        key = (platform.get("os"), platform.get("architecture"))
        if key == ATTESTATION_PLATFORM:
            descriptor = _validated_descriptor(manifest, "OCI attestation manifest")
            annotations = dict(descriptor.annotations)
            if annotations.get(REFERENCE_TYPE_ANNOTATION) != ATTESTATION_MANIFEST_TYPE:
                raise RuntimeError("OCI unknown/unknown descriptor is not a BuildKit attestation manifest")
            reference_digest = annotations.get(REFERENCE_DIGEST_ANNOTATION)
            if reference_digest is None or DIGEST_PATTERN.fullmatch(reference_digest) is None:
                raise RuntimeError("OCI attestation manifest has an invalid payload reference")
            if reference_digest in attestations:
                raise RuntimeError("OCI index contains duplicate attestations for a platform payload")
            attestations[reference_digest] = descriptor
            continue
        if key not in REQUIRED_PLATFORMS:
            raise RuntimeError(f"OCI index contains an unexpected platform payload: {key}")
        typed_key = (str(key[0]), str(key[1]))
        descriptor = _validated_descriptor(manifest, f"OCI platform manifest {typed_key}")
        if typed_key in platforms:
            raise RuntimeError(f"OCI index contains a duplicate platform payload: {typed_key}")
        platforms[typed_key] = descriptor

    if set(platforms) != REQUIRED_PLATFORMS:
        raise RuntimeError(f"OCI index does not contain the required platform payloads: {sorted(platforms)}")
    payload_digests = {descriptor.digest for descriptor in platforms.values()}
    if set(attestations) != payload_digests:
        raise RuntimeError(
            "OCI index must contain exactly one BuildKit attestation manifest for each platform payload"
        )
    attestation_digests = [descriptor.digest for descriptor in attestations.values()]
    if len(set(attestation_digests)) != len(attestation_digests):
        raise RuntimeError("OCI index contains a duplicate attestation manifest")
    if len(manifests) != len(platforms) + len(attestations):
        raise RuntimeError("OCI index contains an unexpected descriptor count")

    return ValidatedIndex(
        annotations=_validated_string_map(payload.get("annotations", {}), "OCI index annotations"),
        platforms=tuple(sorted(platforms.items())),
        attestations=tuple(sorted(attestations.items())),
    )


def platform_payloads(payload: object) -> dict[tuple[str, str], str]:
    """Return payload digests after validating the complete index."""

    validated = _validated_index(payload)
    return {platform: descriptor.digest for platform, descriptor in validated.platforms}


def assert_equivalent_indexes(candidate: object, existing: object) -> None:
    candidate_index = _validated_index(candidate)
    existing_index = _validated_index(existing)
    candidate_payloads = {
        platform: descriptor.digest for platform, descriptor in candidate_index.platforms
    }
    existing_payloads = {
        platform: descriptor.digest for platform, descriptor in existing_index.platforms
    }
    if candidate_payloads != existing_payloads:
        raise RuntimeError(
            "OCI version tag payload differs from the verified candidate: "
            f"existing={existing_payloads}, candidate={candidate_payloads}"
        )
    if candidate_index != existing_index:
        raise RuntimeError("OCI version tag descriptor set differs from the verified candidate")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--existing", type=Path)
    args = parser.parse_args()
    if args.index is not None:
        if args.candidate is not None or args.existing is not None:
            parser.error("--index cannot be combined with --candidate or --existing")
        payload = json.loads(args.index.read_text(encoding="utf-8"))
        platform_payloads(payload)
        print("OCI index is valid")
        return
    if args.candidate is None or args.existing is None:
        parser.error("provide --index, or provide both --candidate and --existing")
    candidate = json.loads(args.candidate.read_text(encoding="utf-8"))
    existing = json.loads(args.existing.read_text(encoding="utf-8"))
    assert_equivalent_indexes(candidate, existing)
    print("OCI descriptor sets match")


if __name__ == "__main__":
    main()

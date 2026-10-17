"""Keep reviewed signed image provenance without broad identity exclusions."""

from __future__ import annotations

import hashlib
from pathlib import Path
import zlib

import pytest

from test_repository_identity import identity, _value


PATH = "docs/images/console/synthetic-provenance.png"


def _chunk(kind: bytes, payload: bytes) -> bytes:
    body = kind + payload
    return len(payload).to_bytes(4, "big") + body + zlib.crc32(body).to_bytes(4, "big")


def _fixture(monkeypatch, *, extra_metadata: bytes = b"") -> tuple[bytes, bytes, bytes]:
    vendor = _value((111, 112, 101, 110, 97, 105)).encode()
    provenance = _chunk(b"caBX", b"signed-source " + vendor + b" " + extra_metadata + b" ")
    header = _chunk(b"IHDR", b"\0\0\0\1\0\0\0\1\x08\x06\0\0\0")
    pixels = _chunk(b"IDAT", zlib.compress(b"\0\0\0\0\xff"))
    image = b"\x89PNG\r\n\x1a\n" + header + provenance + pixels + _chunk(b"IEND", b"")
    monkeypatch.setattr(identity, "_REVIEWED_PNG_PROVENANCE", {
        PATH: (hashlib.sha256(image).hexdigest(), hashlib.sha256(provenance).hexdigest()),
    })
    return image, provenance, vendor


@pytest.mark.parametrize("location", [PATH, "git:123456789abc:" + PATH, "bundle.zip!lingshu-gate-0.4.10/" + PATH])
def test_exact_reviewed_provenance_is_separate_from_product_identity(monkeypatch, location: str) -> None:
    image, provenance, _ = _fixture(monkeypatch)
    original = bytes(image)
    assert identity._scan_bytes(image, location, strict_text=False) == []
    retained, proof = identity._reviewed_png_provenance(image, location)
    assert proof == provenance
    assert retained == image.replace(provenance, b"", 1)
    assert image == original


def test_changed_or_copied_images_do_not_inherit_provenance_approval(monkeypatch) -> None:
    image, provenance, vendor = _fixture(monkeypatch)
    modified = image.replace(provenance, _chunk(b"caBX", b"changed " + vendor))
    for data, location in [(modified, PATH), (image, "docs/images/other.png"), (image, "README.png")]:
        findings = identity._scan_bytes(data, location, strict_text=False)
        assert any(item.rule_id == "TXT-040" for item in findings)


def test_product_metadata_is_not_covered_even_when_the_provenance_is_approved(monkeypatch) -> None:
    image, provenance, vendor = _fixture(monkeypatch)
    modified = image[:-12] + _chunk(b"tEXt", b"Product\0" + vendor) + image[-12:]
    # Approve the exact image to exercise the chunk boundary independently of
    # the full-image digest: the product metadata must still fail.
    monkeypatch.setattr(identity, "_REVIEWED_PNG_PROVENANCE", {
        PATH: (hashlib.sha256(modified).hexdigest(), hashlib.sha256(provenance).hexdigest()),
    })
    assert any(item.rule_id == "TXT-040" for item in identity._scan_bytes(modified, PATH, strict_text=False))


def test_provenance_does_not_exempt_other_identity_rules(monkeypatch) -> None:
    other = _value((99, 111, 100, 101, 120)).encode()
    image, _, _ = _fixture(monkeypatch, extra_metadata=other)
    assert any(item.rule_id == "TXT-045" for item in identity._scan_bytes(image, PATH, strict_text=False))


@pytest.mark.parametrize("dimension", ["image", "chunk"])
def test_each_provenance_digest_is_required(monkeypatch, dimension: str) -> None:
    image, _, _ = _fixture(monkeypatch)
    image_digest, chunk_digest = identity._REVIEWED_PNG_PROVENANCE[PATH]
    monkeypatch.setattr(identity, "_REVIEWED_PNG_PROVENANCE", {
        PATH: ("0" * 64 if dimension == "image" else image_digest,
               "0" * 64 if dimension == "chunk" else chunk_digest),
    })
    assert any(item.rule_id == "TXT-040" for item in identity._scan_bytes(image, PATH, strict_text=False))


def test_invalid_png_crc_is_not_treated_as_reviewed_provenance(monkeypatch) -> None:
    image, provenance, _ = _fixture(monkeypatch)
    invalid_proof = provenance[:-1] + bytes([provenance[-1] ^ 1])
    invalid = image.replace(provenance, invalid_proof)
    monkeypatch.setattr(identity, "_REVIEWED_PNG_PROVENANCE", {
        PATH: (hashlib.sha256(invalid).hexdigest(), hashlib.sha256(invalid_proof).hexdigest()),
    })
    assert identity._reviewed_png_provenance(invalid, PATH) is None
    assert any(item.rule_id == "TXT-040" for item in identity._scan_bytes(invalid, PATH, strict_text=False))


def test_reviewed_repository_artwork_remains_byte_identical_and_signed() -> None:
    root = Path(__file__).resolve().parents[1]
    assert len(identity._REVIEWED_PNG_PROVENANCE) == 4
    for path, (digest, _) in identity._REVIEWED_PNG_PROVENANCE.items():
        image = (root / path).read_bytes()
        assert hashlib.sha256(image).hexdigest() == digest
        assert identity._reviewed_png_provenance(image, path) is not None
        assert identity._scan_bytes(image, path, strict_text=False) == []


def test_new_history_exceptions_are_limited_to_the_reviewed_immutable_releases() -> None:
    reviewed = {
        "ebad81939459469b9ba473c14a1f68132b5f3eee",
        "bc8a920fa1987dfedb8e47ff4c984bd2cd55cd48",
    }
    snapshots = [item for item in identity._HISTORY_SNAPSHOT_EXCEPTIONS if item.commits & reviewed]
    assert len(snapshots) == 7
    for item in snapshots:
        assert item.commits == reviewed
        assert len(item.blob) == 40 and len(item.sha256) == 64
        assert item.findings
        assert all(rule in {"TXT-015", "TXT-045"} for rule, _ in item.findings)

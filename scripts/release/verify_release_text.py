"""Verify release text against the notes prepared from the checked-out source."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def verify_release_text(payload: object, *, tag: str, notes: str) -> None:
    if not isinstance(payload, dict):
        raise RuntimeError("Release text response has an unexpected shape")
    if payload.get("name") != f"Lingshu Gate {tag}":
        raise RuntimeError("Release title differs from the verified source title")
    body = payload.get("body")
    if not isinstance(body, str) or body.rstrip("\r\n") != notes.rstrip("\r\n"):
        raise RuntimeError("Release body differs from the verified source notes")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-json", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--notes", type=Path, required=True)
    args = parser.parse_args()
    verify_release_text(
        json.loads(args.release_json.read_text(encoding="utf-8")),
        tag=args.tag,
        notes=args.notes.read_text(encoding="utf-8"),
    )


if __name__ == "__main__":
    main()

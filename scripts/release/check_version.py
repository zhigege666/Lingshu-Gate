"""Validate source version and an optional release tag."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from scripts.release.common import is_prerelease, read_version


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", default="")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()

    version = read_version()
    if args.tag and args.tag != f"v{version}":
        raise SystemExit(f"Release tag {args.tag!r} does not match source version v{version}")
    print(version)
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(f"version={version}\n")
            output.write(f"prerelease={str(is_prerelease(version)).lower()}\n")
    elif os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as output:
            output.write(f"version={version}\n")
            output.write(f"prerelease={str(is_prerelease(version)).lower()}\n")


if __name__ == "__main__":
    main()

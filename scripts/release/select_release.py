"""Select a release from an exact main revision and its push baseline."""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

from scripts.release.common import REPOSITORY_ROOT, parse_version

VERSION_PATH = "src/lingshu_gate/_version.py"
REVISION_PATTERN = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments], cwd=repository, capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        raise RuntimeError("Cannot verify release history; fetch the complete push baseline")
    return result.stdout


def select_release(
    repository: Path,
    *,
    event_name: str,
    ref: str,
    sha: str,
    before: str = "",
    requested_tag: str = "",
) -> dict[str, str]:
    """Fail closed for unsupported events or unprovable version changes."""

    if ref != "refs/heads/main" or event_name not in {"push", "workflow_dispatch"}:
        raise RuntimeError("Release publication requires a main push or manual main dispatch")
    if REVISION_PATTERN.fullmatch(sha) is None or set(sha) == {"0"}:
        raise RuntimeError("Release source must be a full commit SHA")
    if _git(repository, "rev-parse", "HEAD").strip() != sha:
        raise RuntimeError("Checked-out source does not match the requested release revision")

    version = parse_version(_git(repository, "show", f"{sha}:{VERSION_PATH}"))
    tag = f"v{version}"
    if event_name == "workflow_dispatch":
        if requested_tag != tag:
            raise RuntimeError(f"Release tag must match source version {tag}")
        return {"publish": "true", "tag": tag, "reason": "Manual release requested"}

    if REVISION_PATTERN.fullmatch(before) is None or set(before) == {"0"}:
        raise RuntimeError("Automatic publication requires an existing push baseline")
    _git(repository, "merge-base", "--is-ancestor", before, sha)
    previous = parse_version(_git(repository, "show", f"{before}:{VERSION_PATH}"))
    changed = version != previous
    return {
        "publish": str(changed).lower(),
        "tag": tag,
        "reason": f"Version changed from {previous} to {version}" if changed else "Version unchanged",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--before", default="")
    parser.add_argument("--tag", default="")
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--github-summary", type=Path)
    args = parser.parse_args()
    try:
        decision = select_release(
            REPOSITORY_ROOT,
            event_name=args.event,
            ref=args.ref,
            sha=args.sha,
            before=args.before,
            requested_tag=args.tag,
        )
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"{decision['reason']}: {decision['tag']} (publish={decision['publish']})")
    if args.github_output is not None:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(f"publish={decision['publish']}\ntag={decision['tag']}\n")
    if args.github_summary is not None:
        with args.github_summary.open("a", encoding="utf-8") as summary:
            summary.write(f"## Release selection\n\n{decision['reason']}.\n\n")
            summary.write(f"- Tag: `{decision['tag']}`\n- Revision: `{args.sha}`\n")
            summary.write(f"- Start publication: `{decision['publish']}`\n")


if __name__ == "__main__":
    main()

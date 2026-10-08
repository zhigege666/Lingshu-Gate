"""Bind an existing-tag recovery to its product source and reviewed workflow."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Mapping

REPOSITORY = "zhigege666/Lingshu-Gate"
RECOVERY_TAG = "v0.4.5"
RECOVERY_SHA = "c0ea7d04cd16ac01536d0c0f00edab0c5ffc349e"
RECOVERY_TREE = "716da35e388aab6784d8b41d6ae4e79a4c17f948"
PREDICATE_TYPE = f"https://github.com/{REPOSITORY}/attestations/release-source/v1"
REQUIRED_JOBS = {"version", "quality", "native", "docker-compose", "docker-offline", "docker-publish"}
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")


def _git(*arguments: str) -> str:
    result = subprocess.run(["git", *arguments], capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError("Cannot verify release Git identity")
    return result.stdout.strip()


def _tag_sha(tag: str) -> str:
    result = subprocess.run(
        ["gh", "api", f"repos/{REPOSITORY}/git/ref/tags/{tag}"],
        capture_output=True, text=True, check=False, timeout=30,
    )
    if result.returncode:
        raise ValueError("Cannot verify existing release tag")
    value = json.loads(result.stdout)
    if value.get("object", {}).get("type") != "commit":
        raise ValueError("Release tag must directly identify its existing commit")
    return value["object"]["sha"]


def identity(environment: Mapping[str, str], *, verify_remote: bool = True) -> dict[str, str]:
    """Reject an unlisted recovery or a product/tooling identity mismatch."""
    event, ref = environment.get("GITHUB_EVENT_NAME"), environment.get("GITHUB_REF", "")
    requested = environment.get("LINGSHU_GATE_RELEASE_EXISTING_TAG", "")
    if environment.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise ValueError("Unexpected release repository")
    if event not in {"push", "pull_request", "workflow_dispatch"}:
        raise ValueError("Unexpected release event")
    workflow_sha = environment.get("GITHUB_WORKFLOW_SHA", "")
    workflow_ref = environment.get("GITHUB_WORKFLOW_REF", "")
    if not SHA_PATTERN.fullmatch(workflow_sha) or workflow_ref != f"{REPOSITORY}/.github/workflows/release.yml@{ref}":
        raise ValueError("Unexpected reviewed workflow identity")
    if _git("rev-parse", f"{workflow_sha}^{{commit}}") != workflow_sha:
        raise ValueError("Reviewed workflow revision is unavailable")
    if requested:
        if event != "workflow_dispatch" or ref != "refs/heads/main" or requested != RECOVERY_TAG:
            raise ValueError("Existing-tag recovery requires main and the exact allowed tag")
        source_sha, source_tree, tag = RECOVERY_SHA, RECOVERY_TREE, RECOVERY_TAG
    else:
        if event == "workflow_dispatch" and not ref.startswith("refs/tags/v"):
            raise ValueError("Branch dispatch requires an explicitly allowed existing tag")
        if event == "push" and not ref.startswith("refs/tags/v"):
            raise ValueError("Formal release push requires a version tag")
        source_sha = environment.get("GITHUB_SHA", "")
        source_tree = _git("rev-parse", "HEAD^{tree}")
        tag = ref.removeprefix("refs/tags/") if ref.startswith("refs/tags/v") else ""
    if not SHA_PATTERN.fullmatch(source_sha) or not SHA_PATTERN.fullmatch(source_tree):
        raise ValueError("Invalid product source identity")
    if _git("rev-parse", "HEAD") != source_sha or _git("rev-parse", "HEAD^{tree}") != source_tree:
        raise ValueError("Product checkout does not match the verified commit and tree")
    if tag and verify_remote and _tag_sha(tag) != source_sha:
        raise ValueError("Existing release tag no longer matches the product source")
    return {"source_sha": source_sha, "source_tree": source_tree, "tag": tag,
            "workflow_sha": workflow_sha, "workflow_ref": workflow_ref}


def source_predicate(environment: Mapping[str, str], jobs: Mapping[str, dict]) -> dict:
    value = identity(environment)
    if not value["tag"] or set(jobs) != REQUIRED_JOBS or any(job.get("result") != "success" for job in jobs.values()):
        raise ValueError("Every formal release job must succeed before publication")
    run_id, attempt = environment.get("GITHUB_RUN_ID", ""), environment.get("GITHUB_RUN_ATTEMPT", "")
    if not run_id.isdecimal() or int(run_id) < 1 or not attempt.isdecimal() or int(attempt) < 1:
        raise ValueError("Invalid release run identity")
    return {"repository": REPOSITORY, **value, "run_id": run_id, "run_attempt": attempt,
            "verified_jobs": sorted(REQUIRED_JOBS)}


def _producer_run(run_id: str, attempt: str) -> dict:
    result = subprocess.run(
        ["gh", "api", f"repos/{REPOSITORY}/actions/runs/{run_id}/attempts/{attempt}"],
        capture_output=True, text=True, check=False, timeout=30,
    )
    if result.returncode:
        raise ValueError("Cannot verify original publication producer")
    return json.loads(result.stdout)


def verify_source_attestations(results: object, expected: dict, *, existing_release: bool = False) -> dict:
    if not isinstance(results, list) or not results:
        raise ValueError("No verified product source attestation")
    matched = None
    for result in results:
        if not isinstance(result, dict):
            raise ValueError("Invalid verified product source attestation")
        verification = result.get("verificationResult", {})
        statement = verification.get("statement", {})
        timestamps = verification.get("verifiedTimestamps")
        if not isinstance(timestamps, list) or not timestamps or statement.get("predicateType") != PREDICATE_TYPE:
            raise ValueError("Product source attestation does not match this verified release run")
        predicate = statement.get("predicate")
        if predicate == expected:
            matched = predicate
        elif existing_release and isinstance(predicate, dict):
            # Keep the exact signed source/tooling contract. Only the genuine
            # original producer's run/attempt may differ during immutable reentry.
            original = {**expected, "run_id": predicate.get("run_id"), "run_attempt": predicate.get("run_attempt")}
            if predicate == original:
                matched = predicate
    if matched is None:
        raise ValueError("Product source attestation does not match this verified release run")
    if existing_release:
        run_id, attempt = matched["run_id"], matched["run_attempt"]
        if not isinstance(run_id, str) or not re.fullmatch(r"[1-9][0-9]{0,19}", run_id) or not isinstance(attempt, str) or not re.fullmatch(r"[1-9][0-9]{0,9}", attempt):
            raise ValueError("Invalid original publication producer")
        run = _producer_run(run_id, attempt)
        ref = expected["workflow_ref"].split("@", 1)[1]
        branch = ref.removeprefix("refs/heads/").removeprefix("refs/tags/")
        if (run.get("id") != int(run_id) or run.get("run_attempt") != int(attempt)
                or run.get("head_sha") != expected["workflow_sha"] or run.get("head_branch") != branch
                or run.get("repository", {}).get("full_name") != REPOSITORY
                or run.get("path") != ".github/workflows/release.yml"
                or run.get("event") not in ({"workflow_dispatch"} if ref == "refs/heads/main" else {"push", "workflow_dispatch"})
                or run.get("status") != "completed" or run.get("conclusion") not in {"success", "failure", "cancelled"}):
            raise ValueError("Original publication producer does not match the signed workflow identity")
    return matched


def verify_release_text(metadata: dict, tag: str, notes: str) -> None:
    if metadata.get("name") != f"Lingshu Gate {tag}" or not isinstance(metadata.get("body"), str):
        raise ValueError("Immutable release title or body is invalid")
    if metadata["body"].rstrip("\r\n") != notes.rstrip("\r\n"):
        raise ValueError("Immutable release body differs from the verified source notes")


def run_product_command(command: list[str], environment: Mapping[str, str]) -> int:
    identity(environment, verify_remote=False)
    if not command:
        raise ValueError("Missing product build command")
    # The unchanged product's release helpers otherwise label packages with the
    # workflow event SHA. Let them read the actual product checkout instead.
    child_environment = dict(environment)
    child_environment.pop("GITHUB_SHA", None)
    return subprocess.run(command, env=child_environment, check=False).returncode


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="operation", required=True)
    subparsers.add_parser("verify")
    run = subparsers.add_parser("run")
    run.add_argument("command", nargs=argparse.REMAINDER)
    predicate = subparsers.add_parser("predicate")
    predicate.add_argument("--output", type=Path, required=True)
    check = subparsers.add_parser("verify-attestation")
    check.add_argument("--results", type=Path, required=True)
    check.add_argument("--existing-release", action="store_true")
    text = subparsers.add_parser("verify-text")
    text.add_argument("--release-json", type=Path, required=True)
    text.add_argument("--notes", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        if arguments.operation == "run":
            command = arguments.command
            raise SystemExit(run_product_command(command[1:] if command[:1] == ["--"] else command, os.environ))
        if arguments.operation == "verify-text":
            value = identity(os.environ)
            verify_release_text(json.loads(arguments.release_json.read_text(encoding="utf-8")), value["tag"],
                                arguments.notes.read_text(encoding="utf-8"))
        elif arguments.operation in {"predicate", "verify-attestation"}:
            value = source_predicate(os.environ, json.loads(os.environ["LINGSHU_GATE_RELEASE_JOB_RESULTS"]))
            if arguments.operation == "predicate":
                arguments.output.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
            else:
                producer = verify_source_attestations(json.loads(arguments.results.read_text(encoding="utf-8")), value,
                                                      existing_release=arguments.existing_release)
                print(json.dumps(producer, sort_keys=True))
        else:
            value = identity(os.environ)
            for variable, entries in (
                ("GITHUB_OUTPUT", value),
                ("GITHUB_ENV", {f"LINGSHU_GATE_RELEASE_{key.upper()}": item for key, item in value.items()}),
            ):
                with Path(os.environ[variable]).open("a", encoding="utf-8") as output:
                    for key, item in entries.items():
                        output.write(f"{key}={item}\n")
            print(json.dumps(value, sort_keys=True))
    except (ValueError, KeyError, subprocess.TimeoutExpired) as exc:
        raise SystemExit(f"Release identity verification failed: {exc}") from None


if __name__ == "__main__":
    main()

"""Synthetic publication boundaries; these tests never contact a registry or GitHub."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from scripts.release.collect_artifacts import expected_asset_names
from scripts.release.common import read_version, write_checksums
from scripts.release.verify_release_text import verify_release_text

ROOT = Path(__file__).resolve().parents[1]
VERSION = read_version()
TAG = f"v{VERSION}"
SHA = "a" * 40
NOTES = "# Lingshu Gate\n\nEnglish notes.\n\n中文说明。\n"


def _steps() -> list[dict]:
    workflow = yaml.load((ROOT / ".github/workflows/release.yml").read_text(), Loader=yaml.BaseLoader)
    return workflow["jobs"]["publish"]["steps"]


@pytest.mark.parametrize("ending", ["", "\n", "\r\n", "\n\n"])
def test_release_text_accepts_only_terminal_line_ending_normalization(ending: str) -> None:
    verify_release_text({"name": f"Lingshu Gate {TAG}", "body": NOTES.rstrip("\n") + ending}, tag=TAG, notes=NOTES)


@pytest.mark.parametrize("payload", [
    None, [], {},
    {"name": None, "body": NOTES},
    {"name": f"Lingshu Gate {TAG} ", "body": NOTES},
    {"name": "Lingshu Gate v9.0.0", "body": NOTES},
    {"name": f"Lingshu Gate {TAG}", "body": None},
    {"name": f"Lingshu Gate {TAG}", "body": NOTES.replace("中文说明", "其他说明")},
    {"name": f"Lingshu Gate {TAG}", "body": NOTES.rstrip("\n") + " "},
    {"name": f"Lingshu Gate {TAG}", "body": NOTES.replace("\n\n", "\n")},
])
def test_release_text_rejects_missing_malformed_or_changed_source_text(payload: object) -> None:
    with pytest.raises(RuntimeError):
        verify_release_text(payload, tag=TAG, notes=NOTES)


def test_publication_proves_every_asset_before_registry_or_release_writes() -> None:
    steps = _steps()
    names = [step["name"] for step in steps]
    proof = names.index("Verify every release asset attestation")
    assert names.index("Validate any existing release without mutation") < proof
    assert names.index("Attest release assets") < proof
    for writer in ("Log in to GitHub Container Registry for promotion",
                   "Promote version tag without replacing an existing digest",
                   "Log in to Docker Hub", "Mirror verified version to Docker Hub",
                   "Sign promoted container digest", "Create release",
                   "Update Docker Hub latest after verified stable publication"):
        assert proof < names.index(writer)
    by_name = {step["name"]: step for step in steps}
    guarded = ("Set up pinned Docker Buildx for promotion",
               "Log in to GitHub Container Registry for promotion",
               "Verify release tag still targets source revision before promotion",
               "Promote version tag without replacing an existing digest", "Log in to Docker Hub",
               "Mirror verified version to Docker Hub", "Detect container signing configuration",
               "Attest release assets", "Create release",
               "Verify release tag still targets source revision before publication")
    for name in guarded:
        assert by_name[name]["if"] == "steps.existing-release.outputs.exists != 'true'"
    for name in ("Install Cosign", "Sign promoted container digest"):
        assert by_name[name]["if"] == "steps.signing.outputs.enabled == 'true'"
    assert by_name["Update Docker Hub latest after verified stable publication"]["if"] == (
        "needs.version.outputs.prerelease == 'false' && steps.existing-release.outputs.exists != 'true'"
    )


@pytest.fixture
def publication_fixture(tmp_path: Path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    release_dir = tmp_path / "dist/release"
    release_dir.mkdir(parents=True)
    for name in expected_asset_names(VERSION):
        (release_dir / name).write_bytes(name.encode())
    write_checksums(release_dir, sorted(release_dir.iterdir()))
    (tmp_path / "scripts").symlink_to(ROOT / "scripts", target_is_directory=True)
    (tmp_path / "packaging").mkdir()
    (tmp_path / "packaging/release-notes.md").write_text(NOTES)
    state = {
        "name": f"Lingshu Gate {TAG}", "body": NOTES,
        "tagName": TAG, "isDraft": False, "isImmutable": True, "isPrerelease": False,
        "assets": [{"name": path.name} for path in sorted(release_dir.iterdir())],
    }
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps(state))
    gh = bin_dir / "gh"
    gh.write_text(f"#!{sys.executable}\n" + '''import json, os, pathlib, shutil, sys
args = sys.argv[1:]
root = pathlib.Path(os.environ["FIXTURE_ROOT"])
with (root / "gh-calls.jsonl").open("a") as stream:
    stream.write(json.dumps(args) + "\\n")
if args[:2] == ["release", "view"]:
    print((root / "state.json").read_text())
elif args[:2] == ["release", "download"]:
    asset = args[args.index("--pattern") + 1]
    dest = pathlib.Path(args[args.index("--dir") + 1])
    shutil.copyfile(root / "dist/release" / asset, dest / asset)
    if os.environ.get("PROOF_FAILURE") == "asset_bytes":
        (dest / asset).write_bytes(b"changed asset")
elif args[:2] == ["attestation", "verify"]:
    if os.environ.get("PROOF_FAILURE") == "cli":
        sys.exit(1)
    if os.environ.get("PROOF_FAILURE") == "proof_empty":
        print("[]")
        sys.exit(0)
    timestamps = [] if os.environ.get("PROOF_FAILURE") == "timestamp" else [{"type": "synthetic"}]
    print(json.dumps([{"verificationResult": {"verifiedTimestamps": timestamps}}]))
else:
    sys.exit("Unexpected GitHub operation in read-only publication fixture")
''')
    gh.chmod(0o755)
    # Any Docker invocation in an existing-release publication is a test failure.
    docker = bin_dir / "docker"
    docker.write_text("#!/bin/sh\nexit 97\n")
    docker.chmod(0o755)
    env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
           "FIXTURE_ROOT": str(tmp_path), "RUNNER_TEMP": str(tmp_path), "RELEASE_TAG": TAG,
           "EXPECTED_PRERELEASE": "false", "GITHUB_OUTPUT": str(tmp_path / "output"),
           "GITHUB_REPOSITORY": "zhigege666/Lingshu-Gate", "GITHUB_REF": f"refs/tags/{TAG}",
           "GITHUB_SHA": SHA, "GITHUB_WORKFLOW_SHA": SHA, "GH_TOKEN": "synthetic-test-token"}
    return tmp_path, state, env


def _run(step: dict, root: Path, env: dict) -> subprocess.CompletedProcess:
    script = step["run"].replace("${{ needs.version.outputs.version }}", VERSION).replace("${{ github.ref_name }}", TAG)
    script = script.replace("/tmp/lingshu-gate-", str(root / "lingshu-gate-"))
    return subprocess.run(["bash", "-c", script], cwd=root, env=env, capture_output=True, text=True, check=False)


def test_prepared_notes_bind_source_text_mirror_and_exact_container_digest(publication_fixture) -> None:
    root, _, env = publication_fixture
    env.update({"DOCKERHUB_USERNAME": "exampleteam", "CONTAINER_IMAGE": "ghcr.io/exampleteam/lingshu-gate",
                "CONTAINER_DIGEST": "sha256:" + "b" * 64})
    step = next(step for step in _steps() if step["name"] == "Prepare exact release title and source notes")
    result = _run(step, root, env)
    assert result.returncode == 0, result.stderr
    prepared = (root / "lingshu-gate-release-notes.md").read_text()
    assert prepared == (NOTES + f"\nDocker Hub mirror: `docker.io/exampleteam/lingshu-gate:{VERSION}`\n"
                        + f"\nContainer image: `ghcr.io/exampleteam/lingshu-gate@{env['CONTAINER_DIGEST']}`\n")
    assert (root / "packaging/release-notes.md").read_text() == NOTES
    verify_release_text({"name": f"Lingshu Gate {TAG}", "body": prepared}, tag=TAG, notes=prepared)
    with pytest.raises(RuntimeError, match="body differs"):
        verify_release_text({"name": f"Lingshu Gate {TAG}", "body": prepared.replace("b" * 64, "c" * 64)}, tag=TAG, notes=prepared)


@pytest.mark.parametrize("failure", ["", "body", "title", "asset_bytes", "asset_missing", "asset_stale"])
def test_new_release_readback_rejects_changed_text_or_assets_before_latest(publication_fixture, failure: str) -> None:
    root, state, env = publication_fixture
    (root / "lingshu-gate-release-notes.md").write_text(NOTES)
    if failure in {"body", "title"}:
        state["body" if failure == "body" else "name"] += " altered"
    if failure == "asset_missing":
        state["assets"].pop()
    if failure == "asset_stale":
        state["assets"].append({"name": "unexpected.txt"})
    (root / "state.json").write_text(json.dumps(state))
    if failure == "asset_bytes":
        env["PROOF_FAILURE"] = failure
    step = next(step for step in _steps() if step["name"] == "Verify newly published immutable release")
    result = _run(step, root, env)
    assert (result.returncode == 0) is (failure == ""), result.stderr
    calls = [json.loads(line) for line in (root / "gh-calls.jsonl").read_text().splitlines()]
    assert all(call[:2] in (["release", "view"], ["release", "download"]) for call in calls)


@pytest.mark.parametrize("failure", ["", "body", "title", "asset_bytes", "asset_missing", "asset_stale", "cli", "timestamp", "proof_empty"])
def test_existing_release_validates_text_bytes_and_all_proofs_without_publication(publication_fixture, failure: str) -> None:
    root, state, env = publication_fixture
    # Source notes are already prepared here; run the actual workflow's validation
    # and attestation shell bodies with synthetic GitHub data and local assets.
    (root / "lingshu-gate-release-notes.md").write_text(NOTES)
    if failure in {"body", "title"}:
        state["body" if failure == "body" else "name"] += " altered"
        (root / "state.json").write_text(json.dumps(state))
    if failure in {"asset_missing", "asset_stale"}:
        if failure == "asset_missing":
            state["assets"].pop()
        else:
            state["assets"].append({"name": "unexpected.txt"})
        (root / "state.json").write_text(json.dumps(state))
    if failure in {"cli", "timestamp", "proof_empty", "asset_bytes"}:
        env["PROOF_FAILURE"] = failure
    by_name = {step["name"]: step for step in _steps()}
    validation = _run(by_name["Validate any existing release without mutation"], root, env)
    if failure in {"body", "title", "asset_bytes", "asset_missing", "asset_stale"}:
        assert validation.returncode != 0
        calls = [json.loads(line) for line in (root / "gh-calls.jsonl").read_text().splitlines()]
        assert all(call[:2] in (["release", "view"], ["release", "download"]) for call in calls)
        assert not any(call[:2] == ["attestation", "verify"] for call in calls)
        return
    assert validation.returncode == 0, validation.stderr
    assert "exists=true" in (root / "output").read_text()
    proof = _run(by_name["Verify every release asset attestation"], root, env)
    assert (proof.returncode == 0) is (failure == ""), proof.stderr
    calls = [json.loads(line) for line in (root / "gh-calls.jsonl").read_text().splitlines()]
    assert all(call[:2] in (["release", "view"], ["release", "download"], ["attestation", "verify"]) for call in calls)
    verified = [call for call in calls if call[:2] == ["attestation", "verify"]]
    assert len(verified) == (11 if failure == "" else 1)
    for call in verified:
        assert call[call.index("--repo") + 1] == env["GITHUB_REPOSITORY"]
        assert call[call.index("--cert-identity") + 1] == f"https://github.com/{env['GITHUB_REPOSITORY']}/.github/workflows/release.yml@{env['GITHUB_REF']}"
        assert call[call.index("--signer-digest") + 1] == SHA
        assert call[call.index("--source-digest") + 1] == SHA
        assert call[call.index("--source-ref") + 1] == env["GITHUB_REF"]
        assert "--deny-self-hosted-runners" in call

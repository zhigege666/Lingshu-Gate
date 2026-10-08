from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
import yaml

from scripts.release import release_identity as release


ROOT = Path(__file__).resolve().parents[1]
TOOLING_SHA = "1" * 40


@pytest.fixture
def recovery(monkeypatch):
    environment = {
        "GITHUB_REPOSITORY": release.REPOSITORY,
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_SHA": TOOLING_SHA,
        "GITHUB_WORKFLOW_SHA": TOOLING_SHA,
        "GITHUB_WORKFLOW_REF": f"{release.REPOSITORY}/.github/workflows/release.yml@refs/heads/main",
        "LINGSHU_GATE_RELEASE_EXISTING_TAG": release.RECOVERY_TAG,
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
    }
    git = {("rev-parse", "HEAD"): release.RECOVERY_SHA,
           ("rev-parse", "HEAD^{tree}"): release.RECOVERY_TREE,
           ("rev-parse", f"{TOOLING_SHA}^{{commit}}"): TOOLING_SHA}
    monkeypatch.setattr(release, "_git", lambda *arguments: git[arguments])
    monkeypatch.setattr(release, "_tag_sha", lambda tag: release.RECOVERY_SHA)
    return environment, git


def test_recovery_keeps_product_commit_and_tree_distinct_from_tooling(recovery):
    environment, _ = recovery
    result = release.identity(environment)
    assert result == {"source_sha": release.RECOVERY_SHA, "source_tree": release.RECOVERY_TREE,
                      "tag": release.RECOVERY_TAG, "workflow_sha": TOOLING_SHA,
                      "workflow_ref": environment["GITHUB_WORKFLOW_REF"]}


@pytest.mark.parametrize("event", ["push", "workflow_dispatch", "pull_request"])
def test_existing_tag_and_pull_request_routes_keep_their_event_source(recovery, event):
    environment, _ = recovery
    ref = "refs/pull/59/merge" if event == "pull_request" else "refs/tags/v0.4.5"
    environment = {**environment, "GITHUB_EVENT_NAME": event, "GITHUB_REF": ref,
                   "GITHUB_SHA": release.RECOVERY_SHA, "LINGSHU_GATE_RELEASE_EXISTING_TAG": "",
                   "GITHUB_WORKFLOW_REF": f"{release.REPOSITORY}/.github/workflows/release.yml@{ref}"}
    result = release.identity(environment)
    assert result["source_sha"] == release.RECOVERY_SHA
    assert result["tag"] == ("" if event == "pull_request" else "v0.4.5")


@pytest.mark.parametrize(("field", "value"), [
    ("LINGSHU_GATE_RELEASE_EXISTING_TAG", ""),
    ("LINGSHU_GATE_RELEASE_EXISTING_TAG", "v0.4.4"),
    ("LINGSHU_GATE_RELEASE_EXISTING_TAG", "v0.4.5\nsource_sha=forged"),
    ("GITHUB_REF", "refs/heads/feature"),
    ("GITHUB_EVENT_NAME", "pull_request"),
    ("GITHUB_EVENT_NAME", "push"),
    ("GITHUB_REPOSITORY", "example/other"),
    ("GITHUB_WORKFLOW_SHA", "not-a-commit"),
    ("GITHUB_WORKFLOW_REF", f"{release.REPOSITORY}/.github/workflows/other.yml@refs/heads/main"),
])
def test_recovery_rejects_unlisted_input_or_untrusted_workflow(recovery, field, value):
    environment, _ = recovery
    with pytest.raises(ValueError):
        release.identity({**environment, field: value})


@pytest.mark.parametrize(("argument", "value"), [("HEAD", TOOLING_SHA), ("HEAD^{tree}", "2" * 40)])
def test_recovery_rejects_wrong_product_checkout(recovery, argument, value):
    environment, git = recovery
    git[("rev-parse", argument)] = value
    with pytest.raises(ValueError, match="Product checkout"):
        release.identity(environment)


def test_recovery_rejects_a_moved_existing_tag(recovery, monkeypatch):
    environment, _ = recovery
    monkeypatch.setattr(release, "_tag_sha", lambda tag: TOOLING_SHA)
    with pytest.raises(ValueError, match="no longer matches"):
        release.identity(environment)


def test_packaging_child_uses_checkout_revision_without_changing_workflow_identity(recovery, monkeypatch):
    environment, _ = recovery
    observed = []
    monkeypatch.setattr(release.subprocess, "run", lambda command, **kwargs:
                        observed.append((command, kwargs)) or SimpleNamespace(returncode=7))
    assert release.run_product_command(["python", "-m", "scripts.release.build_native"], environment) == 7
    assert "GITHUB_SHA" not in observed[0][1]["env"]
    assert observed[0][1]["env"]["GITHUB_WORKFLOW_SHA"] == TOOLING_SHA
    assert environment["GITHUB_SHA"] == TOOLING_SHA


def test_wrong_source_prevents_any_packaging_command(recovery, monkeypatch):
    environment, git = recovery
    git[("rev-parse", "HEAD")] = TOOLING_SHA
    def forbidden(*args, **kwargs):
        pytest.fail("Unverified source must not start a product command")
    monkeypatch.setattr(release.subprocess, "run", forbidden)
    with pytest.raises(ValueError):
        release.run_product_command(["python", "-m", "scripts.release.build_native"], environment)


@pytest.mark.parametrize("result", ["failure", "cancelled", "skipped", ""])
@pytest.mark.parametrize("job", sorted(release.REQUIRED_JOBS))
def test_publication_rejects_every_unsuccessful_formal_job(recovery, job, result):
    environment, _ = recovery
    jobs = {name: {"result": "success"} for name in release.REQUIRED_JOBS}
    jobs[job]["result"] = result
    with pytest.raises(ValueError, match="Every formal release job"):
        release.source_predicate(environment, jobs)


def test_source_attestation_requires_current_run_and_preserves_timestamp_gate(recovery):
    environment, _ = recovery
    jobs = {name: {"result": "success"} for name in release.REQUIRED_JOBS}
    expected = release.source_predicate(environment, jobs)
    valid = {"verificationResult": {"verifiedTimestamps": [{"type": "tlog"}],
             "statement": {"predicateType": release.PREDICATE_TYPE, "predicate": expected}}}
    release.verify_source_attestations([valid], expected)
    stale = deepcopy(valid)
    stale["verificationResult"]["statement"]["predicate"]["run_attempt"] = "2"
    with pytest.raises(ValueError):
        release.verify_source_attestations([stale], expected)
    release.verify_source_attestations([stale, valid], expected)
    invalid = deepcopy(valid)
    invalid["verificationResult"]["verifiedTimestamps"] = []
    with pytest.raises(ValueError):
        release.verify_source_attestations([invalid, valid], expected)
    wrong_source = deepcopy(valid)
    wrong_source["verificationResult"]["statement"]["predicate"]["source_sha"] = TOOLING_SHA
    with pytest.raises(ValueError):
        release.verify_source_attestations([wrong_source], expected)


@pytest.mark.parametrize("current_run,current_attempt", [("123", "2"), ("456", "1")])
def test_immutable_reentry_cli_preserves_real_original_producer(tmp_path, current_run, current_attempt):
    result, calls = _reentry_cli(tmp_path, current_run=current_run, current_attempt=current_attempt)
    assert result.returncode == 0, result.stderr
    producer = json.loads(result.stdout)
    assert producer["run_id"] == "123" and producer["run_attempt"] == "1"
    assert producer["workflow_sha"] == TOOLING_SHA and producer["source_sha"] == release.RECOVERY_SHA
    assert f"repos/{release.REPOSITORY}/actions/runs/123/attempts/1" in calls


@pytest.mark.parametrize("fault", ["fresh-publication", "source", "tree", "tag", "workflow", "timestamp", "producer-id", "producer-attempt", "producer-workflow", "producer-path", "producer-repository", "quality"])
def test_immutable_reentry_cli_rejects_unverified_source_or_producer(tmp_path, fault):
    result, _ = _reentry_cli(tmp_path, current_run="456", current_attempt="2", fault=fault)
    assert result.returncode != 0
    assert "Release identity verification failed" in result.stderr


def _reentry_cli(tmp_path, *, current_run, current_attempt, fault=""):
    """Run the actual parser and verifier; only read-only Git/GitHub endpoints are fixtures."""
    predicate = {"repository": release.REPOSITORY, "source_sha": release.RECOVERY_SHA,
                 "source_tree": release.RECOVERY_TREE, "tag": release.RECOVERY_TAG,
                 "workflow_sha": TOOLING_SHA,
                 "workflow_ref": f"{release.REPOSITORY}/.github/workflows/release.yml@refs/heads/main",
                 "run_id": "123", "run_attempt": "1", "verified_jobs": sorted(release.REQUIRED_JOBS)}
    if fault in {"source", "tree", "workflow"}:
        predicate[{"source": "source_sha", "tree": "source_tree", "workflow": "workflow_sha"}[fault]] = "2" * 40
    if fault == "tag":
        predicate["tag"] = "v0.4.4"
    results = [{"verificationResult": {"verifiedTimestamps": [] if fault == "timestamp" else [{"type": "tlog"}],
                "statement": {"predicateType": release.PREDICATE_TYPE, "predicate": predicate}}}]
    results_file = tmp_path / "verified-results.json"
    results_file.write_text(json.dumps(results))
    producer = {"id": 123, "run_attempt": 1, "head_sha": TOOLING_SHA, "head_branch": "main",
                "path": ".github/workflows/release.yml", "repository": {"full_name": release.REPOSITORY},
                "event": "workflow_dispatch", "status": "completed", "conclusion": "failure"}
    if fault == "producer-id":
        producer["id"] = 999
    if fault == "producer-attempt":
        producer["run_attempt"] = 2
    if fault == "producer-workflow":
        producer["head_sha"] = "2" * 40
    if fault == "producer-path":
        producer["path"] = ".github/workflows/release-quality-diagnostic.yml"
    if fault == "producer-repository":
        producer["repository"] = {"full_name": "example/other"}
    fixture = tmp_path / "producer-api.json"
    fixture.write_text(json.dumps(producer))
    calls_file = tmp_path / "gh-calls.jsonl"
    binaries = tmp_path / "bin"
    binaries.mkdir()
    git = binaries / "git"
    git.write_text(f"#!{sys.executable}\nimport sys\nvalues={{'HEAD':'{release.RECOVERY_SHA}','HEAD^{{tree}}':'{release.RECOVERY_TREE}','{TOOLING_SHA}^{{commit}}':'{TOOLING_SHA}'}}\nassert sys.argv[1]=='rev-parse'\nprint(values[sys.argv[2]])\n")
    gh = binaries / "gh"
    gh.write_text(f"#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\np=sys.argv[2]\nwith Path(os.environ['FIXTURE_GH_CALLS']).open('a') as f: f.write(json.dumps(p)+'\\n')\nassert sys.argv[1]=='api'\nif p=='repos/{release.REPOSITORY}/git/ref/tags/v0.4.5': print(json.dumps({{'object':{{'type':'commit','sha':'{release.RECOVERY_SHA}'}}}}))\nelif p=='repos/{release.REPOSITORY}/actions/runs/123/attempts/1': print(Path(os.environ['FIXTURE_PRODUCER_API']).read_text())\nelse: raise SystemExit(3)\n")
    git.chmod(0o755)
    gh.chmod(0o755)
    jobs = {name: {"result": "success"} for name in release.REQUIRED_JOBS}
    if fault == "quality":
        jobs["quality"]["result"] = "failure"
    environment = {**os.environ, "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
                   "GITHUB_REPOSITORY": release.REPOSITORY, "GITHUB_EVENT_NAME": "workflow_dispatch",
                   "GITHUB_REF": "refs/heads/main", "GITHUB_SHA": TOOLING_SHA,
                   "GITHUB_WORKFLOW_SHA": TOOLING_SHA, "GITHUB_WORKFLOW_REF": predicate["workflow_ref"],
                   "GITHUB_RUN_ID": current_run, "GITHUB_RUN_ATTEMPT": current_attempt,
                   "LINGSHU_GATE_RELEASE_EXISTING_TAG": release.RECOVERY_TAG,
                   "LINGSHU_GATE_RELEASE_JOB_RESULTS": json.dumps(jobs),
                   "FIXTURE_GH_CALLS": str(calls_file), "FIXTURE_PRODUCER_API": str(fixture)}
    command = [sys.executable, str(ROOT / "scripts/release/release_identity.py"), "verify-attestation",
               "--results", str(results_file)]
    if fault != "fresh-publication":
        command.append("--existing-release")
    result = subprocess.run(command, env=environment, capture_output=True, text=True, timeout=10, check=False)
    calls = [json.loads(line) for line in calls_file.read_text().splitlines()] if calls_file.exists() else []
    return result, calls


def test_immutable_title_and_body_match_the_verified_source_notes():
    notes = "# Lingshu Gate v0.4.5\n\nRelease notes.\n"
    valid = {"name": "Lingshu Gate v0.4.5", "body": notes}
    release.verify_release_text(valid, release.RECOVERY_TAG, notes)
    for changed in [{**valid, "name": "Lingshu Gate v0.4.4"}, {**valid, "body": notes + "Added claim."}]:
        with pytest.raises(ValueError):
            release.verify_release_text(changed, release.RECOVERY_TAG, notes)


def test_recovery_workflow_keeps_source_pins_and_all_formal_gates():
    workflow = yaml.load((ROOT / ".github/workflows/release.yml").read_text(), Loader=yaml.BaseLoader)
    jobs = workflow["jobs"]
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["on"]["workflow_dispatch"]["inputs"]["existing_tag"]["default"] == ""
    for name in {"version", *release.REQUIRED_JOBS - {"version"}, "publish"}:
        steps = jobs[name]["steps"]
        checkout = steps[0]
        assert checkout["uses"].startswith("actions/checkout@")
        assert release.RECOVERY_SHA in checkout["with"]["ref"]
        assert "inputs.existing_tag == 'v0.4.5'" in checkout["with"]["ref"]
        assert "github.ref == 'refs/heads/main'" in checkout["with"]["ref"]
        assert checkout["with"]["fetch-depth"] == "0"
        assert checkout["with"]["persist-credentials"] == "false"
        assert steps[1]["id"] == "identity"
        assert '${GITHUB_WORKFLOW_SHA}:scripts/release/release_identity.py' in steps[1]["run"]
    assert set(jobs["publish"]["needs"]) == release.REQUIRED_JOBS
    publish = jobs["publish"]["steps"]
    names = [step["name"] for step in publish]
    assert names.index("Require immutable releases before publication") < names.index("Promote version tag without replacing an existing digest")
    immutable = next(step for step in publish if step["name"] == "Require immutable releases before publication")
    assert immutable["env"]["GH_TOKEN"] == "${{ secrets.RELEASE_SETTINGS_TOKEN }}"
    assert "'.enabled == true'" in immutable["run"]
    assert names.index("Verify every release asset attestation") < names.index("Promote version tag without replacing an existing digest")
    assert names.index("Verify every release asset attestation") < names.index("Create release")
    verification = next(step for step in publish if step["name"] == "Verify every release asset attestation")["run"]
    for flag in ["--cert-identity", "--signer-digest", "--source-ref", "--source-digest", "--deny-self-hosted-runners"]:
        assert verification.count(flag) == 2
    assert 'test "${#attested_assets[@]}" -eq 11' in verification
    assert "verify-attestation" in verification
    assert "producer_options=(--existing-release)" in verification
    steps = {step["name"]: step for step in publish}
    assert steps["Verify every release asset attestation"]["env"]["EXISTING_IMMUTABLE_RELEASE"] == "${{ steps.existing-release.outputs.immutable }}"
    for name in ["Set up pinned Docker Buildx for promotion", "Log in to GitHub Container Registry for promotion",
                 "Verify release tag still targets source revision before promotion", "Promote version tag without replacing an existing digest",
                 "Log in to Docker Hub", "Mirror verified version to Docker Hub", "Create release"]:
        assert steps[name]["if"] == "steps.existing-release.outputs.exists != 'true'"
    assert "steps.existing-release.outputs.exists != 'true'" in steps["Update Docker Hub latest after verified stable publication"]["if"]
    core = next(step for step in jobs["docker-publish"]["steps"] if step.get("id") == "build")
    assert "org.opencontainers.image.revision=${{ needs.version.outputs.source_sha }}" in core["with"]["labels"]
    for name in ["docker-publish", "docker-offline", "publish"]:
        assert "inputs.existing_tag == 'v0.4.5'" in jobs[name]["if"]

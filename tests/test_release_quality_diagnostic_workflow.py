"""Read-only workflow contracts; these tests never dispatch a workflow."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = "c0ea7d04cd16ac01536d0c0f00edab0c5ffc349e"
SOURCE_TREE = "716da35e388aab6784d8b41d6ae4e79a4c17f948"


def workflow():
    return yaml.load((ROOT / ".github/workflows/release-quality-diagnostic.yml").read_text(), Loader=yaml.BaseLoader)


def steps():
    return {step["name"]: step for step in workflow()["jobs"]["quality"]["steps"]}


def test_diagnostics_are_manual_read_only_and_have_no_publication_path():
    value = workflow()
    assert set(value["on"]) == {"workflow_dispatch"}
    assert not value["on"]["workflow_dispatch"]  # No unvalidated caller-supplied source/ref inputs.
    assert value["permissions"] == {"contents": "read"}
    assert set(value["jobs"]) == {"quality"}
    job = value["jobs"]["quality"]
    assert "permissions" not in job and "environment" not in job
    assert job["runs-on"] == "ubuntu-22.04" and job["timeout-minutes"] == "40"
    allowed = {"actions/checkout", "actions/setup-python", "actions/setup-node",
               "astral-sh/setup-uv", "actions/upload-artifact"}
    assert {step["uses"].split("@")[0] for step in job["steps"] if "uses" in step} <= allowed
    text = json.dumps(value)
    for forbidden in ("secrets.", "contents: write", "id-token", "gh release", "git push", "docker push",
                      "docker login", "repository_dispatch", "workflow_call", "gh api"):
        assert forbidden not in text


def test_product_and_diagnostic_revisions_are_separate_and_checkout_is_exact():
    job = workflow()["jobs"]["quality"]
    assert job["env"]["LINGSHU_GATE_DIAGNOSTIC_SOURCE_SHA"] == SOURCE_SHA
    assert job["env"]["LINGSHU_GATE_DIAGNOSTIC_SOURCE_TREE"] == SOURCE_TREE
    assert job["env"]["LINGSHU_GATE_DIAGNOSTIC_SOURCE_TAG"] == "v0.4.5"
    assert job["defaults"]["run"]["working-directory"] == "source"
    product = steps()["Checkout fixed product source and history"]["with"]
    tools = steps()["Checkout exact diagnostic workflow revision"]["with"]
    assert product == {"ref": SOURCE_SHA, "path": "source", "fetch-depth": "0", "persist-credentials": "false"}
    assert tools == {"ref": "${{ github.workflow_sha }}", "path": "diagnostic-tools",
                     "fetch-depth": "1", "persist-credentials": "false"}


def test_diagnostic_environment_matches_original_release_and_retains_all_tests():
    value = steps()
    original = yaml.load((ROOT / ".github/workflows/release.yml").read_text(), Loader=yaml.BaseLoader)
    assert value["Set up release Python"]["with"]["python-version"] == original["env"]["LINGSHU_GATE_RELEASE_PYTHON_VERSION"]
    assert value["Set up release Node.js"]["with"]["node-version"] == original["env"]["LINGSHU_GATE_RELEASE_NODE_VERSION"]
    assert value["Set up release uv"]["with"]["version"] == "0.11.33"
    assert value["Install frozen quality and release dependencies"]["run"] == "uv sync --frozen --group release"
    assert value["Verify and build fixed-source Console"]["working-directory"] == "source/web"
    for command in ("npm ci", "npm run check:ux", "npm test", "npm run build"):
        assert command in value["Verify and build fixed-source Console"]["run"]
    command = value["Diagnose all original backend and release tests"]["run"]
    assert "ruff check ." in command and "mypy" in command
    assert 'python "$GITHUB_WORKSPACE/diagnostic-tools/scripts/quality/pytest_evidence.py"' in command
    assert "-q -vv --tb=short --maxfail=1" in command
    assert "--gate-evidence-dir=" in command and "--junitxml=" in command
    assert "faulthandler_timeout=120" in command
    for excluded in ("--deselect", "--ignore", "--disable", " -k ", " -m ", "tests/", "PYTHONPATH", " || "):
        assert excluded not in command
    upload = value["Retain immediate failure and interrupted-session evidence"]
    assert upload["if"] == "always()"
    assert "gate-release-quality-provenance.json" in upload["with"]["path"]
    assert "gate-release-quality" in upload["with"]["path"]


def _git(path, *arguments):
    return subprocess.check_output(["git", *arguments], cwd=path, text=True).strip()


def _repository(path):
    path.mkdir()
    _git(path, "init", "-q")
    (path / "fixture.txt").write_text("synthetic provenance fixture\n")
    _git(path, "add", "fixture.txt")
    _git(path, "-c", "user.name=Synthetic Fixture", "-c", "user.email=fixture@example.test", "commit", "-qm", "fixture")
    return _git(path, "rev-parse", "HEAD")


@pytest.mark.parametrize("fault", [None, "source_sha", "source_tree", "tag_sha", "annotated_tag", "dirty_source", "tooling_sha"])
def test_provenance_step_executes_and_rejects_each_mismatch(tmp_path, fault):
    # All Git state lives in these new synthetic repositories; no real tag is mutated.
    source = tmp_path / "source"
    sha = _repository(source)
    tree = _git(source, "rev-parse", "HEAD^{tree}")
    _git(source, "tag", "v0.4.5")
    tools = tmp_path / "diagnostic-tools"
    tools_sha = _repository(tools)
    helper = tools / "scripts/quality/pytest_evidence.py"
    helper.parent.mkdir(parents=True)
    helper.write_text("# synthetic helper\n")
    _git(tools, "add", "scripts")
    _git(tools, "-c", "user.name=Synthetic Fixture", "-c", "user.email=fixture@example.test", "commit", "-qm", "helper")
    tools_sha = _git(tools, "rev-parse", "HEAD")
    output = tmp_path / "runner-temp"
    output.mkdir()
    env = {**os.environ, "GITHUB_WORKSPACE": str(tmp_path), "RUNNER_TEMP": str(output),
           "LINGSHU_GATE_DIAGNOSTIC_SOURCE_SHA": sha, "LINGSHU_GATE_DIAGNOSTIC_SOURCE_TREE": tree,
           "LINGSHU_GATE_DIAGNOSTIC_SOURCE_TAG": "v0.4.5", "GITHUB_WORKFLOW_SHA": tools_sha,
           "GITHUB_WORKFLOW_REF": "synthetic/repository/diagnostic.yml@refs/heads/fixture", "GITHUB_SHA": tools_sha}
    if fault in ("source_sha", "source_tree", "tooling_sha"):
        key = {"source_sha": "LINGSHU_GATE_DIAGNOSTIC_SOURCE_SHA", "source_tree": "LINGSHU_GATE_DIAGNOSTIC_SOURCE_TREE",
               "tooling_sha": "GITHUB_WORKFLOW_SHA"}[fault]
        env[key] = "0" * 40
    elif fault == "tag_sha":
        _git(source, "-c", "user.name=Synthetic Fixture", "-c", "user.email=fixture@example.test",
             "commit", "--allow-empty", "-qm", "other synthetic source")
        env["LINGSHU_GATE_DIAGNOSTIC_SOURCE_SHA"] = _git(source, "rev-parse", "HEAD")
    elif fault == "annotated_tag":
        _git(source, "tag", "-d", "v0.4.5")
        _git(source, "-c", "user.name=Synthetic Fixture", "-c", "user.email=fixture@example.test",
             "tag", "-am", "synthetic annotated tag", "v0.4.5")
    elif fault == "dirty_source":
        (source / "fixture.txt").write_text("synthetic changed source\n")
    shell = steps()["Verify source tag and separate workflow provenance"]["run"]
    python = shell.split("python - <<'PY'\n", 1)[1].split("\nPY\n", 1)[0]
    result = subprocess.run([sys.executable, "-c", python], cwd=source, env=env, capture_output=True, text=True, timeout=20)
    evidence = output / "gate-release-quality-provenance.json"
    if fault:
        assert result.returncode != 0 and not evidence.exists(), result.stdout + result.stderr
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        document = json.loads(evidence.read_text())
        assert document["tested_source_sha"] == sha and document["tested_source_tree"] == tree
        assert document["existing_tag_sha"] == sha
        assert document["workflow_sha"] == document["diagnostic_tooling_sha"] == tools_sha
        assert document["tested_source_sha"] != document["workflow_sha"]

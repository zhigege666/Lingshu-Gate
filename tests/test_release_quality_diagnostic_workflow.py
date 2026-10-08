"""Read-only workflow contracts; these tests never dispatch a workflow."""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from xml.etree import ElementTree as ET

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
    assert "defaults" not in job and "PYTHONUNBUFFERED" not in job["env"]
    product = steps()["Checkout fixed product source and history"]["with"]
    tools = steps()["Checkout exact diagnostic workflow revision"]["with"]
    assert product == {"ref": SOURCE_SHA, "fetch-depth": "0", "persist-credentials": "false"}
    assert tools == {"ref": "${{ github.workflow_sha }}", "fetch-depth": "1", "persist-credentials": "false"}


def test_diagnostic_environment_matches_original_release_and_retains_all_tests():
    value = steps()
    original = yaml.load((ROOT / ".github/workflows/release.yml").read_text(), Loader=yaml.BaseLoader)
    assert workflow()["env"] == original["env"] and len(workflow()["env"]) == 7
    assert value["Set up release Python"]["with"]["python-version"] == original["env"]["LINGSHU_GATE_RELEASE_PYTHON_VERSION"]
    assert value["Set up release Node.js"]["with"]["node-version"] == original["env"]["LINGSHU_GATE_RELEASE_NODE_VERSION"]
    assert value["Set up release uv"]["with"]["version"] == "0.11.33"
    assert value["Install frozen quality and release dependencies"]["run"] == "uv sync --frozen --group release"
    assert value["Verify and build fixed-source Console"]["working-directory"] == "web"
    assert value["Set up release Node.js"]["with"]["cache-dependency-path"] == "web/package-lock.json"
    assert value["Set up release uv"]["with"]["cache-dependency-glob"] == "uv.lock"
    for command in ("npm ci", "npm run check:ux", "npm test", "npm run build"):
        assert command in value["Verify and build fixed-source Console"]["run"]
    command = value["Diagnose all original backend and release tests"]["run"]
    assert "ruff check ." in command and "mypy" in command
    assert "uv run --no-sync pytest -q --maxfail=1" in command and "--junitxml=" in command
    for excluded in ("--deselect", "--ignore", "--disable", " -k ", " -m ", "tests/", "PYTHONPATH", " || ",
                     "pytest_evidence", "--gate-evidence", " -vv", "--tb=", "PYTHONUNBUFFERED", "faulthandler_timeout"):
        assert excluded not in command
    upload = value["Retain immediate failure and interrupted-session evidence"]
    assert upload["if"] == "always()"
    assert "gate-release-quality-provenance.json" in upload["with"]["path"]
    assert "gate-release-quality" in upload["with"]["path"]
    assert "gate-diagnostic-workflow.json" in upload["with"]["path"]


def _git(path, *arguments):
    return subprocess.check_output(["git", *arguments], cwd=path, text=True).strip()


def _repository(path):
    path.mkdir()
    _git(path, "init", "-q")
    (path / "fixture.txt").write_text("synthetic provenance fixture\n")
    _git(path, "add", "fixture.txt")
    _git(path, "-c", "user.name=Synthetic Fixture", "-c", "user.email=fixture@example.test", "commit", "-qm", "fixture")
    return _git(path, "rev-parse", "HEAD")


@pytest.mark.parametrize("fault", [None, "source_sha", "source_tree", "tag_sha", "annotated_tag", "dirty_source", "tooling_sha", "workspace_root", "platform_sha"])
def test_provenance_step_executes_and_rejects_each_mismatch(tmp_path, fault):
    # All Git state lives in these new synthetic repositories; no real tag is mutated.
    source = tmp_path / "source"
    sha = _repository(source)
    tree = _git(source, "rev-parse", "HEAD^{tree}")
    _git(source, "tag", "v0.4.5")
    diagnostic = source / ".github/workflows/release-quality-diagnostic.yml"
    diagnostic.parent.mkdir(parents=True)
    diagnostic.write_text("# synthetic diagnostic workflow\n")
    _git(source, "add", ".github")
    _git(source, "-c", "user.name=Synthetic Fixture", "-c", "user.email=fixture@example.test", "commit", "-qm", "tooling")
    tools_sha = _git(source, "rev-parse", "HEAD")
    output = tmp_path / "runner-temp"
    output.mkdir()
    env = {**os.environ, **workflow()["env"], "GITHUB_WORKSPACE": str(source), "RUNNER_TEMP": str(output),
           "LINGSHU_GATE_DIAGNOSTIC_SOURCE_SHA": sha, "LINGSHU_GATE_DIAGNOSTIC_SOURCE_TREE": tree,
           "LINGSHU_GATE_DIAGNOSTIC_SOURCE_TAG": "v0.4.5", "GITHUB_WORKFLOW_SHA": tools_sha,
           "GITHUB_WORKFLOW_REF": "synthetic/repository/diagnostic.yml@refs/heads/fixture", "GITHUB_SHA": tools_sha}
    capture = steps()["Preserve actual platform workflow identity outside the product checkout"]["run"]
    capture_python = capture.split("python - <<'PY'\n", 1)[1].split("\nPY", 1)[0]
    result = subprocess.run([sys.executable, "-c", capture_python], cwd=source, env=env, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    _git(source, "checkout", "-q", sha)
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
    elif fault == "workspace_root":
        env["GITHUB_WORKSPACE"] = str(tmp_path)
    elif fault == "platform_sha":
        env["GITHUB_SHA"] = "0" * 40
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
        assert document["product_at_workspace_root"] is True
        assert document["controlled_product_context"] == {"GITHUB_SHA": sha, "GITHUB_REF": "refs/tags/v0.4.5",
                                                           "GITHUB_REF_NAME": "v0.4.5", "GITHUB_REF_TYPE": "tag"}
        assert document["platform_context"]["GITHUB_SHA"] == tools_sha
        assert document["release_environment"] == workflow()["env"]


def _backend_launch(tmp_path, source_text, *, fail_ruff=False):
    source = tmp_path / "workspace"
    source.mkdir()
    (source / "pytest.ini").write_text("[pytest]\n")
    tests = source / "tests"
    tests.mkdir()
    (tests / "test_synthetic.py").write_text(source_text)
    runner_temp = tmp_path / "runner-temp"
    runner_temp.mkdir()
    binary = tmp_path / "bin"
    binary.mkdir()
    calls = tmp_path / "uv-calls.jsonl"
    pytest_cli = Path(sys.executable).with_name("pytest")
    assert pytest_cli.is_file(), "The frozen test environment must supply the real pytest CLI"
    shim = binary / "uv"
    shim.write_text(
        f"#!{sys.executable}\nimport json,os,sys\nfrom pathlib import Path\n"
        "assert sys.argv[1:3]==['run','--no-sync']\n"
        "names=['GITHUB_SHA','GITHUB_REF','GITHUB_REF_NAME','GITHUB_REF_TYPE','GITHUB_WORKFLOW_SHA','GITHUB_WORKFLOW_REF','PYTHONUNBUFFERED']\n"
        f"with Path({str(calls)!r}).open('a') as f: f.write(json.dumps({{'args':sys.argv[1:],'cwd':os.getcwd(),'context':{{k:os.environ.get(k) for k in names}}}})+'\\n')\n"
        f"if sys.argv[3]=='ruff': raise SystemExit({7 if fail_ruff else 0})\n"
        "if sys.argv[3]=='mypy': raise SystemExit(0)\n"
        "assert sys.argv[3]=='pytest'\n"
        f"os.execv({str(pytest_cli)!r},[{str(pytest_cli)!r},*sys.argv[4:]])\n")
    shim.chmod(0o755)
    shell = tmp_path / "diagnose.sh"
    shell.write_text(steps()["Diagnose all original backend and release tests"]["run"])
    environment = {**os.environ, **workflow()["env"],
                   "PATH": str(binary) + os.pathsep + str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"],
                   "RUNNER_TEMP": str(runner_temp), "GITHUB_WORKSPACE": str(source),
                   "LINGSHU_GATE_DIAGNOSTIC_SOURCE_SHA": SOURCE_SHA,
                   "LINGSHU_GATE_DIAGNOSTIC_SOURCE_TAG": "v0.4.5",
                   "GITHUB_SHA": "1" * 40, "GITHUB_REF": "refs/heads/reviewed-diagnostic",
                   "GITHUB_WORKFLOW_SHA": "1" * 40,
                   "GITHUB_WORKFLOW_REF": "synthetic/repository/diagnostic.yml@refs/heads/reviewed-diagnostic"}
    for name in ("PYTHONUNBUFFERED", "PYTHONPATH", "PYTEST_ADDOPTS"):
        environment.pop(name, None)
    return ["bash", str(shell)], source, environment, runner_temp, calls


def test_formal_shaped_cli_stops_at_first_failure_and_retains_standard_trace(tmp_path):
    sentinel = tmp_path / "later-test-ran"
    source = ("from pathlib import Path\n"
              "def test_pass_first():\n    assert True\n"
              "def test_first_failure():\n    assert False, 'synthetic-first-failure-trace'\n"
              f"def test_unreached():\n    Path({str(sentinel)!r}).touch()\n")
    command, workspace, environment, runner_temp, calls = _backend_launch(tmp_path, source)
    result = subprocess.run(command, cwd=workspace, env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode == 1 and not sentinel.exists(), result.stdout + result.stderr
    assert "FAILED tests/test_synthetic.py::test_first_failure" in result.stdout
    assert "synthetic-first-failure-trace" in result.stdout and "stopping after 1 failures" in result.stdout
    receipt = json.loads((runner_temp / "gate-release-quality/command-result.json").read_text())
    assert receipt["exit_code"] == 1 and receipt["phase"] == "pytest" and receipt["signal"] == ""
    suite = ET.parse(runner_temp / "gate-release-quality/junit.xml").getroot().find("testsuite")
    assert suite.attrib["failures"] == "1" and suite.attrib["tests"] == "2"
    invocations = [json.loads(line) for line in calls.read_text().splitlines()]
    assert [call["args"][2] for call in invocations] == ["ruff", "mypy", "pytest"]
    assert invocations[-1]["args"] == ["run", "--no-sync", "pytest", "-q", "--maxfail=1",
                                         "--junitxml=" + str(runner_temp / "gate-release-quality/junit.xml")]
    for call in invocations:
        assert call["cwd"] == str(workspace)
        assert call["context"]["GITHUB_SHA"] == SOURCE_SHA and call["context"]["GITHUB_REF"] == "refs/tags/v0.4.5"
        assert call["context"]["GITHUB_WORKFLOW_SHA"] == "1" * 40
        assert call["context"]["GITHUB_WORKFLOW_REF"].endswith("@refs/heads/reviewed-diagnostic")
        assert call["context"]["PYTHONUNBUFFERED"] is None


@pytest.mark.parametrize("source,exit_code,marker", [
    ("def test_one():\n    assert True\ndef test_two():\n    assert True\n", 0, "2 passed"),
    ("import pytest\n@pytest.fixture\ndef bad_setup():\n    raise ValueError('synthetic-setup-trace')\n"
     "def test_setup_failure(bad_setup):\n    pass\ndef test_unreached():\n    assert False\n", 1, "synthetic-setup-trace"),
])
def test_standard_pytest_cli_preserves_success_and_setup_failure(tmp_path, source, exit_code, marker):
    command, workspace, environment, runner_temp, _ = _backend_launch(tmp_path, source)
    result = subprocess.run(command, cwd=workspace, env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode == exit_code and marker in result.stdout, result.stdout + result.stderr
    receipt = json.loads((runner_temp / "gate-release-quality/command-result.json").read_text())
    assert receipt["exit_code"] == exit_code and receipt["phase"] == "pytest"
    assert (runner_temp / "gate-release-quality/junit.xml").is_file()


def test_quality_failure_preserves_exit_and_does_not_start_pytest(tmp_path):
    command, workspace, environment, runner_temp, calls = _backend_launch(tmp_path, "def test_unused(): pass\n", fail_ruff=True)
    result = subprocess.run(command, cwd=workspace, env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode == 7
    receipt = json.loads((runner_temp / "gate-release-quality/command-result.json").read_text())
    assert receipt["exit_code"] == 7 and receipt["phase"] == "ruff"
    assert len(calls.read_text().splitlines()) == 1 and not (runner_temp / "gate-release-quality/junit.xml").exists()


def test_diagnostic_refuses_existing_evidence_without_overwrite(tmp_path):
    command, workspace, environment, runner_temp, calls = _backend_launch(tmp_path, "def test_unused(): pass\n")
    destination = runner_temp / "gate-release-quality"
    destination.mkdir()
    sentinel = destination / "command-result.json"
    sentinel.write_text("existing-user-evidence")
    result = subprocess.run(command, cwd=workspace, env=environment, capture_output=True, text=True, timeout=20)
    assert result.returncode != 0 and sentinel.read_text() == "existing-user-evidence"
    assert not calls.exists()


def test_interrupted_cli_retains_nonzero_signal_receipt(tmp_path):
    ready = tmp_path / "test-started"
    source = ("import time\nfrom pathlib import Path\n"
              f"def test_wait():\n    Path({str(ready)!r}).touch()\n    while True:\n        time.sleep(.01)\n")
    command, workspace, environment, runner_temp, _ = _backend_launch(tmp_path, source)
    process = subprocess.Popen(command, cwd=workspace, env=environment, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, text=True, start_new_session=True)
    try:
        deadline = time.monotonic() + 15
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.01)
        assert ready.exists(), "The actual pytest CLI did not start its synthetic wait node"
        os.killpg(process.pid, signal.SIGTERM)
        output, _ = process.communicate(timeout=10)
        assert process.returncode == 143, output
        receipt = json.loads((runner_temp / "gate-release-quality/command-result.json").read_text())
        assert receipt["exit_code"] == 143 and receipt["signal"] == "TERM" and receipt["phase"] == "pytest"
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
        process.communicate(timeout=10)

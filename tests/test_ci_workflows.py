from __future__ import annotations

import fnmatch
import os
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]


def _workflow(name: str) -> dict:
    return yaml.load((ROOT / ".github" / "workflows" / name).read_text(), Loader=yaml.BaseLoader)


def test_ci_result_is_always_reported_and_depends_on_all_source_tests() -> None:
    workflow = _workflow("backend.yml")
    assert "pull_request" in workflow["on"]
    assert not {"paths", "paths-ignore"}.intersection(workflow["on"]["pull_request"])
    assert workflow["permissions"] == {"contents": "read"}
    result = workflow["jobs"]["result"]
    assert result["if"] == "always()"
    assert set(result["needs"]) == {"source", "compatibility"}
    assert workflow["jobs"]["compatibility"]["needs"] == "source"


@pytest.mark.parametrize(
    ("source", "compatibility", "succeeds"),
    [
        ("success", "success", True),
        ("failure", "success", False),
        ("success", "failure", False),
        ("skipped", "success", False),
        ("success", "skipped", False),
        ("cancelled", "success", False),
        ("success", "cancelled", False),
        ("", "success", False),
        ("success", "", False),
    ],
)
def test_ci_result_rejects_failed_cancelled_skipped_or_missing_tests(source, compatibility, succeeds) -> None:
    step = _workflow("backend.yml")["jobs"]["result"]["steps"][0]
    assert step["env"]["SOURCE_RESULT"] == "${{ needs.source.result }}"
    assert step["env"]["COMPATIBILITY_RESULT"] == "${{ needs.compatibility.result }}"
    result = subprocess.run(
        ["bash", "-c", step["run"]],
        env={**os.environ, "SOURCE_RESULT": source, "COMPATIBILITY_RESULT": compatibility},
        capture_output=True,
        text=True,
        check=False,
    )
    assert (result.returncode == 0) is succeeds


def test_compatibility_keeps_all_supported_python_versions_with_one_console_build() -> None:
    workflow = _workflow("backend.yml")
    source = workflow["jobs"]["source"]
    compatibility = workflow["jobs"]["compatibility"]
    primary = next(step["with"]["python-version"] for step in source["steps"]
                   if step.get("uses", "").startswith("actions/setup-python@"))
    assert {primary, *compatibility["strategy"]["matrix"]["python-version"]} == {"3.11", "3.12", "3.13"}
    source_commands = "\n".join(step.get("run", "") for step in source["steps"])
    for command in ("npm run check:ux", "npm test", "npm run build", "ruff check .", "mypy", "pytest -q"):
        assert command in source_commands
    assert "--history" in source_commands
    compatibility_commands = "\n".join(step.get("run", "") for step in compatibility["steps"])
    assert "pytest -q" in compatibility_commands
    assert "npm ci" in compatibility_commands
    assert "npm run build" not in compatibility_commands
    assert "npm test" not in compatibility_commands

    upload = next(step for step in source["steps"]
                  if step.get("uses", "").startswith("actions/upload-artifact@"))["with"]
    download = next(step for step in compatibility["steps"]
                    if step.get("uses", "").startswith("actions/download-artifact@"))["with"]
    assert upload["name"] == download["name"] == "ci-console-${{ github.sha }}"
    assert upload["path"] == download["path"] == "src/lingshu_gate/static/console"
    assert upload["if-no-files-found"] == "error"
    assert "run-id" not in download and "github-token" not in download


@pytest.mark.parametrize(
    ("path", "required"),
    [
        ("README.md", False),
        ("README.zh-CN.md", False),
        ("docs/operations.md", False),
        ("web/src/app.tsx", False),
        ("web/src/styles.css", False),
        ("src/lingshu_gate/_version.py", True),
        ("src/lingshu_gate/runtime_environment.py", True),
        ("src/lingshu_gate/cli.py", True),
        ("src/lingshu_gate/config.py", True),
        ("src/lingshu_gate/auth.py", True),
        ("src/lingshu_gate/build_deploy.py", True),
        ("src/lingshu_gate/build_preflight.py", True),
        ("src/lingshu_gate/diagnostics.py", True),
        ("pyproject.toml", True),
        ("uv.lock", True),
        ("web/package-lock.json", True),
        ("web/vite.config.ts", True),
        ("scripts/release/build_native.py", True),
        ("scripts/quality/check_repository_identity.py", True),
        ("packaging/native/start.cmd", True),
        (".github/workflows/release.yml", True),
    ],
)
def test_full_native_matrix_is_triggered_by_packaging_risks(path: str, required: bool) -> None:
    patterns = _workflow("release.yml")["on"]["pull_request"]["paths"]
    assert any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns) is required


def test_formal_release_retains_its_own_complete_source_validation() -> None:
    workflow = _workflow("release.yml")
    assert workflow["on"]["push"]["tags"] == ["v*"]
    steps = {step["name"]: step for step in workflow["jobs"]["quality"]["steps"]}
    for name in (
        "Validate repository identity",
        "Verify and build Console",
        "Verify pip export is synchronized",
        "Verify backend and release engineering",
    ):
        assert steps[name]["if"] == "github.event_name != 'pull_request'"
    commands = steps["Verify backend and release engineering"]["run"]
    assert "ruff check ." in commands and "mypy" in commands and "pytest -q" in commands
    assert steps["Verify release engineering on pull requests"]["if"] == "github.event_name == 'pull_request'"
    assert "tests/test_release_packaging.py" in steps["Verify release engineering on pull requests"]["run"]

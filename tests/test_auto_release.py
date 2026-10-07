"""Exercise release selection against real Git histories without publishing."""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))
parse_version = importlib.import_module("scripts.release.common").parse_version
select_release = importlib.import_module("scripts.release.select_release").select_release

VERSION_PATH = "src/lingshu_gate/_version.py"


def _git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-c", "commit.gpgsign=false", *arguments],
        cwd=repository,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    _git(root, "init", "--initial-branch=main")
    _git(root, "config", "user.name", "Release test")
    _git(root, "config", "user.email", "release-test@example.invalid")
    _git(root, "config", "core.hooksPath", str(tmp_path / "no-hooks"))
    return root


def _commit(repository: Path, source: str, path: str = VERSION_PATH) -> str:
    destination = repository / path
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source, encoding="utf-8")
    _git(repository, "add", path)
    _git(repository, "commit", "-m", "Update test source")
    return _git(repository, "rev-parse", "HEAD")


def _version(repository: Path, version: str) -> str:
    return _commit(repository, f'__version__ = "{version}"\n')


def _push(repository: Path, before: str, sha: str | None = None) -> dict[str, str]:
    return select_release(
        repository,
        event_name="push",
        ref="refs/heads/main",
        sha=sha if sha is not None else _git(repository, "rev-parse", "HEAD"),
        before=before,
    )


@pytest.mark.parametrize("version", ["0.2.0", "0.2.0-rc.1"])
def test_single_commit_version_change_selects_exact_tag(repository: Path, version: str) -> None:
    before = _version(repository, "0.1.0")
    _version(repository, version)

    result = _push(repository, before)

    assert result["publish"] == "true"
    assert result["tag"] == f"v{version}"
    assert "0.1.0" in result["reason"] and version in result["reason"]


def test_multi_commit_push_compares_before_not_last_commit_parent(repository: Path) -> None:
    before = _version(repository, "0.1.0")
    _version(repository, "0.2.0")
    _commit(repository, "Release documentation\n", "README.md")

    result = _push(repository, before)

    assert result["publish"] == "true"
    assert result["tag"] == "v0.2.0"


def test_version_bump_reverted_within_same_push_does_not_publish(repository: Path) -> None:
    before = _version(repository, "0.1.0")
    _version(repository, "0.2.0")
    _version(repository, "0.1.0")

    assert _push(repository, before)["publish"] == "false"


@pytest.mark.parametrize("change", ["ordinary", "comment"])
def test_unchanged_version_does_not_publish(repository: Path, change: str) -> None:
    before = _version(repository, "0.2.0")
    if change == "ordinary":
        _commit(repository, "UI maintenance\n", "README.md")
    else:
        _commit(repository, '# Version source for packaging.\n__version__ = "0.2.0"\n')

    result = _push(repository, before)

    assert result["publish"] == "false"
    assert result["tag"] == "v0.2.0"


@pytest.mark.parametrize("tag", ["v0.2.0", "", "v0.2.1", "0.2.0", "v0.2.0\npublish=true"])
def test_manual_release_requires_exact_tag_without_push_baseline(repository: Path, tag: str) -> None:
    sha = _version(repository, "0.2.0")
    arguments = {"event_name": "workflow_dispatch", "ref": "refs/heads/main", "sha": sha, "requested_tag": tag}

    if tag == "v0.2.0":
        result = select_release(repository, **arguments)
        assert result["publish"] == "true"
        assert result["tag"] == tag
    else:
        with pytest.raises(RuntimeError):
            select_release(repository, **arguments)


@pytest.mark.parametrize("before", ["", "0" * 40, "1234567", "--all", "f" * 40])
def test_push_rejects_missing_invalid_or_unavailable_baseline(repository: Path, before: str) -> None:
    _version(repository, "0.2.0")

    with pytest.raises(RuntimeError):
        _push(repository, before)


@pytest.mark.parametrize("sha", ["", "0" * 40, "1234567", "--all", "f" * 40])
def test_release_rejects_invalid_or_unverified_source_revision(repository: Path, sha: str) -> None:
    before = _version(repository, "0.1.0")
    _version(repository, "0.2.0")

    with pytest.raises(RuntimeError):
        _push(repository, before, sha)


def test_checked_out_revision_must_match_even_if_requested_commit_exists(repository: Path) -> None:
    before = _version(repository, "0.1.0")
    selected = _version(repository, "0.2.0")
    _commit(repository, "Later revision\n", "README.md")

    with pytest.raises(RuntimeError):
        _push(repository, before, selected)


def test_nonancestor_push_baseline_fails_closed(repository: Path) -> None:
    common = _version(repository, "0.1.0")
    abandoned = _version(repository, "0.2.0")
    _git(repository, "checkout", "--detach", common)
    _version(repository, "0.3.0")

    with pytest.raises(RuntimeError):
        _push(repository, abandoned)


def test_baseline_without_version_file_fails_closed(repository: Path) -> None:
    before = _commit(repository, "Initial project\n", "README.md")
    _version(repository, "0.2.0")

    with pytest.raises(RuntimeError):
        _push(repository, before)


def test_current_revision_without_version_file_fails_closed(repository: Path) -> None:
    before = _version(repository, "0.1.0")
    _git(repository, "rm", VERSION_PATH)
    _git(repository, "commit", "-m", "Remove version source")

    with pytest.raises(RuntimeError):
        _push(repository, before)


@pytest.mark.parametrize("boundary", ["before", "current"])
@pytest.mark.parametrize(
    "source",
    [
        '__version__ = "01.2.0"\n',
        '__version__ = "0.2.0"\n__version__ = "0.2.0"\n',
        '__version__ = "0.1.0"\n__version__ = "0.2.0"\n',
        '__version__ = "0.2.0"\n__version__ = None\n',
        '    __version__ = "0.2.0"\n',
        "__version__ = '0.2.0\"\n",
    ],
    ids=[
        "invalid-semver", "duplicate-same", "duplicate-different", "nonliteral-reassignment",
        "leading-indent", "mismatched-quotes",
    ],
)
def test_invalid_or_ambiguous_version_at_either_boundary_fails_closed(
    repository: Path, boundary: str, source: str
) -> None:
    before = _commit(repository, source) if boundary == "before" else _version(repository, "0.1.0")
    if boundary == "current":
        _commit(repository, source)
    else:
        _version(repository, "0.3.0")

    with pytest.raises(RuntimeError):
        _push(repository, before)


def test_version_parser_never_executes_version_expression(tmp_path: Path) -> None:
    marker = tmp_path / "executed.txt"
    source = f'__version__ = __import__("pathlib").Path({str(marker)!r}).write_text("executed")\n'

    with pytest.raises(RuntimeError):
        parse_version(source)

    assert not marker.exists()


def test_version_parser_accepts_documented_constant_without_executing_statements() -> None:
    source = (
        '\"\"\"Package version example:\n__version__ = "9.9.9"\n\"\"\"\n'
        '# Release source\n__version__ = ("0.2." "0")  # Actual release version\n'
    )

    assert parse_version(source) == "0.2.0"
    with pytest.raises(RuntimeError):
        parse_version(source + 'raise RuntimeError("must not execute")\n')


def test_version_mentioned_only_in_docstring_is_not_a_release_version() -> None:
    with pytest.raises(RuntimeError):
        parse_version('\"\"\"Version example:\n__version__ = "0.2.0"\n\"\"\"\n')


@pytest.mark.parametrize(
    ("event", "ref"),
    [
        ("push", "refs/heads/feature"),
        ("workflow_dispatch", "refs/heads/feature"),
        ("push", "refs/tags/v0.2.0"),
        ("pull_request", "refs/heads/main"),
        ("pull_request_target", "refs/heads/main"),
        ("schedule", "refs/heads/main"),
    ],
)
def test_only_main_push_or_manual_main_can_select_publication(repository: Path, event: str, ref: str) -> None:
    sha = _version(repository, "0.2.0")

    with pytest.raises(RuntimeError):
        select_release(repository, event_name=event, ref=ref, sha=sha, before=sha, requested_tag="v0.2.0")


@pytest.mark.parametrize("decision", ["publish", "skip", "error"])
def test_cli_outputs_are_usable_by_actions_and_fail_closed(repository: Path, tmp_path: Path, decision: str) -> None:
    before = _version(repository, "0.1.0")
    sha = _version(repository, "0.2.0") if decision == "publish" else _commit(repository, "Notes\n", "README.md")
    if decision == "error":
        before = "0" * 40
    scripts = repository / "scripts" / "release"
    scripts.mkdir(parents=True)
    for filename in ("common.py", "select_release.py"):
        shutil.copyfile(REPOSITORY_ROOT / "scripts" / "release" / filename, scripts / filename)
    output = tmp_path / "github-output"
    summary = tmp_path / "github-summary"
    output.write_text("previous=value\n", encoding="utf-8")
    summary.write_text("Existing summary\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable, "-m", "scripts.release.select_release",
            "--event", "push", "--ref", "refs/heads/main", "--sha", sha,
            "--before", before, "--github-output", str(output), "--github-summary", str(summary),
        ],
        cwd=repository,
        capture_output=True,
        text=True,
        check=False,
    )

    if decision == "error":
        assert result.returncode != 0
        assert result.stderr.strip()
        assert "Traceback" not in result.stderr
        assert output.read_text(encoding="utf-8") == "previous=value\n"
        assert summary.read_text(encoding="utf-8") == "Existing summary\n"
    else:
        assert result.returncode == 0, result.stderr
        expected_publish = "true" if decision == "publish" else "false"
        expected_tag = "v0.2.0" if decision == "publish" else "v0.1.0"
        assert output.read_text(encoding="utf-8").splitlines() == [
            "previous=value", f"publish={expected_publish}", f"tag={expected_tag}",
        ]
        assert expected_tag in result.stdout
        assert f"publish={expected_publish}" in result.stdout
        assert summary.read_text(encoding="utf-8").startswith("Existing summary\n")
        assert sha in summary.read_text(encoding="utf-8")


def test_workflow_limits_automatic_trigger_and_gates_write_permissions() -> None:
    path = REPOSITORY_ROOT / ".github" / "workflows" / "publish-release.yml"
    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)

    assert set(workflow["on"]) == {"push", "workflow_dispatch"}
    assert workflow["on"]["push"] == {"branches": ["main"]}
    assert workflow["on"]["workflow_dispatch"]["inputs"]["tag"]["required"] == "true"
    assert workflow["permissions"] == {"contents": "read"}
    selection = workflow["jobs"]["select"]
    assert selection.get("permissions", workflow["permissions"]) == {"contents": "read"}
    checkout = next(step for step in selection["steps"] if step.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["ref"] == "${{ github.sha }}"
    assert checkout["with"]["fetch-depth"] == "0"
    assert checkout["with"]["persist-credentials"] == "false"
    selector = next(step for step in selection["steps"] if step.get("id") == "release")
    assert selector["env"]["RELEASE_BEFORE"] == "${{ github.event.before }}"
    assert '--before "$RELEASE_BEFORE"' in selector["run"]
    assert "HEAD^" not in selector["run"]
    assert "secrets." not in yaml.dump(selection)
    publication = workflow["jobs"]["publish"]
    assert publication["needs"] == "select"
    assert publication["if"] == "needs.select.outputs.publish == 'true'"
    assert publication["permissions"] == {"contents": "write", "actions": "write"}
    assert publication["env"]["RELEASE_TAG"] == "${{ needs.select.outputs.tag }}"
    assert workflow["concurrency"]["cancel-in-progress"] == "false"
    assert workflow["concurrency"]["queue"] == "max"


def test_registry_publication_keeps_queued_releases_instead_of_replacing_pending() -> None:
    path = REPOSITORY_ROOT / ".github" / "workflows" / "release.yml"
    workflow = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    concurrency = workflow["jobs"]["publish"]["concurrency"]

    assert concurrency["queue"] == "max"
    assert concurrency["cancel-in-progress"] == "false"
    assert "${{" not in concurrency["group"]

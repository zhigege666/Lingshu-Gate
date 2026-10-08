"""Exercise real pytest reporting, including a killed unfinished session."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest


ROOT = Path(__file__).resolve().parents[1]


def command(tmp_path, source, *, evidence=True):
    fixture = tmp_path / "test_synthetic.py"
    fixture.write_text(source, encoding="utf-8")
    config = tmp_path / "pytest.ini"
    config.write_text("[pytest]\n", encoding="utf-8")
    destination = tmp_path / "evidence"
    args = [sys.executable, "-u", "-m", "pytest", "-q", "--tb=short", "-c", str(config),
            "-p", "scripts.quality.pytest_evidence"]
    if evidence:
        args += ["--gate-evidence-dir=" + str(destination), "--junitxml=" + str(destination / "junit.xml")]
    args += [str(fixture)]
    env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONUNBUFFERED": "1"}
    return args, env, destination


@pytest.mark.parametrize(("source", "exit_code", "failures", "errors", "skipped", "complete"), [
    ("def test_ok():\n    assert True\n", 0, 0, 0, 0, True),
    ("def test_fail():\n    assert False, 'synthetic-failure-marker'\n", 1, 1, 0, 0, True),
    ("import pytest\n@pytest.fixture\ndef fixture():\n    raise ValueError('synthetic-setup-marker')\n"
     "def test_setup(fixture):\n    pass\n", 1, 0, 1, 0, True),
    ("import pytest\n@pytest.fixture\ndef fixture():\n    yield\n    raise ValueError('synthetic-teardown-marker')\n"
     "def test_teardown(fixture):\n    assert True\n", 1, 0, 1, 0, True),
    ("import pytest\ndef test_skip():\n    pytest.skip('synthetic-skip-marker')\n", 0, 0, 0, 1, True),
    ("raise ValueError('synthetic-collection-marker')\n", 2, 0, 1, 0, False),
])
def test_live_evidence_preserves_real_pytest_outcomes(tmp_path, source, exit_code, failures, errors, skipped, complete):
    args, env, destination = command(tmp_path, source)
    result = subprocess.run(args, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == exit_code, result.stdout + result.stderr
    suite = ET.parse(destination / "partial-junit.xml").getroot().find("testsuite")
    assert int(suite.attrib["failures"]) == failures
    assert int(suite.attrib["errors"]) == errors
    assert int(suite.attrib["skipped"]) == skipped
    properties = {item.attrib["name"]: item.attrib["value"] for item in suite.find("properties")}
    assert properties["complete"] == str(complete).lower()
    events = [json.loads(line) for line in (destination / "events.jsonl").read_text().splitlines()]
    assert events[-1]["event"] == "session_finish" and events[-1]["exit_code"] == exit_code
    assert (destination / "junit.xml").is_file()
    if failures or errors:
        assert "GATE_TEST_FAILURE" in result.stdout or "GATE_COLLECTION_FAILURE" in result.stdout


def test_failure_trace_and_partial_junit_survive_process_kill(tmp_path):
    ready = tmp_path / "ready"
    source = ("import time\nfrom pathlib import Path\n"
              "def test_fail_first():\n    assert False, 'failure-before-interruption'\n"
              f"def test_wait_second():\n    Path({str(ready)!r}).touch()\n    while True:\n        time.sleep(.01)\n")
    args, env, destination = command(tmp_path, source)
    process = subprocess.Popen(args, cwd=tmp_path, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        deadline = time.monotonic() + 20
        while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(.01)
        assert ready.exists(), "Synthetic second test did not start"
        suite = ET.parse(destination / "partial-junit.xml").getroot().find("testsuite")
        assert suite.attrib["failures"] == "1"
        assert "failure-before-interruption" in suite.find("testcase/failure").text
        assert not (destination / "junit.xml").exists()
        process.kill()
        stdout, _ = process.communicate(timeout=10)
        assert "GATE_TEST_FAILURE" in stdout and "failure-before-interruption" in stdout
        events = [json.loads(line) for line in (destination / "events.jsonl").read_text().splitlines()]
        assert any(event["event"] == "test_report" and event.get("outcome") == "failed" for event in events)
        assert events[-1]["event"] == "test_report" and events[-1]["phase"] == "setup"
        assert not any(event["event"] == "session_finish" for event in events)
        assert process.returncode != 0
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=10)


def test_diagnostics_are_opt_in_and_refuse_existing_data(tmp_path):
    args, env, destination = command(tmp_path, "def test_ok():\n    assert True\n", evidence=False)
    result = subprocess.run(args, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0 and not destination.exists()
    args, env, destination = command(tmp_path, "def test_ok():\n    assert True\n")
    destination.mkdir()
    sentinel = destination / "user-data.txt"
    sentinel.write_text("preserve-existing-data")
    result = subprocess.run(args, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode != 0
    assert sentinel.read_text() == "preserve-existing-data"
    assert list(destination.iterdir()) == [sentinel]


def test_external_diagnostic_launcher_imports_only_fixed_source_product_modules(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    package = source / "scripts/release"
    package.mkdir(parents=True)
    (package.parent / "__init__.py").write_text("")
    (package / "__init__.py").write_text("MARKER='fixed-source'\n")
    (source / "pytest.ini").write_text("[pytest]\n")
    (source / "test_source_binding.py").write_text(
        "from pathlib import Path\nfrom scripts import release\n"
        "def test_binding():\n"
        "    assert release.MARKER=='fixed-source'\n"
        "    assert Path(release.__file__).resolve().is_relative_to(Path.cwd())\n")
    destination = tmp_path / "evidence"
    args = [sys.executable, str(ROOT / "scripts/quality/pytest_evidence.py"), "-q",
            "--gate-evidence-dir=" + str(destination)]
    env = {**os.environ, "LINGSHU_GATE_DIAGNOSTIC_SOURCE_SHA": "1" * 40, "GITHUB_SHA": "2" * 40,
           "GITHUB_WORKFLOW_SHA": "3" * 40}
    result = subprocess.run(args, cwd=source, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    first = json.loads((destination / "events.jsonl").read_text().splitlines()[0])
    assert first["tested_source_sha"] == "1" * 40
    assert first["workflow_event_sha"] == "2" * 40 and first["workflow_sha"] == "3" * 40


@pytest.mark.parametrize("failing", [False, True], ids=["passing-session", "first-failure"])
def test_shared_json_monkeypatch_does_not_interrupt_live_evidence(tmp_path, failing):
    (tmp_path / "conftest.py").write_text(
        "import json\nimport pytest\n"
        "patch = pytest.MonkeyPatch()\n"
        "@pytest.fixture(scope='session', autouse=True)\n"
        "def guarded_shared_json():\n"
        "    original_dumps, original_dump = json.dumps, json.dump\n"
        "    def bounded_dumps(value, **kwargs):\n"
        "        assert not isinstance(value, (dict, list)), 'shared-json-guard'\n"
        "        return original_dumps(value, **kwargs)\n"
        "    def bounded_dump(value, stream, **kwargs):\n"
        "        assert not isinstance(value, (dict, list)), 'shared-json-guard'\n"
        "        return original_dump(value, stream, **kwargs)\n"
        "    patch.setattr(json, 'dumps', bounded_dumps)\n"
        "    patch.setattr(json, 'dump', bounded_dump)\n"
        "    yield\n"
        "    # Keep the guard through session_finish; unconfigure restores it.\n"
        "def pytest_unconfigure(config):\n"
        "    patch.undo()\n", encoding="utf-8")
    outcome = "assert False, 'shared-json-failure-marker'" if failing else "assert True"
    source = ("import io\nimport json\nimport pytest\n"
              "def test_guard_is_active():\n"
              "    with pytest.raises(AssertionError, match='shared-json-guard'):\n"
              "        json.dumps({'synthetic': True})\n"
              "    with pytest.raises(AssertionError, match='shared-json-guard'):\n"
              "        json.dump({'synthetic': True}, io.StringIO())\n"
              f"def test_outcome():\n    {outcome}\n"
              "def test_remaining():\n    assert True\n")
    args, env, destination = command(tmp_path, source)
    # This fixture deliberately keeps the shared patch through session_finish.
    # Exclude pytest's own JSON cache writer from this isolated child process.
    args += ["--maxfail=1", "-p", "no:cacheprovider"]
    result = subprocess.run(args, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == int(failing), result.stdout + result.stderr
    assert "INTERNALERROR" not in result.stdout + result.stderr
    events = [json.loads(line) for line in (destination / "events.jsonl").read_text().splitlines()]
    finish = events[-1]
    assert finish["event"] == "session_finish" and finish["exit_code"] == int(failing)
    assert finish["collected"] == 3 and finish["finished"] == (2 if failing else 3)
    assert finish["complete"] is not failing
    failures = [event for event in events if event["event"] == "test_report" and event.get("outcome") == "failed"]
    assert len(failures) == int(failing)
    suite = ET.parse(destination / "partial-junit.xml").getroot().find("testsuite")
    assert int(suite.attrib["failures"]) == int(failing) and suite.attrib["errors"] == "0"
    properties = {item.attrib["name"]: item.attrib["value"] for item in suite.find("properties")}
    assert properties["complete"] == str(not failing).lower()
    assert (destination / "junit.xml").is_file()
    if failing:
        assert failures[0]["nodeid"] == "test_synthetic.py::test_outcome"
        assert "shared-json-failure-marker" in failures[0]["detail"]
        assert "GATE_TEST_FAILURE test_synthetic.py::test_outcome [call]" in result.stdout
        assert "shared-json-failure-marker" in suite.find("testcase/failure").text

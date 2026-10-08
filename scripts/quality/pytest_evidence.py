"""Opt-in release diagnostics that survive cancellation without changing tests."""
from __future__ import annotations

import json
import os
import platform
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest


def pytest_addoption(parser):
    parser.addoption("--gate-evidence-dir", help="Create a new directory for live release test evidence")


def pytest_configure(config):
    destination = config.getoption("--gate-evidence-dir")
    if destination:
        config.pluginmanager.register(Evidence(Path(destination), config), "gate-release-evidence")


def _xml_text(value):
    # JSONL retains the original text; XML 1.0 cannot represent control bytes.
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", lambda match: repr(match.group())[1:-1], value)


class Evidence:
    def __init__(self, destination, config):
        # Refuse existing files/directories rather than overwrite another run.
        destination.mkdir()
        self.destination = destination
        self.config = config
        self.journal = (destination / "events.jsonl").open("x", encoding="utf-8")
        self.started = time.monotonic()
        self.collected = []
        self.cases = {}
        self.finished = set()
        self.collection_failed = False
        self._event("session_start", python=platform.python_version(), pytest=pytest.__version__,
                    tested_source_sha=os.environ.get("LINGSHU_GATE_DIAGNOSTIC_SOURCE_SHA"),
                    workflow_event_sha=os.environ.get("GITHUB_SHA"), workflow_ref=os.environ.get("GITHUB_WORKFLOW_REF"),
                    workflow_sha=os.environ.get("GITHUB_WORKFLOW_SHA"))
        self._snapshot(complete=False)

    def _event(self, event, **values):
        self.journal.write(json.dumps({"utc": datetime.now(timezone.utc).isoformat(),
                                       "event": event, **values}, ensure_ascii=False) + "\n")
        self.journal.flush()

    def _line(self, message):
        terminal = self.config.pluginmanager.getplugin("terminalreporter")
        if terminal is not None:
            terminal.write_line(message)
            terminal.flush()

    def pytest_collection_finish(self, session):
        self.collected = [item.nodeid for item in session.items]
        with (self.destination / "collection.json").open("x", encoding="utf-8") as stream:
            json.dump(self.collected, stream, ensure_ascii=False)
        self._event("collection", count=len(self.collected))
        self._line(f"GATE_TEST_COLLECTION {len(self.collected)} items")

    def pytest_runtest_logstart(self, nodeid, location):
        self._event("test_start", nodeid=nodeid)
        self._line(f"GATE_TEST_START {nodeid}")

    def pytest_runtest_logreport(self, report):
        context = str(getattr(report, "context", ""))
        identity = report.nodeid + (f" {context}" if context else "")
        case = self.cases.setdefault(identity, {"nodeid": report.nodeid, "duration": 0.0, "reports": []})
        case["duration"] += report.duration
        result = {"phase": report.when, "outcome": report.outcome}
        if report.failed or report.skipped:
            result["detail"] = report.longreprtext
        case["reports"].append(result)
        self._event("test_report", nodeid=report.nodeid, context=context, duration=report.duration, **result)
        if report.failed:
            self._line(f"GATE_TEST_FAILURE {identity} [{report.when}]")
            self._line(report.longreprtext)
            for heading, content in report.sections:
                self._line(f"{heading}\n{content}")
            # Persist before the next test; cancellation cannot erase this failure.
            self._snapshot(complete=False)
        if report.when == "teardown":
            self.finished.add(report.nodeid)
            if len(self.finished) % 25 == 0:
                self._snapshot(complete=False)

    def pytest_collectreport(self, report):
        if report.failed:
            self.collection_failed = True
            self._event("collection_failure", nodeid=report.nodeid, detail=report.longreprtext)
            self.cases[report.nodeid] = {"nodeid": report.nodeid, "duration": 0.0,
                                       "reports": [{"phase": "collection", "outcome": "failed",
                                                    "detail": report.longreprtext}]}
            self._line(f"GATE_COLLECTION_FAILURE {report.nodeid}\n{report.longreprtext}")
            self._snapshot(complete=False)

    def _snapshot(self, *, complete):
        root = ET.Element("testsuites")
        suite = ET.SubElement(root, "testsuite", name="gate-release-live", tests=str(len(self.cases)),
                              time=f"{time.monotonic() - self.started:.6f}")
        properties = ET.SubElement(suite, "properties")
        for name, value in (("complete", str(complete).lower()), ("collected", str(len(self.collected))),
                            ("finished", str(len(self.finished)))):
            ET.SubElement(properties, "property", name=name, value=value)
        failures = errors = skipped = 0
        for identity, case in self.cases.items():
            item = ET.SubElement(suite, "testcase", name=_xml_text(identity),
                                 classname=case["nodeid"].split("::")[0].replace("/", "."),
                                 time=f"{case['duration']:.6f}")
            for report in case["reports"]:
                if report["outcome"] == "failed":
                    kind = "failure" if report["phase"] == "call" else "error"
                    failures += kind == "failure"
                    errors += kind == "error"
                    ET.SubElement(item, kind, message=report["phase"]).text = _xml_text(report["detail"])
                elif report["outcome"] == "skipped":
                    skipped += 1
                    ET.SubElement(item, "skipped").text = _xml_text(report["detail"])
        suite.set("failures", str(failures))
        suite.set("errors", str(errors))
        suite.set("skipped", str(skipped))
        # Only replace our own snapshot inside the freshly created directory.
        with tempfile.NamedTemporaryFile(dir=self.destination, prefix="snapshot-", delete=False) as stream:
            temporary = Path(stream.name)
            ET.ElementTree(root).write(stream, encoding="utf-8", xml_declaration=True)
        temporary.replace(self.destination / "partial-junit.xml")

    def pytest_sessionfinish(self, session, exitstatus):
        complete = (len(self.finished) == len(self.collected) and int(exitstatus) in (0, 1, 5)
                    and not self.collection_failed and not session.shouldstop and not session.shouldfail)
        self._event("session_finish", exit_code=int(exitstatus), complete=complete,
                    collected=len(self.collected), finished=len(self.finished))
        self._snapshot(complete=complete)
        self.journal.close()


if __name__ == "__main__":
    # Load only this diagnostic plugin from the workflow checkout. Product
    # imports, including scripts.release, must resolve from the tested checkout.
    sys.path.insert(0, str(Path.cwd()))
    raise SystemExit(pytest.main(sys.argv[1:], plugins=[sys.modules[__name__]]))

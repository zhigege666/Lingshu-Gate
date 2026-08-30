"""First-party observability event namespace tests."""

from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.logging import log_event
from lingshu_gate.mcp_restart_history import McpRestartHistoryStore
from lingshu_gate.observability_store import ObservabilityStore


class ObservabilityEventNamespaceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory(
            ignore_cleanup_errors=True
        )
        self.data_dir = Path(self.temporary_directory.name)
        self.database = SQLiteDatabase("", self.data_dir)
        self.store = ObservabilityStore(self.database)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_event_and_log_writes_require_gate_namespace(self) -> None:
        event = self.store.emit_event("gate.runtime.started")
        log = self.store.add_log(
            "info",
            "Runtime started",
            event_type="gate.runtime.started",
        )

        self.assertEqual(event["type"], "gate.runtime.started")
        self.assertEqual(log["event_type"], "gate.runtime.started")
        with self.assertRaisesRegex(ValueError, "Gate namespace"):
            self.store.emit_event("runtime.started")
        with self.assertRaisesRegex(ValueError, "Gate namespace"):
            self.store.add_log(
                "warning",
                "Invalid event namespace",
                event_type="runtime.started",
            )
        with self.assertRaisesRegex(ValueError, "Gate namespace"):
            self.store.add_log("warning", "Empty event namespace", event_type="")

        event_types = {
            str(row["type"])
            for row in self.database.query_all("SELECT type FROM events")
        }
        log_event_types = {
            str(row["event_type"])
            for row in self.database.query_all(
                "SELECT event_type FROM logs WHERE event_type IS NOT NULL"
            )
        }
        self.assertTrue(all(value.startswith("gate.") for value in event_types))
        self.assertTrue(all(value.startswith("gate.") for value in log_event_types))

    def test_event_type_filters_remain_strict_and_are_not_rewritten(self) -> None:
        self.store.emit_event("gate.auth.login", subject_id="user-1")
        self.store.add_log(
            "info",
            "Login",
            event_type="gate.auth.login",
            server_id="server-1",
        )

        self.assertEqual(self.store.list_events(event_type="auth.login"), [])
        self.assertEqual(self.store.list_logs(event_type="auth.login"), [])
        self.assertEqual(
            len(self.store.list_events(event_type="gate.auth.login")),
            1,
        )
        self.assertEqual(
            len(self.store.list_logs(event_type="gate.auth.login")),
            1,
        )

    def test_structured_log_and_restart_history_share_the_same_boundary(self) -> None:
        logger = logging.getLogger("test.gate.events")
        log_event(
            logger,
            logging.INFO,
            "gate.mcp.server_started",
            "Server started",
        )
        history = McpRestartHistoryStore(self.data_dir)
        entry = history.append(
            "server-1",
            "gate.mcp.restart_scheduled",
            "Restart scheduled",
        )
        self.assertEqual(entry["event_type"], "gate.mcp.restart_scheduled")

        with self.assertRaisesRegex(ValueError, "Gate namespace"):
            log_event(logger, logging.INFO, "mcp_server_started", "Invalid")
        with self.assertRaisesRegex(ValueError, "Gate namespace"):
            history.append("server-1", "mcp_restart_scheduled", "Invalid")


if __name__ == "__main__":
    unittest.main()

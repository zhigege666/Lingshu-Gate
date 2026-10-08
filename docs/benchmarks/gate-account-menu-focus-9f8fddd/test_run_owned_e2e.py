"""Pure boundary regressions. Never import Gate or launch a fixture/browser."""

from __future__ import annotations

import json
import ctypes
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import run_owned_e2e as owned


class OwnedBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="gate-owned-negative-")
        self.addCleanup(self.temporary.cleanup)
        self.parent = Path(self.temporary.name)
        self.layout = owned.new_layout(self.parent)
        self.root = Path(str(self.layout["root"]))
        self.python = Path(sys.executable)
        self.node = self.parent / "explicit-node" / "node"
        self.browsers = self.parent / "readonly-browser-binaries"
        self.browsers.mkdir()

    def environment(self, ambient: dict[str, str], *, fixture_child: bool = False) -> dict[str, str]:
        return owned.clean_environment(
            self.layout, ambient, self.python, self.node, self.browsers, fixture_child=fixture_child
        )

    def test_catalog_switch_is_rejected_before_preparation(self) -> None:
        with patch.object(owned, "_source_check") as source_check:
            for value in ["1", "0", ""]:
                with self.subTest(value=value), self.assertRaises(owned.BoundaryError):
                    owned.prepare(
                        self.parent,
                        Path("does-not-exist"),
                        self.python,
                        self.node,
                        self.browsers,
                        {"GATE_E2E_OAUTH_CATALOG_SCALE": value},
                    )
            source_check.assert_not_called()

    def test_unknown_e2e_parameter_is_rejected(self) -> None:
        with self.assertRaises(owned.BoundaryError):
            self.environment({"GATE_E2E_UNREVIEWED_SCENARIO": "1"})

    def test_unregistered_fixture_root_is_rejected(self) -> None:
        with self.assertRaises(owned.BoundaryError):
            self.environment({"GATE_E2E_TEMP_ROOT": str(self.parent)}, fixture_child=True)

    def test_fixture_child_still_rejects_catalog_injection(self) -> None:
        ambient = {"GATE_E2E_TEMP_ROOT": str(self.layout["fixture"]), "GATE_E2E_OAUTH_CATALOG_SCALE": "1"}
        with self.assertRaises(owned.BoundaryError):
            self.environment(ambient, fixture_child=True)

    def test_fixture_entry_injection_cannot_import_or_execute_gate(self) -> None:
        ambient = {"GATE_E2E_TEMP_ROOT": str(self.layout["fixture"]), "GATE_E2E_OAUTH_CATALOG_SCALE": "1"}
        with (
            patch.object(owned.os, "execve") as execute,
            patch.object(owned.importlib.util, "spec_from_file_location") as load,
        ):
            for entry in [False, True]:
                with self.subTest(entry=entry), self.assertRaises(owned.BoundaryError):
                    owned.fixture(self.root, ambient, entry=entry)
            execute.assert_not_called()
            load.assert_not_called()
        self.assertFalse((self.root / "fixture-launch-intent.json").exists())

    def test_fixture_entry_without_approval_cannot_import_gate(self) -> None:
        ambient = {"GATE_E2E_TEMP_ROOT": str(self.layout["fixture"])}
        with patch.object(owned.importlib.util, "spec_from_file_location") as load:
            with self.assertRaises(owned.BoundaryError):
                owned.fixture(self.root, ambient, entry=True)
            load.assert_not_called()

    def test_ambient_options_secrets_and_home_do_not_reach_inert_child(self) -> None:
        ambient = {
            name: "MUST_NOT_LEAK"
            for name in [
                "GH_TOKEN",
                "AWS_ACCESS_KEY_ID",
                "HTTP_PROXY",
                "HTTPS_PROXY",
                "ALL_PROXY",
                "LD_PRELOAD",
                "PYTHONPATH",
                "NODE_OPTIONS",
                "LINGSHU_GATE_ADMIN_PASSWORD",
                "LINGSHU_GATE_DB_URL",
                "npm_config_userconfig",
            ]
        }
        ambient.update({"HOME": str(self.parent), "TMPDIR": str(self.parent), "PATH": "MUST_NOT_LEAK"})
        environment = self.environment(ambient)
        # Real, harmless Python child proves the execution environment boundary.
        # It imports no Gate code and starts no server or new identity/grant.
        result = subprocess.run(
            [str(self.python), "-c", "import json,os;print(json.dumps(dict(os.environ)))"],
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )
        received = json.loads(result.stdout)
        for name in ambient:
            if name not in {"HOME", "TMPDIR", "PATH"}:
                self.assertNotIn(name, received)
        self.assertNotIn("MUST_NOT_LEAK", result.stdout)
        self.assertEqual(received["HOME"], self.layout["home"])
        for name in ["TMPDIR", "TMP", "TEMP"]:
            self.assertEqual(received[name], self.layout["tmp"])
        for name in [
            "XDG_CONFIG_HOME",
            "XDG_STATE_HOME",
            "XDG_CACHE_HOME",
            "PLAYWRIGHT_JSON_OUTPUT_NAME",
            "PLAYWRIGHT_HTML_OUTPUT_DIR",
            "npm_config_cache",
        ]:
            self.assertTrue(Path(received[name]).is_relative_to(self.root))
        self.assertEqual([k for k in received if k.startswith("GATE_E2E_")], ["GATE_E2E_TEMP_ROOT"])

    def test_all_report_paths_and_four_desktops_are_owned(self) -> None:
        source = Path(__file__).resolve().parents[3]
        owned._write_config(self.layout, source, self.python)
        configuration = (self.root / "owned.config.ts").read_text()
        self.assertEqual(json.loads((self.root / "package.json").read_text())["type"], "module")
        for relative in [
            "artifacts/test-results",
            "artifacts/results.json",
            "artifacts/html",
            "defer-cleanup.ts",
            "tests",
        ]:
            self.assertIn(str(self.root / relative), configuration)
        self.assertNotIn("/e2e/teardown.ts", configuration)
        for width, height, _ in owned.DESKTOPS:
            self.assertIn(f"desktop-{width}x{height}", configuration)
        focus = (self.root / "tests/account-focus-targets.spec.ts").read_text()
        self.assertNotIn("page.route(", focus)
        self.assertIn("page.setViewportSize({ width, height })", focus)
        self.assertIn("const openFrames = 0", focus)
        self.assertIn("window.gateAccountFrameQueue.advance()", focus)

    def test_missing_oauth_entry_blocks_preparation_inventory(self) -> None:
        source = self.parent / "fake-source"
        static_root = source / "src/lingshu_gate/static"
        for directory, name in [("console", "index.html"), ("oauth", "oauth.html")]:
            (static_root / directory).mkdir(parents=True)
            (static_root / directory / name).write_text("synthetic entry")
        self.assertIn("oauth.html", owned._inventory(source)["oauth"])
        (static_root / "oauth/oauth.html").unlink()
        with self.assertRaises(owned.BoundaryError):
            owned._inventory(source)

    def test_missing_scope_approval_starts_nothing(self) -> None:
        with patch.object(owned.subprocess, "Popen") as launch:
            with self.assertRaises(owned.BoundaryError):
                owned.run(self.layout, {}, fixture_scope_approved=False)
            launch.assert_not_called()
        with self.assertRaises(owned.BoundaryError):
            owned._require_execution_approval(self.root, self.layout)

    def test_live_pid_blocks_directory_removal(self) -> None:
        identity = owned.process_identity(os.getpid())
        self.assertIsNotNone(identity)
        self.assertFalse(owned.remove_after_exit(self.layout, str(self.layout["token"]), [identity], []))
        self.assertTrue(self.root.exists())

    def test_zombie_is_not_reaping_proof(self) -> None:
        identity = {"pid": 123456789, "start_ticks": 7, "ppid": 1, "state": "Z"}
        with patch.object(owned, "process_identity", return_value=identity):
            self.assertFalse(owned.remove_after_exit(self.layout, str(self.layout["token"]), [identity], []))
        self.assertTrue(self.root.exists())

    def test_pid_reuse_is_not_signalled_or_deleted(self) -> None:
        recorded = {"pid": 123456789, "start_ticks": 7, "ppid": 1, "state": "S"}
        replacement = {**recorded, "start_ticks": 8}
        with patch.object(owned, "process_identity", return_value=replacement), patch.object(owned.os, "kill") as kill:
            with self.assertRaises(owned.BoundaryError):
                owned.signal_owned(recorded, signal.SIGTERM)
            with self.assertRaises(owned.BoundaryError):
                owned.remove_after_exit(self.layout, str(self.layout["token"]), [recorded], [])
            kill.assert_not_called()
        self.assertTrue(self.root.exists())

    def test_protected_original_pid_is_never_signalled(self) -> None:
        with patch.object(owned.os, "kill") as kill, self.assertRaises(owned.BoundaryError):
            owned.signal_owned({"pid": owned.PROTECTED_PID}, signal.SIGTERM)
        kill.assert_not_called()

    def test_open_listener_blocks_directory_removal(self) -> None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            port = listener.getsockname()[1]
            self.assertFalse(owned.remove_after_exit(self.layout, str(self.layout["token"]), [], [port]))
            self.assertTrue(self.root.exists())

    def test_unknown_or_nonloopback_peer_cannot_close_cleanup_boundary(self) -> None:
        with self.assertRaises(owned.BoundaryError):
            owned.peer_port(self.layout)
        path = Path(str(self.layout["fixture"])) / "http-peer.json"
        path.write_text(json.dumps({"endpoint": "http://example.test:1234/mcp"}))
        with self.assertRaises(owned.BoundaryError):
            owned.peer_port(self.layout)

    def test_root_symlink_does_not_delete_target(self) -> None:
        other = self.parent / "unrelated"
        other.mkdir()
        sentinel = other / "keep.txt"
        sentinel.write_text("keep")
        moved = self.parent / "recorded-root-moved"
        self.root.rename(moved)
        self.root.symlink_to(other, target_is_directory=True)
        with self.assertRaises(owned.BoundaryError):
            owned.remove_after_exit(self.layout, str(self.layout["token"]), [], [])
        self.assertEqual(sentinel.read_text(), "keep")

    def test_nested_symlink_never_removes_unrelated_file(self) -> None:
        sentinel = self.parent / "keep.txt"
        sentinel.write_text("keep")
        (self.root / "external-link").symlink_to(sentinel)
        self.assertTrue(owned.remove_after_exit(self.layout, str(self.layout["token"]), [], []))
        self.assertEqual(sentinel.read_text(), "keep")

    def test_exception_retains_fake_application_state_until_exact_owned_cleanup(self) -> None:
        fixture_root = str(self.layout["fixture"])
        with patch.dict(os.environ, {"GATE_E2E_TEMP_ROOT": fixture_root}):
            application = owned.HeldAppDirectory(prefix="gate-browser-synthetic-", dir=fixture_root)
            sentinel = Path(application.name) / "state.sentinel"
            with self.assertRaises(RuntimeError):
                with application:
                    sentinel.write_text("temporary persistent state")
                    raise RuntimeError("synthetic failure")
        self.assertTrue(sentinel.exists())
        self.assertTrue(owned.remove_after_exit(self.layout, str(self.layout["token"]), [], []))
        self.assertFalse(sentinel.exists())

    def test_process_permission_uncertainty_is_not_exit_proof(self) -> None:
        with patch.object(Path, "read_text", side_effect=PermissionError):
            with self.assertRaises(owned.BoundaryError):
                owned.process_identity(123456789)

    def test_detached_orphan_blocks_cleanup_until_identity_reaped_and_listener_closed(self) -> None:
        # Harmless local process/socket probe only: no Gate, SQLite, identity,
        # classification, grant, OAuth client or browser is started.
        libc = ctypes.CDLL(None, use_errno=True)
        previous = ctypes.c_int()
        self.assertEqual(libc.prctl(37, ctypes.byref(previous), 0, 0, 0), 0)
        self.assertEqual(libc.prctl(36, 1, 0, 0, 0), 0)
        port_file = Path(str(self.layout["fixture"])) / "http-peer.json"
        child_code = (
            "import json,signal,socket,sys,time;from pathlib import Path;"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
            "s=socket.socket();s.bind(('127.0.0.1',0));s.listen();"
            "Path(sys.argv[1]).write_text(json.dumps({'endpoint':'http://127.0.0.1:'"
            "+str(s.getsockname()[1])+'/mcp'}));time.sleep(30)"
        )
        leader_code = (
            "import subprocess,sys;"
            "subprocess.Popen([sys.executable,'-c',sys.argv[1],sys.argv[2]],"
            "start_new_session=True,stdin=subprocess.DEVNULL,"
            "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)"
        )
        known = {}
        try:
            leader = subprocess.Popen([str(self.python), "-c", leader_code, child_code, str(port_file)])
            identity = owned.process_identity(leader.pid)
            if identity:
                known[leader.pid] = identity
            leader.wait(timeout=3)
            deadline = time.monotonic() + 3
            while not port_file.exists() and time.monotonic() < deadline:
                owned.observe_owned(known, os.getpid())
                time.sleep(0.02)
            owned.observe_owned(known, os.getpid())
            self.assertTrue(port_file.exists())
            port = owned.peer_port(self.layout)
            self.assertFalse(
                owned.remove_after_exit(self.layout, str(self.layout["token"]), list(known.values()), [port])
            )
            self.assertTrue(self.root.exists())
            self.assertTrue(owned.reap_owned(known, grace_seconds=0.25))
            self.assertTrue(owned.listener_closed(port))
            self.assertTrue(
                owned.remove_after_exit(self.layout, str(self.layout["token"]), list(known.values()), [port])
            )
        finally:
            owned.reap_owned(known, grace_seconds=0.25)
            libc.prctl(36, previous.value, 0, 0, 0)


if __name__ == "__main__":
    unittest.main()

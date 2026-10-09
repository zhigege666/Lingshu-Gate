"""Pure boundary regressions. Never import Gate or launch a fixture/browser."""

from __future__ import annotations

import json
import hashlib
import importlib.util
import ctypes
import errno
import os
import py_compile
from pathlib import Path
import signal
import socket
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
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
            "verify-static.ts",
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

    def fake_product(self) -> tuple[Path, dict[str, object]]:
        source = self.parent / "fake-product"
        package = source / "src/lingshu_gate"
        package.mkdir(parents=True)
        files = {}
        for name in ["__init__.py", "main.py"]:
            path = package / name
            path.write_text("raise RuntimeError('synthetic module must never execute')\n")
            files[str(path.relative_to(source))] = hashlib.sha256(path.read_bytes()).hexdigest()
        peer = source / "scripts/e2e/http_peer.py"
        peer.parent.mkdir(parents=True)
        peer.write_text("raise RuntimeError('synthetic helper must never execute')\n")
        files[str(peer.relative_to(source))] = hashlib.sha256(peer.read_bytes()).hexdigest()
        return source, {"files": files}

    def test_preloaded_peer_is_rejected_before_resolving_or_importing_product(self) -> None:
        source, binding = self.fake_product()
        old = SimpleNamespace(__file__=str(self.parent / "old-install/http_peer.py"))
        original_path = list(sys.path)
        with patch.dict(sys.modules, {"http_peer": old}), patch.object(owned.importlib.util, "find_spec") as resolve:
            with self.assertRaises(owned.BoundaryError):
                owned._bind_product_source(source, binding)
            resolve.assert_not_called()
        self.assertEqual(sys.path, original_path)

    def test_peer_matching_timestamp_and_size_cache_cannot_supply_old_code(self) -> None:
        source, binding = self.fake_product()
        path = source / "scripts/e2e/http_peer.py"
        stale = b"PEER_IMPLEMENTATION = 'stale---peer'\n"
        current = b"PEER_IMPLEMENTATION = 'current-peer'\n"
        self.assertEqual(len(stale), len(current))
        path.write_bytes(stale)
        timestamp = int(path.stat().st_mtime)
        cache = Path(importlib.util.cache_from_source(str(path)))
        cache.parent.mkdir()
        py_compile.compile(
            str(path), cfile=str(cache), doraise=True, invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP
        )
        cached_bytes = cache.read_bytes()
        path.write_bytes(current)
        os.utime(path, (timestamp, timestamp))
        binding["files"]["scripts/e2e/http_peer.py"] = hashlib.sha256(current).hexdigest()
        # The standard loader demonstrably chooses the still-valid old pyc.
        ordinary = owned.importlib.machinery.SourceFileLoader("ordinary_peer_probe", str(path))
        self.assertIn("stale---peer", ordinary.get_code("ordinary_peer_probe").co_consts)
        finder = owned.ReviewedProductFinder(source, binding)
        specification = finder.find_spec("http_peer", [str(self.parent / "old-install")])
        self.assertEqual(specification.origin, str(path))
        code = specification.loader.get_code("http_peer")
        self.assertIn("current-peer", code.co_consts)
        self.assertNotIn("stale---peer", code.co_consts)
        self.assertEqual(cache.read_bytes(), cached_bytes)
        self.assertNotIn("http_peer", sys.modules)

    def test_peer_changed_blob_is_rejected_before_compilation(self) -> None:
        source, binding = self.fake_product()
        specification = owned.ReviewedProductFinder(source, binding).find_spec("http_peer")
        (source / "scripts/e2e/http_peer.py").write_text("raise RuntimeError('changed helper bytes')\n")
        with self.assertRaises(owned.BoundaryError):
            specification.loader.get_code("http_peer")

    def test_peer_absent_from_binding_cannot_fall_back_to_installed_helper(self) -> None:
        source, binding = self.fake_product()
        del binding["files"]["scripts/e2e/http_peer.py"]
        with self.assertRaises(owned.BoundaryError):
            owned.ReviewedProductFinder(source, binding).find_spec("http_peer", [str(self.parent / "old-install")])

    def test_actual_peer_file_and_spec_must_both_match_git_bound_source(self) -> None:
        source, binding = self.fake_product()
        path = str(source / "scripts/e2e/http_peer.py")
        old = str(self.parent / "old-install/http_peer.py")
        for module in [
            SimpleNamespace(__file__=old, __spec__=SimpleNamespace(origin=path)),
            SimpleNamespace(__file__=path, __spec__=SimpleNamespace(origin=old)),
        ]:
            with self.subTest(module=module), patch.dict(sys.modules, {"http_peer": module}):
                with self.assertRaises(owned.BoundaryError):
                    owned._check_loaded_product(source, binding)

    def test_old_venv_origin_is_rejected_without_importing_product(self) -> None:
        source, binding = self.fake_product()
        old = self.parent / "old-venv/site-packages/lingshu_gate/__init__.py"
        old.parent.mkdir(parents=True)
        old.write_text("raise RuntimeError('old installation executed')\n")
        with (
            patch.object(owned.sys, "path", list(sys.path)),
            patch.object(owned.importlib.util, "find_spec", return_value=SimpleNamespace(origin=str(old))),
            patch.object(owned.importlib, "import_module") as product_import,
            self.assertRaises(owned.BoundaryError),
        ):
            owned._bind_product_source(source, binding)
        product_import.assert_not_called()

    def test_preloaded_old_venv_module_blocks_source_binding(self) -> None:
        source, binding = self.fake_product()
        stale = SimpleNamespace(__file__=str(self.parent / "old-venv/lingshu_gate/main.py"))
        with patch.dict(sys.modules, {"lingshu_gate.main": stale}), self.assertRaises(owned.BoundaryError):
            owned._bind_product_source(source, binding)

    def test_worker_pythonpath_is_generated_from_bound_source(self) -> None:
        source, binding = self.fake_product()
        binding["source_sha"] = owned.SOURCE_SHA
        self.layout.update({"source": str(source), "source_binding": binding})
        marker = self.root / "owner.json"
        marker.unlink()
        owned._json_write(marker, self.layout)
        environment = self.environment({"PYTHONPATH": str(self.parent / "old-venv")})
        self.assertEqual(environment["PYTHONPATH"], str(source / "src"))
        result = subprocess.run(
            [
                str(self.python),
                "-B",
                "-c",
                "import importlib.util;print(importlib.util.find_spec('lingshu_gate').origin)",
            ],
            env=environment,
            cwd=self.root,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), str(source / "src/lingshu_gate/__init__.py"))

    def test_inert_child_binds_current_source_ahead_of_actual_old_install(self) -> None:
        source, binding = self.fake_product()
        old = self.parent / "old-site-packages/lingshu_gate"
        old.mkdir(parents=True)
        (old / "__init__.py").write_text("raise RuntimeError('old installation must not execute')\n")
        script = (
            "import importlib.util,json,sys\n"
            "sys.path.insert(0,sys.argv[1]);import run_owned_e2e as owned\n"
            "sys.path.insert(0,sys.argv[2])\n"
            "assert importlib.util.find_spec('lingshu_gate').origin==sys.argv[2]+'/lingshu_gate/__init__.py'\n"
            "owned._bind_product_source(owned.Path(sys.argv[3]),json.loads(sys.argv[4]))\n"
            "assert importlib.util.find_spec('lingshu_gate').origin==sys.argv[3]+'/src/lingshu_gate/__init__.py'\n"
            "assert not any(name=='lingshu_gate' or name.startswith('lingshu_gate.') for name in sys.modules)\n"
            "print('current source bound; no product code imported')\n"
        )
        result = subprocess.run(
            [
                str(self.python),
                "-I",
                "-B",
                "-c",
                script,
                str(Path(__file__).parent),
                str(old.parent),
                str(source),
                json.dumps(binding),
            ],
            env=self.environment({}),
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "current source bound; no product code imported")

    def test_source_finder_ignores_old_venv_and_cached_bytecode_without_execution(self) -> None:
        source, binding = self.fake_product()
        package = source / "src/lingshu_gate"
        (package / "__pycache__").mkdir()
        (package / "__pycache__/main.pyc").write_bytes(b"stale bytecode")
        finder = owned.ReviewedProductFinder(source, binding)
        specification = finder.find_spec("lingshu_gate.main", [str(self.parent / "old-venv/lingshu_gate")])
        self.assertEqual(specification.origin, str(package / "main.py"))
        self.assertEqual(specification.loader.get_code("lingshu_gate.main").co_filename, str(package / "main.py"))
        with self.assertRaises(owned.BoundaryError):
            finder.find_spec("lingshu_gate.only_in_old_install", [str(self.parent / "old-venv/lingshu_gate")])
        self.assertNotIn("lingshu_gate", sys.modules)

    def test_changed_source_bytes_cannot_be_compiled_for_product(self) -> None:
        source, binding = self.fake_product()
        finder = owned.ReviewedProductFinder(source, binding)
        specification = finder.find_spec("lingshu_gate.main")
        (source / "src/lingshu_gate/main.py").write_text("raise RuntimeError('changed bytes')\n")
        with self.assertRaises(owned.BoundaryError):
            specification.loader.get_code("lingshu_gate.main")

    def test_actual_module_file_and_spec_must_both_match_source(self) -> None:
        source, binding = self.fake_product()
        path = str(source / "src/lingshu_gate/main.py")
        old = str(self.parent / "old-venv/lingshu_gate/main.py")
        for module in [
            SimpleNamespace(__file__=old, __spec__=SimpleNamespace(origin=path)),
            SimpleNamespace(__file__=path, __spec__=SimpleNamespace(origin=old)),
        ]:
            with self.subTest(module=module), patch.dict(sys.modules, {"lingshu_gate.main": module}):
                with self.assertRaises(owned.BoundaryError):
                    owned._check_loaded_product(source, binding)

    def test_git_blob_bytes_are_checked_even_when_status_says_clean(self) -> None:
        source, _ = self.fake_product()
        path = source / "src/lingshu_gate/main.py"
        reviewed = path.read_bytes()
        git_digest = hashlib.sha1(b"blob " + str(len(reviewed)).encode() + b"\0" + reviewed).hexdigest()
        record = b"100644 blob " + git_digest.encode() + b"\tsrc/lingshu_gate/main.py\0"
        path.write_text("raise RuntimeError('ignored dirty bytes')\n")
        with (
            patch.object(
                owned.subprocess,
                "check_output",
                side_effect=[
                    owned.SOURCE_SHA + "\n",
                    "",
                    owned.SOURCE_TREE + "\n" + owned.WEB_TREE + "\n",
                    record,
                ],
            ),
            self.assertRaises(owned.BoundaryError),
        ):
            owned._source_check(source)

    def test_old_ignored_static_trees_cannot_become_the_baseline(self) -> None:
        source = self.parent / "old-static"
        for directory, entry in [("console", "index.html"), ("oauth", "oauth.html")]:
            root = source / "src/lingshu_gate/static" / directory
            root.mkdir(parents=True)
            (root / entry).write_text("old installed UI")
        self.assertEqual(set(owned._inventory(source)), {"console", "oauth"})
        with self.assertRaises(owned.BoundaryError):
            owned._verified_static(source)

    def test_pinned_static_proof_cannot_be_replaced_by_a_new_baseline(self) -> None:
        with patch.object(owned, "STATIC_MANIFEST_SHA256", "0" * 64), self.assertRaises(owned.BoundaryError):
            owned._verified_static(self.parent)

    def test_each_static_directory_and_file_set_must_match_pinned_build(self) -> None:
        source_input = Path(os.environ.get("GATE_OWNED_STATIC_TEST_SOURCE", str(Path(__file__).resolve().parents[3])))
        owned._source_check(source_input)
        actual = source_input / "src/lingshu_gate/static"
        # Only copy immutable build inputs into this negative test's fresh root.
        # No Gate import, server or application state is needed.
        for label, relative, operation in [
            ("console-old", "console/index.html", "change"),
            ("oauth-old", "oauth/oauth.html", "change"),
            ("unexpected", "oauth/old-extra.js", "extra"),
            ("missing", "oauth/oauth.html", "remove"),
        ]:
            with self.subTest(case=label):
                source = self.parent / label
                static = source / "src/lingshu_gate/static"
                shutil.copytree(actual, static)
                owned._verified_static(source)
                path = static / relative
                if operation == "remove":
                    path.unlink()
                else:
                    path.write_text("old static bytes")
                with self.assertRaises(owned.BoundaryError):
                    owned._verified_static(source)

    def test_wrong_actual_console_or_oauth_route_directory_is_rejected(self) -> None:
        source, _ = self.fake_product()

        def endpoint_for(static):
            def endpoint():
                return static

            return endpoint

        expected = source / "src/lingshu_gate/static"
        meta = SimpleNamespace(STATIC_DIR=expected)
        app = SimpleNamespace(
            routes=[
                SimpleNamespace(path=path, endpoint=endpoint_for(expected / "oauth"))
                for path in ["/oauth/consent", "/oauth/assets/{asset_path:path}"]
            ]
        )
        with patch.dict(sys.modules, {"lingshu_gate.interfaces.control_api.meta_routes": meta}):
            owned._check_app_static_routes(app, source)
            app.routes[0].endpoint = endpoint_for(self.parent / "old-static/oauth")
            with self.assertRaises(owned.BoundaryError):
                owned._check_app_static_routes(app, source)
            meta.STATIC_DIR = self.parent / "old-static"
            with self.assertRaises(owned.BoundaryError):
                owned._check_app_static_routes(app, source)

    def test_wrong_served_console_bytes_or_enabled_oauth_blocks_acceptance(self) -> None:
        raw = b"reviewed synthetic static bytes"
        digest = hashlib.sha256(raw).hexdigest()
        inventory = {"console": {"index.html": digest}, "oauth": {"oauth.html": digest}}

        def approved_disabled(path):
            return (200, raw) if path == "/" else (404, b'{"error":"oauth_disabled"}')

        receipt = owned._check_served_inventory(inventory, approved_disabled)
        self.assertTrue(receipt["oauth_routes_disabled"])
        self.assertFalse(receipt["oauth_ui_served_bytes_verified"])
        with self.assertRaises(owned.BoundaryError):
            owned._check_served_inventory(inventory, lambda _: (200, b"old served UI"))
        with self.assertRaises(owned.BoundaryError):
            owned._check_served_inventory(inventory, lambda _: (200, raw))

    def test_served_verification_without_approval_starts_no_http_probe(self) -> None:
        with patch.object(owned, "_check_served_inventory") as probe, self.assertRaises(owned.BoundaryError):
            owned.verify_served(self.root)
        probe.assert_not_called()

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

    def test_closed_loopback_listener_requires_connection_refused(self) -> None:
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            listener.listen()
            self.assertFalse(owned.listener_closed(port))
        self.assertTrue(owned.listener_closed(port))

    def test_uncertain_connect_results_retain_owned_state(self) -> None:
        for result in [errno.ETIMEDOUT, errno.EHOSTUNREACH, errno.ENETUNREACH,
                       errno.EACCES, errno.EINTR, errno.EADDRNOTAVAIL]:
            layout = owned.new_layout(self.parent)
            root = Path(str(layout["root"]))
            with self.subTest(result=result), patch.object(socket.socket, "connect_ex", return_value=result):
                with self.assertRaises(owned.BoundaryError):
                    owned.remove_after_exit(layout, str(layout["token"]), [], [12345])
                self.assertTrue(root.exists())

    def test_connect_exception_retains_owned_state(self) -> None:
        with patch.object(socket.socket, "connect_ex", side_effect=OSError(errno.EACCES, "synthetic")):
            with self.assertRaises(owned.BoundaryError):
                owned.remove_after_exit(self.layout, str(self.layout["token"]), [], [12345])
        self.assertTrue(self.root.exists())

    def test_invalid_port_never_probes_or_removes(self) -> None:
        for port in [True, 0, 65536, "12345"]:
            with self.subTest(port=port), patch.object(socket.socket, "connect_ex") as probe:
                with self.assertRaises(owned.BoundaryError):
                    owned.remove_after_exit(self.layout, str(self.layout["token"]), [], [port])
                probe.assert_not_called()
                self.assertTrue(self.root.exists())

    def test_real_sigint_reaps_detached_listener_and_preserves_unowned_state(self) -> None:
        self.interrupted_owned_run(signal.SIGINT)

    def test_second_signal_is_deferred_while_execution_unwinds(self) -> None:
        receipt = {}
        guard = owned.OwnedRunSignals(receipt)
        with self.assertRaises(KeyboardInterrupt):
            guard.interrupt(signal.SIGINT, None)
        self.assertTrue(guard.cleaning)
        guard.interrupt(signal.SIGINT, None)
        self.assertTrue(receipt["signal_deferred_during_cleanup"])

    def test_second_sigint_during_reap_is_deferred(self) -> None:
        self.interrupted_owned_run(signal.SIGINT, repeat=True)

    def test_real_sigterm_reaps_detached_listener(self) -> None:
        self.interrupted_owned_run(signal.SIGTERM)

    def interrupted_owned_run(self, interruption: int, *, repeat: bool = False) -> None:
        """Real isolated manager, detached grandchild and listener; no Gate import."""
        libc = ctypes.CDLL(None, use_errno=True)
        previous = ctypes.c_int()
        self.assertEqual(libc.prctl(37, ctypes.byref(previous), 0, 0, 0), 0)
        self.assertEqual(libc.prctl(36, 1, 0, 0, 0), 0)
        sentinel = self.parent / "unowned-retained.txt"
        sentinel.write_text("must remain unchanged")
        ready = self.parent / "ready.private.json"
        cleaning = self.parent / "cleanup-entered"
        output = self.parent / "signal-result.private.json"
        child = self.parent / "listener.py"
        child.write_text(
            "import json,os,signal,socket,sys,time\n"
            "from pathlib import Path\n"
            "signal.signal(signal.SIGTERM,signal.SIG_IGN)\n"
            "s=socket.socket();s.bind(('127.0.0.1',0));s.listen()\n"
            "value={'endpoint':'http://127.0.0.1:'+str(s.getsockname()[1])+'/mcp'}\n"
            "Path(sys.argv[1]).write_text(json.dumps(value))\n"
            "Path(sys.argv[2]).write_text(json.dumps({'pid':os.getpid(),'port':s.getsockname()[1]}))\n"
            "time.sleep(30)\n"
        )
        manager = self.parent / "manager.py"
        manager.write_text(
            "import json,os,subprocess,sys,time\n"
            "from pathlib import Path\n"
            "sys.path.insert(0,sys.argv[1]);import run_owned_e2e as owned\n"
            "layout=owned.read_layout(Path(sys.argv[2]))\n"
            "source=Path(sys.argv[3]);cli=source/'web/node_modules/playwright/cli.js'\n"
            "cli.parent.mkdir(parents=True);cli.write_text(\n"
            "'import subprocess,sys,time\\nsubprocess.Popen([sys.executable,'+repr(sys.argv[4])+','\n"
            "+repr(str(Path(layout['fixture'])/'http-peer.json'))+','+repr(sys.argv[5])+'],start_new_session=True)\\ntime.sleep(30)\\n')\n"
            "layout.update({'source':str(source),'python':sys.executable,'node':sys.executable,'browsers':str(source), 'adapter_sha256':'real-signal-probe'})\n"
            "marker=Path(layout['root'])/'owner.json';marker.unlink();owned._json_write(marker,layout)\n"
            "owned._prepared_inputs=lambda layout:source\n"
            "owned.clean_environment=lambda *args,**kwargs:{'PATH':'/usr/bin:/bin','PYTHONUNBUFFERED':'1'}\n"
            "real_reap=owned.reap_owned\n"
            "def reap(known):\n"
            " Path(sys.argv[6]).write_text('cleanup entered')\n"
            " if sys.argv[8]=='repeat':time.sleep(0.5)\n"
            " return real_reap(known,grace_seconds=0.25)\n"
            "owned.reap_owned=reap\n"
            "value=owned.run(layout,{},fixture_scope_approved=True)\n"
            "Path(sys.argv[7]).write_text(json.dumps(value))\n"
        )
        known = {}
        identities = []
        process = None
        self.real_probe_receipt = {"listener_started": False, "interruption_sent": False}
        try:
            process = subprocess.Popen(
                [str(self.python), "-I", "-B", str(manager), str(Path(owned.__file__).parent),
                 str(self.root), str(self.parent / "inert-source"), str(child), str(ready),
                 str(cleaning), str(output), "repeat" if repeat else "once"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            )
            leader = owned.process_identity(process.pid)
            self.assertIsNotNone(leader)
            known[process.pid] = leader
            deadline = time.monotonic() + 5
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                owned.observe_owned(known, os.getpid())
                time.sleep(0.02)
            self.assertTrue(ready.exists(), "real listener did not become ready")
            owned.observe_owned(known, os.getpid())
            identities = list(known.values())
            port = json.loads(ready.read_text())["port"]
            self.assertFalse(owned.listener_closed(port))
            self.real_probe_receipt["listener_started"] = True
            os.kill(process.pid, interruption)
            self.real_probe_receipt["interruption_sent"] = True
            if repeat:
                deadline = time.monotonic() + 3
                while not cleaning.exists() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(cleaning.exists())
                os.kill(process.pid, signal.SIGINT)
            exit_code = process.wait(timeout=5)
            self.real_probe_receipt["manager_exit_code"] = exit_code
            self.assertEqual(exit_code, 0)
            result = json.loads(output.read_text())
            self.assertTrue(result["execution_interrupted"])
            self.assertEqual(result["command_exit_code"], 128 + interruption)
            self.assertTrue(result["owned_descendants_reaped"])
            self.assertTrue(result["two_listeners_closed"])
            self.assertEqual(result["temporary_persistent_state"], "destroyed_with_exact_owned_root")
            self.assertFalse(self.root.exists())
            self.assertTrue(owned.listener_closed(port))
            for identity in identities:
                self.assertIsNone(owned.process_identity(identity["pid"]))
            self.assertEqual(sentinel.read_text(), "must remain unchanged")
            if repeat:
                self.assertTrue(result["signal_deferred_during_cleanup"])
        finally:
            # Also closes the demonstrated pre-fix failure. This outer test
            # subreaper owns/adopts only this real manager's known descendants.
            owned.observe_owned(known, os.getpid())
            self.real_probe_receipt["outer_owned_reap_complete"] = owned.reap_owned(known, grace_seconds=0.25)
            self.real_probe_receipt["outer_owned_processes_gone"] = all(
                owned.process_identity(identity["pid"]) is None for identity in known.values()
            )
            self.real_probe_receipt["unowned_sentinel_preserved"] = sentinel.read_text() == "must remain unchanged"
            if process is not None:
                process.wait(timeout=3)
            libc.prctl(36, previous.value, 0, 0, 0)

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

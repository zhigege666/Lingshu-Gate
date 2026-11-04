"""Exercise native update selection using real archives and simulated GitHub evidence."""

import hashlib
import importlib.util
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = importlib.util.spec_from_file_location("extract_native", ROOT / "scripts/release/extract_native.py")
assert ARCHIVE and ARCHIVE.loader
extractor = importlib.util.module_from_spec(ARCHIVE)
ARCHIVE.loader.exec_module(extractor)

SPEC = importlib.util.spec_from_file_location("native_update", ROOT / "packaging/native/gate_native_update.py")
assert SPEC and SPEC.loader
updater = importlib.util.module_from_spec(SPEC)
with patch.dict(sys.modules, {"extract_native": extractor}):
    SPEC.loader.exec_module(updater)


class NativeReleaseUpdateTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.cache = self.base / ".native-updates"
        self.cache.mkdir()
        self.target = "linux-x86_64"
        self.original = "0.5.10"
        self.state = {"active": self.original}
        self.name = "lingshu-gate-v0.5.11-linux-x86_64"
        self.info = {"application": "Lingshu Gate", "target": self.target, "version": self.original}
        (self.base / "BUILD-INFO.json").write_text(json.dumps(self.info))
        (self.base / "data").mkdir()
        (self.base / "data" / "existing").write_text("keep")
        self.archive = io.BytesIO()
        with tarfile.open(mode="w:gz", fileobj=self.archive) as tar:
            root = tarfile.TarInfo(self.name)
            root.type = tarfile.DIRTYPE
            root.mode = 0o755
            tar.addfile(root)
            for name, data in {
                "start.sh": b"#!/bin/sh\n",
                "lingshu-gate": b"#!/bin/sh\necho 'lingshu-gate 0.5.11'\n",
                "BUILD-INFO.json": json.dumps({**self.info, "version": "0.5.11"}).encode(),
            }.items():
                member = tarfile.TarInfo(f"{self.name}/{name}")
                member.size = len(data)
                member.mode = 0o755
                tar.addfile(member, io.BytesIO(data))
        data = self.archive.getvalue()
        self.asset = {"id": 100, "name": self.name + ".tar.gz", "size": len(data),
                      "digest": "sha256:" + hashlib.sha256(data).hexdigest()}
        self.tag = "v0.5.11"
        self.attested = True
        self.checks = []
        self.records = [{"repository_id": 1351128499, "bundle": {"sigstore": "fixture"}}]
        self.timestamps = [{"verified": True}]
        self.bad_binary = False

    def response(self, path, *, binary=False):
        if path == "releases/latest":
            content = {"tag_name": self.tag, "draft": False, "prerelease": False, "assets": [self.asset]}
        elif path == "releases/assets/100" and binary:
            return io.BytesIO(self.archive.getvalue())
        elif path == "attestations/" + self.asset["digest"] + "?per_page=100":
            content = {"attestations": self.records}
        elif path == "commits/v0.5.11":
            content = {"sha": "a" * 40}
        else:
            self.fail(path)
        return io.BytesIO(json.dumps(content).encode())

    def install(self):
        run = subprocess.run

        def invoke(args, **kwargs):
            if args[0] != "gh":
                if self.bad_binary:
                    return subprocess.CompletedProcess(args, 0, "bad")
                return run(args, **kwargs)
            self.checks.append(args)
            self.assertIn("refs/tags/v0.5.11", args)
            self.assertIn("https://github.com/zhigege666/Lingshu-Gate/.github/workflows/release.yml@refs/tags/v0.5.11", args)
            self.assertIn("--deny-self-hosted-runners", args)
            self.assertEqual(args[args.index("--source-digest") + 1], "a" * 40)
            self.assertEqual(args[args.index("--signer-digest") + 1], "a" * 40)
            self.assertEqual(json.loads(Path(args[args.index("--bundle") + 1]).read_text()), self.records[0]["bundle"])
            if not self.attested:
                raise subprocess.CalledProcessError(1, args)
            return subprocess.CompletedProcess(args, 0, json.dumps([{"verificationResult": {"verifiedTimestamps": self.timestamps}}]))

        with patch.object(updater, "public_response", self.response), patch.object(
            updater.shutil, "which", return_value="gh"
        ), patch.object(updater.subprocess, "run", invoke):
            return updater.install(self.base, self.cache, self.state, self.target, self.original)

    @unittest.skipIf(os.name == "nt", "fixture binary is a POSIX executable")
    def test_install_and_rollback_reuse_the_original_payload_and_data(self):
        self.assertEqual(self.install(), "0.5.11")
        marker = self.cache / "active.json"
        self.assertEqual(json.loads(marker.read_text()), {"active": "0.5.11", "previous": "0.5.10"})
        self.assertEqual(len(self.checks), 1)
        updater.main(["rollback", "--install-dir", str(self.base)])
        self.state = json.loads(marker.read_text())
        self.assertEqual(self.state, {"active": "0.5.10", "skipped": "0.5.11"})
        self.assertEqual(self.install(), self.original)
        self.assertEqual(len(self.checks), 1)
        self.assertEqual((self.base / "data/existing").read_text(), "keep")

    def test_bad_digest_or_provenance_leaves_the_selected_release_untouched(self):
        self.attested = False
        with self.assertRaises(subprocess.CalledProcessError):
            self.install()
        self.asset["digest"] = "sha256:" + "0" * 64
        with self.assertRaisesRegex(ValueError, "mismatch"):
            self.install()
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_failed_candidate_version_probe_keeps_original_and_no_marker(self):
        self.bad_binary = True
        with self.assertRaisesRegex(ValueError, "expected Gate version"):
            self.install()
        self.assertFalse((self.cache / "active.json").exists())

    def test_starts_selected_package_with_flags_and_original_data(self):
        argv = ["start", "--install-dir", str(self.base), "--", "--port", "16900"]
        with patch.dict(os.environ, {}, clear=True), patch.object(updater.os, "execv") as launch:
            if os.name == "nt":
                with patch.object(updater.subprocess, "call", return_value=0) as child:
                    with self.assertRaises(SystemExit):
                        updater.main(argv)
                    child.assert_called_once_with([str(self.base / "lingshu-gate"), "--port", "16900"])
            else:
                updater.main(argv)
                program = str(self.base / "lingshu-gate")
                launch.assert_called_once_with(program, [program, "--port", "16900"])
            self.assertEqual(os.environ["LINGSHU_GATE_DATA_DIR"], str(self.base / "data"))

    def test_missing_timestamp_or_wrong_repository_is_rejected(self):
        self.timestamps = []
        with self.assertRaisesRegex(ValueError, "timestamp"):
            self.install()
        self.records[0]["repository_id"] = 0
        with self.assertRaisesRegex(ValueError, "provenance bundle"):
            self.install()
        self.assertEqual(list(self.cache.iterdir()), [])

    def test_redirect_to_untrusted_host_is_rejected_before_download(self):
        policy = updater.PublicRedirect()
        for url in ["http://api.github.com/path", "https://api.github.com.example.org", "https://127.0.0.1/"]:
            with self.assertRaisesRegex(ValueError, "redirect"):
                policy.redirect_request(None, None, 302, "", {}, url)

    def test_old_or_current_release_skips_download_and_downgrade(self):
        self.tag = "v0.5.9"
        self.assertEqual(self.install(), self.original)
        self.assertEqual(self.checks, [])


if __name__ == "__main__":
    unittest.main()

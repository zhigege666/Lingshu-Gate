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
        self.asset = {"name": self.name + ".tar.gz", "size": len(data),
                      "digest": "sha256:" + hashlib.sha256(data).hexdigest()}
        self.tag = "v0.5.11"
        self.attested = True
        self.checks = []

    def gh(self, *args):
        if args[0] == "api":
            return json.dumps({"tag_name": self.tag, "draft": False, "prerelease": False, "assets": [self.asset]})
        if args[:2] == ("release", "download"):
            (Path(args[-1]) / self.asset["name"]).write_bytes(self.archive.getvalue())
            return ""
        self.checks.append(args)
        self.assertIn("refs/tags/v0.5.11", args)
        self.assertIn("https://github.com/zhigege666/Lingshu-Gate/.github/workflows/release.yml@refs/tags/v0.5.11", args)
        self.assertIn("--deny-self-hosted-runners", args)
        if not self.attested:
            raise subprocess.CalledProcessError(1, ["gh", "attestation", "verify"])
        return ""

    def install(self):
        with patch.object(updater, "github", self.gh):
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
        with patch.object(updater.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "bad")):
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

    def test_old_or_current_release_skips_download_and_downgrade(self):
        self.tag = "v0.5.9"
        self.assertEqual(self.install(), self.original)
        self.assertEqual(self.checks, [])


if __name__ == "__main__":
    unittest.main()

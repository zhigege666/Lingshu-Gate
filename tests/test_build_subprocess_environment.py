"""构建子进程环境隔离测试。"""

from __future__ import annotations

import os
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from lingshu_gate.build_deploy import SUBPROCESS_ENV_PASSTHROUGH, _build_subprocess_environment, _run_command


class BuildSubprocessEnvironmentTest(unittest.TestCase):
    def test_environment_is_allowlisted_and_uses_build_local_directories(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir, patch.dict(
            os.environ,
            {
                "PATH": "C:\\runtime-bin",
                "SYSTEMROOT": "C:\\Windows",
                "SECRET_TOKEN": "must-not-leak",
                "HTTP_PROXY": "http://must-not-leak",
                "npm_config_registry": "https://must-not-leak",
            },
            clear=True,
        ):
            build_dir = Path(temporary_dir) / "build-a"
            environment = _build_subprocess_environment(build_dir)

            self.assertEqual(environment["PATH"], "C:\\runtime-bin")
            self.assertEqual(environment["SYSTEMROOT"], "C:\\Windows")
            self.assertNotIn("SECRET_TOKEN", environment)
            self.assertNotIn("HTTP_PROXY", environment)
            self.assertNotIn("npm_config_registry", environment)
            self.assertTrue(
                set(environment).issuperset(
                    {
                        "HOME",
                        "TMP",
                        "TEMP",
                        "TMPDIR",
                        "npm_config_cache",
                        "NPM_CONFIG_USERCONFIG",
                        "NPM_CONFIG_GLOBALCONFIG",
                        "NPM_CONFIG_AUDIT",
                        "NPM_CONFIG_FUND",
                        "NPM_CONFIG_UPDATE_NOTIFIER",
                        "PIP_CACHE_DIR",
                        "PIP_NO_INPUT",
                        "PIP_DISABLE_PIP_VERSION_CHECK",
                        "PYTHONPYCACHEPREFIX",
                    }
                )
            )
            self.assertEqual(environment["NPM_CONFIG_AUDIT"], "false")
            self.assertEqual(environment["NPM_CONFIG_FUND"], "false")
            self.assertEqual(environment["NPM_CONFIG_UPDATE_NOTIFIER"], "false")
            self.assertEqual(environment["PIP_NO_INPUT"], "1")
            self.assertEqual(environment["PIP_DISABLE_PIP_VERSION_CHECK"], "1")
            self.assertNotEqual(
                environment["NPM_CONFIG_USERCONFIG"],
                environment["NPM_CONFIG_GLOBALCONFIG"],
            )
            for config_name in ("NPM_CONFIG_USERCONFIG", "NPM_CONFIG_GLOBALCONFIG"):
                npmrc = Path(environment[config_name])
                self.assertTrue(npmrc.is_file())
                self.assertEqual(npmrc.read_text(encoding="utf-8"), "")
                self.assertTrue(npmrc.is_relative_to(build_dir))
            self.assertTrue(set(environment).intersection(SUBPROCESS_ENV_PASSTHROUGH).issubset(SUBPROCESS_ENV_PASSTHROUGH))
            for name in ("HOME", "TMP", "TMPDIR", "npm_config_cache", "PIP_CACHE_DIR", "PYTHONPYCACHEPREFIX"):
                location = Path(environment[name])
                self.assertTrue(location.is_dir(), name)
                self.assertTrue(location.is_relative_to(build_dir), name)

    def test_each_build_gets_distinct_home_and_cache_roots(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            first = _build_subprocess_environment(root / "build-a")
            second = _build_subprocess_environment(root / "build-b")

            for name in ("HOME", "TMP", "npm_config_cache", "PIP_CACHE_DIR", "PYTHONPYCACHEPREFIX"):
                self.assertNotEqual(first[name], second[name], name)

    @patch("lingshu_gate.build_deploy.subprocess.Popen")
    def test_command_passes_isolated_environment_to_subprocess(self, popen) -> None:
        process = popen.return_value
        process.pid = 1234
        process.returncode = 0
        process.stdout = io.BytesIO(b"ok")
        process.stderr = io.BytesIO(b"")
        process.poll.return_value = 0
        with tempfile.TemporaryDirectory() as temporary_dir:
            root = Path(temporary_dir)
            environment = _build_subprocess_environment(root / "build-a")
            result = _run_command(["node", "--version"], root, 10, environment)

        self.assertEqual(result["returncode"], 0)
        self.assertIs(popen.call_args.kwargs["env"], environment)
        self.assertEqual(popen.call_args.kwargs["cwd"], str(root))
        self.assertFalse(popen.call_args.kwargs["text"])
        if os.name == "nt":
            self.assertIn("creationflags", popen.call_args.kwargs)
        else:
            self.assertTrue(popen.call_args.kwargs["start_new_session"])


if __name__ == "__main__":
    unittest.main()

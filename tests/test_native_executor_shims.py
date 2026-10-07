"""Execute only Gate's fixed launchers, with mocked exec; no project code."""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

from lingshu_gate.adapters.native_executor.shims import PROGRAMS, install_shims, shim_source


class Executed(Exception):
    pass


@pytest.mark.parametrize("manager,program,cli", [("npm", "npm", "bin/npm-cli.js"), ("pnpm", "pnpm", "bin/pnpm.cjs"), ("yarn", "yarn", "bin/yarn.js"), ("yarn", "yarnpkg", "bin/yarn.js")])
def test_nested_manager_calls_bind_absolute_verified_node_and_cli(manager, program, cli):
    with patch.object(sys, "argv", ["/tool/shims/" + program, "run", "clean"]), patch("os.execve", side_effect=Executed) as execute, pytest.raises(Executed):
        exec(shim_source(manager), {"__name__": "__main__"})
    assert execute.call_args.args[:2] == ("/usr/local/bin/node", ["/usr/local/bin/node", "/tool/package/" + cli, "run", "clean"])
    assert execute.call_args.args[2]["npm_config_offline"] == "true"


@pytest.mark.parametrize("program", ["pnpm", "yarn", "corepack"])
def test_unselected_image_global_manager_has_a_fixed_denial_shim(program):
    with patch.object(sys, "argv", ["/tool/shims/" + program, "--version"]), patch("os.execve") as execute, pytest.raises(SystemExit, match="does not provide"):
        exec(shim_source("npm"), {"__name__": "__main__"})
    execute.assert_not_called()


@pytest.mark.parametrize("arguments", [["missing-package"], ["--package=missing", "tool"], ["--yes", "missing"], ["../outside"]])
def test_npx_never_acquires_or_installs_missing_packages(tmp_path, arguments):
    source = shim_source("npm").replace('Path("/work/project")', "Path(" + repr(str(tmp_path)) + ")")
    with patch.object(sys, "argv", ["/tool/shims/npx", *arguments]), patch("os.execve") as execute, patch("pathlib.Path.cwd", return_value=tmp_path), pytest.raises(SystemExit):
        exec(source, {"__name__": "__main__"})
    execute.assert_not_called()


def test_npx_executes_only_existing_contained_binary(tmp_path):
    directory = tmp_path / "node_modules" / ".bin"
    directory.mkdir(parents=True)
    binary = directory / "fixture"
    binary.write_text("fixture bytes, never executed")
    binary.chmod(0o755)
    source = shim_source("npm").replace('Path("/work/project")', "Path(" + repr(str(tmp_path)) + ")")
    with patch.object(sys, "argv", ["/tool/shims/npx", "--no-install", "fixture", "literal argument"]), patch("pathlib.Path.cwd", return_value=tmp_path), patch("os.execve", side_effect=Executed) as execute, pytest.raises(Executed):
        exec(source, {"__name__": "__main__"})
    assert execute.call_args.args[:2] == (str(binary), [str(binary), "literal argument"])


def test_shims_are_readonly_content_and_cover_all_image_manager_names(tmp_path):
    install_shims(tmp_path, "npm")
    assert set(path.name for path in (tmp_path / "shims").iterdir()) == set(PROGRAMS)
    assert all(not path.stat().st_mode & 0o222 for path in (tmp_path / "shims").iterdir())
    assert not os.stat(tmp_path / "shims").st_mode & 0o222

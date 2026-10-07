"""Gate-owned, read-only manager launchers; no image-global CLI fallback."""
from __future__ import annotations

from pathlib import Path

SHIM_REVISION = 1
PROGRAMS = ("npm", "npx", "pnpm", "pnpx", "yarn", "yarnpkg", "corepack")
CLI = {"npm": "bin/npm-cli.js", "pnpm": "bin/pnpm.cjs", "yarn": "bin/yarn.js"}


def shim_source(manager: str) -> str:
    if manager not in CLI:
        raise ValueError("package_manager_shim_unsupported")
    return '''#!/usr/bin/python3
import os
import re
import sys
from pathlib import Path

manager = ''' + repr(manager) + '''
cli = ''' + repr("/tool/package/" + CLI[manager]) + '''
node = "/usr/local/bin/node"
name = Path(sys.argv[0]).name
arguments = sys.argv[1:]
environment = dict(os.environ)
environment.update({"npm_config_offline":"true", "npm_config_yes":"false", "COREPACK_ENABLE_NETWORK":"0", "COREPACK_ENABLE_AUTO_PIN":"0", "YARN_ENABLE_NETWORK":"0", "YARN_IGNORE_PATH":"1"})
if name == manager or manager == "yarn" and name == "yarnpkg":
    os.execve(node, [node, cli, *arguments], environment)
if (manager, name) not in {("npm", "npx"), ("pnpm", "pnpx")}:
    sys.exit("Selected toolchain does not provide this manager command")
if arguments == ["--version"]:
    os.execve(node, [node, cli, "--version"], environment)
while arguments and arguments[0] in {"--no-install", "--offline", "--"}:
    arguments.pop(0)
if not arguments or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", arguments[0]):
    sys.exit("Only an existing project binary is permitted; package acquisition is disabled")
project = Path("/work/project")
current = Path.cwd().resolve()
if not current.is_relative_to(project):
    sys.exit("Existing binary execution requires the isolated project directory")
for directory in (current, *current.parents):
    if not directory.is_relative_to(project):
        break
    candidate = directory / "node_modules" / ".bin" / arguments[0]
    if candidate.is_file() and candidate.resolve().is_relative_to(project) and os.access(candidate, os.X_OK):
        os.execve(str(candidate), [str(candidate), *arguments[1:]], environment)
sys.exit("Project binary is unavailable; no download or automatic install is permitted")
'''


def install_shims(root: Path, manager: str) -> None:
    directory = root / "shims"
    directory.mkdir(mode=0o700)
    source = shim_source(manager)
    for name in PROGRAMS:
        target = directory / name
        target.write_text(source)
        target.chmod(0o555)
    directory.chmod(0o555)

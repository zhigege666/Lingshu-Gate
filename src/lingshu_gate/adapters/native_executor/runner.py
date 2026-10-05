"""Fixed entrypoint inside the digest-pinned image (stdlib only).

This file never runs on the Gate host. No socket, proxy or secret is supplied.
"""
from __future__ import annotations

import json
import ctypes
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path("/work")
TOOL_BINS = {"npm": "bin/npm-cli.js", "pnpm": "bin/pnpm.cjs", "yarn": "bin/yarn.js"}


def protect_runner() -> None:
    # Same-UID project children must not ptrace PID 1 or write its /proc fds
    # to manufacture a successful exit. Capabilities are independently absent.
    if ctypes.CDLL(None, use_errno=True).prctl(4, 0, 0, 0, 0) != 0:
        raise ValueError("runner_dumpability_control_failed")


def environment() -> dict[str, str]:
    return {"PATH": "/tool/shims:/work/project/node_modules/.bin:/usr/local/bin:/usr/bin:/bin", "HOME": "/tmp/gate-home", "LANG": "C.UTF-8", "CI": "true", "COREPACK_ENABLE_NETWORK": "0", "COREPACK_ENABLE_AUTO_PIN": "0", "npm_config_cache": "/work/cache", "npm_config_offline": "true", "npm_config_audit": "false", "npm_config_fund": "false", "npm_config_update_notifier": "false", "npm_config_userconfig": "/dev/null", "npm_config_globalconfig": "/dev/null", "npm_config_registry": "https://registry.npmjs.org/", "npm_config_manage_package_manager_versions": "false", "npm_config_package_manager_strict": "false", "npm_config_package_manager_strict_version": "false", "npm_config_use_node_version": "", "YARN_IGNORE_PATH": "1", "YARN_ENABLE_NETWORK": "0", "NODE_OPTIONS": "", "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_TERMINAL_PROMPT": "0", "GIT_NO_REPLACE_OBJECTS": "1", "GIT_LFS_SKIP_SMUDGE": "1"}


def execute(argv: list[str], *, cwd: Path = ROOT, output: Path | None = None, input_path: Path | None = None) -> int:
    # Engine disables logs; stdout/stderr never enter Gate/journal. The only
    # output file option is used by trusted raw-object decoding below.
    with (output.open("wb") if output else open(os.devnull, "wb")) as writer:
        if input_path:
            with input_path.open("rb") as reader:
                return subprocess.run(argv, cwd=cwd, stdin=reader, stdout=writer, stderr=subprocess.DEVNULL, env=environment(), check=False).returncode
        return subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=writer, stderr=subprocess.DEVNULL, env=environment(), check=False).returncode


def probe(argv: list[str], maximum: int = 128) -> str:
    result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, env=environment(), timeout=5, check=True)
    if len(result.stdout) > maximum:
        raise ValueError("probe_output_limit")
    return result.stdout.decode().strip().removeprefix("v")


def git_command(*args: str) -> list[str]:
    policy = {"protocol.allow": "never", "core.hooksPath": "/dev/null", "credential.helper": "", "core.fsmonitor": "false", "init.templateDir": "", "http.sslVerify": "true", "http.followRedirects": "false", "submodule.recurse": "false", "fetch.recurseSubmodules": "false", "filter.lfs.required": "false", "filter.lfs.smudge": "", "filter.lfs.process": "", "core.attributesFile": "/dev/null", "core.useReplaceRefs": "false", "fetch.fsckObjects": "true", "transfer.fsckObjects": "true"}
    argv = ["/usr/bin/git"]
    for key, value in policy.items():
        argv += ["-c", key + "=" + value]
    return [*argv, *args]


def git_decode(request: dict) -> dict:
    commit = request["commit_sha"]
    if len(commit) != 40 or any(ch not in "0123456789abcdef" for ch in commit):
        raise ValueError("invalid_commit")
    os.environ.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_TERMINAL_PROMPT": "0", "GIT_NO_REPLACE_OBJECTS": "1", "GIT_LFS_SKIP_SMUDGE": "1"})
    # execute's sanitized env includes no inherited Git environment. Explicit
    # command configuration disables all potentially executable hooks/config.
    repo = ROOT / "repo.git"
    if execute(git_command("init", "--bare", "--object-format=sha1", str(repo))):
        raise ValueError("git_init_failed")
    base = ["--git-dir=" + str(repo)]
    (repo / "shallow").write_text(commit + "\n")
    if execute(git_command(*base, "index-pack", "--stdin", "--fix-thin", "--strict"), input_path=Path("/pack/pack.bin")):
        raise ValueError("git_pack_rejected")
    if probe(git_command(*base, "cat-file", "-t", commit)) != "commit":
        raise ValueError("git_commit_type_mismatch")
    if execute(git_command(*base, "fsck", "--strict", "--no-reflogs")):
        raise ValueError("git_fsck_rejected")
    listing = ROOT / "objects.list"
    if execute(git_command(*base, "cat-file", "--batch-all-objects", "--batch-check=%(objectname) %(objecttype) %(objectsize)"), output=listing):
        raise ValueError("git_object_list_failed")
    if listing.stat().st_size > 1024 * 1024:
        raise ValueError("git_object_count_limit")
    objects = ROOT / "objects"
    objects.mkdir()
    count = total = 0
    for line in listing.read_text().splitlines():
        oid, kind, size = line.split(" ")
        count += 1
        total += int(size)
        if count > 10000 or total > 216 * 1024 * 1024 or kind not in {"commit", "tree", "blob", "tag"} or len(oid) != 40 or any(ch not in "0123456789abcdef" for ch in oid):
            raise ValueError("git_object_limit")
        if execute(git_command(*base, "cat-file", kind, oid), output=objects / oid):
            raise ValueError("git_object_export_failed")
        if (objects / oid).stat().st_size != int(size):
            raise ValueError("git_object_size_changed")
    shutil.rmtree(repo)
    return {"returncode": 0, "object_format": "sha1", "commit_sha": commit}


def selftest() -> dict:
    checks = []
    if ctypes.CDLL(None, use_errno=True).prctl(3, 0, 0, 0, 0) == 0:
        checks.append("runner_nondumpable")
    host = json.loads(Path("/request.json").read_text()).get("host_namespaces", {})
    names = {key: os.readlink("/proc/self/ns/" + key) for key in ("user", "mnt", "pid", "net")}
    if all(host.get(key) and names[key] != host[key] for key in names):
        checks.append("namespaces_distinct")
    if len(Path("/proc/net/route").read_text().splitlines()) == 1 and set(os.listdir("/sys/class/net")) == {"lo"}:
        checks.append("network_disconnected")
    mounts = [line.split() for line in Path("/proc/self/mountinfo").read_text().splitlines()]
    root_ro = any(fields[4] == "/" and "ro" in fields[5].split(",") for fields in mounts)
    tools_ro = all(any(fields[4] == target and "ro" in fields[5].split(",") for fields in mounts) for target in ("/gate-runner.py", "/request.json", "/sys/fs/cgroup"))
    if root_ro and tools_ro:
        checks.append("root_readonly")
    status = Path("/proc/self/status").read_text()
    if "NoNewPrivs:\t1" in status:
        checks.append("no_new_privileges")
    if "CapEff:\t0000000000000000" in status:
        checks.append("capabilities_dropped")
    cgroup = Path("/sys/fs/cgroup")
    memory = (cgroup / "memory.max").read_text().strip()
    pids = (cgroup / "pids.max").read_text().strip()
    cpu = (cgroup / "cpu.max").read_text().split()
    if memory == "1073741824" and pids == "128" and len(cpu) == 2 and cpu[0] != "max" and int(cpu[0]) <= int(cpu[1]):
        checks.append("controller_limits")
    # Leave an independent descendant alive. The controller must kill the
    # entire sandbox and observe populated=0 before accepting this evidence.
    subprocess.Popen(["/usr/bin/python3", "-c", "import time; time.sleep(60)"], start_new_session=True, env=environment(), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"returncode": 0, "report": {"checks": checks, "node_version": probe(["/usr/local/bin/node", "--version"]), "git_version": probe(["/usr/bin/git", "--version"])}}


def tool_probe(request: dict) -> dict:
    name = request["manager"]
    if name not in TOOL_BINS:
        raise ValueError("manager_unsupported")
    return {"returncode": 0, "node_version": probe(["/usr/local/bin/node", "--version"]), "package_manager_version": probe(["/usr/local/bin/node", "/tool/package/" + TOOL_BINS[name], "--version"])}


def seed_npm() -> dict:
    (ROOT / "cache").mkdir()
    # cacache is part of the SRI-verified official npm distribution. Seed only
    # verified tarballs, without parsing or executing project/package scripts.
    code = "const fs=require('fs');const c=require('/tool/package/node_modules/cacache');(async()=>{for(const x of JSON.parse(fs.readFileSync('/dependencies/index.json','utf8'))){await c.put('/work/cache/_cacache','gate:'+x.integrity,fs.readFileSync('/dependencies/'+x.file),{integrity:x.integrity});}})().catch(()=>process.exit(1));"
    return {"returncode": execute(["/usr/local/bin/node", "-e", code])}


def command(request: dict) -> dict:
    name = request["manager"]
    argv = request["command"]
    if name not in TOOL_BINS or argv not in [[name, "run", "build"], ["npm", "ci"]]:
        raise ValueError("command_not_generated")
    project = ROOT / "project"
    shutil.copytree("/input", project, symlinks=True)
    if Path("/cache").exists():
        shutil.copytree("/cache", ROOT / "cache")
        for path in (ROOT / "cache").rglob("*"):
            if not path.is_symlink():
                path.chmod(0o700 if path.is_dir() else 0o600)
        (ROOT / "cache").chmod(0o700)
    # Review/override cannot activate an unplanned different package manager.
    executable = ["/usr/local/bin/node", "/tool/package/" + TOOL_BINS[name]]
    args = ["ci", "--offline", "--no-audit", "--no-fund", "--cache=/work/cache"] if argv == ["npm", "ci"] else ["run", "build"]
    result = tool_probe(request)
    if result["package_manager_version"] != request["version"]:
        raise ValueError("tool_version_mismatch")
    result["returncode"] = execute([*executable, *args], cwd=project)
    return result


def main() -> None:
    request = json.loads(Path(sys.argv[1]).read_text())
    kind = request["kind"]
    try:
        protect_runner()
        if kind != "selftest":
            deadline = time.monotonic() + 10
            while not Path("/gate-control/admitted").is_file():
                if time.monotonic() >= deadline:
                    raise ValueError("runner_admission_timeout")
                time.sleep(0.02)
        result = selftest() if kind == "selftest" else git_decode(request) if kind == "git" else tool_probe(request) if kind == "tool_probe" else seed_npm() if kind == "npm_seed" else command(request) if kind == "command" else {"returncode": 1}
    except Exception:
        result = {"returncode": 1}
    (ROOT / "result.json").write_text(json.dumps(result))
    if kind != "selftest":
        status = result["returncode"]
        sys.exit(status if type(status) is int and 0 <= status <= 255 else 1)
    # Selftest deliberately leaves a descendant for whole-group stop evidence.
    time.sleep(60)
    sys.exit(result["returncode"])


if __name__ == "__main__":
    main()

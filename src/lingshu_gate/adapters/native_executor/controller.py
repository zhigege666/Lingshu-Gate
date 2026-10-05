"""Fixed local rootless Podman operations; never a host command fallback."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable, NoReturn, Iterator
from uuid import uuid4

from lingshu_gate.adapters.native_executor.journal import JobJournal
from lingshu_gate.native_executor_config import NativeExecutorConfig
from lingshu_gate.ports.safe_network_executor import PHASE_CHECKS, ROOTLESS_CHECKS, ExecutorReadiness, SafeExecutionCancelled
from lingshu_gate.registry import ToolExecutionError
from lingshu_gate.safe_files import open_regular_file

CID = re.compile(r"^[0-9a-f]{64}$")
MEMORY = 1024 * 1024 * 1024
PIDS = 128
MAX_WORKSPACE = 2 * 1024 * 1024 * 1024


def reject(code: str, message: str) -> NoReturn:
    raise ToolExecutionError(code, message, next_action="Review Native executor provisioning; host execution and automatic replay are prohibited.")


def secure_directory(path: Path) -> None:
    info = path.lstat()
    if path.resolve() != path or not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        reject("executor_directory_unsafe", "Executor directories require owned, non-linked mode 0700 provisioning")


def _bounded_paths(root: Path) -> Iterator[Path]:
    count = 0
    for path in root.rglob("*"):
        count += 1
        if count > 30000:
            reject("executor_content_limit", "Content inventory exceeds its entry limit")
        yield path


def read_regular_result(path: Path, *, maximum: int = 8192) -> dict[str, Any]:
    """Open untrusted output without following links or blocking on a FIFO."""
    deadline = time.monotonic() + 1
    try:
        with open_regular_file(path, maximum=maximum) as (reader, info):
            content = bytearray()
            while True:
                if time.monotonic() >= deadline:
                    raise ValueError
                chunk = reader.read(min(4096, maximum + 1 - len(content)))
                if not chunk:
                    break
                content.extend(chunk)
                if len(content) > maximum:
                    raise ValueError
            if len(content) != info.st_size:
                raise ValueError
        value = json.loads(content)
        if not isinstance(value, dict) or time.monotonic() >= deadline:
            raise ValueError
        return value
    except (OSError, ValueError, RecursionError):
        reject("executor_result_rejected", "Frozen phase result is not an unchanged bounded regular JSON file")


class PodmanController:
    def __init__(self, config: NativeExecutorConfig) -> None:
        self.config = config
        self.root = config.root or Path("/nonexistent")
        self.workspaces = self.root / "workspaces"
        self.journal: JobJournal | None = None
        self._gate = threading.BoundedSemaphore(1)
        self._stop = threading.Event()
        self._active: set[str] = set()
        self._mutex = threading.RLock()
        self.evidence = ExecutorReadiness("linux_rootless_oci", sys.platform)
        self.missing: list[str] = ["executor_not_started"]
        self.node_version = ""

    def _cli(self, arguments: list[str], *, timeout: float = 10, allow_failure: bool = False) -> bytes:
        import pwd
        account = pwd.getpwuid(os.getuid())
        environment = {"PATH": "/usr/bin:/bin", "HOME": account.pw_dir, "XDG_RUNTIME_DIR": f"/run/user/{os.getuid()}", "LANG": "C.UTF-8"}
        # A private bounded file avoids pipe deadlocks/unbounded capture of an
        # engine's output. Only structural CLI results cross this boundary.
        with (self.root / "cli-output").open("w+b") as output:
            process = subprocess.Popen([self.config.podman_bin, "--remote=false", *arguments], stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.DEVNULL, env=environment, cwd=self.root, close_fds=True)
            try:
                deadline = time.monotonic() + timeout
                while process.poll() is None:
                    if output.tell() > 256 * 1024 or time.monotonic() >= deadline:
                        process.kill()
                        process.wait()
                        raise TimeoutError("executor_engine_response_limit")
                    time.sleep(0.02)
                if process.returncode and not allow_failure:
                    reject("executor_engine_failed", "Fixed Podman operation failed; engine output withheld")
                output.seek(0)
                data = output.read(256 * 1024 + 1)
                if len(data) > 256 * 1024:
                    reject("executor_engine_response_limit", "Engine structural output exceeded the byte limit")
                if process.returncode:
                    return b""
                return data
            except BaseException:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                raise

    def inspect(self, name: str) -> dict[str, Any] | None:
        content = self._cli(["container", "inspect", name], allow_failure=True)
        if not content:
            # Distinguish "not found" from a broken engine before inferring
            # absence. info failure cannot establish resource termination.
            self._cli(["info", "--format=json"])
            containers = json.loads(self._cli(["ps", "--all", "--format=json", "--filter=name=^" + name + "$"]))
            if containers:
                raise InterruptedError("executor_container_status_unknown")
            return None
        value = json.loads(content)
        if not isinstance(value, list) or len(value) != 1 or not CID.fullmatch(value[0].get("Id", "")):
            raise InterruptedError("executor_container_status_unknown")
        return value[0]

    @staticmethod
    def _cgroup(pid: int) -> str:
        content = Path(f"/proc/{pid}/cgroup").read_text()
        entries = [line[3:] for line in content.splitlines() if line.startswith("0::")]
        if len(entries) != 1 or entries[0] == "/" or ".." in Path(entries[0]).parts:
            reject("executor_cgroup_unverified", "A dedicated sandbox cgroup could not be observed")
        return entries[0]

    @staticmethod
    def _empty(cgroup: str | None) -> bool:
        if not cgroup or cgroup == "/" or not cgroup.startswith("/") or ".." in Path(cgroup).parts:
            return False
        path = Path("/sys/fs/cgroup") / cgroup.lstrip("/") / "cgroup.events"
        try:
            return "populated 0" in path.read_text().splitlines()
        except FileNotFoundError:
            return not path.parent.exists()
        except OSError:
            return False

    def terminate(self, name: str, cgroup: str | None) -> None:
        info = self.inspect(name)
        if info is not None and not cgroup and info.get("State", {}).get("Pid"):
            cgroup = self._cgroup(int(info["State"]["Pid"]))
        if info is not None and info.get("State", {}).get("Running"):
            self._cli(["kill", "--signal=KILL", info["Id"]])
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            info = self.inspect(name)
            if (info is None or not info.get("State", {}).get("Running")) and self._empty(cgroup):
                if info:
                    self._cli(["rm", info["Id"]])
                return
            time.sleep(0.05)
        raise InterruptedError("executor_whole_group_termination_unknown")

    def _quota(self) -> bool:
        # Require a separately provisioned bounded tmpfs, not an unbounded
        # writable host directory or an optimistic free-space check.
        for line in Path("/proc/self/mountinfo").read_text().splitlines():
            fields = line.split()
            if fields[4] == str(self.workspaces) and " - tmpfs " in line:
                info = os.statvfs(self.workspaces)
                return 0 < info.f_blocks * info.f_frsize <= MAX_WORKSPACE and "nosuid" in fields[5] and "nodev" in fields[5]
        return False

    def start(self) -> None:
        self.missing = []
        if sys.platform != "linux":
            self.missing.append("unsupported_platform_linux_required")
            return
        if os.getuid() == 0:
            self.missing.append("rootless_user_required")
        try:
            secure_directory(self.root)
            secure_directory(self.workspaces)
        except (OSError, ToolExecutionError):
            self.missing.append("executor_owned_directories_missing_or_unsafe")
            return
        binary = Path(self.config.podman_bin)
        try:
            info = binary.stat()
            if not binary.is_file() or not os.access(binary, os.X_OK) or info.st_mode & 0o022:
                raise OSError
        except OSError:
            self.missing.append("podman_binary_missing_or_unsafe")
            return
        if not self._quota():
            self.missing.append("bounded_tmpfs_workspace_required")
        if self.missing:
            return
        try:
            self.journal = JobJournal(self.root)
            raw = json.loads(self._cli(["info", "--format=json"]))
            host = raw.get("host", {})
            if not host.get("security", {}).get("rootless"):
                self.missing.append("rootless_engine_required")
            if host.get("cgroupVersion") != "v2":
                self.missing.append("cgroup_v2_required")
            for required in ("cpu", "memory", "pids"):
                if required not in set(host.get("cgroupControllers", [])):
                    self.missing.append("delegated_cgroup_controller_" + required + "_required")
            image_content = self._cli(["image", "inspect", self.config.image], allow_failure=True)
            images = json.loads(image_content) if image_content else []
            if not isinstance(images, list) or not images or self.config.image not in images[0].get("RepoDigests", []):
                self.missing.append("preloaded_exact_image_digest_required")
            if self.missing:
                return
            self.reconcile()
            namespaces = {name: os.readlink("/proc/self/ns/" + name) for name in ("user", "mnt", "pid", "net")}
            report = self.run("readiness:" + uuid4().hex, {"kind": "selftest", "host_namespaces": namespaces}, timeout=10, cancelled=lambda: False, readiness=True)
            observed = report.get("report", {})
            expected = {"network_disconnected", "namespaces_distinct", "root_readonly", "no_new_privileges", "capabilities_dropped", "controller_limits", "runner_nondumpable"}
            for absent in sorted(expected - set(observed.get("checks", []))):
                self.missing.append("sandbox_selftest_" + absent + "_required")
            if not re.fullmatch(r"\d+\.\d+\.\d+", observed.get("node_version", "")):
                self.missing.append("sandbox_selftest_node_version_required")
            if not self.missing:
                self.node_version = observed["node_version"]
                checks = ROOTLESS_CHECKS | PHASE_CHECKS["git_acquisition"] | PHASE_CHECKS["offline_build"]
                self.evidence = ExecutorReadiness("linux_rootless_oci", "linux", checks)
            self.release_output(report)
        except ToolExecutionError as error:
            self.missing.append(error.code)
        except InterruptedError:
            self.missing.append("executor_reconciliation_or_termination_unknown")
        except TimeoutError:
            self.missing.append("executor_engine_or_selftest_timeout")
        except (OSError, ValueError):
            self.missing.append("engine_image_or_reconciliation_failed")

    def readiness(self) -> dict[str, Any]:
        missing = sorted(set(self.missing + list(self.evidence.blocked_reasons("offline_build"))))
        return {"available": not missing and not self._stop.is_set(), "code": "safe_executor_ready" if not missing and not self._stop.is_set() else "safe_executor_unavailable", "backend": "native_rootless_podman", "missing": missing + (["executor_closed"] if self._stop.is_set() else []), "support": {"git": "https_sha1", "tools": ["npm", "pnpm", "yarn_classic"], "offline_install": ["npm_registry_lock_v2_v3"], "pnpm_yarn_install": "unsupported_cache_workflow", "python_install": "unsupported_cache_workflow"}}

    def require_ready(self) -> None:
        state = self.readiness()
        if not state["available"]:
            raise ToolExecutionError(state["code"], "Native isolated executor is not ready", details={"missing": state["missing"]}, next_action="Provision and validate the listed prerequisites; Core and host fallback remain disabled.")

    def reconcile(self) -> None:
        assert self.journal is not None
        for job in self.journal.unfinished():
            try:
                info = self.inspect(job["name"])
                if info is None and not job["cgroup"]:
                    # Outcome remains interrupted; the key can never be reused.
                    self.journal.update(job["key"], "interrupted_terminated")
                    continue
                cgroup = job["cgroup"]
                if info and info.get("State", {}).get("Pid"):
                    cgroup = self._cgroup(int(info["State"]["Pid"]))
                self.terminate(job["name"], cgroup)
                self.journal.update(job["key"], "interrupted_terminated")
            except Exception:
                self.journal.update(job["key"], "unknown")
                raise InterruptedError("executor_restart_reconciliation_unknown") from None

    def _create(self, job: dict[str, Any], directory: Path, mounts: dict[str, Path]) -> str:
        # The caller never supplies image, host path, flags or shell commands.
        arguments = ["create", "--pull=never", "--name=" + job["name"], "--label=io.lingshu-gate.job=" + job["digest"], "--network=none", "--pid=private", "--ipc=private", "--uts=private", "--cgroupns=private", "--userns=keep-id", f"--user={os.getuid()}:{os.getgid()}", "--cgroups=enabled", "--cap-drop=ALL", "--security-opt=no-new-privileges", "--read-only", f"--memory={MEMORY}", f"--memory-swap={MEMORY}", "--cpus=1", f"--pids-limit={PIDS}", "--ulimit=nofile=256:256", "--http-proxy=false", "--log-driver=none", "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=67108864", "--workdir=/work", "--env=PATH=/tool/package/bin:/usr/local/bin:/usr/bin:/bin", "--env=HOME=/tmp/gate-home", "--entrypoint=/usr/bin/python3"]
        mounted = {"/work": directory / "output", "/gate-control": directory / "control", "/gate-runner.py": Path(__file__).with_name("runner.py"), "/request.json": directory / "request.json", **mounts}
        for destination, source in mounted.items():
            if "," in str(source) or not source.is_absolute() or source.is_symlink():
                reject("executor_mount_rejected", "Executor content mount is unsafe")
            arguments += ["--mount", f"type=bind,src={source},dst={destination}" + ("" if destination in {"/work", "/gate-control"} else ",ro=true")]
        content = self._cli([*arguments, self.config.image, "/gate-runner.py", "/request.json"])
        cid = content.decode().strip()
        if not CID.fullmatch(cid):
            raise InterruptedError("executor_container_create_unknown")
        return cid

    def run(self, key: str, request: dict[str, Any], *, mounts: dict[str, Path] | None = None, timeout: int, cancelled: Callable[[], bool], readiness: bool = False) -> dict[str, Any]:
        if not readiness:
            self.require_ready()
        assert self.journal is not None
        if not 0 < timeout <= 1800 or request.get("kind") not in {"selftest", "git", "tool_probe", "npm_seed", "command"}:
            reject("executor_request_rejected", "Unrecognized executor phase or deadline")
        if not self._gate.acquire(blocking=False):
            reject("executor_busy", "The bounded Native executor is busy")
        job: dict[str, Any] | None = None
        cgroup: str | None = None
        command_exit: int | None = None
        directory: Path | None = None
        started = time.monotonic()
        try:
            job = self.journal.reserve(key, {"request": request, "image": self.config.image, "timeout": timeout, "mounts": {name: self._inventory(path) for name, path in (mounts or {}).items()}}, str(request["kind"]))
            directory = self.workspaces / job["name"]
            directory.mkdir(mode=0o700)
            (directory / "output").mkdir(mode=0o700)
            (directory / "control").mkdir(mode=0o700)
            (directory / "request.json").write_text(json.dumps(request))
            self._active.add(job["key"])
            cid = self._create(job, directory, mounts or {})
            self.journal.update(key, "created", container_id=cid)
            self._cli(["start", cid])
            self.journal.update(key, "running")
            deadline = started + timeout
            while True:
                info = self.inspect(job["name"])
                if info is None:
                    raise InterruptedError("executor_lost_container")
                pid = int(info.get("State", {}).get("Pid") or 0)
                if pid and not cgroup:
                    cgroup = self._cgroup(pid)
                    self.journal.update(key, "running", cgroup=cgroup)
                    if request["kind"] == "command":
                        # PID 1 admits project code only after this durable
                        # cgroup observation. A fast command cannot outrun it.
                        (directory / "control" / "admitted").write_text("observed\n")
                if self._stop.is_set() or cancelled() or time.monotonic() >= deadline:
                    self.terminate(job["name"], cgroup)
                    self.journal.update(key, "cancelled" if cancelled() or self._stop.is_set() else "failed")
                    if cancelled() or self._stop.is_set():
                        raise SafeExecutionCancelled("executor_cancelled_after_whole_group_stop")
                    raise TimeoutError("executor_phase_timeout")
                report_file = directory / "output" / "result.json"
                if request["kind"] != "command" and report_file.is_file():
                    break
                if not info.get("State", {}).get("Running"):
                    if request["kind"] == "command":
                        command_exit = info.get("State", {}).get("ExitCode")
                        if type(command_exit) is not int or not 0 <= command_exit <= 255:
                            raise InterruptedError("executor_command_exit_unknown")
                    break
                time.sleep(0.05)
            # Container exit alone is insufficient. Observe the whole cgroup;
            # kill descendants before parsing or copying any project output.
            if cgroup is None:
                raise InterruptedError("executor_cgroup_observation_missing")
            self.terminate(job["name"], cgroup)
            self.journal.update(key, "terminated")
            self._freeze(directory / "output")
            result = read_regular_result(report_file)
            if type(result.get("returncode")) is not int:
                reject("executor_result_rejected", "Phase result lacks a bounded exit status")
            if request["kind"] == "command":
                # Shared output is untrusted: scripts can forge result.json.
                # Only the engine-observed PID 1 exit establishes success.
                result["returncode"] = command_exit
                result["package_manager_version"] = request.get("version")
                result["node_version"] = self.node_version
            result.update({"duration_ms": int((time.monotonic() - started) * 1000), "output": directory / "output", "job_key": key})
            self.journal.update(key, "completed" if result["returncode"] == 0 else "failed", result={"returncode": result["returncode"], "output_sha256": self._inventory(directory / "output")})
            return result
        except SafeExecutionCancelled:
            raise
        except BaseException:
            if job and self.journal:
                row = self.journal.lookup(key)
                if row and row["state"] == "terminated":
                    self.journal.update(key, "failed")
                if row and row["state"] not in {"terminated", "completed", "failed", "cancelled"}:
                    try:
                        self.terminate(job["name"], cgroup)
                        self.journal.update(key, "failed")
                    except Exception:
                        self.journal.update(key, "unknown")
                        self.missing.append("job_termination_unknown")
                        raise InterruptedError("executor_phase_outcome_unknown") from None
                row = self.journal.lookup(key)
                if directory and row and row["state"] in {"failed", "cancelled"}:
                    self.release_output({"output": directory / "output"})
            raise
        finally:
            if job:
                self._active.discard(job["key"])
            self._gate.release()

    @staticmethod
    def _freeze(root: Path) -> None:
        for parent, folders, files in os.walk(root, followlinks=False):
            for name in files + folders:
                path = Path(parent) / name
                if not path.is_symlink():
                    path.chmod(path.stat().st_mode & 0o555)
        root.chmod(0o500)

    @staticmethod
    def _inventory(path: Path) -> str:
        paths = [path] if path.is_file() else sorted(_bounded_paths(path))
        count = total = 0
        deadline = time.monotonic() + 30
        entries = []
        for item in paths:
            count += 1
            if count > 30000 or time.monotonic() > deadline:
                reject("executor_content_limit", "Content inventory exceeds its entry/deadline limit")
            relative = item.name if path.is_file() else item.relative_to(path).as_posix()
            info = item.lstat()
            entry: dict[str, Any] = {"path": relative, "mode": stat.S_IMODE(info.st_mode)}
            if stat.S_ISLNK(info.st_mode):
                entry.update({"type": "link", "target": os.readlink(item)})
            elif stat.S_ISREG(info.st_mode):
                digest = hashlib.sha256()
                with open_regular_file(item, maximum=500 * 1024 * 1024 - total) as (stream, opened):
                    while chunk := stream.read(64 * 1024):
                        total += len(chunk)
                        if total > 500 * 1024 * 1024 or time.monotonic() > deadline:
                            reject("executor_content_limit", "Content inventory exceeds its byte/deadline limit")
                        digest.update(chunk)
                entry.update({"type": "file", "size": opened.st_size, "sha256": digest.hexdigest()})
            elif stat.S_ISDIR(info.st_mode):
                entry["type"] = "directory"
            else:
                reject("executor_content_type_rejected", "Content inventory contains unsupported types")
            entries.append(entry)
        return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    def release_output(self, result: dict[str, Any]) -> None:
        path = result.get("output")
        if not isinstance(path, Path) or path.parent.parent != self.workspaces or not path.parent.name.startswith("gate-job-"):
            return
        # Frozen directories become writable only after all resources terminated.
        for parent, folders, _ in os.walk(path.parent, followlinks=False):
            Path(parent).chmod(0o700)
            for name in folders:
                item = Path(parent) / name
                if not item.is_symlink():
                    item.chmod(0o700)
        shutil.rmtree(path.parent)

    def close(self) -> None:
        self._stop.set()
        # In-flight run owns the controller until its whole-group stop completes.
        if self._gate.acquire(timeout=15):
            try:
                if self.journal:
                    self.reconcile()
                    self.journal.close()
                    self.journal = None
            finally:
                self._gate.release()

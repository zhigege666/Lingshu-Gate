"""Production Native adapter joining the existing Gate delivery coordinator."""
from __future__ import annotations

import re
import shutil
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from lingshu_gate.adapters.native_executor.controller import PodmanController, reject
from lingshu_gate.adapters.native_executor.git import HTTPSGitBackend
from lingshu_gate.adapters.native_executor.https import PROXY_SCHEMES, PinnedHTTPS
from lingshu_gate.adapters.native_executor.packages import ToolCache, project_policy
from lingshu_gate.git_acquisition import VerifiedGitAcquisition
from lingshu_gate.git_source import digest_json
from lingshu_gate.native_executor_config import NativeExecutorConfig
from lingshu_gate.network_artifact import export_network_artifact
from lingshu_gate.ports.safe_network_executor import REQUIRED_CAPABILITIES, TEST_TARGETS, SafeExecutionCancelled


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


class NativeNetworkExecutor:
    capabilities = REQUIRED_CAPABILITIES
    proxy_schemes = {phase: PROXY_SCHEMES for phase in ("git", "npm", "pnpm", "yarn", "python")}

    def __init__(self, config: NativeExecutorConfig, build_root: Path, *, controller: PodmanController | None = None, https: PinnedHTTPS | None = None) -> None:
        self.controller = controller or PodmanController(config)
        self.https = https or PinnedHTTPS(proxy_hosts=config.proxy_hosts)
        self.git = VerifiedGitAcquisition(HTTPSGitBackend(self.controller, self.https))
        self.tools = ToolCache(self.controller, self.https)
        self.build_root = build_root.resolve()
        self._gate = threading.BoundedSemaphore(1)
        self._closed = threading.Event()

    def start(self) -> None:
        self.controller.start()

    def readiness(self) -> dict[str, Any]:
        return self.controller.readiness()

    def require_ready(self) -> None:
        self.controller.require_ready()
        if self._closed.is_set():
            reject("safe_executor_unavailable", "Native executor has closed")

    def close(self) -> None:
        self._closed.set()
        # Acquisition checks this on every bounded chunk before dispatch. Close
        # admission before shutting down the journal/controller.
        if self._gate.acquire(timeout=15):
            try:
                self.controller.close()
            finally:
                self._gate.release()
        else:
            self.controller.close()

    def validate_plan(self, plan: dict[str, Any]) -> None:
        self.require_ready()
        for step in plan.get("steps", []):
            if step.get("phase") == "install" and step.get("command") != ["npm", "ci"]:
                reject("dependency_cache_workflow_unsupported", "This Native adapter supports npm registry lock v2/v3 installs only; pnpm/Yarn/Python installs require a reviewed cache adapter")

    def _admit(self) -> None:
        self.require_ready()
        if not self._gate.acquire(blocking=False):
            reject("executor_busy", "Native acquisition/offline executor is busy; no automatic retry was dispatched")

    def resolve_commit(self, request: dict[str, Any], *, material: dict[str, Any], timeout_seconds: int) -> str:
        self._admit()
        try:
            return self.git.resolve_commit(request, material=material, timeout_seconds=timeout_seconds)
        finally:
            self._gate.release()

    def export_snapshot(self, request: dict[str, Any], *, material: dict[str, Any], cancel: threading.Event) -> bytes:
        self._admit()
        try:
            return self.git.export_snapshot(request, material=material, cancel=cancel)
        finally:
            self._gate.release()

    def probe(self, target: str, *, material: dict[str, Any], timeout_seconds: int, max_response_bytes: int, method: str) -> dict[str, Any]:
        self._admit()
        try:
            if target not in TEST_TARGETS.values() or method != "HEAD" or not 0 < timeout_seconds <= 5 or not 0 < max_response_bytes <= 4096:
                reject("proxy_probe_rejected", "Proxy probes require a server-owned HEAD target and fixed limits")
            status, _ = self.https.request(target, rule=ToolCache._rule(target), material=material, deadline=time.monotonic() + timeout_seconds, maximum=max_response_bytes, method="HEAD", cancelled=self._closed.is_set)
            return {"ok": True, "http_status": status}
        finally:
            self._gate.release()

    @staticmethod
    def _phase_key(network: dict[str, Any], phase: str) -> str:
        execution = network.get("execution") or {}
        if not re.fullmatch(r"[0-9a-f]{32}", str(execution.get("build_id", ""))) or not execution.get("plan_fingerprint") or not execution.get("source_sha256") or not execution.get("actor_id"):
            reject("executor_binding_missing", "Isolated phases require the persisted actor/build/source/plan binding")
        return f"build:{execution['build_id']}:{phase}"

    @staticmethod
    def _selection(network: dict[str, Any], material: dict[str, Any], phase: str) -> None:
        selected = network.get(phase) or {}
        if selected.get("mode") not in {"profile", "direct"} or (selected.get("mode") == "profile") != bool(material.get("proxy")) or selected.get("mode") == "profile" and (type(selected.get("version")) is not int or selected["version"] < 1):
            reject("network_material_missing", "Pinned network selection differs from supplied material; no direct fallback is permitted")

    def prepare_package_manager(self, specification: dict[str, Any], *, network: dict[str, Any], material: dict[str, Any], timeout_seconds: int, cancel_requested: Callable[[], bool]) -> dict[str, Any]:
        self._admit()
        started = timestamp()
        try:
            self._selection(network, material, "install")
            key = self._phase_key(network, "prepare")
            result = self.tools.prepare(specification, network=network, material=material, deadline=time.monotonic() + min(timeout_seconds, 120), cancelled=lambda: cancel_requested() or self._closed.is_set(), key=key)
            return {field: value for field, value in result.items() if field != "cache_path"} | {"started_at": started, "finished_at": timestamp()}
        finally:
            self._gate.release()

    def _cwd(self, cwd: Path, network: dict[str, Any]) -> Path:
        identity = network.get("execution") or {}
        expected = self.build_root / str(identity.get("build_id")) / "source"
        if cwd != expected or cwd.resolve() != expected or not cwd.is_dir():
            reject("executor_project_path_rejected", "Isolated build input must be the coordinator-owned source directory")
        return expected

    def run_command(self, command: list[str], *, cwd: Path, environment: dict[str, str], network: dict[str, Any], material: dict[str, Any], timeout_seconds: int, cancel_requested: Callable[[], bool]) -> dict[str, Any]:
        self._admit()
        started = timestamp()
        clock = time.monotonic()
        result: dict[str, Any] | None = None
        seeded: dict[str, Any] | None = None
        dependencies: Path | None = None
        exported: Path | None = None
        try:
            self._selection(network, material, "install")
            manager = network.get("package_manager") or {}
            name = manager.get("name")
            if command not in [["npm", "ci"], [name, "run", "build"]] or name not in {"npm", "pnpm", "yarn"}:
                reject("dependency_cache_workflow_unsupported", "The selected generated command has no reviewed offline adapter")
            phase = "install" if command == ["npm", "ci"] else "build"
            key = self._phase_key(network, phase)
            self._cwd(cwd, network)
            project_policy(cwd, manager, install=phase == "install")
            tool = self.tools.prepared(manager)
            deadline = time.monotonic() + min(timeout_seconds, 1800)
            def cancelled() -> bool:
                return cancel_requested() or self._closed.is_set()
            mounts = {"/tool": tool, "/input": cwd}
            binding = {"execution": network["execution"], "network_sha256": digest_json({key: value for key, value in network.items() if key != "package_manager"}), "lockfile_sha256": manager.get("lockfile_sha256")}
            if phase == "install":
                dependencies = self.tools.npm_dependencies(cwd, manager, network=network, material=material, deadline=deadline, cancelled=cancelled)
                seeded = self.controller.run(key + ":seed", {"kind": "npm_seed", "binding": binding}, mounts={"/tool": tool, "/dependencies": dependencies}, timeout=max(1, min(120, int(deadline - time.monotonic()))), cancelled=cancelled)
                if seeded["returncode"]:
                    reject("dependency_cache_seed_failed", "Isolated verified npm cache preparation failed")
                mounts["/cache"] = seeded["output"] / "cache"
            result = self.controller.run(key, {"kind": "command", "manager": name, "version": manager["version"], "command": command, "binding": binding}, mounts=mounts, timeout=max(1, int(deadline - time.monotonic())), cancelled=cancelled)
            if result["returncode"] == 0:
                # Copy only a frozen, bounded contained tree, then publish to
                # the existing source path. BuildDeploy remains artifact owner.
                exported = cwd.parent / ("native-export-" + uuid4().hex)
                exported.mkdir(mode=0o700)
                export_network_artifact(result["output"] / "project", exported, ignored={".git"}, forbidden_values=[value for value in material.values() if isinstance(value, str)], cancelled=cancelled)
                for path in exported.rglob("*"):
                    if path.is_file() and not path.is_symlink():
                        path.chmod(path.stat().st_mode | 0o200)
                backup = cwd.parent / ("native-source-" + uuid4().hex)
                cwd.rename(backup)
                try:
                    exported.rename(cwd)
                    exported = None
                except BaseException:
                    backup.rename(cwd)
                    raise
                finally:
                    if backup.exists() and cwd.exists():
                        shutil.rmtree(backup)
            return {field: result.get(field) for field in ("returncode", "package_manager_version", "node_version")} | {"stdout": "", "stderr": "", "duration_ms": int((time.monotonic() - clock) * 1000), "started_at": started, "finished_at": timestamp()}
        except SafeExecutionCancelled:
            return {"returncode": 130, "cancelled": True, "stdout": "", "stderr": "", "duration_ms": int((time.monotonic() - clock) * 1000), "started_at": started, "finished_at": timestamp()}
        except TimeoutError:
            return {"returncode": 124, "timed_out": True, "stdout": "", "stderr": "", "duration_ms": int((time.monotonic() - clock) * 1000), "started_at": started, "finished_at": timestamp()}
        finally:
            if dependencies:
                shutil.rmtree(dependencies)
            if result:
                self.controller.release_output(result)
            if seeded:
                self.controller.release_output(seeded)
            if exported:
                shutil.rmtree(exported)
            self._gate.release()


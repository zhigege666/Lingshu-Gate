"""Build and deploy pipeline for uploaded MCP projects."""

from __future__ import annotations

import json
import os
import signal
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from lingshu_gate.build_plan import build_plan, finalize_manifest, plan_commands, plan_waves, validate_plan
from lingshu_gate.build_preflight import check_diff, compute_preflight_fingerprint, fingerprint_key, preflight_diff, run_build_preflight, scope_key as compute_scope_key, tools_signature
from lingshu_gate.credential_store import CredentialStore
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.mcp_config_store import McpConfigStore
from lingshu_gate.mcp_runtime import McpRuntimeManager, McpTargetApplyError
from lingshu_gate.models import ResourceDeleteConflict
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.project_uploads import ProjectUploadStore

IGNORED_COPY_DIRS = {".git", "node_modules", ".venv", "venv", "target", "__pycache__"}
ARTIFACT_IGNORED_COPY_DIRS = {".git", ".venv", "venv", "target", "__pycache__"}
MAX_CAPTURE_CHARS = 24_000
MAX_CAPTURE_BYTES = MAX_CAPTURE_CHARS * 4
PROCESS_READ_CHUNK_BYTES = 16 * 1024
PROCESS_POLL_INTERVAL_SECONDS = 0.1
PROCESS_TERMINATE_GRACE_SECONDS = 1.0
SUPPORTED_LOCAL_RUNTIMES = {"node", "python"}
TERMINAL_BUILD_STATUSES = {"success", "failed", "unsupported", "cancelled"}
BUILD_EXECUTOR_WORKERS = 2
STEP_EXECUTOR_WORKERS = 4
# 构建子进程不继承服务进程的令牌、代理或用户级配置；仅保留定位
# node/python 所需的最小系统变量。每次构建再补充独立的 HOME、缓存目录。
SUBPROCESS_ENV_PASSTHROUGH = ("PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "SYSTEMDRIVE")
ROLLBACK_SNAPSHOT_DIR = "deployment-rollback-snapshots"
ROLLBACK_SNAPSHOT_PREFIX = "deployment-rollback-"


def iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BuildCancelled(Exception):
    """Raised by the background worker when a cancel request is observed."""


class BuildBlocked(Exception):
    """Raised before a Build is created when preflight gate conditions fail.

    Carries the structured preflight result so the API layer and Console can
    render actionable feedback instead of persisting an unsupported/failed Build.
    """

    def __init__(self, code: str, message: str, preflight: dict[str, Any]) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.preflight = preflight


class LocalExecutionBlocked(ValueError):
    """Raised when the current process role cannot execute build/deploy work."""

    code = "runtime_role_execution_blocked"

    def __init__(self, operation: str, runtime_role: str) -> None:
        self.operation = operation
        self.runtime_role = runtime_role
        self.message = (
            f"{operation} is disabled for runtime role {runtime_role!r}; "
            "use the local runtime role"
        )
        super().__init__(self.message)

    def detail(self) -> dict[str, str]:
        return {
            "code": self.code,
            "message": self.message,
            "operation": self.operation,
            "runtime_role": self.runtime_role,
        }


class DeploymentRollbackError(ValueError):
    """人工回滚无法安全恢复原始 Manifest 时返回稳定错误码。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class BuildDeployStore:
    """Build/deploy service for uploaded local managed_process MCP projects."""

    def __init__(
        self,
        database: SQLiteDatabase,
        data_dir: Path,
        uploads: ProjectUploadStore,
        configs: McpConfigStore,
        runtime: McpRuntimeManager,
        observability: ObservabilityStore,
        *,
        runtime_role: str = "local",
    ) -> None:
        self.database = database
        self.data_dir = data_dir
        self.uploads = uploads
        self.configs = configs
        self.runtime = runtime
        self.observability = observability
        self.runtime_role = runtime_role.strip().lower()
        # Only the single-process local role may execute uploaded code.
        # Unknown/future roles remain fail-closed until they gain a dedicated
        # worker execution contract.
        self.local_execution_enabled = self.runtime_role == "local"
        # 历史展示仍只入库脱敏 Manifest；人工回滚所需原文复用现有
        # CredentialStore 加密能力，并与普通业务凭据隔离存放。
        self.rollback_snapshots = CredentialStore(data_dir / ROLLBACK_SNAPSHOT_DIR)
        self.root = data_dir / "builds"
        self.root.mkdir(parents=True, exist_ok=True)
        self.executor = ThreadPoolExecutor(max_workers=BUILD_EXECUTOR_WORKERS, thread_name_prefix="gate-build")
        self._step_lock = threading.Lock()

    def _require_local_execution(self, operation: str) -> None:
        if self.local_execution_enabled:
            return
        blocked = LocalExecutionBlocked(operation, self.runtime_role)
        self.observability.emit_event(
            "gate.runtime_role.execution_blocked",
            source="builds",
            payload=blocked.detail(),
        )
        self.observability.add_log(
            "warning",
            blocked.message,
            source="builds",
            event_type="gate.runtime_role.execution_blocked",
            payload=blocked.detail(),
        )
        raise blocked

    def list_builds(self) -> list[dict[str, Any]]:
        rows = self.database.query_all("SELECT * FROM builds ORDER BY created_at DESC LIMIT 100")
        return [_build_row(row) for row in rows]

    def get_build(self, build_id: str) -> dict[str, Any]:
        row = self.database.query_one("SELECT * FROM builds WHERE id = ?", (build_id,))
        if not row:
            raise KeyError(f"build not found: {build_id}")
        return _build_row(row)

    def delete_build(self, build_id: str) -> dict[str, Any]:
        build = self.get_build(build_id)
        status = str(build.get("status") or "")
        if status not in TERMINAL_BUILD_STATUSES:
            raise ResourceDeleteConflict(
                code="build_active" if status in {"queued", "running", "cancel_requested"} else "build_not_terminal",
                message=f"构建当前状态为 {status or 'unknown'}，只能删除已经结束的构建。",
                resource_type="build",
                resource_id=build_id,
                dependencies={"status": status},
            )

        deployment_rows = self.database.query_all(
            "SELECT id, server_id FROM deployments WHERE build_id = ? ORDER BY created_at DESC",
            (build_id,),
        )
        if deployment_rows:
            deployment_ids = [str(row["id"]) for row in deployment_rows]
            server_ids = sorted({str(row["server_id"]) for row in deployment_rows})
            raise ResourceDeleteConflict(
                code="build_has_deployments",
                message=f"构建仍关联 {len(deployment_ids)} 条部署记录，请先删除部署历史。",
                resource_type="build",
                resource_id=build_id,
                dependencies={"deployment_count": len(deployment_ids), "deployment_ids": deployment_ids, "server_ids": server_ids},
            )

        referenced_server_ids = self._build_reference_server_ids(build)
        if referenced_server_ids:
            raise ResourceDeleteConflict(
                code="build_in_use",
                message="构建制品仍被 MCP 配置或运行时引用，请先停止并删除对应 MCP 配置。",
                resource_type="build",
                resource_id=build_id,
                dependencies={"server_ids": referenced_server_ids},
            )

        builds_root = self.root.resolve()
        build_dir = (self.root / build_id).resolve()
        if build_dir.parent != builds_root:
            raise ValueError(f"unsafe build directory: {build_dir}")

        trash_dir: Path | None = None
        if build_dir.exists():
            if not build_dir.is_dir():
                raise ValueError(f"build path is not a directory: {build_dir}")
            trash_root = self.root / ".trash"
            trash_root.mkdir(parents=True, exist_ok=True)
            trash_dir = trash_root / f"{build_id}-{uuid4().hex}"
            build_dir.replace(trash_dir)

        deleted_log_count = 0
        try:
            # 构建日志和构建主记录必须在同一事务删除，避免留下孤儿日志。
            with self.database.connect() as connection:
                row = connection.execute("SELECT COUNT(*) AS count FROM build_logs WHERE build_id = ?", (build_id,)).fetchone()
                deleted_log_count = int(row["count"] or 0) if row else 0
                connection.execute("DELETE FROM build_logs WHERE build_id = ?", (build_id,))
                connection.execute("DELETE FROM builds WHERE id = ?", (build_id,))
                connection.commit()
        except Exception:
            if trash_dir is not None and trash_dir.exists() and not build_dir.exists():
                trash_dir.replace(build_dir)
            raise

        if trash_dir is not None:
            shutil.rmtree(trash_dir, ignore_errors=True)
        self.observability.emit_event("gate.build.deleted", source="builds", subject_type="build", subject_id=build_id, payload={"upload_id": build.get("upload_id"), "deleted_log_count": deleted_log_count})
        self.observability.add_log("info", "Build history deleted", source="builds", event_type="gate.build.deleted", payload={"build_id": build_id, "upload_id": build.get("upload_id"), "deleted_log_count": deleted_log_count})
        return {"deleted": True, "build": build, "deleted_log_count": deleted_log_count}

    def list_build_logs(
        self,
        build_id: str,
        *,
        limit: int = 200,
        after_sequence: int | None = None,
    ) -> list[dict[str, Any]]:
        self.get_build(build_id)
        limit = max(1, min(int(limit or 200), 1000))
        if after_sequence is None:
            rows = self.database.query_all(
                "SELECT * FROM build_logs WHERE build_id = ? ORDER BY sequence ASC LIMIT ?",
                (build_id, limit),
            )
        else:
            rows = self.database.query_all(
                "SELECT * FROM build_logs WHERE build_id = ? AND sequence > ? ORDER BY sequence ASC LIMIT ?",
                (build_id, int(after_sequence), limit),
            )
        return [_build_log_row(row) for row in rows]

    def list_deployments(self) -> list[dict[str, Any]]:
        rows = self.database.query_all("SELECT * FROM deployments ORDER BY created_at DESC LIMIT 100")
        return [_deployment_row(row) for row in rows]

    def get_deployment(self, deployment_id: str) -> dict[str, Any]:
        row = self.database.query_one("SELECT * FROM deployments WHERE id = ?", (deployment_id,))
        if not row:
            raise KeyError(f"deployment not found: {deployment_id}")
        return _deployment_row(row)

    def _rollback_snapshot_id(self, deployment_id: str) -> str:
        return f"{ROLLBACK_SNAPSHOT_PREFIX}{deployment_id}"

    def _save_rollback_snapshot(self, deployment_id: str, manifest: Any) -> None:
        payload = manifest.model_dump(mode="json", exclude={"manifest_path"})
        self.rollback_snapshots.save_credential(
            name=f"Deployment rollback snapshot {deployment_id}",
            value=_dumps(payload),
            credential_id=self._rollback_snapshot_id(deployment_id),
        )

    def _delete_rollback_snapshot(self, deployment_id: str) -> None:
        try:
            self.rollback_snapshots.delete_credential(self._rollback_snapshot_id(deployment_id))
        except KeyError:
            return

    def _load_rollback_snapshot(
        self,
        deployment_id: str,
        safe_fallback: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            serialized = self.rollback_snapshots.resolve_value(
                self._rollback_snapshot_id(deployment_id)
            )
        except KeyError:
            # 兼容旧部署：不含掩码的历史快照仍可可靠回滚；一旦出现
            # "***" 就不能把展示值误当成原始秘密写回配置。
            if _contains_masked_value(safe_fallback):
                raise DeploymentRollbackError(
                    "rollback_snapshot_unavailable",
                    "旧部署只保留了脱敏 Manifest，无法可靠恢复原始秘密",
                )
            return dict(safe_fallback)
        except Exception as exc:
            raise DeploymentRollbackError(
                "rollback_snapshot_unavailable",
                "受保护的旧 Manifest 快照无法解密",
            ) from exc

        try:
            snapshot = json.loads(serialized or "")
        except (TypeError, ValueError) as exc:
            raise DeploymentRollbackError(
                "rollback_snapshot_unavailable",
                "受保护的旧 Manifest 快照内容无效",
            ) from exc
        if not isinstance(snapshot, dict):
            raise DeploymentRollbackError(
                "rollback_snapshot_unavailable",
                "受保护的旧 Manifest 快照不是对象",
            )
        return snapshot

    def delete_deployment(self, deployment_id: str) -> dict[str, Any]:
        deployment = self.get_deployment(deployment_id)
        status = str(deployment.get("status") or "")
        if status == "running":
            raise ResourceDeleteConflict(
                code="deployment_active",
                message="部署仍在执行，完成或失败后才能删除部署历史。",
                resource_type="deployment",
                resource_id=deployment_id,
                dependencies={"status": status, "server_id": deployment.get("server_id")},
            )

        # 这里只删除历史快照，不停止服务、不删除 MCP 配置，也不修改期望运行状态。
        self.database.execute("DELETE FROM deployments WHERE id = ?", (deployment_id,))
        try:
            self._delete_rollback_snapshot(deployment_id)
        except Exception as exc:  # noqa: BLE001 - 主记录已删除，只能记录加密快照清理失败
            self.observability.add_log(
                "warning",
                f"Encrypted rollback snapshot cleanup failed: {exc}",
                source="deployments",
                event_type="gate.deployment.rollback_snapshot_cleanup_failed",
                server_id=str(deployment.get("server_id") or "") or None,
                payload={"deployment_id": deployment_id},
            )
        self.observability.emit_event("gate.deployment.deleted", source="deployments", subject_type="deployment", subject_id=deployment_id, payload={"build_id": deployment.get("build_id"), "server_id": deployment.get("server_id"), "runtime_unchanged": True})
        self.observability.add_log("info", "Deployment history deleted; runtime unchanged", source="deployments", event_type="gate.deployment.deleted", server_id=str(deployment.get("server_id") or "") or None, payload={"deployment_id": deployment_id, "build_id": deployment.get("build_id")})
        return {"deleted": True, "deployment": deployment, "runtime_unchanged": True, "message": "deployment_history_deleted"}

    def _build_reference_server_ids(self, build: dict[str, Any]) -> list[str]:
        build_id = str(build.get("id") or "")
        artifact_dir = Path(str(build.get("artifact_dir") or "")).resolve()
        referenced: set[str] = set()

        config_list = self.configs.list_configs()
        for config in config_list.configs:
            if _manifest_references_build(config.manifest, build_id, artifact_dir):
                referenced.add(config.id)

        # 配置文件可能刚被修改但尚未重载；同时检查运行时快照，覆盖这一时间窗。
        for server_id, manifest in self.runtime.iter_manifests().items():
            manifest_data = manifest.model_dump(mode="json", exclude={"manifest_path"})
            if _manifest_references_build(manifest_data, build_id, artifact_dir):
                referenced.add(server_id)
        return sorted(referenced)

    def preflight_upload(self, upload_id: str, *, runtime_override: str | None = None, project_root: str | None = None, refresh: bool = False) -> dict[str, Any]:
        """Run Build preflight without creating a Build job, using a cache-first path.

        The result is cached by a structural fingerprint (key files + file count +
        toolchain signature). Cache hits skip the toolchain version probes and file
        reads done by ``run_build_preflight``. ``refresh=True`` forces a recompute.
        """

        upload = self.uploads.get_upload(upload_id)
        fingerprint = compute_preflight_fingerprint(upload, runtime_override=runtime_override, project_root=project_root)
        fingerprint["tool_probe_mode"] = (
            "version" if self.local_execution_enabled else "path"
        )
        cache_key = fingerprint_key(fingerprint)
        scope_key = compute_scope_key(upload_id, fingerprint)

        if not refresh:
            cached = self._load_preflight_cache(cache_key)
            if cached is not None:
                result = {**cached["result"], "cache": {"hit": True, "cache_key": cache_key, "cached_at": cached["updated_at"], "reused_tools": True, "fingerprint": _fingerprint_summary(fingerprint)}, "diff": {"has_previous": True, "unchanged": True, "changed_files": {"added": [], "removed": [], "modified": []}, "file_count_delta": 0, "tool_changes": [], "affected_checks": [], "check_changes": []}}
                self.observability.emit_event("gate.build.preflight", source="builds", subject_type="upload", subject_id=upload_id, payload={"runtime": result.get("runtime"), "status": result.get("status"), "project_root_dir": result.get("project_root_dir"), "cache_hit": True})
                return result

        previous = self._load_latest_scope_cache(scope_key)
        previous_fingerprint = previous["fingerprint"] if previous else {}
        previous_result = previous["result"] if previous else {}
        tools_cache = None
        reused_tools = False
        if previous_fingerprint and tools_signature(previous_fingerprint) == tools_signature(fingerprint):
            previous_tools = previous_result.get("tools")
            if isinstance(previous_tools, dict):
                tools_cache = previous_tools
                reused_tools = True

        result = run_build_preflight(
            upload,
            runtime_override=runtime_override,
            project_root=project_root,
            tools_cache=tools_cache,
            probe_tool_versions=self.local_execution_enabled,
        )
        diff = {**preflight_diff(previous_fingerprint, fingerprint), **check_diff(previous_result.get("checks") if isinstance(previous_result.get("checks"), list) else [], result.get("checks") or []), "reused_tools": reused_tools}
        self._store_preflight_cache(upload_id, cache_key, scope_key, fingerprint, result)
        self.observability.emit_event("gate.build.preflight", source="builds", subject_type="upload", subject_id=upload_id, payload={"runtime": result.get("runtime"), "status": result.get("status"), "project_root_dir": result.get("project_root_dir"), "cache_hit": False, "reused_tools": reused_tools, "affected_checks": len(diff.get("affected_checks") or [])})
        return {**result, "cache": {"hit": False, "cache_key": cache_key, "cached_at": iso_now(), "reused_tools": reused_tools, "fingerprint": _fingerprint_summary(fingerprint)}, "diff": diff}

    def _load_preflight_cache(self, cache_key: str) -> dict[str, Any] | None:
        row = self.database.query_one("SELECT * FROM preflight_cache WHERE cache_key = ?", (cache_key,))
        if not row:
            return None
        return {"result": _loads(row["result_json"], {}), "fingerprint": _loads(row["fingerprint_json"], {}), "updated_at": row["updated_at"]}

    def _load_latest_scope_cache(self, scope_key: str) -> dict[str, Any] | None:
        row = self.database.query_one("SELECT * FROM preflight_cache WHERE scope_key = ? ORDER BY updated_at DESC LIMIT 1", (scope_key,))
        if not row:
            return None
        return {"result": _loads(row["result_json"], {}), "fingerprint": _loads(row["fingerprint_json"], {}), "updated_at": row["updated_at"]}

    def _store_preflight_cache(self, upload_id: str, cache_key: str, scope_key: str, fingerprint: dict[str, Any], result: dict[str, Any]) -> None:
        now = iso_now()
        self.database.execute(
            """
            INSERT INTO preflight_cache (cache_key, upload_id, scope_key, fingerprint_json, result_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET upload_id = excluded.upload_id, scope_key = excluded.scope_key, fingerprint_json = excluded.fingerprint_json, result_json = excluded.result_json, updated_at = excluded.updated_at
            """,
            (cache_key, upload_id, scope_key, _dumps(fingerprint), _dumps(result), now, now),
        )

    def build_upload(
        self,
        upload_id: str,
        *,
        run_install: bool = True,
        run_build: bool = True,
        timeout_seconds: int = 300,
        runtime_override: str | None = None,
        project_root: str | None = None,
        prepared_preflight: dict[str, Any] | None = None,
        source_sha256: str = "",
        plan_fingerprint: str = "",
        operation_id: str | None = None,
        owner_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a queued build and execute it in the background."""

        self._require_local_execution("build")
        upload = self.uploads.get_upload(upload_id)
        preflight = prepared_preflight or run_build_preflight(
            upload,
            runtime_override=runtime_override,
            project_root=project_root,
        )
        runtime = str(preflight.get("runtime") or upload.get("detected_runtime") or "unknown")

        guard = _evaluate_build_guard(preflight, runtime)
        if guard is not None:
            self.observability.emit_event("gate.build.blocked", source="builds", subject_type="upload", subject_id=upload_id, payload={"code": guard["code"], "runtime": runtime, "preflight_status": preflight.get("status"), "project_root_dir": preflight.get("project_root_dir")})
            self.observability.add_log("warning", f"Build blocked before creation: {guard['message']}", source="builds", event_type="gate.build.blocked", payload={"upload_id": upload_id, "runtime": runtime, "code": guard["code"]})
            raise BuildBlocked(guard["code"], guard["message"], preflight)

        build_id = uuid4().hex
        build_dir = self.root / build_id
        source_dir = build_dir / "source"
        artifact_dir = build_dir / "artifact"
        build_dir.mkdir(parents=True, exist_ok=False)
        artifact_dir.mkdir(parents=True, exist_ok=True)

        upload_root = Path(str(preflight.get("project_root_dir") or upload.get("root_dir") or ""))
        if not upload_root.exists() or not upload_root.is_dir():
            return self._record_build(
                build_id,
                upload_id,
                runtime,
                upload_root,
                artifact_dir,
                "failed",
                [],
                [],
                {"preflight": preflight},
                f"upload root not found: {upload_root}",
                source_sha256=source_sha256,
                plan_fingerprint=plan_fingerprint,
                operation_id=operation_id,
                owner_id=owner_id,
            )

        plan = build_plan(
            preflight,
            run_install=run_install,
            run_build=run_build,
        )
        validation = validate_plan(plan)
        if not validation["ok"]:
            return self._record_build(
                build_id,
                upload_id,
                runtime,
                upload_root,
                artifact_dir,
                "failed",
                [],
                [],
                {"preflight": preflight, "plan": plan},
                f"Build plan is invalid: {'; '.join(validation['errors'][:6])}",
                source_sha256=source_sha256,
                plan_fingerprint=plan_fingerprint,
                operation_id=operation_id,
                owner_id=owner_id,
            )
        plan = validation["normalized"]
        steps_state = _init_step_states(plan)
        timeout_seconds = max(1, min(int(timeout_seconds or 300), 1800))
        # 构建来源与幂等操作必须先随 queued 记录一次性落库，再提交后台
        # worker；否则快速 worker 可能先进入运行态，而来源字段仍为空。
        self._insert_build_record(
            build_id,
            upload_id,
            runtime,
            source_dir,
            artifact_dir,
            status="queued",
            plan=plan,
            steps=steps_state,
            source_sha256=source_sha256,
            plan_fingerprint=plan_fingerprint,
            operation_id=operation_id,
            owner_id=owner_id,
        )
        self._insert_build_log(build_id, sequence=0, phase="preflight", level="info" if preflight.get("status") == "ok" else "warning", message=f"Build preflight completed: status={preflight.get('status')} runtime={runtime}", command=[], result={"returncode": 0, "stdout": _dumps(preflight), "stderr": "", "started_at": iso_now(), "finished_at": iso_now(), "duration_ms": 0})
        self._insert_build_log(build_id, sequence=1, phase="plan", level="info", message=f"Build plan compiled and validated: {len(plan.get('steps') or [])} step(s)", command=[], result={"returncode": 0, "stdout": _dumps(plan), "stderr": "", "started_at": iso_now(), "finished_at": iso_now(), "duration_ms": 0})
        self._insert_build_log(build_id, sequence=2, phase="queue", level="info", message="Build queued and waiting for background worker", command=[], result=None)
        self.observability.emit_event("gate.build.queued", source="builds", subject_type="build", subject_id=build_id, payload={"upload_id": upload_id, "runtime": runtime, "preflight_status": preflight.get("status"), "project_root_dir": str(upload_root), "plan_steps": len(plan.get("steps") or [])})
        self.executor.submit(self._run_build_job, build_id, upload, runtime, upload_root, source_dir, artifact_dir, plan, timeout_seconds)
        return self.get_build(build_id)

    def plan_upload(
        self,
        upload_id: str,
        *,
        runtime_override: str | None = None,
        project_root: str | None = None,
        run_install: bool = True,
        run_build: bool = True,
        refresh: bool = False,
    ) -> dict[str, Any]:
        """Preview the Build Plan (IR) without executing a build.

        Reuses the cache-first preflight path and compiles the IR so callers can
        inspect the exact command sequence and manifest strategy beforehand.
        """

        preflight = self.preflight_upload(upload_id, runtime_override=runtime_override, project_root=project_root, refresh=refresh)
        plan = build_plan(preflight, run_install=run_install, run_build=run_build)
        validation = validate_plan(plan)
        self.observability.emit_event("gate.build.plan", source="builds", subject_type="upload", subject_id=upload_id, payload={"runtime": plan.get("runtime"), "buildable": plan.get("buildable"), "plan_steps": len(plan.get("steps") or []), "plan_valid": validation["ok"]})
        return {"preflight": preflight, "plan": plan, "validation": {"ok": validation["ok"], "errors": validation["errors"]}}

    def cancel_build(self, build_id: str) -> dict[str, Any]:
        build = self.get_build(build_id)
        status = str(build.get("status") or "")
        if status == "cancel_requested":
            return build
        if status not in {"queued", "running"}:
            raise ValueError(f"build is not cancellable: {status}")
        self._set_build_status(build_id, "cancel_requested")
        self._insert_build_log(build_id, sequence=self._next_build_log_sequence(build_id), phase="cancel", level="warning", message="Cancel requested. Any running command and its process group will be stopped.", command=[], result=None)
        self.observability.emit_event("gate.build.cancel_requested", source="builds", subject_type="build", subject_id=build_id, payload={"previous_status": status})
        return self.get_build(build_id)

    def _persist_deployment_outcome(
        self,
        deployment_id: str,
        *,
        status: str,
        config_path: str | None,
        started: bool,
        config_applied: bool,
        runtime_started: bool,
        rollback_attempted: bool,
        rollback_succeeded: bool | None,
        rollback_error: str | None,
        error: str | None,
    ) -> None:
        self.database.execute(
            """
            UPDATE deployments
            SET status = ?, config_path = ?, started = ?, config_applied = ?,
                runtime_started = ?, rollback_attempted = ?,
                rollback_succeeded = ?, rollback_error = ?, error = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                config_path,
                1 if started else 0,
                1 if config_applied else 0,
                1 if runtime_started else 0,
                1 if rollback_attempted else 0,
                None if rollback_succeeded is None else (1 if rollback_succeeded else 0),
                rollback_error,
                error,
                iso_now(),
                deployment_id,
            ),
        )

    def deploy_build(
        self,
        build_id: str,
        *,
        server_id: str | None = None,
        start: bool = False,
        overwrite: bool = False,
        owner_id: str | None = None,
        manifest_override: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._require_local_execution("deploy")
        build = self.get_build(build_id)
        if build["status"] != "success":
            raise ValueError(f"build is not deployable: {build['status']}; error={build.get('error') or 'none'}")
        manifest = dict(manifest_override or build.get("manifest") or {})
        if server_id:
            manifest["id"] = server_id
            manifest["name"] = manifest.get("name") or server_id
        server_id = str(manifest.get("id") or "").strip()
        if not server_id:
            raise ValueError("server_id is required")

        previous_runtime_manifest = None
        previous_manifest: dict[str, Any] | None = None
        try:
            previous_runtime_manifest = self.configs.load_manifest(server_id)
            previous_manifest = previous_runtime_manifest.safe_dict()
        except KeyError:
            previous_manifest = None

        iter_manifests = getattr(self.runtime, "iter_manifests", None)
        runtime_manifests = iter_manifests() if callable(iter_manifests) else {}
        previous_runtime_restore_manifest = runtime_manifests.get(server_id)
        previous_runtime_present = previous_runtime_restore_manifest is not None
        previous_runtime_should_start = False
        if previous_runtime_present:
            previous_runtime_state = self.runtime.get_server(server_id)
            desired_state = str(getattr(previous_runtime_state, "desired_state", "") or "")
            previous_runtime_should_start = desired_state == "running" or (
                not desired_state
                and str(getattr(previous_runtime_state, "status", "") or "") == "running"
            )

        deployment_id = uuid4().hex
        now = iso_now()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO deployments (
                    id, build_id, server_id, status, manifest_json,
                    previous_manifest_json, started, config_applied,
                    runtime_started, rollback_attempted, rollback_succeeded,
                    rollback_error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    deployment_id,
                    build_id,
                    server_id,
                    "running",
                    _dumps(manifest),
                    _dumps(previous_manifest) if previous_manifest else None,
                    0,
                    0,
                    0,
                    0,
                    None,
                    None,
                    now,
                    now,
                ),
            )
            if owner_id:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO project_delivery_resource_owners (
                        resource_type, resource_id, owner_id, created_at, updated_at
                    ) VALUES ('deployment', ?, ?, ?, ?)
                    """,
                    (deployment_id, owner_id, now, now),
                )
            connection.commit()
        self.observability.emit_event("gate.deploy.started", source="deployments", subject_type="deployment", subject_id=deployment_id, payload={"build_id": build_id, "server_id": server_id, "overwrite": overwrite, "start": start})

        status = "success"
        error: str | None = None
        config_path: str | None = None
        started = False
        config_applied = False
        runtime_started = False
        runtime_applied = False
        rollback_attempted = False
        rollback_succeeded: bool | None = None
        rollback_error: str | None = None
        try:
            if previous_runtime_manifest is not None:
                # 受保护快照必须先于配置副作用完成；失败时只留下可审计的
                # failed deployment，不会触碰现有配置或 Runtime。
                self._save_rollback_snapshot(deployment_id, previous_runtime_manifest)
            config = self.configs.save_config(manifest, expected_id=server_id if previous_manifest else None, overwrite=overwrite)
            config_applied = True
            config_path = config.path
            self.database.execute(
                """
                UPDATE deployments
                SET config_path = ?, config_applied = 1, updated_at = ?
                WHERE id = ?
                """,
                (config_path, iso_now(), deployment_id),
            )
            runtime_manifest = self.configs.load_manifest(server_id)
            server = self.runtime.apply_manifest(runtime_manifest, start=start, source="deploy")
            runtime_applied = True
            runtime_started = server.status == "running"
            started = runtime_started
            self.database.execute(
                """
                UPDATE deployments
                SET started = ?, runtime_started = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    1 if started else 0,
                    1 if runtime_started else 0,
                    iso_now(),
                    deployment_id,
                ),
            )
            # 成功终态必须在返回前落库；此处若失败，异常分支仍会恢复
            # 旧磁盘配置和旧 Runtime/intent，避免账面与运行态漂移。
            self._persist_deployment_outcome(
                deployment_id,
                status="success",
                config_path=config_path,
                started=started,
                config_applied=config_applied,
                runtime_started=runtime_started,
                rollback_attempted=False,
                rollback_succeeded=None,
                rollback_error=None,
                error=None,
            )
        except Exception as exc:  # noqa: BLE001 - boundary records deploy failures
            status = "failed"
            error = str(exc)
            if config_applied:
                rollback_attempted = True
                # 先持久化“已尝试、结果未知”，再执行补偿。若进程在补偿
                # 中断，null 能明确区别于已确认成功或失败。
                try:
                    self.database.execute(
                        """
                        UPDATE deployments
                        SET rollback_attempted = 1, rollback_succeeded = NULL,
                            rollback_error = NULL, updated_at = ?
                        WHERE id = ?
                        """,
                        (iso_now(), deployment_id),
                    )
                except Exception as marker_exc:  # noqa: BLE001 - 落账失败不能阻止物理补偿
                    error = f"{error}; rollback marker persistence failed: {marker_exc}"

                compensation_errors: list[str] = []
                if isinstance(exc, McpTargetApplyError) and "target rollback failed:" in str(exc):
                    compensation_errors.append(f"runtime compensation failed: {exc}")
                try:
                    if previous_runtime_manifest is not None:
                        self.configs.save_config(
                            previous_runtime_manifest.model_dump(mode="json", exclude={"manifest_path"}),
                            expected_id=server_id,
                            overwrite=True,
                        )
                    else:
                        self.configs.delete_config(server_id)
                except Exception as compensation_exc:  # noqa: BLE001 - 记录磁盘补偿失败
                    compensation_errors.append(f"config compensation failed: {compensation_exc}")

                # apply_manifest 已成功返回后才需要显式恢复旧 Runtime；若它
                # 自身抛错，则 RuntimeManager 已负责内部目标级补偿。
                if runtime_applied:
                    try:
                        if previous_runtime_present:
                            if previous_runtime_restore_manifest is None:
                                raise RuntimeError("previous runtime manifest is unavailable")
                            self.runtime.apply_manifest(
                                previous_runtime_restore_manifest,
                                start=previous_runtime_should_start,
                                source="deploy_compensation",
                            )
                        else:
                            self.runtime.remove_manifest(server_id)
                    except Exception as compensation_exc:  # noqa: BLE001 - 合并 Runtime 补偿失败
                        compensation_errors.append(f"runtime compensation failed: {compensation_exc}")

                rollback_succeeded = not compensation_errors
                rollback_error = "; ".join(compensation_errors) or None
                if rollback_error:
                    error = f"{error}; {rollback_error}"
            self.observability.add_log("error", f"Deploy failed: {error}", source="deployments", event_type="gate.deploy.failed", payload={"deployment_id": deployment_id, "build_id": build_id, "server_id": server_id})
            try:
                self._persist_deployment_outcome(
                    deployment_id,
                    status=status,
                    config_path=config_path,
                    started=started,
                    config_applied=config_applied,
                    runtime_started=runtime_started,
                    rollback_attempted=rollback_attempted,
                    rollback_succeeded=rollback_succeeded,
                    rollback_error=rollback_error,
                    error=error,
                )
            except Exception as persistence_exc:
                raise RuntimeError(
                    f"deployment bookkeeping failed after compensation: {persistence_exc}"
                ) from exc
        else:
            self.observability.add_log("info", "Deploy completed", source="deployments", event_type="gate.deploy.success", server_id=server_id, payload={"deployment_id": deployment_id, "build_id": build_id, "started": started})
        self.observability.emit_event(
            f"gate.deploy.{status}",
            source="deployments",
            subject_type="deployment",
            subject_id=deployment_id,
            payload={
                "build_id": build_id,
                "server_id": server_id,
                "started": started,
                "config_applied": config_applied,
                "runtime_started": runtime_started,
                "rollback_attempted": rollback_attempted,
                "rollback_succeeded": rollback_succeeded,
                "rollback_error": rollback_error,
                "error": error,
            },
        )
        return self.get_deployment(deployment_id)

    def rollback_deployment(self, deployment_id: str, *, start: bool = False) -> dict[str, Any]:
        self._require_local_execution("deployment_rollback")
        deployment = self.get_deployment(deployment_id)
        safe_previous = deployment.get("previous_manifest")
        if not isinstance(safe_previous, dict) or not safe_previous:
            raise ValueError("deployment has no previous manifest snapshot")
        previous = self._load_rollback_snapshot(deployment_id, safe_previous)
        server_id = str(previous.get("id") or deployment.get("server_id") or "")
        if not server_id:
            raise ValueError("previous manifest has no server id")
        try:
            self.configs.save_config(previous, expected_id=server_id, overwrite=True)
            runtime_manifest = self.configs.load_manifest(server_id)
            server = self.runtime.apply_manifest(runtime_manifest, start=start, source="deploy_rollback")
        except Exception as exc:  # noqa: BLE001 - rollback boundary should be observable
            self.observability.add_log("error", f"Rollback failed: {exc}", source="deployments", event_type="gate.deploy.rollback_failed", payload={"deployment_id": deployment_id, "server_id": server_id})
            raise
        started = bool(start and server.status == "running")
        self.observability.emit_event("gate.deploy.rollback", source="deployments", subject_type="deployment", subject_id=deployment_id, payload={"server_id": server_id, "started": started})
        return {"deployment": deployment, "server": server.model_dump(mode="json"), "message": "rolled_back"}

    def _run_build_job(self, build_id: str, upload: dict[str, Any], runtime: str, upload_root: Path, source_dir: Path, artifact_dir: Path, plan: dict[str, Any], timeout_seconds: int) -> None:
        upload_id = str(upload.get("id") or "")
        plan_steps = list(plan.get("steps") or [])
        commands: list[list[str]] = plan_commands(plan)
        step_states = _init_step_states(plan)
        logs: list[dict[str, Any]] = []
        status = "success"
        error: str | None = None
        manifest: dict[str, Any] = {}
        entrypoint: str | None = None
        try:
            self._raise_if_cancel_requested(build_id)
            self._set_build_status(build_id, "running")
            shutil.copytree(upload_root, source_dir, ignore=shutil.ignore_patterns(*IGNORED_COPY_DIRS), dirs_exist_ok=True)
            environment = _build_subprocess_environment(source_dir.parent)
            self._insert_build_log(build_id, sequence=self._next_build_log_sequence(build_id), phase="prepare", level="info", message=f"Build worker started for runtime={runtime} via IR plan ({len(commands)} step(s))", command=[], result=None)
            self.observability.emit_event("gate.build.started", source="builds", subject_type="build", subject_id=build_id, payload={"upload_id": upload_id, "runtime": runtime, "plan_steps": len(commands)})

            if not plan_steps:
                self._insert_build_log(build_id, sequence=self._next_build_log_sequence(build_id), phase="command", level="info", message="No install/build command required", command=[], result=None)
            else:
                self._execute_plan_dag(build_id, plan, plan_steps, step_states, source_dir, timeout_seconds, logs, environment)
            self._raise_if_cancel_requested(build_id)
            _copy_artifact(source_dir, artifact_dir)
            manifest = finalize_manifest(plan, upload, build_id, artifact_dir)
            entrypoint = _entrypoint(manifest)
        except BuildCancelled as exc:
            status = "cancelled"
            error = str(exc)
            _mark_pending_steps(step_states, "skipped")
            self._insert_build_log(build_id, sequence=self._next_build_log_sequence(build_id), phase="cancel", level="warning", message=error, command=[], result={"returncode": 130, "stdout": "", "stderr": error, "started_at": iso_now(), "finished_at": iso_now(), "duration_ms": 0})
            self.observability.add_log("warning", f"Build cancelled: {error}", source="builds", event_type="gate.build.cancelled", payload={"build_id": build_id, "upload_id": upload_id, "runtime": runtime})
        except Exception as exc:  # noqa: BLE001 - background worker must persist failures
            status = "failed"
            error = str(exc)
            _mark_pending_steps(step_states, "skipped")
            self._insert_build_log(build_id, sequence=self._next_build_log_sequence(build_id), phase="build", level="error", message=error, command=[], result={"returncode": 1, "stdout": "", "stderr": error, "started_at": iso_now(), "finished_at": iso_now(), "duration_ms": 0})
            self.observability.add_log("error", f"Build failed: {error}", source="builds", event_type="gate.build.failed", payload={"build_id": build_id, "upload_id": upload_id, "runtime": runtime, "failure_code": _failure_code(error)})
        else:
            self._insert_build_log(build_id, sequence=self._next_build_log_sequence(build_id), phase="build", level="info", message="Build completed", command=[], result={"returncode": 0, "stdout": "", "stderr": "", "started_at": iso_now(), "finished_at": iso_now(), "duration_ms": 0})
            self.observability.add_log("info", "Build completed", source="builds", event_type="gate.build.success", payload={"build_id": build_id, "upload_id": upload_id, "runtime": runtime, "command_count": len(commands)})
        self._persist_step_states(build_id, step_states)
        self._update_build(build_id, status, entrypoint, commands, logs, manifest, error)
        self.observability.emit_event(f"gate.build.{status}", source="builds", subject_type="build", subject_id=build_id, payload={"upload_id": upload_id, "runtime": runtime, "error": error, "failure_code": _failure_code(error) if error else None})

    def _persist_step_states(self, build_id: str, step_states: list[dict[str, Any]]) -> None:
        self.database.execute("UPDATE builds SET steps_json = ?, updated_at = ? WHERE id = ?", (_dumps(step_states), iso_now(), build_id))

    def _execute_plan_dag(self, build_id: str, plan: dict[str, Any], plan_steps: list[dict[str, Any]], step_states: list[dict[str, Any]], source_dir: Path, timeout_seconds: int, logs: list[dict[str, Any]], environment: dict[str, str]) -> None:
        """Run plan steps wave by wave, parallelizing independent steps.

        Dependencies (``depends_on``) serialize dependent steps into later waves;
        a linear install->build plan degrades to sequential execution. Fails fast:
        a failed step aborts scheduling of later waves, and the outer handler marks
        remaining pending steps as skipped.
        """

        waves = plan_waves(plan)
        for wave in waves:
            self._raise_if_cancel_requested(build_id)
            if len(wave) == 1:
                result = self._run_single_step(build_id, plan_steps[wave[0]], wave[0], step_states, source_dir, timeout_seconds, environment)
                logs.append(result)
                if result.get("cancelled"):
                    raise BuildCancelled("build cancelled by user request")
                if result["returncode"] != 0:
                    raise RuntimeError(_command_error(result))
                continue
            failure: dict[str, Any] | None = None
            cancelled = False
            with ThreadPoolExecutor(max_workers=min(len(wave), STEP_EXECUTOR_WORKERS), thread_name_prefix=f"gate-step-{build_id[:8]}") as pool:
                futures = {pool.submit(self._run_single_step, build_id, plan_steps[index], index, step_states, source_dir, timeout_seconds, environment): index for index in wave}
                for future in as_completed(futures):
                    result = future.result()
                    logs.append(result)
                    cancelled = cancelled or bool(result.get("cancelled"))
                    if result["returncode"] != 0 and failure is None:
                        failure = result
            if cancelled:
                raise BuildCancelled("build cancelled by user request")
            if failure is not None:
                raise RuntimeError(_command_error(failure))

    def _run_single_step(self, build_id: str, step: dict[str, Any], index: int, step_states: list[dict[str, Any]], source_dir: Path, timeout_seconds: int, environment: dict[str, str]) -> dict[str, Any]:
        command = list(step.get("command") or [])
        with self._step_lock:
            step_states[index]["status"] = "running"
            step_states[index]["started_at"] = iso_now()
            self._persist_step_states(build_id, step_states)
        result = _run_command(
            command,
            source_dir,
            timeout_seconds,
            environment,
            cancel_requested=lambda: self._is_cancel_requested(build_id),
        )
        with self._step_lock:
            state = step_states[index]
            state["returncode"] = result["returncode"]
            state["duration_ms"] = result["duration_ms"]
            state["finished_at"] = result["finished_at"]
            state["status"] = (
                "cancelled"
                if result.get("cancelled")
                else ("success" if result["returncode"] == 0 else "failed")
            )
            level = "error" if result["returncode"] != 0 else "info"
            message = _command_error(result) if result["returncode"] != 0 else f"command completed rc={result['returncode']}: {' '.join(command)}"
            self._insert_build_log(build_id, sequence=self._next_build_log_sequence(build_id), phase="command", level=level, message=message, command=command, result=result)
            self._persist_step_states(build_id, step_states)
        return result

    def _insert_build_record(
        self,
        build_id: str,
        upload_id: str,
        runtime: str,
        source_dir: Path,
        artifact_dir: Path,
        *,
        status: str,
        plan: dict[str, Any] | None = None,
        steps: list[dict[str, Any]] | None = None,
        source_sha256: str = "",
        plan_fingerprint: str = "",
        operation_id: str | None = None,
        owner_id: str | None = None,
    ) -> None:
        now = iso_now()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO builds (
                    id, upload_id, status, runtime, source_sha256,
                    plan_fingerprint, operation_id, source_dir, artifact_dir,
                    command_json, logs_json, manifest_json, plan_json, steps_json,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    build_id,
                    upload_id,
                    status,
                    runtime,
                    source_sha256,
                    plan_fingerprint,
                    operation_id or "",
                    str(source_dir),
                    str(artifact_dir),
                    "[]",
                    "[]",
                    "{}",
                    _dumps(plan or {}),
                    _dumps(steps or []),
                    now,
                    now,
                ),
            )
            if owner_id:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO project_delivery_resource_owners (
                        resource_type, resource_id, owner_id, created_at, updated_at
                    ) VALUES ('build', ?, ?, ?, ?)
                    """,
                    (build_id, owner_id, now, now),
                )
            connection.commit()

    def _record_build(
        self,
        build_id: str,
        upload_id: str,
        runtime: str,
        source_dir: Path,
        artifact_dir: Path,
        status: str,
        commands: list[list[str]],
        logs: list[dict[str, Any]],
        manifest: dict[str, Any],
        error: str | None,
        *,
        source_sha256: str = "",
        plan_fingerprint: str = "",
        operation_id: str | None = None,
        owner_id: str | None = None,
    ) -> dict[str, Any]:
        now = iso_now()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO builds (
                    id, upload_id, status, runtime, source_sha256,
                    plan_fingerprint, operation_id, source_dir, artifact_dir,
                    command_json, logs_json, manifest_json, error, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    build_id,
                    upload_id,
                    status,
                    runtime,
                    source_sha256,
                    plan_fingerprint,
                    operation_id or "",
                    str(source_dir),
                    str(artifact_dir),
                    _dumps(commands),
                    _dumps(logs),
                    _dumps(manifest),
                    error,
                    now,
                    now,
                ),
            )
            if owner_id:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO project_delivery_resource_owners (
                        resource_type, resource_id, owner_id, created_at, updated_at
                    ) VALUES ('build', ?, ?, ?, ?)
                    """,
                    (build_id, owner_id, now, now),
                )
            connection.commit()
        self._insert_build_log(build_id, sequence=0, phase="build", level="warning" if status == "unsupported" else "error", message=error or status, command=[], result={"returncode": 1, "stdout": "", "stderr": error or status, "started_at": now, "finished_at": now, "duration_ms": 0})
        self.observability.emit_event(f"gate.build.{status}", source="builds", subject_type="build", subject_id=build_id, payload={"upload_id": upload_id, "runtime": runtime, "error": error, "failure_code": _failure_code(error) if error else None})
        if error:
            self.observability.add_log("warning" if status == "unsupported" else "error", f"Build {status}: {error}", source="builds", event_type=f"gate.build.{status}", payload={"build_id": build_id, "upload_id": upload_id, "runtime": runtime, "failure_code": _failure_code(error)})
        return self.get_build(build_id)

    def _set_build_status(self, build_id: str, status: str) -> None:
        self.database.execute("UPDATE builds SET status = ?, updated_at = ? WHERE id = ?", (status, iso_now(), build_id))

    def _update_build(self, build_id: str, status: str, entrypoint: str | None, commands: list[list[str]], logs: list[dict[str, Any]], manifest: dict[str, Any], error: str | None) -> None:
        self.database.execute(
            """
            UPDATE builds SET status = ?, entrypoint = ?, command_json = ?, logs_json = ?, manifest_json = ?, error = ?, updated_at = ? WHERE id = ?
            """,
            (status, entrypoint, _dumps(commands), _dumps(logs), _dumps(manifest), error, iso_now(), build_id),
        )

    def _insert_build_log(self, build_id: str, *, sequence: int, phase: str, level: str, message: str, command: list[str], result: dict[str, Any] | None) -> None:
        now = iso_now()
        result = result or {}
        self.database.execute(
            """
            INSERT INTO build_logs (id, build_id, sequence, phase, level, message, command_json, returncode, stdout, stderr, duration_ms, started_at, finished_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid4().hex,
                build_id,
                sequence,
                phase,
                level,
                message,
                _dumps(command),
                result.get("returncode"),
                str(result.get("stdout") or "")[-MAX_CAPTURE_CHARS:],
                str(result.get("stderr") or "")[-MAX_CAPTURE_CHARS:],
                result.get("duration_ms"),
                str(result.get("started_at") or now),
                result.get("finished_at"),
                now,
            ),
        )

    def _next_build_log_sequence(self, build_id: str) -> int:
        row = self.database.query_one("SELECT MAX(sequence) AS max_sequence FROM build_logs WHERE build_id = ?", (build_id,))
        return int(row["max_sequence"] or 0) + 1 if row else 1

    def _raise_if_cancel_requested(self, build_id: str) -> None:
        if self._is_cancel_requested(build_id):
            raise BuildCancelled("build cancelled by user request")

    def _is_cancel_requested(self, build_id: str) -> bool:
        return self.get_build(build_id)["status"] == "cancel_requested"


def _build_subprocess_environment(build_dir: Path) -> dict[str, str]:
    """返回单个构建专用的最小子进程环境，不继承服务进程环境。"""

    isolated_root = build_dir / ".subprocess-env"
    home_dir = isolated_root / "home"
    temp_dir = isolated_root / "tmp"
    npm_cache_dir = isolated_root / "npm-cache"
    pip_cache_dir = isolated_root / "pip-cache"
    pycache_dir = isolated_root / "pycache"
    xdg_cache_dir = isolated_root / "xdg-cache"
    xdg_config_dir = isolated_root / "xdg-config"
    for directory in (home_dir, temp_dir, npm_cache_dir, pip_cache_dir, pycache_dir, xdg_cache_dir, xdg_config_dir):
        directory.mkdir(parents=True, exist_ok=True)
    npm_user_config_file = isolated_root / "npmrc"
    npm_global_config_file = isolated_root / "npm-global.npmrc"
    npm_user_config_file.write_text("", encoding="utf-8")
    npm_global_config_file.write_text("", encoding="utf-8")

    environment = {
        key: value
        for key in SUBPROCESS_ENV_PASSTHROUGH
        if (value := os.environ.get(key))
    }
    environment.update(
        {
            "HOME": str(home_dir),
            "USERPROFILE": str(home_dir),
            "TMP": str(temp_dir),
            "TEMP": str(temp_dir),
            "TMPDIR": str(temp_dir),
            "npm_config_cache": str(npm_cache_dir),
            "NPM_CONFIG_USERCONFIG": str(npm_user_config_file),
            "NPM_CONFIG_GLOBALCONFIG": str(npm_global_config_file),
            "NPM_CONFIG_AUDIT": "false",
            "NPM_CONFIG_FUND": "false",
            "NPM_CONFIG_UPDATE_NOTIFIER": "false",
            "PIP_CACHE_DIR": str(pip_cache_dir),
            "PIP_CONFIG_FILE": os.devnull,
            "PIP_NO_INPUT": "1",
            "PIP_DISABLE_PIP_VERSION_CHECK": "1",
            "PYTHONPYCACHEPREFIX": str(pycache_dir),
            "PYTHONNOUSERSITE": "1",
            "XDG_CACHE_HOME": str(xdg_cache_dir),
            "XDG_CONFIG_HOME": str(xdg_config_dir),
        }
    )
    return environment


def _run_command(
    command: list[str],
    cwd: Path,
    timeout_seconds: int,
    environment: dict[str, str],
    *,
    cancel_requested: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Run one build command with bounded output and a process-group boundary."""

    started_at = iso_now()
    monotonic_started = time.monotonic()
    stdout_tail = _BoundedByteTail(MAX_CAPTURE_BYTES)
    stderr_tail = _BoundedByteTail(MAX_CAPTURE_BYTES)
    process: subprocess.Popen[bytes] | None = None

    def result(
        returncode: int,
        *,
        stderr_suffix: str = "",
        cancelled: bool = False,
    ) -> dict[str, Any]:
        stderr = stderr_tail.text()
        if stderr_suffix:
            stderr = f"{stderr}\n{stderr_suffix}".strip()[-MAX_CAPTURE_CHARS:]
        return {
            "command": command,
            "returncode": returncode,
            "stdout": stdout_tail.text(),
            "stderr": stderr,
            "duration_ms": int((time.monotonic() - monotonic_started) * 1000),
            "started_at": started_at,
            "finished_at": iso_now(),
            "cancelled": cancelled,
        }

    try:
        if cancel_requested is not None and cancel_requested():
            return result(
                130,
                stderr_suffix="command cancelled before process start",
                cancelled=True,
            )
        popen_options: dict[str, Any] = {
            "cwd": str(cwd),
            "env": environment,
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": False,
        }
        if os.name == "nt":
            popen_options["creationflags"] = int(
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            )
        else:
            popen_options["start_new_session"] = True
        process = subprocess.Popen(command, **popen_options)
    except FileNotFoundError as exc:
        return result(127, stderr_suffix=f"command not found: {command[0]} ({exc})")

    assert process.stdout is not None
    assert process.stderr is not None
    stdout_thread = threading.Thread(
        target=_drain_process_stream,
        args=(process.stdout, stdout_tail),
        name=f"gate-build-stdout-{process.pid}",
        daemon=True,
    )
    stderr_thread = threading.Thread(
        target=_drain_process_stream,
        args=(process.stderr, stderr_tail),
        name=f"gate-build-stderr-{process.pid}",
        daemon=True,
    )
    stdout_thread.start()
    stderr_thread.start()

    deadline = monotonic_started + max(float(timeout_seconds), 0.001)
    termination_reason: str | None = None
    cancelled = False
    try:
        while process.poll() is None:
            if cancel_requested is not None and cancel_requested():
                cancelled = True
                termination_reason = "command cancelled by user request"
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                termination_reason = f"command timed out after {timeout_seconds}s"
                break
            time.sleep(min(PROCESS_POLL_INTERVAL_SECONDS, remaining))
    except BaseException:
        _terminate_process_group(process)
        _finish_stream_threads(process, stdout_thread, stderr_thread)
        raise

    if termination_reason is not None:
        _terminate_process_group(process)

    _finish_stream_threads(process, stdout_thread, stderr_thread)
    if cancelled:
        return result(130, stderr_suffix=termination_reason or "command cancelled", cancelled=True)
    if termination_reason is not None:
        return result(124, stderr_suffix=termination_reason)
    return result(int(process.returncode or 0))


class _BoundedByteTail:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self._buffer = bytearray()
        self._lock = threading.Lock()

    def append(self, chunk: bytes) -> None:
        with self._lock:
            if len(chunk) >= self.limit:
                self._buffer = bytearray(chunk[-self.limit :])
                return
            self._buffer.extend(chunk)
            overflow = len(self._buffer) - self.limit
            if overflow > 0:
                del self._buffer[:overflow]

    def text(self) -> str:
        with self._lock:
            raw = bytes(self._buffer)
        return raw.decode("utf-8", "replace")[-MAX_CAPTURE_CHARS:]


def _drain_process_stream(stream: Any, tail: _BoundedByteTail) -> None:
    try:
        while True:
            chunk = stream.read(PROCESS_READ_CHUNK_BYTES)
            if not chunk:
                return
            tail.append(bytes(chunk))
    except (OSError, ValueError):
        return


def _terminate_process_group(process: subprocess.Popen[bytes]) -> None:
    """Terminate the isolated command group, escalating after a short grace."""

    if os.name == "nt":
        try:
            process.send_signal(getattr(signal, "CTRL_BREAK_EVENT", signal.SIGTERM))
        except (OSError, ValueError):
            try:
                process.terminate()
            except OSError:
                pass
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError:
            try:
                process.terminate()
            except OSError:
                pass

    try:
        process.wait(timeout=PROCESS_TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass

    # Waiting for the direct child is not enough: a child may have ignored the
    # graceful signal while remaining in the isolated group.
    if os.name == "nt":
        if process.poll() is None:
            try:
                process.kill()
            except OSError:
                pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            if process.poll() is None:
                try:
                    process.kill()
                except OSError:
                    pass
    try:
        process.wait(timeout=PROCESS_TERMINATE_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        pass


def _finish_stream_threads(
    process: subprocess.Popen[bytes],
    stdout_thread: threading.Thread,
    stderr_thread: threading.Thread,
) -> None:
    for thread in (stdout_thread, stderr_thread):
        thread.join(timeout=PROCESS_TERMINATE_GRACE_SECONDS)
    if stdout_thread.is_alive() or stderr_thread.is_alive():
        # A descendant inherited a pipe after the direct child exited. It is in
        # the same isolated group and must not outlive the build step.
        _terminate_process_group(process)
        for stream in (process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        for thread in (stdout_thread, stderr_thread):
            thread.join(timeout=PROCESS_TERMINATE_GRACE_SECONDS)


def _copy_artifact(source_dir: Path, artifact_dir: Path) -> None:
    if artifact_dir.exists():
        shutil.rmtree(artifact_dir)
    # 安装步骤在 source_dir 生成 node_modules；运行制品必须保留它，否则
    # npm start 虽然能找到入口文件，但会在 server/discover 前因依赖缺失退出。
    shutil.copytree(source_dir, artifact_dir, ignore=shutil.ignore_patterns(*ARTIFACT_IGNORED_COPY_DIRS))


def _command_error(result: dict[str, Any]) -> str:
    command = " ".join(str(part) for part in result.get("command", []))
    stderr = str(result.get("stderr") or "").strip()
    stdout = str(result.get("stdout") or "").strip()
    detail = stderr or stdout or "no output"
    return f"command failed rc={result.get('returncode')}: {command}; {detail[-1200:]}"


def _init_step_states(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """Build the initial per-step runtime view from an IR plan."""

    states: list[dict[str, Any]] = []
    for index, step in enumerate(plan.get("steps") or []):
        states.append({
            "index": index,
            "id": step.get("id"),
            "phase": step.get("phase"),
            "command": list(step.get("command") or []),
            "depends_on": list(step.get("depends_on") or []),
            "status": "pending",
            "returncode": None,
            "duration_ms": None,
            "started_at": None,
            "finished_at": None,
        })
    return states


def _mark_pending_steps(step_states: list[dict[str, Any]], status: str) -> None:
    for state in step_states:
        if state.get("status") in {"pending", "running"}:
            state["status"] = status


def _fingerprint_summary(fingerprint: dict[str, Any]) -> dict[str, Any]:
    """Return a compact fingerprint view for API responses (drops verbose stats)."""

    raw_key_files = fingerprint.get("key_files")
    key_files: dict[str, Any] = raw_key_files if isinstance(raw_key_files, dict) else {}
    raw_tools = fingerprint.get("tools")
    tools: dict[str, Any] = raw_tools if isinstance(raw_tools, dict) else {}
    return {
        "file_count": fingerprint.get("file_count"),
        "key_files": sorted(str(name) for name in key_files.keys()),
        "tools": tools,
        "runtime_override": fingerprint.get("runtime_override"),
        "project_root": fingerprint.get("project_root"),
    }


def _evaluate_build_guard(preflight: dict[str, Any], runtime: str) -> dict[str, str] | None:
    """Return a block descriptor when a Build must be rejected before creation.

    The gate makes preflight authoritative: unknown/ambiguous/docker runtimes or
    any preflight error stop the request instead of persisting a dead Build.
    """

    if preflight.get("status") == "error":
        return {"code": "preflight_failed", "message": _preflight_error(preflight)}
    if runtime == "docker":
        return {
            "code": "unsupported_runtime",
            "message": (
                "Container-image project builds are not supported. Build a Node or Python project, "
                "or configure a reviewed digest-pinned image as a managed_container downstream."
            ),
        }
    if runtime not in SUPPORTED_LOCAL_RUNTIMES:
        return {"code": "runtime_not_selected", "message": f"Runtime could not be resolved for local build (runtime={runtime}). Run Build Preflight and select runtime=node or runtime=python, then retry."}
    return None


def _preflight_error(preflight: dict[str, Any]) -> str:
    errors = [f"{check.get('id')}: {check.get('message')}" for check in preflight.get("checks", []) if check.get("status") == "error"]
    detail = "; ".join(errors[:6]) or "unknown preflight error"
    return f"Build preflight failed: {detail}"


def _failure_code(error: str | None) -> str | None:
    if not error:
        return None
    text = error.lower()
    if "preflight failed" in text:
        return "preflight_failed"
    if "cancelled" in text or "canceled" in text:
        return "cancelled"
    if "command not found" in text:
        return "command_not_found"
    if "timed out" in text or "timeout" in text:
        return "command_timeout"
    if "could not be detected" in text or "project runtime" in text:
        return "runtime_not_detected"
    if "unsupported runtime" in text or "container-image project builds are not supported" in text:
        return "unsupported_runtime"
    if "node entrypoint not found" in text:
        return "node_entrypoint_missing"
    if "python entrypoint not found" in text:
        return "python_entrypoint_missing"
    if "npm install" in text or "npm ci" in text or "pip install" in text:
        return "install_failed"
    if "npm run build" in text:
        return "build_script_failed"
    return "build_failed"


def _failure_hint(status: str, error: str | None) -> dict[str, str] | None:
    if status not in {"failed", "unsupported", "cancelled"} and not error:
        return None
    code = _failure_code(error) or status
    hints = {
        "preflight_failed": ("Build preflight failed", "Fix the failed preflight checks first, such as missing node/npm/python/pip or an invalid project root."),
        "cancelled": (
            "Build cancelled",
            "A stop request was sent and the running command and its process group were terminated; confirm the terminal build state before retrying.",
        ),
        "command_not_found": ("Command not found", "The runtime command is missing in the container or host. Install the required binary, or use an image that contains npm, node, or python."),
        "command_timeout": ("Command timeout", "The install or build command exceeded timeout_seconds. Increase timeout_seconds or reduce dependency/build work."),
        "runtime_not_detected": ("Runtime not detected", "The upload could not be recognized as a Node, Python, or Docker project. Run Build Preflight, check the project root, or manually select runtime=node/python."),
        "unsupported_runtime": (
            "Unsupported runtime",
            "Build a Node or Python project, or configure a reviewed digest-pinned image as a managed_container downstream.",
        ),
        "node_entrypoint_missing": ("Node entrypoint missing", "Add package.json scripts.start, or ensure dist/index.js, index.js, or src/index.js exists after build."),
        "python_entrypoint_missing": ("Python entrypoint missing", "Add server.py, main.py, app.py, or provide an analysis.python_entrypoint in the uploaded project."),
        "install_failed": ("Install failed", "Dependency installation failed. Check stdout/stderr for registry, proxy, package-lock, or requirements issues."),
        "build_script_failed": ("Build script failed", "npm run build failed. Check stderr and the package.json build script."),
        "build_failed": ("Build failed", "Review the latest stderr and command log for details."),
    }
    title, suggestion = hints.get(code, hints["build_failed"])
    return {"code": code, "title": title, "suggestion": suggestion}


def _manifest_references_build(manifest: dict[str, Any], build_id: str, artifact_dir: Path) -> bool:
    """判断 Manifest 是否仍依赖指定构建制品。"""

    if not isinstance(manifest, dict):
        return False
    raw_analysis = manifest.get("analysis")
    analysis: dict[str, Any] = raw_analysis if isinstance(raw_analysis, dict) else {}
    if str(analysis.get("build_id") or "") == build_id:
        return True

    raw_launch = manifest.get("launch")
    launch: dict[str, Any] = raw_launch if isinstance(raw_launch, dict) else {}
    cwd = str(launch.get("cwd") or "").strip()
    if not cwd:
        return False
    try:
        candidate = Path(cwd).resolve()
        artifact_root = artifact_dir.resolve()
        return candidate == artifact_root or artifact_root in candidate.parents
    except (OSError, RuntimeError, ValueError):
        return False


def _entrypoint(manifest: dict[str, Any]) -> str | None:
    raw_launch = manifest.get("launch")
    launch: dict[str, Any] = raw_launch if isinstance(raw_launch, dict) else {}
    raw_args = launch.get("args")
    args: list[Any] = raw_args if isinstance(raw_args, list) else []
    if args:
        return str(args[-1])
    return str(launch.get("command") or "") or None


def _contains_masked_value(value: Any) -> bool:
    if value == "***":
        return True
    if isinstance(value, dict):
        return any(_contains_masked_value(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_masked_value(item) for item in value)
    return False


def _loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _build_row(row: Any) -> dict[str, Any]:
    error = row["error"]
    status = row["status"]
    return {"id": row["id"], "upload_id": row["upload_id"], "status": status, "runtime": row["runtime"], "source_sha256": row["source_sha256"], "plan_fingerprint": row["plan_fingerprint"], "operation_id": row["operation_id"], "source_dir": row["source_dir"], "artifact_dir": row["artifact_dir"], "entrypoint": row["entrypoint"], "commands": _loads(row["command_json"], []), "logs": _loads(row["logs_json"], []), "manifest": _loads(row["manifest_json"], {}), "plan": _loads(row["plan_json"], {}), "steps": _loads(row["steps_json"], []), "error": error, "failure_hint": _failure_hint(status, error), "created_at": row["created_at"], "updated_at": row["updated_at"]}


def _build_log_row(row: Any) -> dict[str, Any]:
    return {"id": row["id"], "build_id": row["build_id"], "sequence": row["sequence"], "phase": row["phase"], "level": row["level"], "message": row["message"], "command": _loads(row["command_json"], []), "returncode": row["returncode"], "stdout": row["stdout"], "stderr": row["stderr"], "duration_ms": row["duration_ms"], "started_at": row["started_at"], "finished_at": row["finished_at"], "created_at": row["created_at"]}


def _deployment_row(row: Any) -> dict[str, Any]:
    rollback_succeeded = row["rollback_succeeded"]
    return {"id": row["id"], "build_id": row["build_id"], "server_id": row["server_id"], "status": row["status"], "manifest": _loads(row["manifest_json"], {}), "previous_manifest": _loads(row["previous_manifest_json"], None), "config_path": row["config_path"], "started": bool(row["started"]), "config_applied": bool(row["config_applied"]), "runtime_started": bool(row["runtime_started"]), "rollback_attempted": bool(row["rollback_attempted"]), "rollback_succeeded": None if rollback_succeeded is None else bool(rollback_succeeded), "rollback_error": row["rollback_error"], "error": row["error"], "created_at": row["created_at"], "updated_at": row["updated_at"]}

"""Git acquisition joins the existing digest/idempotency/ownership delivery service."""

from __future__ import annotations

import hashlib
import json
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Literal
from uuid import uuid4

from pydantic import Field

from lingshu_gate.build_deploy import LocalExecutionBlocked
from lingshu_gate.application.delivery_drafts import DeliveryDraftRequest
from lingshu_gate.git_source import COMMIT_RE, GIT_ENVIRONMENT_POLICY, GIT_POLICY, GitSourceInput, digest_json, repository_rule, snapshot_inventory
from lingshu_gate.network_settings import PROFILE_ID, NetworkSelection, NetworkSettingsStore, StrictModel, now, require_network_permission
from lingshu_gate.ports.safe_network_executor import TEST_TARGETS, SafeExecutionCancelled, SafeNetworkExecutor, require_proxy_support, require_safe_executor
from lingshu_gate.project_delivery_mcp import IDEMPOTENCY_PATTERN, ProjectDeliveryMcpService, _definition, _parse_input
from lingshu_gate.project_uploads import MAX_EXTRACTED_BYTES, MAX_FILES, MAX_ZIP_BYTES
from lingshu_gate.registry import ToolExecutionError, ToolInvocationContext, ToolRegistry

ACTIVE_IMPORT_STATUSES = {"queued", "running", "cancel_requested"}


class _ImportCancelled(Exception):
    """Coordinator cancelled before execution or after the executor returned."""


class GitImportCreate(StrictModel):
    plan_id: str = Field(min_length=16, max_length=64)
    plan_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(pattern=IDEMPOTENCY_PATTERN)
    confirmed: Literal[True]


class GitImportStatus(StrictModel):
    import_id: str = Field(min_length=16, max_length=64)


class GitImportCancel(GitImportStatus):
    idempotency_key: str = Field(pattern=IDEMPOTENCY_PATTERN)
    confirmed: Literal[True]


class ProxyTest(StrictModel):
    profile_id: str = Field(pattern=PROFILE_ID)
    version: int = Field(ge=1)
    target_id: Literal["github", "npm", "python"]
    confirmed: Literal[True]


class GitImportService:
    def __init__(self, delivery: ProjectDeliveryMcpService, network: NetworkSettingsStore, *, executor: SafeNetworkExecutor | None = None) -> None:
        self.delivery = delivery
        self.database = delivery.database
        self.network = network
        self.executor = executor
        self._lock = threading.RLock()
        self._cancels: dict[str, threading.Event] = {}
        self._probe_last: dict[str, float] = {}
        self._probe_gate = threading.BoundedSemaphore(1)
        # The supported single Gate process owns these in-memory execution
        # handles. Persist orphaned coordinator outcomes before accepting work.
        self._reconcile_interrupted()

    def _reconcile_interrupted(self, import_id: str | None = None) -> None:
        recovered: list[tuple[str, str]] = []
        with self._lock, self.database.session() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute("SELECT id,status,progress_json FROM git_imports WHERE status IN ('queued','running','cancel_requested') AND (? IS NULL OR id=?)", (import_id, import_id)).fetchall()
            for row in rows:
                if row["id"] in self._cancels:
                    continue
                progress = json.loads(row["progress_json"])
                progress.append({"phase": "reconcile", "status": "interrupted", "previous_status": row["status"], "execution_state": "unknown"})
                connection.execute("UPDATE git_imports SET status='interrupted',error_code='operation_interrupted',progress_json=?,updated_at=? WHERE id=?", (json.dumps(progress[-12:]), now(), row["id"]))
                recovered.append((row["id"], row["status"]))
        for recovered_id, previous_status in recovered:
            self.delivery.observability.emit_event("gate.git.interrupted", source="projects", subject_type="git_import", subject_id=recovered_id, payload={"previous_status": previous_status, "execution_state": "unknown", "execution_terminated": False})

    def _permission(self, context: ToolInvocationContext, *, write: bool = False) -> None:
        for permission in ("operations.manage", "network.use") + (("tools.invoke",) if write else ()):
            require_network_permission(context.permissions, permission)
            for scopes in ((context.scopes,) if context.auth_type in {"token", "oauth"} else ()) + ((context.delegated_scopes,) if context.delegated_scopes is not None else ()):
                require_network_permission(scopes, permission)

    def _executor(self) -> SafeNetworkExecutor:
        try:
            self.delivery.builds._require_local_execution("git/network")
        except LocalExecutionBlocked as exc:
            raise ToolExecutionError(exc.code, exc.message, next_action="Use an authorized local execution role with a reviewed isolated executor; Core execution remains disabled.") from None
        return require_safe_executor(self.executor)

    def plan(self, arguments: dict[str, Any], context: ToolInvocationContext) -> dict[str, Any]:
        self._permission(context)
        source = _parse_input(GitSourceInput, arguments)
        frozen = self.network.freeze(source.git_network, source.install_network)
        rule = repository_rule(source.repository_url, frozen["git_hosts"])
        base = {"source": source.model_dump(), "network": frozen, "host_rule": rule, "git_config": GIT_POLICY, "environment_policy": GIT_ENVIRONMENT_POLICY, "limits": {"compressed_bytes": MAX_ZIP_BYTES, "expanded_bytes": MAX_EXTRACTED_BYTES, "files": MAX_FILES, "resolve_seconds": 15, "fetch_seconds": 120, "export_seconds": 30, "retry_count": 0}, "credential_revision": self.network._credential_revision(source.credential_ref)}
        try:
            executor = self._executor()
        except ToolExecutionError as exc:
            return {"status": "blocked", "source": source.model_dump(), "network": frozen, "commit_sha": None, "validation": {"ok": False}, **exc.to_payload()}
        self._check_scheme(executor, frozen, "git", "git")
        material = self._material(base)
        try:
            sha = executor.resolve_commit(base, material=material, timeout_seconds=15)
        except Exception:
            raise ToolExecutionError("git_resolution_failed", "Commit resolution failed in the execution environment", next_action="Inspect executor status and repository access; do not reuse an unconfirmed moving ref.") from None
        finally:
            material.clear()
        if not COMMIT_RE.fullmatch(sha) or (source.ref_type == "commit" and source.ref != sha):
            raise ToolExecutionError("git_commit_mismatch", "Executor did not resolve the exact full commit", next_action="Review source and executor output.")
        plan = {**base, "commit_sha": sha}
        plan_id = uuid4().hex
        digest = digest_json(plan)
        expires = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        with self.database.session() as connection:
            connection.execute("INSERT INTO git_import_plans VALUES(?,?,?,?,?,?)", (plan_id, context.actor_id, digest, json.dumps(plan), expires, now()))
            self.network._prune_references(connection)
            self.network._retain(connection, frozen, "git_plan", plan_id)
        return {"status": "ready", "plan_id": plan_id, "plan_digest": digest, "expires_at": expires, "plan": plan, "validation": {"ok": True}, "confirmation_scope": "source acquisition only; build/deploy/start remain separate"}

    def _check_scheme(self, executor: SafeNetworkExecutor, frozen: dict[str, Any], phase: str, kind: str) -> None:
        selected = frozen[phase]
        scheme = self.network._version(selected["profile_id"], selected["version"])["scheme"] if selected["mode"] == "profile" else None
        require_proxy_support(executor, kind, scheme)

    def _material(self, plan: dict[str, Any]) -> dict[str, Any]:
        material = self.network.execution_material(plan["network"], "git")
        ref = plan["source"]["credential_ref"]
        if self.network._credential_revision(ref) != plan["credential_revision"]:
            raise ToolExecutionError("git_credential_changed", "Repository credential revision changed", next_action="Re-plan and confirm acquisition again.")
        material["git_credential"] = self.network.credentials.resolve_value(ref)
        return material

    def create(self, arguments: dict[str, Any], context: ToolInvocationContext) -> dict[str, Any]:
        self._permission(context, write=True)
        body = _parse_input(GitImportCreate, arguments)

        def action(operation_id: str) -> tuple[dict[str, Any], str | None]:
            executor = self._executor()
            row = self.database.query_one("SELECT * FROM git_import_plans WHERE id=? AND actor_id=?", (body.plan_id, context.actor_id))
            if row is None:
                raise ToolExecutionError("git_plan_not_found", "Import plan is unavailable for this actor", next_action="Create a new plan.")
            if row["digest"] != body.plan_digest or datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
                raise ToolExecutionError("git_plan_conflict", "Import plan changed or expired", next_action="Create and confirm a fresh plan.")
            plan = json.loads(row["plan_json"])
            self.network.validate_frozen(plan["network"])
            self._check_scheme(executor, plan["network"], "git", "git")
            # Recheck references before queuing without copying credential values.
            if self.network._credential_revision(plan["source"]["credential_ref"]) != plan["credential_revision"]:
                raise ToolExecutionError("git_credential_changed", "Repository credential changed", next_action="Re-plan and confirm.")
            import_id = uuid4().hex
            self._reconcile_interrupted()
            with self._lock, self.database.session() as connection:
                connection.execute("BEGIN IMMEDIATE")
                active = connection.execute("SELECT count(*) FROM git_imports WHERE status IN ('queued','running','cancel_requested')").fetchone()[0]
                if active >= 4:
                    raise ToolExecutionError("git_queue_full", "Import queue is full", next_action="Wait for existing imports; do not automatically replay this write.")
                connection.execute("INSERT INTO git_imports(id,plan_id,actor_id,status,upload_id,error_code,progress_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)", (import_id, body.plan_id, context.actor_id, "queued", None, None, json.dumps([{"phase": "queue", "status": "queued"}]), now(), now()))
                self.network._retain(connection, plan["network"], "git_import", import_id)
                self._cancels[import_id] = threading.Event()
            try:
                self.delivery.builds.executor.submit(self._run, import_id, plan, executor)
            except Exception:
                with self.database.session() as connection:
                    connection.execute("UPDATE git_imports SET status='failed', error_code='git_queue_failed',updated_at=? WHERE id=?", (now(), import_id))
                    self.network._release(connection, "git_import", import_id)
                with self._lock:
                    self._cancels.pop(import_id, None)
                raise ToolExecutionError("git_queue_failed", "Import could not be queued", next_action="Inspect import status before any new write.") from None
            self.delivery.observability.emit_event("gate.git.queued", source="projects", subject_type="git_import", subject_id=import_id, payload={"actor_id": context.actor_id, "operation_id": operation_id, "commit_sha": plan["commit_sha"], "plan_digest": body.plan_digest})
            return self.status({"import_id": import_id}, context), import_id

        result = self.delivery._run_idempotent(context, "gate_project_git_import", body.idempotency_key, arguments, "git_import", action)
        return {**result, **self.status({"import_id": result["import_id"]}, context)}

    def _run(self, import_id: str, plan: dict[str, Any], executor: SafeNetworkExecutor) -> None:
        with self._lock:
            row = self.database.query_one("SELECT status FROM git_imports WHERE id=?", (import_id,))
            cancel = self._cancels.get(import_id)
            if row is None or row["status"] not in ACTIVE_IMPORT_STATUSES or cancel is None:
                # A delayed callback cannot resurrect a reconciled interruption.
                self._cancels.pop(import_id, None)
                return
        upload_id: str | None = None
        status = "failed"
        error: str | None = None
        phase = "fetch"
        material: dict[str, Any] = {}
        scan_material: dict[str, Any] = {}
        try:
            if cancel.is_set():
                raise _ImportCancelled
            self._progress(import_id, "fetch", "running")
            material = self._material(plan)
            content = executor.export_snapshot(plan, material=material, cancel=cancel)
            if cancel.is_set():
                raise _ImportCancelled
            self._progress(import_id, "validate", "running")
            phase = "validate"
            scan_material = self.network.execution_material(plan["network"], "install")
            for prefix in ("npm", "python"):
                scan_material[prefix] = self.network.credentials.resolve_value(plan["network"].get(f"{prefix}_credential_ref"))
            file_digest, inventory = snapshot_inventory(content, plan["source"]["project_root"], forbidden_values=[value for value in [*material.values(), *scan_material.values()] if isinstance(value, str)])
            if cancel.is_set():
                raise _ImportCancelled
            # Publication/cancellation are serialized: never commit a cancelled snapshot.
            with self._lock:
                if cancel.is_set():
                    raise _ImportCancelled
                self._progress(import_id, "snapshot", "running")
                phase = "snapshot"
                upload = self.delivery.uploads.save_zip(filename=f"git-{plan['commit_sha'][:12]}.zip", content=content)
                upload_id = upload["id"]
                selected_root = self.delivery.uploads.root / upload_id / "extracted" / plan["source"]["project_root"]
                if not selected_root.is_dir():
                    raise ValueError("selected project root is unavailable after upload validation")
                analysis = upload["analysis"]
                analysis.update({"source_sha256": hashlib.sha256(content).hexdigest(), "file_list_sha256": file_digest, "source_size_bytes": len(content), "included_files": inventory, "git_source": {"repository_url": plan["source"]["repository_url"], "ref_type": plan["source"]["ref_type"], "ref": plan["source"]["ref"], "commit_sha": plan["commit_sha"], "import_id": import_id, "project_root": plan["source"]["project_root"]}, "delivery_network": plan["network"], "runtime_template": plan["source"]["runtime_template"], "project_root_dir": str(selected_root)})
                with self.database.session() as connection:
                    connection.execute("UPDATE project_uploads SET analysis_json=?, root_dir=? WHERE id=?", (json.dumps(analysis), str(selected_root), upload_id))
                    row = connection.execute("SELECT actor_id FROM git_imports WHERE id=?", (import_id,)).fetchone()
                    if row is None:
                        raise ValueError("import ownership missing")
                    connection.execute("INSERT INTO project_delivery_resource_owners VALUES('upload',?,?,?,?)", (upload_id, row[0], now(), now()))
                    self.network._retain(connection, plan["network"], "upload", upload_id)
                self.delivery.delivery_drafts.save(upload_id, row[0], DeliveryDraftRequest(expected_revision=0, runtime_override=plan["source"]["runtime_template"], project_root="."))
                status = "success"
                self.database.execute("UPDATE git_imports SET status='success',upload_id=?,updated_at=? WHERE id=?", (upload_id, now(), import_id))
        except (_ImportCancelled, SafeExecutionCancelled):
            status, error = "cancelled", "git_import_cancelled"
        except InterruptedError:
            status, error = "interrupted", "operation_interrupted"
        except TimeoutError:
            error = "git_import_timeout"
        except Exception:
            # Executor exceptions/output can contain credentials. Persist stable code only.
            error = "git_snapshot_rejected" if phase == "validate" else "git_import_failed"
        finally:
            material.clear()
            scan_material.clear()
            if status != "success" and upload_id:
                # Failed publication is not an accepted source. Remove the orphan
                # through the same upload service, never leave it available to build.
                try:
                    self.delivery.uploads.delete_upload(upload_id)
                except Exception:
                    self.database.execute("UPDATE project_uploads SET status='git_import_incomplete' WHERE id=?", (upload_id,))
            with self._lock:
                self._cancels.pop(import_id, None)
                with self.database.session() as connection:
                    connection.execute("UPDATE git_imports SET status=?,upload_id=?,error_code=?,updated_at=? WHERE id=?", (status, upload_id if status == "success" else None, error, now(), import_id))
                    if status != "interrupted":
                        self.network._release(connection, "git_import", import_id)
            self._progress(import_id, "complete", status)
            self.delivery.observability.emit_event(f"gate.git.{status}", source="projects", subject_type="git_import", subject_id=import_id, payload={"commit_sha": plan["commit_sha"], "error_code": error})

    def _progress(self, import_id: str, phase: str, status: str) -> None:
        with self._lock:
            row = self.database.query_one("SELECT progress_json FROM git_imports WHERE id=?", (import_id,))
            if row is None:
                raise ValueError("import progress missing")
            progress = json.loads(row[0])
            progress.append({"phase": phase, "status": status})
            self.database.execute("UPDATE git_imports SET progress_json=?,updated_at=?,status=CASE WHEN status='cancel_requested' THEN status ELSE ? END WHERE id=?", (json.dumps(progress[-12:]), now(), status if phase in {"fetch", "complete"} else "running", import_id))

    def status(self, arguments: dict[str, Any], context: ToolInvocationContext) -> dict[str, Any]:
        self._permission(context)
        body = _parse_input(GitImportStatus, arguments)
        with self._lock:
            row = self.database.query_one("SELECT * FROM git_imports WHERE id=? AND actor_id=?", (body.import_id, context.actor_id))
            if row is None:
                raise ToolExecutionError("git_import_not_found", "Import is unavailable for this actor", next_action="Use the original actor and import ID.")
            if row["status"] in ACTIVE_IMPORT_STATUSES and body.import_id not in self._cancels:
                self._reconcile_interrupted(body.import_id)
                row = self.database.query_one("SELECT * FROM git_imports WHERE id=? AND actor_id=?", (body.import_id, context.actor_id))
                if row is None:
                    raise ToolExecutionError("git_import_not_found", "Import is unavailable for this actor", next_action="Use the original actor and import ID.")
            interrupted = row["status"] == "interrupted"
        return {"status": row["status"], "import_id": row["id"], "upload_id": row["upload_id"], "error_code": row["error_code"], "progress": json.loads(row["progress_json"]), "terminal": row["status"] in {"success", "failed", "cancelled", "interrupted"}, "execution_state": "unknown" if interrupted else "terminated" if row["status"] == "cancelled" else "completed" if row["status"] in {"success", "failed"} else "active", "execution_terminated": row["status"] == "cancelled", "requires_reconciliation": interrupted, "poll_after_ms": 1000, "next_action": "Coordinator queue slot released; executor outcome is unknown. Reconcile the original operation before retrying it; do not blindly replay." if interrupted else None}

    def cancel(self, arguments: dict[str, Any], context: ToolInvocationContext) -> dict[str, Any]:
        self._permission(context, write=True)
        body = _parse_input(GitImportCancel, arguments)

        def action(operation_id: str) -> tuple[dict[str, Any], str | None]:
            with self._lock:
                current = self.status({"import_id": body.import_id}, context)
                if current["requires_reconciliation"]:
                    raise ToolExecutionError("operation_interrupted", "Executor outcome is unknown; cancellation was not confirmed", next_action="Reconcile the original import; no blind replay or cancellation success claim.", details={"import_id": body.import_id, "execution_state": "unknown", "execution_terminated": False})
                if not current["terminal"]:
                    event = self._cancels.get(body.import_id)
                    if event is None:
                        raise ToolExecutionError("operation_interrupted", "Executor completion is unknown after restart", next_action="Reconcile the original import before retrying; no blind replay.")
                    event.set()
                    self.database.execute("UPDATE git_imports SET status='cancel_requested',updated_at=? WHERE id=?", (now(), body.import_id))
                    self.delivery.observability.emit_event("gate.git.cancel_requested", source="projects", subject_type="git_import", subject_id=body.import_id, payload={"actor_id": context.actor_id, "operation_id": operation_id})
                return self.status({"import_id": body.import_id}, context), body.import_id
        result = self.delivery._run_idempotent(context, "gate_project_git_cancel", body.idempotency_key, arguments, "git_import", action)
        return {**result, **self.status({"import_id": result["import_id"]}, context)}

    def test_proxy(self, body: ProxyTest, context: ToolInvocationContext) -> dict[str, Any]:
        self._permission(context, write=True)
        executor = self._executor()
        with self._lock:
            current_time = time.monotonic()
            if current_time - self._probe_last.get(context.actor_id, -60) < 30 or not self._probe_gate.acquire(blocking=False):
                raise ToolExecutionError("network_test_rate_limited", "Wait before another network test", next_action="At most one test at a time and one per actor per 30 seconds.")
            if len(self._probe_last) > 1000:
                self._probe_last = {actor: moment for actor, moment in self._probe_last.items() if current_time - moment < 30}
            self._probe_last[context.actor_id] = current_time
        material: dict[str, Any] = {}
        try:
            frozen = self.network.freeze(NetworkSelection(mode="profile", profile_id=body.profile_id, version=body.version), NetworkSelection(mode="direct"))
            kind = {"github": "git", "npm": "npm", "python": "python"}[body.target_id]
            self._check_scheme(executor, frozen, "git", kind)
            material = self.network.execution_material(frozen, "git")
            response = executor.probe(TEST_TARGETS[body.target_id], material=material, timeout_seconds=5, max_response_bytes=4096, method="HEAD")
            result = {"status": "success" if response.get("ok") is True else "failed", "target_id": body.target_id, "profile_id": body.profile_id, "version": body.version}
        except ToolExecutionError:
            raise
        except Exception:
            result = {"status": "failed", "error_code": "network_test_failed", "target_id": body.target_id}
        finally:
            material.clear()
            self._probe_gate.release()
        self.network._audit("tested", context.actor_id, result)
        return result


def register_git_import_tools(registry: ToolRegistry, service: GitImportService) -> None:
    for tool_id, model, handler, read_only, destructive, open_world in (
        ("gate_project_git_plan", GitSourceInput, service.plan, True, False, True),
        ("gate_project_git_import", GitImportCreate, service.create, False, False, True),
        ("gate_project_git_status", GitImportStatus, service.status, True, False, False),
        ("gate_project_git_cancel", GitImportCancel, service.cancel, False, True, False),
    ):
        definition = _definition(tool_id, tool_id, "Controlled Git source delivery; requires network.use and a reviewed safe executor", model, permission="read" if read_only else "write", read_only=read_only, destructive=destructive, open_world=open_world, sensitive_inputs=["credential_ref"])
        registry.register(definition, handler, contextual=True)

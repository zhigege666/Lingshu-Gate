"""Build Plan (IR) builder for uploaded MCP projects.

Turns a Preflight result into an explicit, inspectable build plan: an ordered
list of build steps plus artifact and manifest strategies. The Build Executor
consumes this IR instead of computing commands inline, so the pipeline becomes
a clear compiler-style flow: Preflight -> IR Builder -> Build Executor -> Deploy.

The module is intentionally pure (no filesystem access at plan time). Concrete
entrypoint resolution happens after the build via ``finalize_manifest`` against
the produced artifact directory, keeping behavior equivalent to the previous
inline implementation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

IR_VERSION = 1
ARTIFACT_IGNORE = [".git", ".venv", "venv", "target", "__pycache__"]
NODE_ENTRYPOINTS = ["dist/index.js", "index.js", "src/index.js"]
PYTHON_ENTRYPOINTS = ["server.py", "main.py", "app.py"]


def build_plan(
    preflight: dict[str, Any],
    *,
    run_install: bool = True,
    run_build: bool = True,
) -> dict[str, Any]:
    """Compile a Preflight result into a Build Plan (IR)."""

    runtime = str(preflight.get("runtime") or "unknown")
    raw_metadata = preflight.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    project_root_dir = preflight.get("project_root_dir")
    steps: list[dict[str, Any]] = []
    warnings: list[str] = []

    if runtime == "node":
        raw_scripts = metadata.get("package_scripts")
        scripts: list[Any] = raw_scripts if isinstance(raw_scripts, list) else []
        has_lock = bool(metadata.get("has_package_lock"))
        install_required = metadata.get("node_install_required") is True
        install_reason = str(metadata.get("node_install_reason") or "").strip()
        if run_install and install_required and (metadata.get("has_pnpm_lock") or metadata.get("has_yarn_lock")):
            warnings.append("Detected a pnpm/yarn lockfile, but the executor installs with npm; the install step may differ from the project's package manager.")
        previous_step = None
        if run_install and install_required:
            reason = install_reason or ("package-lock.json present" if has_lock else "Node dependencies or install lifecycle scripts present")
            steps.append(_step("node-install", "install", ["npm", "ci"] if has_lock else ["npm", "install"], reason))
            previous_step = "node-install"
        elif run_install:
            warnings.append(install_reason or "No Node dependencies or install lifecycle scripts detected; skipping npm install.")
        if run_build and "build" in scripts:
            build_deps = [previous_step] if previous_step else []
            steps.append(_step("node-build", "build", ["npm", "run", "build"], "scripts.build present", depends_on=build_deps))
        manifest = {
            "launch_type": "managed_process",
            "transport": "stdio",
            "runtime": "node",
            "start_script": "start" in scripts,
            "entrypoint_candidates": list(NODE_ENTRYPOINTS),
            "resolve_after_build": bool(steps),
        }
    elif runtime == "python":
        if run_install and metadata.get("has_requirements"):
            steps.append(_step("python-install", "install", ["python", "-m", "pip", "install", "-r", "requirements.txt"], "requirements.txt present"))
        elif run_install:
            warnings.append("No requirements.txt found; skipping dependency install.")
        manifest = {
            "launch_type": "managed_process",
            "transport": "stdio",
            "runtime": "python",
            "entrypoint_candidates": list(PYTHON_ENTRYPOINTS),
            "python_entrypoint": str(metadata.get("python_entrypoint") or ""),
            "resolve_after_build": bool(steps),
        }
    else:
        return {
            "ir_version": IR_VERSION,
            "runtime": runtime,
            "buildable": False,
            "project_root_dir": project_root_dir,
            "steps": [],
            "artifact": None,
            "manifest": None,
            "warnings": [f"Runtime '{runtime}' is not buildable by the local executor. Select runtime=node or runtime=python."],
            "notes": [],
        }

    if not steps:
        warnings.append("No install/build step required for this project.")

    return {
        "ir_version": IR_VERSION,
        "runtime": runtime,
        "buildable": True,
        "project_root_dir": project_root_dir,
        "steps": steps,
        "artifact": {"strategy": "copy_tree", "ignore": list(ARTIFACT_IGNORE)},
        "manifest": manifest,
        "warnings": warnings,
        "notes": [
            f"{len(steps)} build step(s); manifest entrypoint resolved "
            f"{'after build' if steps else 'after artifact packaging'}."
        ],
    }


def plan_commands(plan: dict[str, Any]) -> list[list[str]]:
    """Extract the ordered command list from an IR plan."""

    return [list(step.get("command") or []) for step in (plan.get("steps") or []) if step.get("command")]


SUPPORTED_RUNTIMES = {"node", "python"}
VALID_PHASES = {"install", "build"}
DETERMINISTIC_STEPS: dict[str, dict[str, tuple[str, list[str]] | tuple[str, list[str], list[str]]]] = {
    "node": {
        "node-install": ("install", ["npm", "install"], ["npm", "ci"]),
        "node-build": ("build", ["npm", "run", "build"]),
    },
    "python": {
        "python-install": (
            "install",
            ["python", "-m", "pip", "install", "-r", "requirements.txt"],
        ),
    },
}
DETERMINISTIC_STEP_SEQUENCES = {
    "node": {
        (),
        ("node-install",),
        ("node-build",),
        ("node-install", "node-build"),
    },
    "python": {(), ("python-install",)},
}


def validate_plan(plan: Any) -> dict[str, Any]:
    """Validate that an IR plan matches the current generated-plan contract."""

    errors: list[str] = []
    if not isinstance(plan, dict):
        return {"ok": False, "errors": ["plan is not an object"], "normalized": None}

    version = plan.get("ir_version")
    if not isinstance(version, int):
        errors.append("ir_version missing or not an integer")
    elif version != IR_VERSION:
        errors.append(f"ir_version {version} is unsupported; expected {IR_VERSION}")

    normalized = dict(plan)

    buildable = bool(plan.get("buildable"))
    runtime = str(plan.get("runtime") or "")
    steps = plan.get("steps")

    if not isinstance(steps, list):
        errors.append("steps must be a list")
        steps = []

    if buildable:
        if runtime not in SUPPORTED_RUNTIMES:
            errors.append(f"buildable plan has unsupported runtime: {runtime}")
        if not isinstance(plan.get("manifest"), dict):
            errors.append("buildable plan requires a manifest strategy")
        artifact = plan.get("artifact")
        if not isinstance(artifact, dict) or not artifact.get("strategy"):
            errors.append("buildable plan requires artifact.strategy")

    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            errors.append(f"step[{index}] is not an object")
            continue
        if not step.get("id"):
            errors.append(f"step[{index}] missing id")
        if step.get("phase") not in VALID_PHASES:
            errors.append(f"step[{index}] has invalid phase: {step.get('phase')}")
        if not isinstance(step.get("command"), list) or not step.get("command"):
            errors.append(f"step[{index}] command must be a non-empty list")
        if step.get("depends_on") is not None and not isinstance(step.get("depends_on"), list):
            errors.append(f"step[{index}] depends_on must be a list")
        step_id = str(step.get("id") or "")
        allowed = DETERMINISTIC_STEPS.get(runtime, {}).get(step_id)
        if allowed is None:
            errors.append(f"step[{index}] is not generated for runtime {runtime}: {step_id}")
        elif step.get("phase") != allowed[0] or step.get("command") not in allowed[1:]:
            errors.append(f"step[{index}] does not match the generated command for {step_id}")

    if all(isinstance(step, dict) for step in steps):
        step_ids = tuple(str(step.get("id") or "") for step in steps)
        if buildable and step_ids not in DETERMINISTIC_STEP_SEQUENCES.get(runtime, set()):
            errors.append(f"step sequence is not generated for runtime {runtime}: {', '.join(step_ids)}")
        for index, step in enumerate(steps):
            expected_dependencies = ["node-install"] if step.get("id") == "node-build" and "node-install" in step_ids else []
            if step.get("depends_on") != expected_dependencies:
                errors.append(f"step[{index}] has unexpected dependencies for {step.get('id')}")
        try:
            plan_waves({"steps": steps})
        except ValueError as exc:
            errors.append(str(exc))

    return {"ok": not errors, "errors": errors, "normalized": normalized if not errors else None}


def finalize_manifest(plan: dict[str, Any], upload: dict[str, Any], build_id: str, artifact_dir: Path) -> dict[str, Any]:
    """Resolve the concrete MCP manifest from the IR after the artifact exists."""

    raw_manifest_plan = plan.get("manifest")
    manifest_plan: dict[str, Any] = raw_manifest_plan if isinstance(raw_manifest_plan, dict) else {}
    runtime = str(plan.get("runtime") or "")
    artifact_dir = Path(artifact_dir)

    if runtime == "node":
        if manifest_plan.get("start_script"):
            command, args = "npm", ["run", "start"]
        else:
            raw_candidates = manifest_plan.get("entrypoint_candidates")
            candidates = raw_candidates if isinstance(raw_candidates, list) else NODE_ENTRYPOINTS
            entry = _first_existing(artifact_dir, [str(name) for name in candidates])
            if not entry:
                raise ValueError("Node entrypoint not found: expected start script, dist/index.js, index.js, or src/index.js")
            command, args = "node", [entry]
    elif runtime == "python":
        raw_candidates = manifest_plan.get("entrypoint_candidates")
        entrypoint_candidates = raw_candidates if isinstance(raw_candidates, list) else PYTHON_ENTRYPOINTS
        candidates = [str(manifest_plan.get("python_entrypoint") or "")] + [str(name) for name in entrypoint_candidates]
        entry = _first_existing(artifact_dir, [candidate for candidate in candidates if candidate])
        if not entry:
            raise ValueError("Python entrypoint not found: expected server.py, main.py, app.py, or analysis.python_entrypoint")
        command, args = "python", [entry]
    else:
        raise ValueError(f"Cannot finalize manifest for runtime: {runtime}")

    server_id = _safe_id(Path(str(upload.get("filename") or "uploaded-mcp")).stem)
    return {
        "id": server_id,
        "name": f"Uploaded {server_id}",
        "enabled": True,
        "launch": {"type": "managed_process", "command": command, "args": args, "cwd": str(artifact_dir)},
        "transport": {"type": "stdio"},
        "timeout_seconds": 120,
        "auto_start": False,
        "restart_policy": {"enabled": True, "max_attempts": 3, "delay_seconds": 5, "backoff_multiplier": 2, "max_delay_seconds": 60, "restart_on_exit": True, "reset_after_seconds": 300, "exit_code_allowlist": [], "exit_code_blocklist": [0], "health_check": {"enabled": False, "method": "tools_list", "interval_seconds": 30, "timeout_seconds": 10, "failure_threshold": 3}},
        "analysis": {"upload_id": upload.get("id"), "build_id": build_id, "detected_runtime": runtime, "draft_source": "build_plan_ir"},
    }


def _step(step_id: str, phase: str, command: list[str], reason: str, *, depends_on: list[str] | None = None) -> dict[str, Any]:
    return {"id": step_id, "phase": phase, "command": command, "reason": reason, "depends_on": list(depends_on or [])}


def plan_waves(plan: dict[str, Any]) -> list[list[int]]:
    """Topologically sort steps into parallel waves of step indices.

    Each wave contains steps whose dependencies are all satisfied by earlier
    waves; steps within a wave can run in parallel. Raises ValueError on unknown
    dependency references or dependency cycles.
    """

    steps = list(plan.get("steps") or [])
    id_to_index = {str(step.get("id")): index for index, step in enumerate(steps)}
    deps: dict[int, set[int]] = {}
    for index, step in enumerate(steps):
        resolved: set[int] = set()
        for dep in step.get("depends_on") or []:
            if str(dep) not in id_to_index:
                raise ValueError(f"step '{step.get('id')}' depends on unknown step '{dep}'")
            resolved.add(id_to_index[str(dep)])
        deps[index] = resolved

    waves: list[list[int]] = []
    done: set[int] = set()
    remaining = set(range(len(steps)))
    while remaining:
        ready = sorted(index for index in remaining if deps[index] <= done)
        if not ready:
            raise ValueError("dependency cycle detected in build plan steps")
        waves.append(ready)
        done.update(ready)
        remaining.difference_update(ready)
    return waves


def _first_existing(root: Path, candidates: list[str]) -> str | None:
    for candidate in candidates:
        path = root / candidate
        if path.exists() and path.is_file():
            return candidate
    return None


def _safe_id(value: str) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in value).strip("-._")
    return cleaned or "uploaded-mcp"

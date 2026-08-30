"""Build preflight checks for uploaded MCP projects."""

from __future__ import annotations

import hashlib
import json
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

SUPPORTED_RUNTIME_OVERRIDES = {"node", "python"}
NODE_ENTRYPOINTS = ["dist/index.js", "index.js", "src/index.js"]
PYTHON_ENTRYPOINTS = ["server.py", "main.py", "app.py"]
TOOL_NAMES = ["node", "npm", "npx", "python", "python3", "pip", "pip3"]
PROJECT_MARKERS = ("package.json", "pyproject.toml", "requirements.txt", "Dockerfile")
DESCEND_IGNORED_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "build", "target", "__pycache__"}
FINGERPRINT_KEY_FILES = [
    "package.json",
    "package-lock.json",
    "pnpm-lock.yaml",
    "yarn.lock",
    "pyproject.toml",
    "requirements.txt",
    "Dockerfile",
    *NODE_ENTRYPOINTS,
    *PYTHON_ENTRYPOINTS,
]
NODE_DEPENDENCY_FIELDS = (
    "dependencies",
    "optionalDependencies",
    "devDependencies",
    "peerDependencies",
    "bundledDependencies",
    "bundleDependencies",
)
NODE_INSTALL_LIFECYCLE_SCRIPTS = ("preinstall", "install", "postinstall", "prepare")


def compute_preflight_fingerprint(upload: dict[str, Any], *, runtime_override: str | None = None, project_root: str | None = None) -> dict[str, Any]:
    """Compute a cheap structural fingerprint for Preflight cache keys.

    The fingerprint tracks key project files (size+mtime), total file count, and
    a toolchain availability signature (which() only, no version probes) plus the
    project root and runtime override. Non-key source content is intentionally
    not tracked: Preflight only cares about project structure and toolchain.
    """

    upload_root = Path(str(upload.get("root_dir") or ""))
    selected_root, root_error = _resolve_project_root(upload_root, project_root)
    key_files: dict[str, dict[str, int]] = {}
    file_count = 0
    if selected_root.exists() and selected_root.is_dir():
        for name in FINGERPRINT_KEY_FILES:
            path = selected_root / name
            if path.is_file():
                try:
                    stat = path.stat()
                    key_files[name] = {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}
                except OSError:
                    key_files[name] = {"size": -1, "mtime_ns": -1}
        file_count = len(_scan_files(selected_root))
    tools = {name: bool(shutil.which(name)) for name in TOOL_NAMES}
    return {
        "project_root": project_root or ".",
        "project_root_dir": str(selected_root),
        "runtime_override": (runtime_override or "").strip().lower() or None,
        "root_error": root_error,
        "key_files": key_files,
        "file_count": file_count,
        "tools": tools,
    }


def fingerprint_key(fingerprint: dict[str, Any]) -> str:
    payload = json.dumps(fingerprint, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def scope_key(upload_id: str, fingerprint: dict[str, Any]) -> str:
    """Stable key for the (upload, project_root, runtime_override) scope.

    Independent of file/tool changes so the previous snapshot of the same scope
    can be located for diffing.
    """

    return fingerprint_key(
        {
            "upload_id": upload_id,
            "project_root": fingerprint.get("project_root"),
            "runtime_override": fingerprint.get("runtime_override"),
            "tool_probe_mode": fingerprint.get("tool_probe_mode", "version"),
        }
    )


def tools_signature(fingerprint: dict[str, Any]) -> dict[str, bool]:
    raw_tools = fingerprint.get("tools")
    tools: dict[str, Any] = raw_tools if isinstance(raw_tools, dict) else {}
    return {str(name): bool(value) for name, value in tools.items()}


def preflight_diff(previous_fingerprint: dict[str, Any] | None, current_fingerprint: dict[str, Any]) -> dict[str, Any]:
    """Structural diff between the previous and current fingerprints."""

    empty_files: dict[str, list[str]] = {"added": [], "removed": [], "modified": []}
    if not previous_fingerprint:
        return {"has_previous": False, "unchanged": False, "changed_files": empty_files, "file_count_delta": 0, "tool_changes": []}
    raw_previous_files = previous_fingerprint.get("key_files")
    prev_files: dict[str, Any] = raw_previous_files if isinstance(raw_previous_files, dict) else {}
    raw_current_files = current_fingerprint.get("key_files")
    cur_files: dict[str, Any] = raw_current_files if isinstance(raw_current_files, dict) else {}
    added = sorted(set(cur_files) - set(prev_files))
    removed = sorted(set(prev_files) - set(cur_files))
    modified = sorted(name for name in set(cur_files) & set(prev_files) if cur_files.get(name) != prev_files.get(name))
    prev_tools = tools_signature(previous_fingerprint)
    cur_tools = tools_signature(current_fingerprint)
    tool_changes = [{"name": name, "from": bool(prev_tools.get(name)), "to": bool(cur_tools.get(name))} for name in sorted(set(prev_tools) | set(cur_tools)) if bool(prev_tools.get(name)) != bool(cur_tools.get(name))]
    return {
        "has_previous": True,
        "unchanged": not (added or removed or modified or tool_changes),
        "changed_files": {"added": added, "removed": removed, "modified": modified},
        "file_count_delta": int(current_fingerprint.get("file_count") or 0) - int(previous_fingerprint.get("file_count") or 0),
        "tool_changes": tool_changes,
    }


def check_diff(previous_checks: list[dict[str, Any]] | None, current_checks: list[dict[str, Any]]) -> dict[str, Any]:
    """Identify which preflight checks changed versus the previous result."""

    previous = {str(check.get("id")): check for check in (previous_checks or [])}
    current_ids = {str(check.get("id")) for check in current_checks}
    changes: list[dict[str, Any]] = []
    affected: list[str] = []
    for check in current_checks:
        check_id = str(check.get("id"))
        prior = previous.get(check_id)
        if prior is None:
            changes.append({"id": check_id, "from_status": None, "to_status": check.get("status"), "kind": "added"})
            affected.append(check_id)
        elif prior.get("status") != check.get("status") or prior.get("message") != check.get("message") or prior.get("detail") != check.get("detail"):
            changes.append({"id": check_id, "from_status": prior.get("status"), "to_status": check.get("status"), "kind": "modified"})
            affected.append(check_id)
    for check_id in sorted(set(previous) - current_ids):
        changes.append({"id": check_id, "from_status": previous[check_id].get("status"), "to_status": None, "kind": "removed"})
        affected.append(check_id)
    return {"affected_checks": affected, "check_changes": changes}


def run_build_preflight(
    upload: dict[str, Any],
    *,
    runtime_override: str | None = None,
    project_root: str | None = None,
    tools_cache: dict[str, Any] | None = None,
    probe_tool_versions: bool = True,
) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    upload_root = Path(str(upload.get("root_dir") or ""))
    selected_root, root_error = _resolve_project_root(upload_root, project_root)

    auto_root = (project_root or ".").strip() in {"", "."}
    descended_to = ""
    if not root_error and auto_root and selected_root.exists() and selected_root.is_dir():
        descended = _descend_to_project_root(selected_root)
        if descended != selected_root:
            try:
                descended_to = descended.relative_to(selected_root).as_posix()
            except ValueError:
                descended_to = ""
            selected_root = descended

    if root_error:
        checks.append(_check("project_root.safe", "error", root_error, str(selected_root)))
    if not upload_root.exists() or not upload_root.is_dir():
        checks.append(_check("project_root.upload", "error", "Upload root does not exist", str(upload_root)))
    else:
        checks.append(_check("project_root.upload", "ok", "Upload root exists", str(upload_root)))
    if not selected_root.exists() or not selected_root.is_dir():
        checks.append(_check("project_root.selected", "error", "Selected project root does not exist", str(selected_root)))
        files: set[str] = set()
    else:
        checks.append(_check("project_root.selected", "ok", "Selected project root exists", str(selected_root)))
        files = _scan_files(selected_root)

    if tools_cache and all(name in tools_cache for name in TOOL_NAMES):
        tools = {name: tools_cache[name] for name in TOOL_NAMES}
    elif not probe_tool_versions:
        tools = {name: _locate_tool(name) for name in TOOL_NAMES}
    else:
        tools = {name: _probe_tool(name) for name in TOOL_NAMES}
    for name, info in tools.items():
        checks.append(_check(f"tool.{name}", "ok" if info["available"] else "warning", f"{name} {'available' if info['available'] else 'missing'}", info.get("version") or info.get("path") or info.get("error") or ""))

    package_json = _read_json(selected_root / "package.json") if "package.json" in files else {}
    raw_scripts = package_json.get("scripts")
    scripts: dict[str, Any] = raw_scripts if isinstance(raw_scripts, dict) else {}
    node_install_metadata = _node_install_metadata(package_json, scripts)
    python_entrypoint = _first_existing(selected_root, PYTHON_ENTRYPOINTS)
    candidates: list[str] = []
    if "package.json" in files:
        candidates.append("node")
    if "pyproject.toml" in files or "requirements.txt" in files or python_entrypoint:
        candidates.append("python")
    if "Dockerfile" in files:
        candidates.append("docker")

    detected_runtime = _infer_runtime(candidates)
    override = (runtime_override or "").strip().lower() or None
    if override and override not in SUPPORTED_RUNTIME_OVERRIDES:
        checks.append(_check("runtime.override", "error", "Runtime override must be node or python", override))
        runtime = detected_runtime
    else:
        runtime = override or detected_runtime
        if override:
            checks.append(_check("runtime.override", "ok", "Runtime was manually selected", override))

    if runtime == "node":
        _append_node_checks(checks, selected_root, files, scripts, tools, bool(override))
    elif runtime == "python":
        _append_python_checks(checks, selected_root, files, python_entrypoint, tools, bool(override))
    elif runtime == "ambiguous":
        checks.append(_check("runtime.detected", "warning", "Multiple runtimes detected; select node or python", ", ".join(candidates)))
    elif runtime == "docker":
        checks.append(
            _check(
                "runtime.detected",
                "warning",
                "Container-image project builds are not supported",
                "Build a Node or Python project, or configure a reviewed digest-pinned image as a managed_container downstream",
            )
        )
    else:
        checks.append(_check("runtime.detected", "warning", "Runtime could not be detected", "select node or python manually when appropriate"))

    return {
        "status": _overall_status(checks),
        "runtime": runtime,
        "detected_runtime": detected_runtime,
        "runtime_override": override,
        "runtime_candidates": candidates,
        "project_root": descended_to or (project_root or "."),
        "project_root_dir": str(selected_root),
        "project_root_auto_descended": descended_to,
        "upload_root_dir": str(upload_root),
        "platform": _platform_key(),
        "checks": checks,
        "tools": tools,
        "recommendations": _recommendations(runtime, checks),
        "metadata": {
            "has_package_json": "package.json" in files,
            "has_package_lock": "package-lock.json" in files,
            "has_pnpm_lock": "pnpm-lock.yaml" in files,
            "has_yarn_lock": "yarn.lock" in files,
            "has_pyproject": "pyproject.toml" in files,
            "has_requirements": "requirements.txt" in files,
            "has_dockerfile": "Dockerfile" in files,
            "package_scripts": sorted(str(key) for key in scripts.keys()),
            **node_install_metadata,
            "node_entrypoint": _first_existing(selected_root, NODE_ENTRYPOINTS) or "",
            "python_entrypoint": python_entrypoint or "",
            "file_count": len(files),
        },
    }


def _append_node_checks(checks: list[dict[str, Any]], root: Path, files: set[str], scripts: dict[str, Any], tools: dict[str, dict[str, Any]], manual: bool) -> None:
    if "package.json" in files:
        checks.append(_check("node.package_json", "ok", "package.json found", str(root / "package.json")))
    else:
        checks.append(_check("node.package_json", "warning" if manual else "error", "package.json missing", str(root / "package.json")))
    interesting = [name for name in ["build", "start", "dev", "serve"] if name in scripts]
    checks.append(_check("node.package_scripts", "ok" if interesting else "warning", "package.json scripts inspected", ", ".join(interesting) or "no build/start/dev/serve script"))
    checks.append(_check("node.entrypoint", "ok" if "start" in scripts or _first_existing(root, NODE_ENTRYPOINTS) else "warning", "Node entrypoint check", "scripts.start or dist/index.js/index.js/src/index.js"))
    if not tools["node"]["available"]:
        checks.append(_check("node.required_tool.node", "error", "node is required", "install Node.js"))
    if not tools["npm"]["available"]:
        checks.append(_check("node.required_tool.npm", "error", "npm is required", "install npm"))
    if not tools["npx"]["available"]:
        checks.append(_check("node.required_tool.npx", "warning", "npx is recommended", "install npx"))


def _append_python_checks(checks: list[dict[str, Any]], root: Path, files: set[str], entrypoint: str | None, tools: dict[str, dict[str, Any]], manual: bool) -> None:
    has_marker = "pyproject.toml" in files or "requirements.txt" in files
    checks.append(_check("python.markers", "ok" if has_marker else "warning" if manual else "error", "Python dependency marker check", "pyproject.toml or requirements.txt"))
    checks.append(_check("python.entrypoint", "ok" if entrypoint else "warning", "Python entrypoint check", entrypoint or "server.py/main.py/app.py"))
    if not (tools["python"]["available"] or tools["python3"]["available"]):
        checks.append(_check("python.required_tool.python", "error", "python or python3 is required", "install Python 3.12+"))
    if "requirements.txt" in files and not (tools["pip"]["available"] or tools["pip3"]["available"]):
        checks.append(_check("python.required_tool.pip", "error", "pip or pip3 is required", "install pip"))


def _resolve_project_root(upload_root: Path, project_root: str | None) -> tuple[Path, str | None]:
    raw = (project_root or ".").strip() or "."
    if raw == ".":
        return upload_root.resolve(), None
    base = upload_root.parent if upload_root.parent.name == "extracted" else upload_root
    candidate = Path(raw)
    resolved = candidate.resolve() if candidate.is_absolute() else (base / candidate).resolve()
    try:
        resolved.relative_to(base.resolve())
    except ValueError:
        return resolved, f"Selected project root escapes upload root: {raw}"
    return resolved, None


def _descend_to_project_root(base: Path) -> Path:
    """Return the shallowest sub-directory that actually contains a marker.

    Makes preflight/build resilient to upload roots that point one or more
    directories above the real project (e.g. nested-project/server/package.json),
    even when the stored upload root is too shallow. Returns base unchanged when
    base already holds a marker at its top level.
    """

    for marker in PROJECT_MARKERS:
        if (base / marker).is_file():
            return base
    best_key: tuple[int, int, str] | None = None
    best_dir = base
    try:
        candidates = list(base.rglob("*"))
    except OSError:
        return base
    for path in candidates:
        if path.name not in PROJECT_MARKERS or not path.is_file():
            continue
        rel = path.relative_to(base)
        if any(part in DESCEND_IGNORED_DIRS for part in rel.parts):
            continue
        parent = rel.parent
        depth = len(parent.parts)
        score = 3 if path.name == "package.json" else 2 if path.name in {"pyproject.toml", "requirements.txt"} else 1
        key = (depth, -score, str(parent))
        if best_key is None or key < best_key:
            best_key = key
            best_dir = path.parent
    return best_dir


def _scan_files(root: Path) -> set[str]:
    try:
        return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}
    except OSError:
        return set()


def _infer_runtime(candidates: list[str]) -> str:
    local = [runtime for runtime in candidates if runtime in SUPPORTED_RUNTIME_OVERRIDES]
    if len(local) > 1:
        return "ambiguous"
    if local:
        return local[0]
    if "docker" in candidates:
        return "docker"
    return "unknown"


def _probe_tool(command: str) -> dict[str, Any]:
    path = shutil.which(command)
    result = {"command": command, "available": bool(path), "path": path or "", "version": "", "error": ""}
    if not path:
        result["error"] = "not found"
        return result
    try:
        completed = subprocess.run([command, "--version"], capture_output=True, text=True, timeout=5, check=False)
        version = (completed.stdout or completed.stderr or "").strip().splitlines()
        result["version"] = version[0][:200] if version else f"returncode={completed.returncode}"
    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)
    return result


def _locate_tool(command: str) -> dict[str, Any]:
    """Report PATH availability without spawning a child process."""

    path = shutil.which(command)
    return {
        "command": command,
        "available": bool(path),
        "path": path or "",
        "version": "",
        "error": "" if path else "not found",
    }


def _check(check_id: str, status: str, message: str, detail: str = "") -> dict[str, Any]:
    return {"id": check_id, "status": status, "message": message, "detail": detail}


def _overall_status(checks: list[dict[str, Any]]) -> str:
    statuses = {str(check.get("status") or "") for check in checks}
    if "error" in statuses:
        return "error"
    if "warning" in statuses:
        return "warning"
    return "ok"


def _recommendations(runtime: str, checks: list[dict[str, Any]]) -> list[dict[str, str]]:
    missing = [str(check["id"]).replace("tool.", "") for check in checks if str(check.get("id", "")).startswith("tool.") and check.get("status") == "warning"]
    suffix = f" Missing tools: {', '.join(missing)}." if missing else ""
    if runtime in {"unknown", "ambiguous"}:
        suffix += " Manually select runtime=node or runtime=python if automatic detection is unclear."
    return [
        {"platform": "windows", "message": "Install Node.js 22+ or Python 3.12+, reopen the terminal, and confirm node/npm/npx/python/pip are on PATH." + suffix},
        {"platform": "macos", "message": "Use Homebrew when possible: brew install node python, then confirm node/npm/npx/python3/pip3 are available." + suffix},
        {"platform": "linux", "message": "Install nodejs/npm/python3/python3-pip with your package manager, or use the official Node.js 22+ source." + suffix},
    ]


def _first_existing(root: Path, candidates: list[str]) -> str | None:
    for candidate in candidates:
        path = root / candidate
        if path.exists() and path.is_file():
            return candidate
    return None


def _read_json(path: Path) -> dict[str, Any]:
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _node_install_metadata(package_json: dict[str, Any], scripts: dict[str, Any]) -> dict[str, Any]:
    """提取是否需要安装依赖的证据，不把缺少锁文件误判成需要安装。"""

    dependency_groups: list[str] = []
    for field in NODE_DEPENDENCY_FIELDS:
        value = package_json.get(field)
        if isinstance(value, dict):
            has_entries = any(str(name).strip() for name in value)
        elif isinstance(value, list):
            has_entries = any(str(name).strip() for name in value)
        else:
            has_entries = False
        if has_entries:
            dependency_groups.append(field)

    lifecycle_scripts = [
        name
        for name in NODE_INSTALL_LIFECYCLE_SCRIPTS
        if str(scripts.get(name) or "").strip()
    ]
    if dependency_groups:
        reason = f"Node dependency groups present: {', '.join(dependency_groups)}"
    elif lifecycle_scripts:
        reason = f"Node install lifecycle scripts present: {', '.join(lifecycle_scripts)}"
    else:
        reason = "No Node dependencies or install lifecycle scripts detected"
    return {
        "node_dependency_groups": dependency_groups,
        "node_install_lifecycle_scripts": lifecycle_scripts,
        "node_install_required": bool(dependency_groups or lifecycle_scripts),
        "node_install_reason": reason,
    }


def _platform_key() -> str:
    name = platform.system().lower()
    if name.startswith("win"):
        return "windows"
    if name == "darwin":
        return "macos"
    return name or "unknown"

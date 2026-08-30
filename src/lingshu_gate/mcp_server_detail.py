"""MCP server detail aggregation for runtime diagnostics."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from lingshu_gate.config import Settings
from lingshu_gate.mcp_runtime import McpRuntimeManager
from lingshu_gate.mcp_runtime_cache import McpRuntimeCacheResolver
from lingshu_gate.observability_store import ObservabilityStore

STARTUP_STAGE_EVENTS = [
    "gate.mcp.runtime_cache_ready",
    "gate.mcp.stdio_process_started",
    "gate.mcp.stdio_process_ready",
    "gate.mcp.discovery_started",
    "gate.mcp.discovery_succeeded",
    "gate.mcp.process_exited_during_request",
    "gate.mcp.process_exited_unexpectedly",
    "gate.mcp.restart_scheduled",
    "gate.mcp.auto_restart",
    "gate.mcp.restart_exhausted",
    "gate.mcp.restart_skipped_exit_code",
    "gate.mcp.restart_attempts_reset",
    "gate.mcp.health_check_recovered",
    "gate.mcp.health_check_failed",
    "gate.mcp.health_check_threshold_exceeded",
    "gate.mcp.request_timed_out",
    "gate.mcp.tools_discovered",
    "gate.mcp.tools_registered",
    "gate.mcp.server_running",
    "gate.mcp.server_start_failed",
]


RECOVERY_EVENT_LABELS = {
    "gate.mcp.server_start_failed": "Start failure",
    "gate.mcp.process_exited_unexpectedly": "Unexpected exit",
    "gate.mcp.health_check_failed": "Health check failed",
    "gate.mcp.health_check_threshold_exceeded": "Health threshold exceeded",
    "gate.mcp.health_check_recovered": "Health recovered",
    "gate.mcp.restart_scheduled": "Restart scheduled",
    "gate.mcp.auto_restart": "Auto restart",
    "gate.mcp.restart_exhausted": "Restart exhausted",
    "gate.mcp.restart_skipped_exit_code": "Restart skipped by exit code",
    "gate.mcp.restart_attempts_reset": "Attempts reset",
}


def build_mcp_server_detail(settings: Settings, runtime: McpRuntimeManager, observability_store: ObservabilityStore, server_id: str) -> dict[str, Any]:
    """Build a single server diagnostic payload for Console detail views."""

    status = runtime.get_server(server_id)
    manifest = runtime.iter_manifests()[server_id]
    logs = observability_store.list_logs(server_id=server_id, limit=80)
    events = observability_store.list_events(subject_id=server_id, limit=80)
    restart_history = runtime.list_restart_history(server_id, limit=80)
    cache_plan = McpRuntimeCacheResolver(settings.data_dir).resolve(manifest)
    cache_status = _cache_status(cache_plan.safe_dict())
    timeline = _build_timeline(logs, events)
    stdout = _recent_stream(logs, "stdout")
    stderr = _recent_stream(logs, "stderr")
    status_dict = status.model_dump(mode="json")
    manifest_dict = manifest.safe_dict()
    failure_hints = _failure_hints(status_dict, manifest_dict, cache_status, logs, restart_history)
    recovery_chart = _recovery_chart(restart_history)

    return {
        "server": status_dict,
        "manifest": manifest_dict,
        "runtime_cache": cache_status,
        "timeline": timeline,
        "recent_stdout": stdout,
        "recent_stderr": stderr,
        "logs": logs,
        "events": events,
        "tools": runtime.list_server_tools(server_id),
        "failure_hints": failure_hints,
        "restart_history": restart_history,
        "recovery_chart": recovery_chart,
        "recovery_summary": _recovery_summary(status_dict, manifest_dict, restart_history),
    }


def _cache_status(plan: dict[str, Any]) -> dict[str, Any]:
    cache_dir_value = plan.get("cache_dir")
    cache_dir = Path(str(cache_dir_value)) if cache_dir_value else None
    exists = cache_dir.exists() if cache_dir else False
    writable = cache_dir.exists() and cache_dir.is_dir() and _is_writable(cache_dir) if cache_dir else False
    parent_writable = _is_writable(cache_dir.parent) if cache_dir and cache_dir.parent.exists() else False
    return {
        **plan,
        "exists": exists,
        "writable": writable,
        "parent_writable": parent_writable,
        "size_bytes": _dir_size(cache_dir) if exists and cache_dir else 0,
    }


def _build_timeline(logs: list[dict[str, Any]], events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in logs:
        event_type = item.get("event_type")
        if event_type in STARTUP_STAGE_EVENTS:
            rows.append({
                "created_at": item.get("created_at"),
                "level": item.get("level"),
                "source": "log",
                "event_type": event_type,
                "message": item.get("message"),
                "payload": item.get("payload") or {},
            })
    for item in events:
        event_type = item.get("type")
        if isinstance(event_type, str) and (event_type.startswith("gate.server.") or event_type.startswith("gate.config.")):
            rows.append({
                "created_at": item.get("created_at"),
                "level": "info",
                "source": "event",
                "event_type": event_type,
                "message": event_type,
                "payload": item.get("payload") or {},
            })
    return sorted(rows, key=lambda row: str(row.get("created_at") or ""), reverse=True)[:40]


def _recovery_chart(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for item in history:
        event_type = str(item.get("event_type") or "unknown")
        counts[event_type] = counts.get(event_type, 0) + 1
    return [
        {"event_type": key, "label": RECOVERY_EVENT_LABELS.get(key, key), "count": value}
        for key, value in sorted(counts.items(), key=lambda pair: pair[1], reverse=True)
    ]


def _recovery_summary(status: dict[str, Any], manifest: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any]:
    policy = _dict_or_empty(status.get("restart_policy"))
    health = _dict_or_empty(policy.get("health_check"))
    latest = history[0] if history else {}
    max_attempts = int(policy.get("max_attempts") or 0)
    attempts = int(status.get("restart_attempts") or 0)
    counts: dict[str, int] = {}
    level_counts: dict[str, int] = {"error": 0, "warning": 0, "info": 0}
    for item in history:
        event_type = str(item.get("event_type") or "unknown")
        level = str(item.get("level") or "info")
        counts[event_type] = counts.get(event_type, 0) + 1
        level_counts[level] = level_counts.get(level, 0) + 1
    return {
        "restart_policy_enabled": bool(policy.get("enabled")),
        "restart_on_exit": bool(policy.get("restart_on_exit", True)),
        "health_check_enabled": bool(health.get("enabled")),
        "health_check_method": health.get("method") or "tools_list",
        "total_events": len(history),
        "error_events": level_counts.get("error", 0),
        "warning_events": level_counts.get("warning", 0),
        "info_events": level_counts.get("info", 0),
        "scheduled_restarts": counts.get("gate.mcp.restart_scheduled", 0),
        "auto_restarts": counts.get("gate.mcp.auto_restart", 0),
        "exhausted_restarts": counts.get("gate.mcp.restart_exhausted", 0),
        "skipped_exit_code_restarts": counts.get("gate.mcp.restart_skipped_exit_code", 0),
        "health_failures": counts.get("gate.mcp.health_check_failed", 0) + counts.get("gate.mcp.health_check_threshold_exceeded", 0),
        "health_recoveries": counts.get("gate.mcp.health_check_recovered", 0),
        "attempts_remaining": max(max_attempts - attempts, 0),
        "active_restart_scheduled": bool(status.get("next_restart_at")),
        "latest_event_type": latest.get("event_type"),
        "latest_event_label": RECOVERY_EVENT_LABELS.get(str(latest.get("event_type") or ""), latest.get("event_type")),
        "latest_event_level": latest.get("level"),
        "latest_event_at": latest.get("created_at"),
        "manifest_auto_start": bool(manifest.get("auto_start")),
    }


def _recent_stream(logs: list[dict[str, Any]], stream: str) -> list[str]:
    values: list[str] = []
    for item in logs:
        payload = _dict_or_empty(item.get("payload"))
        if payload.get("stream") != stream:
            continue
        if stream == "stdout":
            raw = payload.get("raw") or item.get("message")
        else:
            raw = payload.get("stderr") or item.get("message")
        if raw:
            values.append(str(raw))
    return values[:20]


def _failure_hints(status: dict[str, Any], manifest: dict[str, Any], cache: dict[str, Any], logs: list[dict[str, Any]], restart_history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    hints: list[dict[str, Any]] = []
    last_error = str(status.get("last_error") or "")
    history_text = "\n".join(str(item.get("event_type") or "") for item in restart_history)
    all_text = "\n".join([last_error, history_text, *[str(item.get("message") or "") for item in logs], *[str(item.get("payload") or "") for item in logs]])
    launch = _dict_or_empty(manifest.get("launch"))
    command = launch.get("command")
    restart_policy = _dict_or_empty(status.get("restart_policy"))

    if status.get("status") == "failed":
        hints.append({"severity": "error", "code": "server_failed", "message": "MCP Server 当前处于 failed 状态，需要查看启动时间线和 recent stderr。"})
    if restart_policy.get("enabled") and status.get("next_restart_at"):
        hints.append({"severity": "warning", "code": "restart_scheduled", "message": f"自动重启已调度，下一次重启时间：{status.get('next_restart_at')}。"})
    if restart_policy.get("enabled") and "gate.mcp.restart_exhausted" in all_text:
        hints.append({"severity": "error", "code": "restart_exhausted", "message": "自动重启次数已耗尽。请查看 recent stderr、启动时间线和 Manifest 配置。"})
    if restart_policy.get("enabled") and "gate.mcp.restart_skipped_exit_code" in all_text:
        hints.append({"severity": "warning", "code": "restart_skipped_exit_code", "message": "自动重启被退出码策略跳过。请检查 exit_code_allowlist / exit_code_blocklist。"})
    if status.get("health_status") == "failed":
        hints.append({"severity": "warning", "code": "health_check_failed", "message": "健康检查正在失败或曾触发恢复。请查看恢复历史和 latest server logs。"})
    if command in {"npx", "npm"} and "process exited while waiting for server/discover" in all_text:
        hints.append({"severity": "warning", "code": "npx_cold_start", "message": "疑似 npm/npx 动态安装或冷启动阶段在 server/discover 前退出。可重试启动，并确认 /data/runtime-cache 可写。"})
    if command in {"npx", "npm"} and not cache.get("writable") and not cache.get("parent_writable"):
        hints.append({"severity": "error", "code": "runtime_cache_not_writable", "message": "runtime cache 不可写，npx/npm 可能无法稳定复用缓存。请检查 /data 挂载是否 rw。"})
    if "MCP request timed out" in all_text or "timed out" in all_text:
        hints.append({"severity": "warning", "code": "discover_timeout", "message": "MCP 发现超时。可以增大 timeout_seconds，或检查 MCP Server 是否启动后没有输出 JSON-RPC 响应。"})
    if "Invalid JSON from MCP stdout" in all_text or "gate.mcp.stdio_invalid_json" in all_text:
        hints.append({"severity": "error", "code": "invalid_stdout_json", "message": "MCP Server 在 stdout 输出了非 JSON-RPC 内容。stdio MCP 的 stdout 必须只输出协议消息，日志应写 stderr。"})
    if launch.get("type") == "managed_process" and not command:
        hints.append({"severity": "error", "code": "missing_command", "message": "launch.command 为空，managed_process 无法启动。"})
    if not hints:
        hints.append({"severity": "info", "code": "no_obvious_issue", "message": "未发现明显失败模式。若仍异常，请查看完整 logs/events 或运行 Diagnostics。"})
    return hints


def _is_writable(path: Path) -> bool:
    try:
        return path.exists() and path.is_dir() and os.access(path, os.W_OK)
    except OSError:
        return False


def _dict_or_empty(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dir_size(path: Path | None) -> int:
    if not path or not path.exists() or not path.is_dir():
        return 0
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total

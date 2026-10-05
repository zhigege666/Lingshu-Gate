"""Isolated delivery port. Native composition verifies a rootless Podman adapter."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from lingshu_gate.registry import ToolExecutionError

REQUIRED_CAPABILITIES = frozenset({
    "isolated_workspace", "bounded_resources", "pinned_dns_egress", "proxy_target_policy",
    "no_redirects", "origin_bound_credentials", "secrets_outside_project",
    "cancel_process_tree", "git_no_hooks_filters_submodules", "artifact_secret_scan",
    "versioned_official_toolchain_cache",
    "no_unplanned_tool_downloads", "dependency_origin_policy",
})
TEST_TARGETS = {"github": "https://github.com/", "npm": "https://registry.npmjs.org/", "python": "https://pypi.org/simple/"}
ExecutionPhase = Literal["git_acquisition", "offline_build"]
ROOTLESS_CHECKS = frozenset({
    "rootless_user", "user_mount_pid_namespaces", "read_only_tools", "bounded_workspace",
    "cgroup_delegation", "cpu_memory_pids_limits", "whole_group_termination",
})
PHASE_CHECKS = {
    "git_acquisition": frozenset({"trusted_acquisition", "pinned_dns_egress", "tls_verify", "no_redirects", "origin_bound_credentials"}),
    "offline_build": frozenset({"network_disconnected", "verified_content_mounts", "secrets_outside_project"}),
}


@dataclass(frozen=True)
class ExecutorReadiness:
    """Observed adapter evidence, not capabilities or permission to inject one.

    A reviewed adapter must check actual namespaces, delegated controllers and
    whole-cgroup termination. CLI discovery must not populate these checks.
    Native composition checks these prerequisites with the actual Podman sandbox;
    Core composition never injects or probes an engine adapter.
    """

    backend: str
    platform: str
    checks: frozenset[str] = frozenset()

    def blocked_reasons(self, phase: ExecutionPhase) -> tuple[str, ...]:
        if phase not in PHASE_CHECKS:
            return ("unsupported_phase",)
        missing = set(ROOTLESS_CHECKS | PHASE_CHECKS[phase]) - self.checks
        if self.platform != "linux":
            missing.add("unsupported_platform")
        if self.backend != "linux_rootless_oci":
            missing.add("reviewed_rootless_backend_missing")
        return tuple(sorted(missing))

    def require(self, phase: ExecutionPhase) -> None:
        missing = self.blocked_reasons(phase)
        if missing:
            raise ToolExecutionError("safe_executor_unavailable", "The reviewed rootless execution boundary is unavailable", next_action="Provision and validate the missing isolation prerequisites; host execution is prohibited.", details={"phase": phase, "missing": list(missing)})


class SafeExecutionCancelled(InterruptedError):
    """Trusted executor confirms the phase and all descendants have terminated.

    Lost connection/restart/uncertain completion must never raise this signal;
    ordinary InterruptedError records an unknown outcome needing reconciliation.
    """


class SafeNetworkExecutor(Protocol):
    capabilities: frozenset[str]
    # Per phase: git, npm, pnpm, yarn, python. No implicit SOCKS promise.
    proxy_schemes: dict[str, frozenset[str]]

    def resolve_commit(self, request: dict[str, Any], *, material: dict[str, Any], timeout_seconds: int) -> str:
        """Resolve ref to full SHA in actual execution environment; bound output."""
        ...

    def export_snapshot(self, request: dict[str, Any], *, material: dict[str, Any], cancel: threading.Event) -> bytes:
        """Fetch exact SHA, verify it, export tracked regular files as bounded ZIP.

        Enforce request limits/deadlines/DNS policy before and during I/O. Never
        checkout with filters or initialize submodules. The SHA must match request.
        Clean credentials and all temporary workspace on success/failure/cancel.
        Cancellation may raise SafeExecutionCancelled only after termination is
        confirmed; interrupted transport/lost completion raises InterruptedError.
        """
        ...

    def probe(self, target: str, *, material: dict[str, Any], timeout_seconds: int, max_response_bytes: int, method: str) -> dict[str, Any]:
        """HEAD only, no redirects, DNS pinned, response capped, no body returned."""
        ...

    def run_command(self, command: list[str], *, cwd: Path, environment: dict[str, str], network: dict[str, Any], material: dict[str, Any], timeout_seconds: int, cancel_requested: Any) -> dict[str, Any]:
        """Execute in isolation; credentials only in trusted egress, never child env.

        Verify installed tool version and actual Node engines against
        network.package_manager; return node_version for pnpm 11 (>=22.13).
        Disable Corepack/pnpm/Yarn auto-switch/download and runtime auto-fetch;
        explicit project overrides cannot activate another declared manager.
        Allow only approved registry/index and public dependency origins, reject
        private/link-local/metadata targets and redirects, including through proxy.
        Never auto-approve dependency builds or fetch a new Node runtime.
        Cancel/timeout kills the entire process tree. Bound stdout,
        stderr, resource use and workspace writes. Scan artifact for network values.
        Stop all descendants/writers and freeze the bounded workspace before
        returning; Gate performs an additional contained-link/secret export check.
        """
        ...

    def prepare_package_manager(self, specification: dict[str, Any], *, network: dict[str, Any], material: dict[str, Any], timeout_seconds: int, cancel_requested: Any) -> dict[str, Any]:
        """Prepare exact official distribution in executor-owned versioned cache.

        Use selected install egress/registry; fetch bounded official metadata for
        the exact version (never tags), authenticate only to its bound origin,
        verify mirror content against official dist.integrity, reject redirects,
        verify an additional declared_integrity pin when supplied,
        traversal/links/oversize archives, and execute no package lifecycle.
        Cache key: manager/version/integrity; no global installation/Corepack
        activation. Validate official Node engines (pnpm 11 >=22.13).
        Return actual node_version, package_manager_version,
        source_integrity (SHA-512 SRI), returncode and bounded status only.
        Subsequent run_command must use this verified tool, not host PATH.
        """
        ...


def require_safe_executor(executor: SafeNetworkExecutor | None) -> SafeNetworkExecutor:
    if executor is None or not REQUIRED_CAPABILITIES <= getattr(executor, "capabilities", frozenset()):
        raise ToolExecutionError("safe_executor_unavailable", "A reviewed isolated network executor is unavailable", next_action="Install and validate a dedicated executor; do not enable host execution or relax Core isolation.")
    readiness = getattr(executor, "require_ready", None)
    if readiness is not None:
        readiness()
    return executor


def require_proxy_support(executor: SafeNetworkExecutor, phase: str, scheme: str | None) -> None:
    if scheme is not None and scheme not in executor.proxy_schemes.get(phase, frozenset()):
        raise ToolExecutionError("proxy_scheme_unsupported", "Executor does not support this proxy scheme for the selected phase", next_action="Select a supported profile explicitly; direct fallback is disabled.", details={"phase": phase, "scheme": scheme})

import type { AuthUser } from "@/components/auth-gate"
import type { NetworkProfile, NetworkSelection } from "@/api/network"

export function networkPermission(user: AuthUser, permission: string) {
  return (user.permissions.includes("*") || user.permissions.includes(permission)) && (!["token", "oauth"].includes(user.auth_type) || user.scopes.includes("*") || user.scopes.includes(permission))
}

export function executorNextAction(missing: string[] = [], zh: boolean) {
  const copy = (cn: string, en: string) => zh ? cn : en
  // 只依据后端检查项解释原因；旧接口未返回检查项时，不推断为未安装。
  if (missing.includes("core_gateway_only_native_delivery_disabled")) return copy("当前实例为 Docker Core，仅提供网关功能。请在 Linux Native 实例中完成 Git 拉取、代理测试和受控依赖安装。", "This Docker Core instance provides gateway functions only. Use a Linux Native instance for Git acquisition, proxy tests and controlled dependency installation.")
  if (missing.includes("unsupported_platform_linux_required") || missing.includes("unsupported_platform")) return copy("当前执行器需要 Linux Native 环境，Windows 和 macOS 无法在本机启用。请在受支持的 Linux Native 实例中执行这些操作。", "The executor requires Linux Native; it cannot be enabled locally on Windows or macOS. Perform these operations in a supported Linux Native instance.")
  if (missing.includes("native_executor_not_configured")) return copy("尚未启用 Native 执行器。请 Gate 部署管理员按配置指引准备隔离环境、启用执行器并重启 Gate。", "The Native executor is not enabled. Ask the Gate deployment administrator to provision the isolation environment, enable the executor and restart Gate using the setup guide.")
  // 未知任务优先于暂时忙碌，不能把需要对账的状态解释为等待即可恢复。
  if (missing.some(reason => ["job_reconciliation_required", "executor_reconciliation_or_termination_unknown", "job_workspace_cleanup_incomplete"].includes(reason))) return copy("任务执行或工作区清理状态待核对。请部署管理员确认任务进程与清理结果，完成对账后再重新检查。", "Task execution or workspace cleanup needs reconciliation. Ask the deployment administrator to verify task processes and cleanup results, reconcile them, then check again.")
  if (missing.some(reason => ["job_reconciliation_in_progress", "trusted_dns_resolution_in_progress"].includes(reason))) return copy("任务核对或网络解析仍在进行。请等待完成后重新检查；持续未恢复时联系部署管理员。", "Task reconciliation or DNS resolution is still in progress. Wait for completion and check again; contact the deployment administrator if it persists.")
  if (missing.includes("executor_owned_directories_missing_or_unsafe")) return copy("执行器目录未通过安全检查。请部署管理员准备独立、由 Gate 账户拥有的 0700 执行器目录及 workspaces 目录。", "Executor directories failed safety checks. Ask the deployment administrator to provision separate 0700 executor and workspaces directories owned by the Gate account.")
  if (missing.includes("podman_binary_missing_or_unsafe")) return copy("Podman 可执行文件或权限未通过检查。请部署管理员核对受审二进制的绝对路径、执行权限及写入权限。", "The Podman binary or its permissions failed checks. Ask the deployment administrator to verify the reviewed absolute binary path and its executable and write permissions.")
  if (missing.includes("bounded_tmpfs_workspace_required")) return copy("工作区需要独立、有容量上限的 tmpfs 挂载。请部署管理员设置 nodev、nosuid，并将总容量限制在 2 GiB 以内。", "The workspace requires a separate bounded tmpfs mount. Ask the deployment administrator to set nodev and nosuid and cap total capacity at 2 GiB.")
  if (missing.includes("rootless_user_required") || missing.includes("rootless_engine_required")) return copy("账户或容器引擎未满足 rootless 要求。请使用专用非 root Linux 账户，并为该账户配置 rootless Podman。", "The account or container engine does not meet rootless requirements. Use a dedicated non-root Linux account with rootless Podman configured for that account.")
  if (missing.some(reason => reason === "cgroup_v2_required" || reason.startsWith("delegated_cgroup_controller_"))) return copy("资源隔离配置未通过检查。请部署管理员启用 cgroup v2，并向 Gate 账户委派 CPU、memory、pids 控制器。", "Resource isolation checks failed. Ask the deployment administrator to enable cgroup v2 and delegate the CPU, memory and pids controllers to the Gate account.")
  if (missing.includes("preloaded_exact_image_digest_required")) return copy("固定摘要的执行器镜像尚未通过检查。请部署管理员预加载受审镜像，并将 image 配置为完整的 @sha256 摘要引用。", "The digest-pinned executor image failed checks. Ask the deployment administrator to preload a reviewed image and configure image with its full @sha256 digest reference.")
  return copy("安全执行环境尚未通过就绪检查。请 Gate 部署管理员按配置指引核对运行平台、执行器配置及检查项，修复后重新检查。", "The safe execution environment has not passed readiness checks. Ask the Gate deployment administrator to review the platform, executor configuration and check items using the setup guide, then check again after remediation.")
}

export function selectionKey(selection: NetworkSelection) {
  return selection.mode === "profile" ? `${selection.profile_id}@${selection.version ?? "current"}` : selection.mode
}

export function selectionFromKey(key: string): NetworkSelection {
  if (key === "inherit" || key === "direct") return { mode: key }
  const [profile_id, raw] = key.split("@")
  return { mode: "profile", profile_id, ...(raw && raw !== "current" ? { version: Number(raw) } : {}) }
}

export function selectionOptions(profiles: NetworkProfile[], zh: boolean, inherit = true) {
  return [
    ...(inherit ? [{ value: "inherit", label: zh ? "继承系统默认（计划时固定）" : "Inherit system default (pin at planning)" }] : []),
    { value: "direct", label: zh ? "直连（不使用代理）" : "Direct (no proxy)" },
    ...profiles.map(profile => ({ value: `${profile.id}@${profile.version}`, label: `${profile.name} · v${profile.version} · ${profile.scheme}${profile.enabled ? "" : zh ? " · 已停用" : " · Disabled"}`, disabled: !profile.enabled || !profile.credential_configured })),
  ]
}

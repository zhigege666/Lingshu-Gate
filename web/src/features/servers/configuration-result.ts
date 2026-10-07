import type { ApplyResponse } from "@/api/client"

/** HTTP success alone cannot establish that the replacement runtime started. */
export function configurationResultError(response: ApplyResponse, serverId: string, apply: boolean, zh = false): string | null {
  if (response.config?.id !== serverId) return zh ? "保存结果尚未确认，请刷新配置后再操作。" : "The save result is unknown. Refresh the configuration before trying again."
  if (!apply) return null
  if (response.server?.id !== serverId || response.server.status !== "running") {
    return response.server?.last_error || (zh ? `配置已保存，但运行状态尚未确认（${response.server?.status || "未知"}）。请先检查服务状态，勿盲目重试。` : `Configuration saved, but runtime activation is not confirmed (${response.server?.status || "unknown"}). Inspect the service before retrying.`)
  }
  return null
}

/** Apply replaces the runtime without starting: loaded/external are valid idle states. */
export function configurationApplyResultError(response: ApplyResponse, serverId: string, zh = false): string | null {
  const unknown = zh ? "配置应用状态未知，请查看服务状态。" : "Configuration application state is unknown. Inspect the service."
  const server = response.server
  if (response.config?.id !== serverId || server?.id !== serverId) return unknown
  const idle = server.status === "stopped"
    || server.status === "loaded" && ["managed_process", "managed_container"].includes(server.launch_type)
    || server.status === "external" && server.launch_type === "external"
  const error = server.last_error && !(server.enabled === false && server.last_error === "Server is disabled")
    ? server.last_error : null
  if (error) return error
  if (!idle || server.desired_state !== "stopped" || server.effective_should_run !== false || server.pid != null) return unknown
  return null
}

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

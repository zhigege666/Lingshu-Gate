import type { AccessResource, ToolDefinition } from "@/api/client"
import type { Locale } from "@/i18n"

const BUILTIN_NAMES = {
  builtin: { "zh-CN": "Gate 基础能力", "en-US": "Gate core capabilities" },
  "gate-control": { "zh-CN": "工具审核管理", "en-US": "Tool review management" },
  "gate-delivery": { "zh-CN": "项目交付与服务管理", "en-US": "Project delivery and service management" },
  "gate-tool-files": { "zh-CN": "工具文件传输", "en-US": "Tool file transfer" },
} satisfies Record<string, Record<Locale, string>>

export function builtinOriginName(source: unknown, serverId: string, locale: Locale): string | null {
  if (source !== "builtin" || !Object.prototype.hasOwnProperty.call(BUILTIN_NAMES, serverId)) return null
  return BUILTIN_NAMES[serverId as keyof typeof BUILTIN_NAMES][locale]
}

export function toolOriginName(tool: ToolDefinition, locale: Locale): string | null {
  const serverId = typeof tool.metadata.server_id === "string" ? tool.metadata.server_id : tool.source
  return builtinOriginName(tool.source, serverId, locale)
}

/** Missing or mixed origin evidence never earns a built-in label or badge. */
export function grantOriginName(resources: AccessResource[], serverId: string, toolId: string | null | undefined, locale: Locale): string | null {
  const selected = resources.filter(item => item.server_id === serverId && (!toolId || item.tool_id === toolId))
  return selected.length && selected.every(item => item.registry_source === "builtin") ? builtinOriginName("builtin", serverId, locale) : null
}

export const builtinOriginBadge = (locale: Locale) => locale === "zh-CN" ? "系统内置" : "Built in"

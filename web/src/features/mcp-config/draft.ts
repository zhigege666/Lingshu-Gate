import { getRecord, type ManifestLike, type RuntimeMode } from "./model"

// 表单按路径修改同一份草稿，仅替换目标字段，保留未覆盖的扩展配置。
export function updateManifestPath(manifest: ManifestLike, path: string[], value: unknown): ManifestLike {
  const [key, ...rest] = path
  if (!key) return manifest
  const next = { ...manifest }
  if (rest.length) next[key] = updateManifestPath(getRecord(manifest[key]), rest, value)
  else if (value === undefined) delete next[key]
  else next[key] = value
  return next
}

export function changeRuntimeMode(manifest: ManifestLike, mode: Exclude<RuntimeMode, "advanced">): ManifestLike {
  const launch = { ...getRecord(manifest.launch) }
  const transport = { ...getRecord(manifest.transport) }
  // 仅显式切换运行方式时移除目标模式不接受的字段，普通编辑不归一化配置。
  for (const key of ["image", "mounts", "environment", "resources"]) delete launch[key]
  launch.type = mode === "external_http" ? "external" : "managed_process"
  if (mode === "external_http") {
    for (const key of ["command", "args", "cwd", "env", "package"]) delete launch[key]
  }
  transport.type = mode === "managed_stdio" ? "stdio" : "streamable_http"
  if (mode === "managed_stdio") {
    delete transport.endpoint
    delete transport.headers
  }
  return {
    ...manifest, launch, transport,
    ...(mode === "external_http" ? { auto_start: false, restart_policy: {
      ...getRecord(manifest.restart_policy), enabled: false,
      health_check: { ...getRecord(getRecord(manifest.restart_policy).health_check), enabled: false },
    } } : {}),
  }
}

export function manifestFingerprint(text: string): string {
  try { return JSON.stringify(JSON.parse(text)) } catch { return text }
}

export const PROTECTED_HEADERS = new Set([
  "content-type", "accept", "mcp-session-id", "mcp-protocol-version", "mcp-method", "mcp-name",
])

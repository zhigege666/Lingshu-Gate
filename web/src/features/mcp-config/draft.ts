import { patchManifestField, type ManifestLike } from "./model"

// Tests and the real editor share the same conversion; no alternate runtime rules.
export { changeRuntimeMode } from "./model"

// 表单按路径修改同一份草稿，仅替换目标字段，保留未覆盖的扩展配置。
export function updateManifestPath(manifest: ManifestLike, path: string[], value: unknown): ManifestLike {
  return patchManifestField(manifest, path, value === undefined ? { kind: "remove" } : { kind: "set", value })
}

export function manifestFingerprint(text: string): string {
  try { return JSON.stringify(JSON.parse(text)) } catch { return text }
}

export const PROTECTED_HEADERS = new Set([
  "content-type", "accept", "mcp-session-id", "mcp-protocol-version", "mcp-method", "mcp-name",
])

import type { RuntimeCacheClearResponse, RuntimeCacheItem, RuntimeCachePathInfo } from "@/api/client"
import type { Locale } from "@/i18n"
export const cacheCopy = {
  "zh-CN": { access: "目录访问", writable: "可写", creatable: "可创建", blocked: "不可写", invalid: "路径不是目录", empty: "无需清理", emptyHint: "没有缓存文件，无需清理。", unreadable: "无法读取缓存，请先检查目录权限。", permissions: "清理需要缓存及父目录可写。", clearFailed: "未确认缓存已清空，请刷新查看当前状态。", refreshFailed: "清理已完成，但状态刷新失败。下方保留清理响应；请刷新后再操作。", alreadyEmpty: "缓存已为空，无需释放文件", unchanged: "不可清理", files: "个文件", impact: "清理后相关服务将在下次启动时重建缓存。" },
  "en-US": { access: "Directory access", writable: "Writable", creatable: "Can create", blocked: "Not writable", invalid: "Path is not a directory", empty: "Nothing to clear", emptyHint: "No cached files; no cleanup is needed.", unreadable: "Cannot inspect cache contents; check directory permissions first.", permissions: "Cleanup needs writable cache and parent directories.", clearFailed: "Cache cleanup was not confirmed. Refresh to inspect the current state.", refreshFailed: "Cleanup completed, but refreshing status failed. The cleanup response is retained below; refresh before another action.", alreadyEmpty: "Cache was already empty; no files needed removal", unchanged: "Cannot clear", files: "files", impact: "Related services will rebuild required caches on their next start." },
} satisfies Record<Locale, Record<string, string>>
export function cacheAccess(path: RuntimeCachePathInfo): "writable" | "creatable" | "blocked" | "invalid" {
  if (path.exists) return !path.is_dir ? "invalid" : path.writable ? "writable" : "blocked"
  return path.parent_writable ? "creatable" : "blocked"
}
export function cacheClearBlock(cache: RuntimeCacheItem): "emptyHint" | "unreadable" | "permissions" | "invalid" | null {
  if (!cache.exists) return "emptyHint"
  if (!cache.is_dir) return "invalid"
  if (!cache.readable) return "unreadable"
  if (cache.file_count === 0 && cache.size_bytes === 0) return "emptyHint"
  if (!cache.writable || !cache.parent_writable) return "permissions"
  return null
}
export function cacheCleanupConfirmed(result: RuntimeCacheClearResponse, name: string): boolean {
  return result.cache === name && result.after?.name === name && result.after.exists && result.after.is_dir && result.after.file_count === 0 && result.after.size_bytes === 0
}

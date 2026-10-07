import type { BuildLog } from "@/api/builds"

// Only the display window is bounded; older records remain in server history.
export const BUILD_LOG_WINDOW = 200
export function mergeBuildLogWindow(previous: readonly BuildLog[], incoming: readonly BuildLog[]) {
  const unique = new Map(previous.map(log => [log.id, log]))
  for (const log of incoming) unique.set(log.id, log)
  return [...unique.values()].sort((a, b) => a.sequence - b.sequence).slice(-BUILD_LOG_WINDOW)
}

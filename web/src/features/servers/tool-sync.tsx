import { Badge } from "antd"
import type { McpToolSync } from "@/api/client"
import type { ServerCopy } from "@/features/servers/copy"
import { formatDateTime } from "@/lib/utils"

export function ToolSyncBadge({ sync, c }: { sync: McpToolSync; c: ServerCopy }) {
  const labels: Record<McpToolSync["state"], string> = {
    idle: c.syncIdle, syncing: c.syncing, ready: c.syncReady,
    retrying: c.syncRetrying, auth_required: c.syncAuthRequired, disabled: c.syncDisabled,
  }
  const status = sync.state === "auth_required" ? "error" : sync.state === "retrying" ? "warning" : sync.state === "syncing" ? "processing" : sync.state === "ready" ? "success" : "default"
  return <Badge status={status} text={labels[sync.state]} />
}

export function ToolSyncSummary({ sync, c }: { sync: McpToolSync; c: ServerCopy }) {
  return <div className="service-tool-sync" role="status">
    <ToolSyncBadge sync={sync} c={c} />
    <span>{c.lastSynced}: {sync.last_success_at ? formatDateTime(sync.last_success_at) : c.neverSynced}</span>
    {sync.state === "retrying" && sync.next_sync_at && <span>{c.nextSync}: {formatDateTime(sync.next_sync_at)}</span>}
  </div>
}

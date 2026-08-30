import type { BuildLog, BuildRecord } from "@/api/builds"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { localizeStatus, type TFunction } from "@/i18n"
import { StatusBadge } from "@/components/builds/status-badge"
import { formatDateTime } from "@/components/builds/build-utils"
import { buildPageText } from "@/pages/builds-page-text"

export function BuildTimelineCard({ build, logs, t }: { build: BuildRecord | null; logs: BuildLog[]; t: TFunction }) {
  if (!build) return null
  const phases = buildTimeline(build, logs, t)
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("startupTimeline")}</CardTitle>
        <CardDescription>{build.id}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        {phases.map((phase) => (
          <div key={phase.key} className="flex items-start gap-3 rounded-lg border p-3 text-sm">
            <StatusBadge value={phase.status} t={t} />
            <div className="min-w-0 flex-1">
              <div className="font-medium">{phase.label}</div>
              <div className="break-words text-xs text-muted-foreground">{phase.detail}</div>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  )
}

function buildTimeline(build: BuildRecord, logs: BuildLog[], t: TFunction) {
  const tx = (key: string) => buildPageText(t, key)
  const hasPhase = (phase: string) => logs.some((log) => log.phase === phase)
  const commandCount = logs.filter((log) => log.phase === "command").length
  return [
    { key: "queued", label: tx("timelineQueued"), status: "info", detail: formatDateTime(build.created_at) },
    { key: "prepare", label: tx("timelinePrepare"), status: hasPhase("prepare") ? "info" : "outline", detail: hasPhase("prepare") ? tx("timelinePrepareDone") : tx("timelineWaiting") },
    { key: "command", label: tx("timelineCommands"), status: commandCount > 0 ? "info" : "outline", detail: `${commandCount} ${tx("commandLogs")}` },
    { key: "final", label: localizeStatus(t, build.status), status: build.status, detail: build.error || formatDateTime(build.updated_at) },
  ]
}

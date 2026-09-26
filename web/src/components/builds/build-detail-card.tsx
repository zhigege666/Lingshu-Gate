import type { BuildLog, BuildRecord, BuildStepState } from "@/api/builds"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { localizeStatus, type TFunction } from "@/i18n"
import { JsonPanel } from "@/components/json-panel"
import { uploadCopy } from "@/components/uploads/upload-copy"
import { StatusBadge } from "@/components/builds/status-badge"
import { copyText, formatCommand, formatDateTime } from "@/components/builds/build-utils"

export function BuildDetailCard({ build, logs, streamConnected, t, onCopied }: { build: BuildRecord | null; logs: BuildLog[]; streamConnected: boolean; t: TFunction; onCopied: (message: string) => void }) {
  const c = uploadCopy(t)
  if (!build) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("buildDetail")}</CardTitle>
        <CardDescription>{t("buildDetailDesc")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <dl className="grid gap-3 text-sm sm:grid-cols-2 xl:grid-cols-4">
          <Info label={t("status")} value={localizeStatus(t, build.status)} />
          <Info label={t("runtimeType")} value={build.runtime} />
          <Info label={t("start")} value={build.entrypoint || "-"} />
          <Info label={c.liveConnection} value={streamConnected ? c.connected : c.disconnected} />
          <Info label={t("uploadId")} value={build.upload_id} />
          <Info label={t("createdAt")} value={formatDateTime(build.created_at)} />
          <Info label={t("updatedAt")} value={formatDateTime(build.updated_at)} />
          <Info label={t("logCount")} value={String(logs.length)} />
        </dl>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" onClick={() => void copyText(build.id).then((ok) => ok && onCopied(t("copyBuildId")))}>{t("copyBuildId")}</Button>
          <Button size="sm" variant="secondary" onClick={() => void copyText(build.artifact_dir).then((ok) => ok && onCopied(t("copyArtifactPath")))}>{t("copyArtifactPath")}</Button>
          <Button size="sm" variant="secondary" onClick={() => void copyText(JSON.stringify(build.manifest || {}, null, 2)).then((ok) => ok && onCopied(t("copyManifest")))}>{t("copyManifest")}</Button>
        </div>
        {build.steps && build.steps.length ? <StepStates steps={build.steps} t={t} /> : null}
        <div className="grid gap-4 xl:grid-cols-2">
          <div className="flex flex-col gap-2">
            <div className="font-medium">{t("buildCommands")}</div>
            <JsonPanel text={build.commands.length ? build.commands.map(formatCommand).join("\n") : t("noData")} maxHeight="max-h-[220px]" />
          </div>
          <div className="flex flex-col gap-2">
            <div className="font-medium">{t("buildManifestPreview")}</div>
            <JsonPanel data={build.manifest || {}} maxHeight="max-h-[220px]" />
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

function Info({ label, value }: { label: string; value: string }) {
  return <div><dt className="text-xs text-muted-foreground">{label}</dt><dd className="mt-1 break-all font-medium">{value}</dd></div>
}

function StepStates({ steps, t }: { steps: BuildStepState[]; t: TFunction }) {
  return (
    <div className="flex flex-col gap-2">
      <div className="font-medium">{t("buildStepStates")}</div>
      <div className="overflow-x-auto rounded-md border">
        <table className="w-full text-sm">
          <thead><tr className="border-b"><th className="px-3 py-2 text-left">#</th><th className="px-3 py-2 text-left">{t("phase")}</th><th className="px-3 py-2 text-left">{t("command")}</th><th className="px-3 py-2 text-left">{t("status")}</th><th className="px-3 py-2 text-left">{t("duration")}</th></tr></thead>
          <tbody>{steps.map((step) => <tr key={`${step.index}-${step.id}`} className="border-b last:border-0"><td className="px-3 py-2 font-mono">{step.index + 1}</td><td className="px-3 py-2 font-mono">{step.phase}</td><td className="px-3 py-2 font-mono">{step.command.join(" ")}</td><td className="px-3 py-2"><StatusBadge value={step.status} t={t} /></td><td className="px-3 py-2 font-mono text-muted-foreground">{step.duration_ms != null ? `${step.duration_ms} ms` : "-"}</td></tr>)}</tbody>
        </table>
      </div>
    </div>
  )
}

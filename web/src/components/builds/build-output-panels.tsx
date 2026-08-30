import type { BuildLog, BuildRecord } from "@/api/builds"
import { JsonPanel } from "@/components/json-panel"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { localizeStatus, type TFunction } from "@/i18n"

export function BuildOutputPanels({ build, log, t }: { build: BuildRecord | null; log: BuildLog | null; t: TFunction }) {
  const stderrText = String(log?.stderr || build?.error || t("noData"))
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle>{t("buildStdout")}</CardTitle>
          <CardDescription>{log?.command?.join(" ") || t("noData")}</CardDescription>
        </CardHeader>
        <CardContent><JsonPanel text={String(log?.stdout || t("noData"))} maxHeight="max-h-[360px]" /></CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{t("buildStderr")}</CardTitle>
          <CardDescription>{log ? `${t("status")}: ${localizeStatus(t, log.level)}` : t("noData")}</CardDescription>
        </CardHeader>
        <CardContent><JsonPanel text={stderrText} maxHeight="max-h-[360px]" /></CardContent>
      </Card>
    </div>
  )
}

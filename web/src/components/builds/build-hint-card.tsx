import type { BuildRecord } from "@/api/builds"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import type { TFunction } from "@/i18n"
import { localizeFailureHint } from "@/components/builds/build-utils"

export function BuildHintCard({ build, t }: { build: BuildRecord | null; t: TFunction }) {
  const hint = localizeFailureHint(t, build?.failure_hint)
  if (!build || !hint) return null
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2"><Badge variant="warning">{t("failureCode")}</Badge>{hint.title}</CardTitle>
        <CardDescription>{t("failureCode")}: {hint.code}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-2 text-sm">
        <p><span className="font-medium">{t("failureSuggestion")}：</span>{hint.suggestion}</p>
        {build.error && <pre className="whitespace-pre-wrap rounded bg-muted p-2 text-xs">{build.error}</pre>}
      </CardContent>
    </Card>
  )
}

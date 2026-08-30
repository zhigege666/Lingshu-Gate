import { useEffect, useState } from "react"
import { api, type DiagnosticsResponse, type RuntimeEnvironment } from "@/api/client"
import { PageHeader, PageToolbar } from "@/components/page-shell"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { JsonPanel } from "@/components/json-panel"
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import type { TFunction } from "@/i18n"
import { statusBadge, TableEmptyRow } from "@/pages/page-utils"

type DiagnosticsCheck = DiagnosticsResponse["checks"][number]

export function DiagnosticsPage({ diagnostics, t, onRunDiagnostics }: { diagnostics: DiagnosticsResponse | null; t: TFunction; onRunDiagnostics: () => void }) {
  const [selectedCheck, setSelectedCheck] = useState<DiagnosticsCheck | null>(null)
  const [query, setQuery] = useState("")
  const checks = diagnostics?.checks || []
  const failedChecks = checks.filter((check) => !check.ok)
  const filteredChecks = [...checks]
    .sort((left, right) => Number(left.ok) - Number(right.ok))
    .filter((check) => !query.trim() || `${check.name} ${check.detail} ${check.severity}`.toLowerCase().includes(query.trim().toLowerCase()))
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        eyebrow={t("healthCheck")}
        title={t("diagnostics")}
        description={t("runtimeEnvironmentDesc")}
        stats={[
          { label: t("check"), value: checks.length },
          { label: t("failed"), value: failedChecks.length, tone: failedChecks.length ? "danger" : "success" },
          { label: t("status"), value: failedChecks.length ? t("warning") : checks.length ? t("ok") : t("waiting"), tone: failedChecks.length ? "warning" : checks.length ? "success" : "default" },
        ]}
        actions={<Button onClick={onRunDiagnostics}>{t("runDiagnostics")}</Button>}
      />
      <Card>
        <CardHeader><CardTitle>{t("diagnostics")}</CardTitle><CardDescription>{failedChecks.length ? `${failedChecks.length} ${t("failed")}` : t("ok")}</CardDescription></CardHeader>
        <CardContent className="flex flex-col gap-3">
          <PageToolbar query={query} onQueryChange={setQuery} placeholder={`${t("search")} ${t("check")} / ${t("detail")}`} resultCount={filteredChecks.length} resultLabel={t("check")} clearLabel={t("clearSearch")} />
          <Table><TableHeader><TableRow><TableHead>{t("check")}</TableHead><TableHead>{t("status")}</TableHead><TableHead>{t("detail")}</TableHead></TableRow></TableHeader><TableBody>{filteredChecks.length === 0 ? <TableEmptyRow colSpan={3} title={t("noData")} /> : filteredChecks.map((check) => <TableRow key={check.name} className="cursor-pointer" onClick={() => setSelectedCheck(check)}><TableCell className="font-medium">{check.name}</TableCell><TableCell>{statusBadge(check.ok ? "ok" : check.severity, t)}</TableCell><TableCell className="max-w-md truncate text-muted-foreground" title={check.detail}>{check.detail}</TableCell></TableRow>)}</TableBody></Table>
        </CardContent>
      </Card>
      <RuntimeEnvironmentCard t={t} />

      <Dialog open={selectedCheck !== null} onOpenChange={(open) => { if (!open) setSelectedCheck(null) }}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">{selectedCheck ? statusBadge(selectedCheck.ok ? "ok" : selectedCheck.severity, t) : null}{selectedCheck?.name}</DialogTitle>
            <DialogDescription>{t("detail")}</DialogDescription>
          </DialogHeader>
          <DialogBody><JsonPanel data={selectedCheck} maxHeight="max-h-[60vh]" /></DialogBody>
        </DialogContent>
      </Dialog>
    </div>
  )
}

function RuntimeEnvironmentCard({ t }: { t: TFunction }) {
  const [env, setEnv] = useState<RuntimeEnvironment | null>(null)
  const [error, setError] = useState("")

  async function refresh() {
    try {
      setEnv(await api.runtimeEnvironment())
      setError("")
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  useEffect(() => { void refresh() }, [])

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("runtimeEnvironment")}</CardTitle>
        <CardDescription>{t("runtimeEnvironmentDesc")} <Button size="sm" variant="secondary" onClick={() => void refresh()}>{t("refresh")}</Button></CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {error ? <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert> : null}
        {env ? <>
          <div className="grid gap-2 text-sm md:grid-cols-4">
            <Field label={t("platform")} value={env.platform} />
            <Field label={t("gateDeployment")} value={env.gate_deployment} />
            <Field label={t("dockerMode")} value={env.docker.mode} tone={env.docker.mode === "unavailable" ? "muted" : "ok"} />
            <Field label="Python" value={env.python_version} />
          </div>
          <div>
            <div className="mb-1 text-sm font-medium">{t("launchCapabilities")}</div>
            <div className="overflow-x-auto rounded-md border">
              <table className="w-full text-sm">
                <thead><tr className="border-b"><th className="px-3 py-2 text-left">{t("launchType")}</th><th className="px-3 py-2 text-left">{t("status")}</th><th className="px-3 py-2 text-left">{t("detail")}</th></tr></thead>
                <tbody>{Object.entries(env.launch_capabilities).map(([name, cap]) => <tr key={name} className="border-b last:border-0"><td className="px-3 py-2 font-mono">{name}</td><td className="px-3 py-2"><Badge variant={cap.available ? "success" : "secondary"}>{cap.available ? t("available") : t("unavailable")}</Badge></td><td className="px-3 py-2 text-muted-foreground">{cap.reason}</td></tr>)}</tbody>
              </table>
            </div>
          </div>
          <div>
            <div className="mb-1 text-sm font-medium">{t("toolchain")}</div>
            <div className="flex flex-wrap gap-2">
              {Object.entries(env.toolchain).map(([name, ok]) => <Badge key={name} variant={ok ? "success" : "outline"} className="font-mono">{name}: {ok ? t("available") : t("unavailable")}</Badge>)}
              <Badge variant={env.docker.cli_available ? "success" : "outline"} className="font-mono" title={env.docker.version || ""}>docker: {env.docker.cli_available ? t("available") : t("unavailable")}</Badge>
            </div>
          </div>
        </> : null}
      </CardContent>
    </Card>
  )
}

function Field({ label, value, tone }: { label: string; value: string; tone?: "ok" | "muted" }) {
  return <div><span className="text-muted-foreground">{label}</span><div className="font-mono font-medium">{tone === "muted" ? <span className="text-muted-foreground">{value}</span> : tone === "ok" ? <Badge variant="success">{value}</Badge> : value}</div></div>
}

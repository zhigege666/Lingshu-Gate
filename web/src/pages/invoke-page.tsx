import { useMemo } from "react"
import { Play } from "lucide-react"
import type { ToolDefinition } from "@/api/client"
import { JsonPanel } from "@/components/json-panel"
import { PageHeader, WorkflowSteps } from "@/components/page-shell"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Textarea } from "@/components/ui/textarea"
import type { TFunction } from "@/i18n"

export function InvokePage(props: {
  t: TFunction
  tools: ToolDefinition[]
  selectedTool: ToolDefinition | undefined
  selectedToolId: string
  invokeArgs: string
  invokeResult: string
  onToolChange: (value: string) => void
  onArgsChange: (value: string) => void
  onInvoke: () => void
}) {
  const { t, tools, selectedTool, selectedToolId, invokeArgs, invokeResult, onToolChange, onArgsChange, onInvoke } = props
  const validationError = useMemo(() => {
    try {
      const value = JSON.parse(invokeArgs)
      return value && typeof value === "object" && !Array.isArray(value) ? "" : t("jsonObjectRequired")
    } catch (error) {
      return t("invalidJson")
    }
  }, [invokeArgs, t])
  const hasResult = invokeResult !== t("waiting")
  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        eyebrow={t("toolTesting")}
        title={t("invoke")}
        description={selectedTool?.description || t("serverToolsHint")}
        stats={[
          { label: t("tools"), value: tools.length },
          { label: t("source"), value: selectedTool?.source || "-" },
          { label: t("permission"), value: selectedTool?.permission || "-" },
        ]}
      />
      <WorkflowSteps ariaLabel={t("workflowProgress")} steps={[
        { label: t("tools"), state: selectedTool ? "done" : "current" },
        { label: t("arguments"), state: !selectedTool ? "next" : validationError ? "current" : "done" },
        { label: t("result"), state: hasResult ? "done" : selectedTool && !validationError ? "current" : "next" },
      ]} />
      <div className="grid gap-4 xl:grid-cols-2">
      <Card><CardHeader><CardTitle>{t("invoke")}</CardTitle><CardDescription>{selectedTool?.id || t("waiting")}</CardDescription></CardHeader><CardContent className="flex flex-col gap-3"><Select value={selectedToolId || "__none"} onValueChange={(value) => onToolChange(value === "__none" ? "" : value)}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="__none">-</SelectItem>{tools.map((tool) => <SelectItem key={tool.id} value={tool.id}>{tool.id}</SelectItem>)}</SelectContent></Select>{selectedTool ? <div className="flex flex-wrap gap-2"><Badge variant="outline">{selectedTool.source}</Badge><Badge variant="secondary">{selectedTool.permission}</Badge></div> : null}<Label>{t("arguments")}</Label><Textarea value={invokeArgs} onChange={(event) => onArgsChange(event.target.value)} aria-invalid={Boolean(validationError) || undefined} className="min-h-[220px] font-mono" />{validationError ? <Alert variant="destructive"><AlertDescription>{validationError}</AlertDescription></Alert> : null}{selectedTool ? <details className="rounded-md border p-3"><summary className="cursor-pointer text-sm font-medium">{t("inputSchema")}</summary><div className="mt-3"><JsonPanel data={selectedTool.input_schema} maxHeight="max-h-64" /></div></details> : null}<Button onClick={onInvoke} disabled={!selectedToolId || Boolean(validationError)}><Play />{t("invokeTool")}</Button></CardContent></Card>
      <Card><CardHeader><CardTitle>{t("result")}</CardTitle><CardDescription>{hasResult ? selectedTool?.id : t("waiting")}</CardDescription></CardHeader><CardContent><JsonPanel text={invokeResult} maxHeight="max-h-[540px]" /></CardContent></Card>
      </div>
    </div>
  )
}

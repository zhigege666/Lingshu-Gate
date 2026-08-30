import { useMemo, useState } from "react"
import { Play } from "lucide-react"
import type { ToolDefinition } from "@/api/client"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { PageHeader, PageToolbar } from "@/components/page-shell"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import type { TFunction } from "@/i18n"
import { JsonPanel } from "@/components/json-panel"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { TableEmptyRow } from "@/pages/page-utils"

export function ToolsPage({ tools, t }: { tools: ToolDefinition[]; t: TFunction }) {
  const [selected, setSelected] = useState<ToolDefinition | null>(null)
  const [query, setQuery] = useState("")
  const [source, setSource] = useState("__all")
  const filteredTools = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return tools.filter((tool) => {
      if (source !== "__all" && tool.source !== source) return false
      if (!needle) return true
      return `${tool.id} ${tool.name} ${tool.description} ${tool.permission} ${tool.source}`.toLowerCase().includes(needle)
    })
  }, [query, source, tools])
  const sources = Array.from(new Set(tools.map((tool) => tool.source))).sort()
  return (
    <div className="flex flex-col gap-4">
    <PageHeader
      eyebrow={t("toolRegistry")}
      title={t("tools")}
      description={t("serverToolsHint")}
      stats={[{ label: t("total"), value: tools.length }, { label: t("source"), value: sources.length }, { label: t("mcpTools"), value: tools.filter((tool) => tool.source === "mcp").length }]}
      actions={<Button asChild><a href="#/invoke"><Play />{t("invoke")}</a></Button>}
    />
    <Card>
      <CardHeader><CardTitle>{t("tools")}</CardTitle></CardHeader>
      <CardContent className="flex flex-col gap-3">
        <PageToolbar query={query} onQueryChange={setQuery} placeholder={`${t("search")} ID / ${t("description")}`} resultCount={filteredTools.length} resultLabel={t("tools")} clearLabel={t("clearSearch")}>
          <Select value={source} onValueChange={setSource}><SelectTrigger className="w-40"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="__all">{t("all")}</SelectItem>{sources.map((item) => <SelectItem key={item} value={item}>{item}</SelectItem>)}</SelectContent></Select>
        </PageToolbar>
        <Table>
          <TableHeader><TableRow><TableHead>{t("id")}</TableHead><TableHead>{t("source")}</TableHead><TableHead>{t("permission")}</TableHead><TableHead>{t("description")}</TableHead></TableRow></TableHeader>
          <TableBody>{filteredTools.length === 0 ? <TableEmptyRow colSpan={4} title={t("noData")} /> : filteredTools.map((tool) => <TableRow key={tool.id} className="cursor-pointer" onClick={() => setSelected(tool)}><TableCell><code>{tool.id}</code></TableCell><TableCell><Badge variant="outline">{tool.source}</Badge></TableCell><TableCell>{tool.permission}</TableCell><TableCell className="max-w-md truncate" title={tool.description}>{tool.description}</TableCell></TableRow>)}</TableBody>
        </Table>
      </CardContent>

      <Dialog open={selected !== null} onOpenChange={(open) => { if (!open) setSelected(null) }}>
        <DialogContent className="max-w-3xl">
          <DialogHeader>
            <DialogTitle>{selected?.name || selected?.id}</DialogTitle>
            <DialogDescription>{selected?.id}</DialogDescription>
          </DialogHeader>
          <DialogBody className="flex flex-col gap-4">
            <div className="flex flex-wrap gap-2 text-xs">
              <Badge variant="outline">{t("source")}: {selected?.source}</Badge>
              <Badge variant="outline">{t("permission")}: {selected?.permission}</Badge>
            </div>
            {selected?.description ? <p className="text-sm text-muted-foreground">{selected.description}</p> : null}
            <div>
              <div className="mb-1 text-sm font-medium">{t("inputSchema")}</div>
              <JsonPanel data={selected?.input_schema ?? {}} maxHeight="max-h-80" />
            </div>
            {selected?.metadata && Object.keys(selected.metadata).length > 0 ? <div>
              <div className="mb-1 text-sm font-medium">{t("metadata")}</div>
              <JsonPanel data={selected.metadata} maxHeight="max-h-60" />
            </div> : null}
            <Button asChild><a href="#/invoke"><Play />{t("invokeTool")}</a></Button>
          </DialogBody>
        </DialogContent>
      </Dialog>
    </Card>
    </div>
  )
}

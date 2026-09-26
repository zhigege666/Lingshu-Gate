import { useMemo, useState } from "react"
import { Select } from "antd"
import { ArrowUpRight, ChevronLeft, ChevronRight, Eye, PencilLine, Play, Plug, RotateCcw, Server, Wrench } from "lucide-react"
import type { McpServer, ToolDefinition } from "@/api/client"
import { JsonPanel } from "@/components/json-panel"
import { InlineEmpty, PageHeader, PageToolbar } from "@/components/page-shell"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import { ALL_TOOL_SERVICES, BUILTIN_TOOL_SERVICE, filterTools, paginateTools, toolAccess, toolServerId, toolServiceOptions, type ToolAccess } from "@/features/tool-catalog"
import type { TFunction } from "@/i18n"
import "./tools-page.css"

type Props = {
  tools: ToolDefinition[]
  servers: McpServer[]
  loading: boolean
  error: string | null
  t: TFunction
  onInvoke: (toolId: string) => void
  onRefresh: () => void
}

export function ToolsPage({ tools, servers, loading, error, t, onInvoke, onRefresh }: Props) {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [service, setService] = useState(ALL_TOOL_SERVICES)
  const [access, setAccess] = useState<"all" | ToolAccess>("all")
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(9)
  const services = useMemo(() => toolServiceOptions(tools, servers), [tools, servers])
  const filteredTools = useMemo(() => filterTools(tools, servers, { query, service, access }), [tools, servers, query, service, access])
  const paged = paginateTools(filteredTools, page, pageSize)
  const selected = tools.find(tool => tool.id === selectedId) || null
  const filtered = Boolean(query || service !== ALL_TOOL_SERVICES || access !== "all")
  const accessLabel = (value: ToolAccess) => t(value === "read" ? "toolReadOnly" : value === "write" ? "toolWrite" : "toolAccessUnknown")
  const serviceLabel = (tool: ToolDefinition) => {
    if (tool.source === "builtin") return t("builtinTools")
    const id = toolServerId(tool)
    const name = servers.find(server => server.id === id)?.name
    return id && name && name !== id ? `${name} · ${id}` : id || tool.source
  }
  function resetFilters() {
    setQuery(""); setService(ALL_TOOL_SERVICES); setAccess("all"); setPage(1)
  }

  return <div className="tool-catalog">
    <PageHeader
      eyebrow={t("toolRegistry")}
      title={t("tools")}
      description={t("toolCatalogHint")}
      helpLabel={t("pageHelp")}
      toolbar={<PageToolbar
        query={query} onQueryChange={value => { setQuery(value); setPage(1) }}
        placeholder={t("searchTools")} clearLabel={t("clearSearch")}
      >
        <Select
          className="tool-service-filter" aria-label={t("mcpServers")}
          value={service} onChange={value => { setService(value); setPage(1) }}
          showSearch={{ optionFilterProp: "label" }}
          popupMatchSelectWidth={false}
          options={[
            { value: ALL_TOOL_SERVICES, label: t("allToolServices") },
            { value: BUILTIN_TOOL_SERVICE, label: t("builtinTools") },
            ...services.map(item => ({ value: item.value, label: `${item.name}${item.name !== item.id ? ` · ${item.id}` : ""} (${item.count})` })),
          ]}
          notFoundContent={t("noData")}
        />
        <Select
          className="tool-access-filter" aria-label={t("permission")}
          value={access} onChange={value => { setAccess(value); setPage(1) }}
          options={[
            { value: "all", label: t("allToolPermissions") },
            { value: "read", label: t("toolReadOnly") },
            { value: "write", label: t("toolWrite") },
            { value: "unknown", label: t("toolAccessUnknown") },
          ]}
        />
        {filtered && <Button variant="ghost" size="sm" onClick={resetFilters}><RotateCcw />{t("resetFilters")}</Button>}
      </PageToolbar>}
    />

    <div className="tool-catalog-summary" role="status">
      <span><strong>{t("toolRegistry")}</strong><Badge variant="secondary">{loading ? "…" : filteredTools.length}</Badge></span>
      <span>{loading ? t("toolCatalogLoading") : `${t("total")} ${tools.length} ${t("tools")}`}</span>
    </div>

    {error ? <Alert variant="destructive"><AlertDescription className="flex flex-wrap items-center justify-between gap-3">
      <span>{t("toolCatalogLoadFailed")} · {error}</span><Button size="sm" variant="outline" onClick={onRefresh}>{t("retry")}</Button>
    </AlertDescription></Alert> : loading ? <div className="tool-catalog-grid" aria-busy="true" aria-label={t("toolCatalogLoading")}>
      {Array.from({ length: 6 }, (_, index) => <Skeleton key={index} className="h-60" />)}
    </div> : filteredTools.length === 0 ? <div className="tool-catalog-empty">
      <InlineEmpty title={t(filtered ? "noMatchingTools" : "noData")} description={t("toolCatalogEmptyHint")} action={filtered ? <Button variant="outline" onClick={resetFilters}>{t("resetFilters")}</Button> : undefined} />
    </div> : <>
      <div className="tool-catalog-grid">
        {paged.items.map(tool => {
          const level = toolAccess(tool)
          const AccessIcon = level === "read" ? Eye : level === "write" ? PencilLine : null
          const ToolIcon = tool.source === "builtin" ? Wrench : Plug
          return <article key={tool.id} className="tool-catalog-card" aria-label={tool.name || tool.id}>
            <div className="tool-card-heading">
              <span className="tool-card-icon"><ToolIcon aria-hidden="true" /></span>
              <div className="tool-card-name"><h2>{tool.name || tool.id}</h2><code>{tool.id}</code></div>
              <Badge variant="outline" className={`tool-access-badge tool-access-${level}`}>
                {AccessIcon && <AccessIcon aria-hidden="true" />}{accessLabel(level)}
              </Badge>
            </div>
            <p className="tool-card-description">{tool.description || t("toolNoDescription")}</p>
            <div className="tool-card-permission"><span>{t("toolPermissionDeclaration")}</span><code>{tool.permission}</code></div>
            <div className="tool-card-footer">
              <span className="tool-card-service" title={serviceLabel(tool)}><Server aria-hidden="true" /><span>{serviceLabel(tool)}</span></span>
              <div className="tool-card-actions">
                <Button size="sm" variant="ghost" onClick={() => setSelectedId(tool.id)} aria-label={`${t("detail")} · ${tool.name || tool.id}`}>{t("detail")}<ArrowUpRight /></Button>
                <Button size="sm" variant="outline" className="tool-card-invoke" onClick={() => onInvoke(tool.id)} aria-label={`${t("invokeTool")} · ${tool.name || tool.id}`}><Play />{t("invoke")}</Button>
              </div>
            </div>
          </article>
        })}
      </div>
      <div className="tool-catalog-pagination">
        <span>{t("toolShowing")} {paged.start}–{paged.end} / {filteredTools.length}</span>
        <div className="tool-pagination-controls">
          <Select
            aria-label={t("toolsPerPage")} value={pageSize}
            onChange={value => { setPageSize(value); setPage(1) }}
            options={[9, 12, 24].map(value => ({ value, label: `${value} / ${t("toolPage")}` }))}
          />
          <Button size="sm" variant="outline" disabled={paged.page <= 1} onClick={() => setPage(paged.page - 1)} aria-label={t("previousPage")}><ChevronLeft /></Button>
          <span className="tool-page-number">{paged.page} / {paged.pageCount}</span>
          <Button size="sm" variant="outline" disabled={paged.page >= paged.pageCount} onClick={() => setPage(paged.page + 1)} aria-label={t("nextPage")}><ChevronRight /></Button>
        </div>
      </div>
    </>}

    <Dialog open={selected !== null && !loading && !error} onOpenChange={open => { if (!open) setSelectedId(null) }}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="break-words">{selected?.name || selected?.id}</DialogTitle>
          <DialogDescription className="break-all">{selected?.id}</DialogDescription>
        </DialogHeader>
        <DialogBody className="flex flex-col gap-4">
          {selected && <>
            <div className="flex flex-wrap gap-2 text-xs">
              <Badge variant="outline" className="break-all">{t("source")}: {serviceLabel(selected)}</Badge>
              <Badge variant="outline" className="break-all">{t("toolPermissionDeclaration")}: {selected.permission}</Badge>
              <Badge variant="secondary">{accessLabel(toolAccess(selected))}</Badge>
            </div>
            <p className="whitespace-pre-wrap break-words text-sm leading-6 text-muted-foreground">{selected.description || t("toolNoDescription")}</p>
            <div><h3 className="mb-2 text-sm font-medium">{t("inputSchema")}</h3><JsonPanel data={selected.input_schema} maxHeight="max-h-80" /></div>
            {Object.keys(selected.metadata).length > 0 && <details>
              <summary className="cursor-pointer text-sm font-medium">{t("metadata")}</summary>
              <div className="mt-2"><JsonPanel data={selected.metadata} maxHeight="max-h-60" /></div>
            </details>}
            <Button onClick={() => { setSelectedId(null); onInvoke(selected.id) }}><Play />{t("invokeTool")}</Button>
          </>}
        </DialogBody>
      </DialogContent>
    </Dialog>
  </div>
}

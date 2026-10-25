import { FORM_COPY } from "@/features/mcp-config/copy"
import { useRemainingViewport } from "@/components/use-remaining-viewport"
import "./maintenance-lists.css"
import { ListPagination, ListViewport, useListPage } from "@/components/list-pagination"
import { useMemo, useRef, useState } from "react"
import { Edit3, Play, Plus, RefreshCcw, Trash2 } from "lucide-react"
import { FormDialog } from "@/components/form-dialog"
import { useConfirm } from "@/components/confirm-dialog"
import type { HttpTrustSaveOptions, McpConfig } from "@/api/client"
import { McpConfigEditor } from "@/components/mcp-config-editor"
import { PageHeader, PageToolbar } from "@/components/page-shell"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { runtimeModeFromManifest } from "@/features/mcp-config/model"
import type { Locale, TFunction } from "@/i18n"
import { TableEmptyRow } from "@/pages/page-utils"

export function ConfigsPage(props: {
  locale: Locale
  t: TFunction
  configs: McpConfig[]
  configErrors: string[]
  selectedConfigId: string
  configText: string
  busy: boolean
  canManageHttpTrust?: boolean
  canManageCredentials?: boolean
  editorOpen: boolean
  onCloseEditor: () => void
  onNewConfig: () => void
  onReloadConfigs: () => void
  onEditConfig: (config: McpConfig) => void
  onApplyConfig: (id: string) => void
  onDeleteConfig: (id: string) => void
  onConfigTextChange: (value: string) => void
  onSaveConfig: (value?: string, httpTrust?: HttpTrustSaveOptions) => Promise<void>
}) {
  const { locale, t, configs, configErrors, selectedConfigId, configText, busy, editorOpen, onCloseEditor, onNewConfig, onReloadConfigs, onEditConfig, onApplyConfig, onDeleteConfig, onConfigTextChange, onSaveConfig } = props
  const remainingViewport = useRemainingViewport()
  const [query, setQuery] = useState("")
  const zh = locale === "zh-CN"
  const { confirm, confirmDialog } = useConfirm(t, true)
  const [editorPending, setEditorPending] = useState(false)
  const [editorDraftDirty, setEditorDraftDirty] = useState(false)
  const [footerContainer, setFooterContainer] = useState<HTMLDivElement | null>(null)
  const editorReturnFocus = useRef<HTMLElement | null>(null)
  const newConfigButton = useRef<HTMLButtonElement | null>(null)
  const session = useRef({ open: false, initialText: configText })
  if (editorOpen && !session.current.open) session.current.initialText = configText
  session.current.open = editorOpen

  async function closeEditor() {
    if (busy || editorPending) return
    if ((editorDraftDirty || configText !== session.current.initialText) && !(await confirm({
      title: zh ? "放弃未保存的配置？" : "Discard unsaved config changes?",
      description: zh ? "关闭后，本次修改将丢失。已保存配置不会改变。" : "Closing discards this draft. The saved config remains unchanged.",
      confirmText: zh ? "放弃修改" : "Discard changes",
      cancelText: zh ? "继续编辑" : "Keep editing",
      destructive: true,
    }))) return
    onCloseEditor()
  }

  const filteredConfigs = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return configs
    return configs.filter((config) => `${config.id} ${config.path} ${JSON.stringify(config.manifest)}`.toLowerCase().includes(needle))
  }, [configs, query])

  const paging = useListPage(filteredConfigs, query)

  function handleCreateNew() {
    editorReturnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    onNewConfig()
  }

  function handleEdit(config: McpConfig) {
    editorReturnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    onEditConfig(config)
  }

  function renderRuntimeBadge(config: McpConfig) {
    const mode = runtimeModeFromManifest(config.manifest)
    switch (mode) {
      case "managed_stdio":
        return <Badge variant="outline" className="bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20 font-mono text-[11px]">{FORM_COPY[props.locale].managedStdio}</Badge>
      case "managed_http":
        return <Badge variant="outline" className="bg-purple-500/10 text-purple-600 dark:text-purple-400 border-purple-500/20 font-mono text-[11px]">{FORM_COPY[props.locale].managedHttp}</Badge>
      case "external_http":
        return <Badge variant="outline" className="bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20 font-mono text-[11px]">{FORM_COPY[props.locale].externalHttp}</Badge>
      case "managed_container_stdio":
        return <Badge variant="outline" className="bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20 font-mono text-[11px]">{FORM_COPY[props.locale].containerStdio}</Badge>
      case "advanced":
      default:
        return <Badge variant="outline" className="bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20 font-mono text-[11px]">{FORM_COPY[props.locale].advancedMode}</Badge>
    }
  }

  return (
    <div ref={remainingViewport} className="maintenance-list-page flex flex-col gap-5">
      <PageHeader closeLabel={t("close")}
        eyebrow={t("configurationCenter")}
        title={t("configs")}
        description={t("configDesc")}
        helpLabel={t("pageHelp")}
        toolbar={<PageToolbar query={query} onQueryChange={setQuery} placeholder={`${t("search")} ID / ${t("path")}`} resultCount={filteredConfigs.length} resultLabel={t("configs")} clearLabel={t("clearSearch")} />}
        actions={<>
          <Button ref={newConfigButton} onClick={handleCreateNew} disabled={busy} className="shadow-xs"><Plus className="size-4 mr-1.5" />{zh ? "新建配置" : "New Config"}</Button>
          <Button variant="outline" onClick={onReloadConfigs} disabled={busy}><RefreshCcw className="size-4 mr-1.5" />{t("reload")}</Button>
        </>}
      />

      <Card className="maintenance-list-card border-border/70 shadow-xs">
        <CardContent className="maintenance-list-content gap-3 p-3 md:p-4">
          {configErrors.map((item) => <Alert key={item} variant="destructive"><AlertDescription>{item}</AlertDescription></Alert>)}
          <ListViewport viewport={paging.viewport} label={t("configs")}>
            <Table className="maintenance-table maintenance-config-table">
              <TableHeader>
                <TableRow className="bg-muted/40 hover:bg-muted/40">
                  <TableHead className="w-[280px] font-semibold">{zh ? "服务与配置 ID" : "Server & Config ID"}</TableHead>
                  <TableHead className="w-[140px] font-semibold">{zh ? "运行方式" : "Runtime Mode"}</TableHead>
                  <TableHead className="w-[160px] font-semibold">{zh ? "启动策略" : "Startup policy"}</TableHead>
                  <TableHead className="font-semibold">{t("path")}</TableHead>
                  <TableHead className="min-w-[240px] text-right font-semibold">{t("actions")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredConfigs.length === 0 ? (
                  <TableEmptyRow colSpan={5} title={busy ? t("loadingData") : configErrors.length ? t("error") : query.trim() && configs.length ? t("noMatchingRecords") : t("noData")} />
                ) : paging.items.map((config) => {
                  const isSelected = selectedConfigId === config.id
                  const name = typeof config.manifest?.name === "string" ? config.manifest.name : null
                  const startup = configStartupDisplay(config.manifest, locale)
                  return (
                    <TableRow
                      key={config.id}
                      className={isSelected ? "bg-accent/40" : "hover:bg-muted/30 transition-colors"}
                    >
                      <TableCell className="py-3">
                        <div className="flex flex-col gap-0.5">
                          <code className="font-semibold text-xs tracking-tight text-foreground">{config.id}</code>
                          {name && <span className="text-xs text-muted-foreground">{name}</span>}
                          <div className="maintenance-row-summary">{renderRuntimeBadge(config)}<span title={startup.description}>{zh ? "启动策略" : "Startup policy"}: {startup.label}</span></div>
                        </div>
                      </TableCell>
                      <TableCell className="py-3">
                        {renderRuntimeBadge(config)}
                      </TableCell>
                      <TableCell className="py-3">
                        {startup.automatic ? (
                          <span title={startup.description} className="inline-flex items-center gap-2 text-xs text-emerald-600 dark:text-emerald-400 font-medium">
                            <span className="size-1.5 rounded-full bg-emerald-500" />
                            {startup.label}
                          </span>
                        ) : (
                          <span title={startup.description} className="text-xs text-muted-foreground">{startup.label}</span>
                        )}
                      </TableCell>
                      <TableCell className="py-3 max-w-md">
                        <span className="truncate block font-mono text-xs text-muted-foreground" title={config.path}>
                          {config.path}
                        </span>
                      </TableCell>
                      <TableCell className="min-w-[240px] py-3 text-right" onClick={(event) => event.stopPropagation()}>
                        <div className="flex items-center justify-end gap-2 whitespace-nowrap">
                          <Button
                            size="sm"
                            variant="ghost"
                            className="text-xs font-normal text-foreground/80 hover:text-foreground"
                            onClick={() => handleEdit(config)}
                            disabled={busy}
                          >
                            <Edit3 className="size-3.5" />{t("edit")}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="text-xs font-normal text-primary hover:text-primary/90"
                            disabled={busy}
                            onClick={() => onApplyConfig(config.id)}
                          >
                            <Play className="size-3.5" />{t("apply")}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="text-xs font-normal text-destructive hover:bg-destructive/10 hover:text-destructive"
                            disabled={busy}
                            onClick={() => onDeleteConfig(config.id)}
                          >
                            <Trash2 className="size-3.5" />{t("delete")}
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </ListViewport>
          <ListPagination paging={paging} t={t} />
        </CardContent>
      </Card>

      <FormDialog
        dirty={editorDraftDirty || configText !== session.current.initialText}
        open={editorOpen}
        title={selectedConfigId ? `${t("edit")} · ${selectedConfigId}` : (zh ? "新建 MCP 配置" : "New MCP config")}
        closeLabel={zh ? "关闭编辑器" : "Close editor"}
        onClose={() => void closeEditor()}
        onCloseAutoFocus={event => {
          const trigger = editorReturnFocus.current
          const target = trigger?.isConnected && !trigger.matches(':disabled, [aria-disabled="true"]') ? trigger : newConfigButton.current
          if (target?.isConnected && !target.matches(':disabled, [aria-disabled="true"]')) {
            event.preventDefault()
            target.focus()
          }
        }}
        pending={busy || editorPending}
        className="manifest-dialog"
        footer={<div ref={setFooterContainer} className="w-full" />}
      >
        <McpConfigEditor
          key={selectedConfigId || "new"}
          locale={locale}
          selectedConfigId={selectedConfigId}
          savedConfigDigest={configs.find(config => config.id === selectedConfigId)?.digest ?? undefined}
          value={configText}
          onChange={onConfigTextChange}
          onSave={onSaveConfig}
          onClose={() => void closeEditor()}
          onPendingChange={setEditorPending}
          onDraftDirtyChange={setEditorDraftDirty}
          footerContainer={footerContainer}
          busy={busy}
          canManageHttpTrust={props.canManageHttpTrust}
          canManageCredentials={props.canManageCredentials}
        />
      </FormDialog>
      {confirmDialog}
    </div>
  )
}

export function configStartupDisplay(manifest: McpConfig["manifest"], locale: Locale) {
  const zh = locale === "zh-CN"
  if (manifest.startup_policy === undefined || manifest.startup_policy === "legacy_restore") {
    return { label: zh ? "恢复上次状态" : "Restore last state", automatic: false,
      description: zh ? "旧启动策略：Gate 启动时恢复已保存的运行意图；未保存意图时才使用 auto_start。修改配置中的启动开关可切换新策略。" : "Legacy policy: Gate restores the saved runtime intent at startup, falling back to auto_start when no intent exists. Edit the startup switch in the configuration to select the new policy." }
  }
  if (manifest.startup_policy !== "gate_start_v1") return { label: zh ? "策略待确认" : "Unconfirmed policy", automatic: false,
    description: zh ? "无法识别此启动策略，请检查配置。" : "This startup policy is unrecognized. Review the configuration." }
  return { label: manifest.auto_start === true ? (zh ? "启动时自动" : "Automatic on startup") : (zh ? "手动启动" : "Manual start"),
    automatic: manifest.auto_start === true && manifest.enabled !== false,
    description: zh ? "Gate 启动时按启用状态和自动启动开关执行一次；禁用的服务不会自动启动或连接。" : "At Gate startup, enabled services follow the automatic-start switch once. Disabled services are not started or connected automatically." }
}

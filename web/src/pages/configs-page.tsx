import { useMemo, useState } from "react"
import { Edit3, Play, Plus, RefreshCcw, Trash2 } from "lucide-react"
import { Modal } from "antd"
import type { McpConfig } from "@/api/client"
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
  editorOpen: boolean
  onCloseEditor: () => void
  onNewConfig: () => void
  onReloadConfigs: () => void
  onEditConfig: (config: McpConfig) => void
  onApplyConfig: (id: string) => void
  onDeleteConfig: (id: string) => void
  onConfigTextChange: (value: string) => void
  onSaveConfig: (value?: string) => Promise<void>
}) {
  const { locale, t, configs, configErrors, selectedConfigId, configText, busy, editorOpen, onCloseEditor, onNewConfig, onReloadConfigs, onEditConfig, onApplyConfig, onDeleteConfig, onConfigTextChange, onSaveConfig } = props
  const [query, setQuery] = useState("")
  const zh = locale === "zh-CN"

  const filteredConfigs = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return configs
    return configs.filter((config) => `${config.id} ${config.path} ${JSON.stringify(config.manifest)}`.toLowerCase().includes(needle))
  }, [configs, query])

  function handleCreateNew() {
    onNewConfig()
  }

  function handleEdit(config: McpConfig) {
    onEditConfig(config)
  }

  function renderRuntimeBadge(config: McpConfig) {
    const mode = runtimeModeFromManifest(config.manifest)
    switch (mode) {
      case "managed_stdio":
        return <Badge variant="outline" className="bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20 font-mono text-[11px]">Stdio</Badge>
      case "managed_http":
        return <Badge variant="outline" className="bg-purple-500/10 text-purple-600 dark:text-purple-400 border-purple-500/20 font-mono text-[11px]">Managed HTTP</Badge>
      case "external_http":
        return <Badge variant="outline" className="bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20 font-mono text-[11px]">External HTTP</Badge>
      case "advanced":
      default:
        return <Badge variant="outline" className="bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20 font-mono text-[11px]">Advanced</Badge>
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <PageHeader
        eyebrow={t("configurationCenter")}
        title={t("configs")}
        description={t("configDesc")}
        helpLabel={t("pageHelp")}
        toolbar={<PageToolbar query={query} onQueryChange={setQuery} placeholder={`${t("search")} ID / ${t("path")}`} resultCount={filteredConfigs.length} resultLabel={t("configs")} clearLabel={t("clearSearch")} />}
        actions={<>
          <Button onClick={handleCreateNew} disabled={busy} className="shadow-xs"><Plus className="size-4 mr-1.5" />{zh ? "新建配置" : "New Config"}</Button>
          <Button variant="outline" onClick={onReloadConfigs} disabled={busy}><RefreshCcw className="size-4 mr-1.5" />{t("reload")}</Button>
        </>}
      />

      <Card className="border-border/70 shadow-xs">
        <CardContent className="flex flex-col gap-3 p-3 md:p-4">
          {configErrors.map((item) => <Alert key={item} variant="destructive"><AlertDescription>{item}</AlertDescription></Alert>)}
          <div className="overflow-x-auto rounded-lg border border-border/70">
            <Table>
              <TableHeader>
                <TableRow className="bg-muted/40 hover:bg-muted/40">
                  <TableHead className="w-[280px] font-semibold">{zh ? "服务与配置 ID" : "Server & Config ID"}</TableHead>
                  <TableHead className="w-[140px] font-semibold">{zh ? "运行方式" : "Runtime Mode"}</TableHead>
                  <TableHead className="w-[110px] font-semibold">{zh ? "自启动" : "Auto Start"}</TableHead>
                  <TableHead className="font-semibold">{t("path")}</TableHead>
                  <TableHead className="min-w-[240px] text-right font-semibold">{t("actions")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredConfigs.length === 0 ? (
                  <TableEmptyRow colSpan={5} title={t("noData")} />
                ) : filteredConfigs.map((config) => {
                  const isSelected = selectedConfigId === config.id
                  const name = typeof config.manifest?.name === "string" ? config.manifest.name : null
                  const isAutoStart = Boolean(config.manifest?.auto_start)
                  return (
                    <TableRow
                      key={config.id}
                      className={isSelected ? "bg-accent/40" : "hover:bg-muted/30 transition-colors"}
                    >
                      <TableCell className="py-3">
                        <div className="flex flex-col gap-0.5">
                          <code className="font-semibold text-xs tracking-tight text-foreground">{config.id}</code>
                          {name && <span className="text-xs text-muted-foreground">{name}</span>}
                        </div>
                      </TableCell>
                      <TableCell className="py-3">
                        {renderRuntimeBadge(config)}
                      </TableCell>
                      <TableCell className="py-3">
                        {isAutoStart ? (
                          <span className="inline-flex items-center gap-1.5 text-xs text-emerald-600 dark:text-emerald-400 font-medium">
                            <span className="size-1.5 rounded-full bg-emerald-500" />
                            {zh ? "开启" : "Enabled"}
                          </span>
                        ) : (
                          <span className="text-xs text-muted-foreground/70">{zh ? "手动" : "Disabled"}</span>
                        )}
                      </TableCell>
                      <TableCell className="py-3 max-w-md">
                        <span className="truncate block font-mono text-xs text-muted-foreground" title={config.path}>
                          {config.path}
                        </span>
                      </TableCell>
                      <TableCell className="min-w-[240px] py-3 text-right" onClick={(event) => event.stopPropagation()}>
                        <div className="flex items-center justify-end gap-1.5">
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-2 text-xs font-normal text-foreground/80 hover:text-foreground"
                            onClick={() => handleEdit(config)}
                            disabled={busy}
                          >
                            <Edit3 className="size-3.5 mr-1" />{t("edit")}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-2 text-xs font-normal text-primary hover:text-primary/90"
                            disabled={busy}
                            onClick={() => onApplyConfig(config.id)}
                          >
                            <Play className="size-3.5 mr-1" />{t("apply")}
                          </Button>
                          <Button
                            size="sm"
                            variant="ghost"
                            className="h-7 px-2 text-xs font-normal text-destructive hover:bg-destructive/10 hover:text-destructive"
                            disabled={busy}
                            onClick={() => onDeleteConfig(config.id)}
                          >
                            <Trash2 className="size-3.5 mr-1" />{t("delete")}
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Modal
        title={null}
        closable={false}
        mask={{ closable: false }}
        keyboard={false}
        open={editorOpen}
        onCancel={onCloseEditor}
        width="100vw"
        style={{ top: 0, maxWidth: "100vw", margin: 0, paddingBottom: 0 }}
        className="[&_.ant-modal-container]:!p-0 [&_.ant-modal-container]:!h-[100dvh] [&_.ant-modal-container]:!flex [&_.ant-modal-container]:!flex-col [&_.ant-modal-container]:!overflow-hidden [&_.ant-modal-container]:!rounded-none [&_.ant-modal-container]:!shadow-2xl [&_.ant-modal-content]:!p-0 [&_.ant-modal-content]:!h-[100dvh] [&_.ant-modal-content]:!flex [&_.ant-modal-content]:!flex-col [&_.ant-modal-content]:!overflow-hidden [&_.ant-modal-content]:!rounded-none [&_.ant-modal-body]:!flex-1 [&_.ant-modal-body]:!overflow-hidden [&_.ant-modal-body]:!flex [&_.ant-modal-body]:!flex-col [&_.ant-modal-body]:!p-0"
        styles={{
          header: {
            padding: "16px 24px",
            borderBottom: "1px solid hsl(var(--border))",
            margin: 0,
            background: "hsl(var(--card))",
          },
          body: {
            flex: 1,
            overflow: "hidden",
            display: "flex",
            flexDirection: "column",
            padding: 0,
            background: "hsl(var(--background))",
          },
        }}
        footer={null}
        destroyOnHidden
      >
        <McpConfigEditor
          key={selectedConfigId || "new"}
          locale={locale}
          selectedConfigId={selectedConfigId}
          value={configText}
          onChange={onConfigTextChange}
          onSave={onSaveConfig}
          onClose={onCloseEditor}
          busy={busy}
        />
      </Modal>
    </div>
  )
}

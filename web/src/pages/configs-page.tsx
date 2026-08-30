import { useMemo, useState } from "react"
import { FilePlus2, RefreshCcw } from "lucide-react"
import type { McpConfig } from "@/api/client"
import { ActionMenu, ActionMenuItem } from "@/components/action-menu"
import { McpConfigEditor } from "@/components/mcp-config-editor"
import { PageHeader, PageToolbar } from "@/components/page-shell"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
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
  onNewConfig: () => void
  onReloadConfigs: () => void
  onEditConfig: (config: McpConfig) => void
  onApplyConfig: (id: string) => void
  onDeleteConfig: (id: string) => void
  onConfigTextChange: (value: string) => void
  onSaveConfig: (value?: string) => void
}) {
  const { locale, t, configs, configErrors, selectedConfigId, configText, busy, onNewConfig, onReloadConfigs, onEditConfig, onApplyConfig, onDeleteConfig, onConfigTextChange, onSaveConfig } = props
  const [query, setQuery] = useState("")
  const filteredConfigs = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return configs
    return configs.filter((config) => `${config.id} ${config.path} ${JSON.stringify(config.manifest)}`.toLowerCase().includes(needle))
  }, [configs, query])

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        eyebrow={t("configurationCenter")}
        title={t("configs")}
        description={t("configDesc")}
        stats={[
          { label: t("total"), value: configs.length },
          { label: t("error"), value: configErrors.length, tone: configErrors.length ? "danger" : "success" },
          { label: t("status"), value: selectedConfigId || t("waiting") },
        ]}
        actions={<>
          <Button onClick={onNewConfig} disabled={busy}><FilePlus2 />{t("genericTemplate")}</Button>
          <Button variant="outline" onClick={onReloadConfigs} disabled={busy}><RefreshCcw />{t("reload")}</Button>
        </>}
      />

      <div className="flex flex-col gap-4">
        <Card>
          <CardContent className="flex flex-col gap-3 pt-5">
            <PageToolbar query={query} onQueryChange={setQuery} placeholder={`${t("search")} ID / ${t("path")}`} resultCount={filteredConfigs.length} resultLabel={t("configs")} clearLabel={t("clearSearch")} />
            {configErrors.map((item) => <Alert key={item} variant="destructive"><AlertDescription>{item}</AlertDescription></Alert>)}
            <div className="overflow-x-auto rounded-lg border">
              <Table>
                <TableHeader><TableRow><TableHead>{t("id")}</TableHead><TableHead>{t("path")}</TableHead><TableHead className="w-24">{t("actions")}</TableHead></TableRow></TableHeader>
                <TableBody>
                  {filteredConfigs.length === 0 ? <TableEmptyRow colSpan={3} title={t("noData")} /> : filteredConfigs.map((config) => (
                    <TableRow key={config.id} className={selectedConfigId === config.id ? "bg-accent/50" : "cursor-pointer"} onClick={() => onEditConfig(config)}>
                      <TableCell><code>{config.id}</code>{selectedConfigId === config.id ? <div className="mt-1 text-xs font-medium text-primary">{t("edit")}</div> : null}</TableCell>
                      <TableCell className="max-w-md break-all text-xs text-muted-foreground">{config.path}</TableCell>
                      <TableCell onClick={(event) => event.stopPropagation()}>
                        <ActionMenu label={t("actions")}>
                          <ActionMenuItem onClick={() => onEditConfig(config)}>{t("edit")}</ActionMenuItem>
                          <ActionMenuItem disabled={busy} onClick={() => onApplyConfig(config.id)}>{t("apply")}</ActionMenuItem>
                          <ActionMenuItem destructive disabled={busy} onClick={() => onDeleteConfig(config.id)}>{t("delete")}</ActionMenuItem>
                        </ActionMenu>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
        <McpConfigEditor locale={locale} selectedConfigId={selectedConfigId} value={configText} onChange={onConfigTextChange} onSave={onSaveConfig} busy={busy} />
      </div>
    </div>
  )
}

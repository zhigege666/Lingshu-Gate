import { Select as SearchSelect } from "antd"
import { FilterRadio } from "@/components/filter-radio"
import { downstreamEmptyState, filterDownstreamCredentials } from "@/features/downstream-credential-filters"
import { RemainingList, ListPagination, ListViewport, useListPage } from "@/components/list-pagination"
import "./downstream-credentials-page.css"
import { usePageRefresh } from "@/components/page-refresh"
import { useEffect, useMemo, useRef, useState } from "react"
import { KeyRound, ShieldAlert } from "lucide-react"
import { api, type UserDownstreamCredential } from "@/api/client"
import { FormDialog } from "@/components/form-dialog"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import { useConfirm } from "@/components/confirm-dialog"
import { PageHeader, PageToolbar } from "@/components/page-shell"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Toaster } from "@/components/ui/toast"
import type { Locale, TFunction } from "@/i18n"
import { formatDateTime } from "@/lib/utils"
import { TableEmptyRow } from "@/pages/page-utils"

const copy = {
  "zh-CN": {
    eyebrow: "安全与访问 · 下游身份",
    title: "我的服务凭据",
    description: "管理访问下游 MCP 服务所需的个人 PAT、API Key 或令牌；它们与登录 Lingshu Gate 的 API Token 完全分离。",
    configured: "已配置",
    missing: "缺失必填",
    httpMcp: "涉及 MCP 服务",
    insecure: "当前通过 HTTP 访问，个人秘密提交已禁用；请启用 HTTPS 后再绑定凭据。",
    service: "MCP 服务",
    slot: "凭据用途",
    injection: "注入方式",
    readonly: "只读",
    accessMode: "访问方式",
    security: "安全状态",
    localSecure: "本地安全连接",
    httpsSecure: "HTTPS 安全连接",
    required: "必填",
    optional: "可选",
    status: "状态",
    unconfigured: "未配置",
    lastUsed: "最近使用",
    bind: "绑定",
    replace: "更新",
    remove: "删除",
    empty: "当前授权资源没有声明用户凭据槽位",
    panelTitle: "绑定个人凭据",
    panelDescription: "凭据只归当前账号所有，明文不会在保存后返回。",
    value: "凭据值",
    valuePlaceholder: "请输入 PAT / API Key",
    save: "保存凭据",
    httpsRequired: "HTTPS 必需",
    technicalTitle: "凭据注入技术说明",
    httpHint: "Streamable HTTP：每位用户创建独立 MCP Session，凭据只进入该用户请求头。",
    stdioHint: "stdio：共享常驻进程无法安全隔离用户环境变量，当前失败关闭。",
    removed: "凭据已删除",
  },
  "en-US": {
    eyebrow: "SECURITY & ACCESS · DOWNSTREAM IDENTITY",
    title: "My Downstream Credentials",
    description: "Manage personal PATs, API keys, and tokens used by downstream MCP services. They are separate from Lingshu Gate API tokens.",
    configured: "Configured",
    missing: "Required missing",
    httpMcp: "MCP services",
    insecure: "This console is using HTTP. Secret submission is disabled until HTTPS is enabled.",
    service: "MCP service",
    slot: "Credential purpose",
    injection: "Injection",
    readonly: "Read only",
    accessMode: "Access mode",
    security: "Security",
    localSecure: "Local secure connection",
    httpsSecure: "Secure HTTPS connection",
    required: "Required",
    optional: "Optional",
    status: "Status",
    unconfigured: "Not configured",
    lastUsed: "Last used",
    bind: "Bind",
    replace: "Replace",
    remove: "Delete",
    empty: "No user credential slots are declared for your granted resources",
    panelTitle: "Bind personal credential",
    panelDescription: "This secret belongs only to your account and is never returned after saving.",
    value: "Credential value",
    valuePlaceholder: "Enter PAT / API key",
    save: "Save credential",
    httpsRequired: "HTTPS required",
    technicalTitle: "Credential injection",
    httpHint: "Streamable HTTP: each user gets an isolated MCP session and request headers.",
    stdioHint: "stdio: shared long-lived process environments cannot isolate users, so the operation fails closed.",
    removed: "Credential deleted",
  },
} satisfies Record<Locale, Record<string, string>>

export function DownstreamCredentialsPage({ locale, t }: { locale: Locale; t: TFunction }) {
  const c = copy[locale]
  const [credentials, setCredentials] = useState<UserDownstreamCredential[]>([])
  const [selected, setSelected] = useState<UserDownstreamCredential | null>(null)
  const [value, setValue] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const saving = useRef(false)
  const { confirm, confirmDialog } = useConfirm(t)
  const closeEditor = useDraftCloseGuard({ dirty: value.length > 0, pending: busy, locale, confirm, onClose: () => { setSelected(null); setValue(""); setFormError(null) } })
  const secureTransport = useMemo(() => {
    if (typeof window === "undefined") return false
    return window.location.protocol === "https:" || ["localhost", "127.0.0.1", "::1"].includes(window.location.hostname)
  }, [])

  const [query, setQuery] = useState("")
  const [serverFilter, setServerFilter] = useState("")
  const [statusFilter, setStatusFilter] = useState("all")
  const [requiredFilter, setRequiredFilter] = useState("all")
  const serviceOptions = useMemo(() => [...new Map(credentials.map(item => [item.server_id, {value:item.server_id,label:`${item.server_name} · ${item.server_id}`}])).values()], [credentials])
  const filteredRecords = useMemo(() => filterDownstreamCredentials(credentials, {query,server:serverFilter,status:statusFilter,required:requiredFilter}), [credentials, query, serverFilter, statusFilter, requiredFilter])
  const paging = useListPage(filteredRecords, JSON.stringify([query,serverFilter,statusFilter,requiredFilter]))
  const emptyState = downstreamEmptyState(credentials.length, busy, Boolean(error))

  usePageRefresh(load, busy)
  useEffect(() => { void load() }, [])

  async function load() {
    setBusy(true)
    setError(null)
    try {
      const result = await api.downstreamCredentials()
      setCredentials(result.credentials)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  function openBinding(credential: UserDownstreamCredential) {
    if (busy) return
    setFormError(null)
    setSelected(credential)
    setValue("")
  }

  async function save() {
    if (!selected || busy || saving.current || !secureTransport || !value.trim()) return
    saving.current = true
    setBusy(true)
    setFormError(null)
    try {
      await api.saveDownstreamCredential(selected.server_id, selected.id, value)
      setMessage(`${t("saved")}: ${selected.server_name} / ${selected.name}`)
      setSelected(null)
      setValue("")
      await load()
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err))
    } finally {
      saving.current = false
      setBusy(false)
    }
  }

  async function remove(credential: UserDownstreamCredential) {
    if (busy || saving.current) return
    if (!(await confirm({
      title: c.remove,
      description: `${credential.server_name} / ${credential.name}`,
      destructive: true,
    }))) return
    setBusy(true)
    setError(null)
    try {
      await api.deleteDownstreamCredential(credential.server_id, credential.id)
      setMessage(`${c.removed}: ${credential.server_name} / ${credential.name}`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const configuredCount = credentials.filter((item) => item.configured).length
  const missingCount = credentials.filter((item) => item.required && !item.configured).length

  return (
    <div className="downstream-credentials-page flex flex-col gap-4">
      <PageHeader closeLabel={t("close")} title={c.title} description={c.description} helpLabel={t("pageHelp")}
        toolbar={<PageToolbar query={query} onQueryChange={setQuery} placeholder={locale === "zh-CN" ? "搜索服务、凭据用途或认证头" : "Search service, purpose or header"} resultCount={filteredRecords.length} resultLabel={locale === "zh-CN" ? "项凭据" : "credential slots"} clearLabel={t("clearSearch")} resetFilters={{ label: t("resetFilters"), disabled: !query && !serverFilter && statusFilter === "all" && requiredFilter === "all", onReset: () => { setQuery(""); setServerFilter(""); setStatusFilter("all"); setRequiredFilter("all") } }}>
          <SearchSelect className="min-w-[200px] max-w-full" showSearch optionFilterProp="label" aria-label={c.service} value={serverFilter} onChange={setServerFilter} options={[{value:"",label:locale === "zh-CN" ? "全部 MCP 服务" : "All MCP services"},...serviceOptions]} />
          <FilterRadio label={c.status} value={statusFilter} onChange={setStatusFilter} options={[{value:"all",label:t("all")},{value:"configured",label:`${c.configured} (${configuredCount})`},{value:"missing",label:`${c.missing} (${missingCount})`},{value:"unconfigured",label:c.unconfigured}]} />
          <FilterRadio label={locale === "zh-CN" ? "是否必填" : "Requirement"} value={requiredFilter} onChange={setRequiredFilter} options={[{value:"all",label:t("all")},{value:"required",label:c.required},{value:"optional",label:c.optional}]} />
        </PageToolbar>}
        helpContent={<><p className="font-medium">{c.technicalTitle}</p><p>{c.httpHint}</p><p>{c.stdioHint}</p></>}
      />

      <p className="text-sm text-muted-foreground">{locale === "zh-CN" ? "用于以你的身份访问下游 MCP，不能用于登录 Gate。已配置仅表示秘密已保存，不代表下游验证成功。" : "Used for your identity at downstream MCP services, not for signing in to Gate. Configured means a secret is stored, not that downstream authentication succeeded."}</p>
      {error && <Alert variant="destructive" role="alert"><AlertDescription>{error}</AlertDescription><Button variant="outline" size="sm" className="mt-2" disabled={busy} onClick={() => void load()}>{t("refresh")}</Button></Alert>}
      {!secureTransport && (
        <Alert className="border-warning/50 bg-warning/10 text-warning">
          <ShieldAlert className="size-4" />
          <AlertDescription>{c.insecure}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardContent className="p-0">
          <RemainingList className="">
            <ListViewport viewport={paging.viewport} label={t("toolShowing")}>
            <Table className="downstream-credentials-table">
              <TableHeader>
                <TableRow>
                  <TableHead>{c.service}</TableHead>
                  <TableHead>{c.slot}</TableHead>
                  <TableHead>{c.status}</TableHead>
                  <TableHead>{c.lastUsed}</TableHead>
                  <TableHead>{t("actions")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredRecords.length === 0 ? <TableEmptyRow colSpan={5} title={emptyState === "empty" ? c.empty : t(emptyState)} /> : paging.items.map((credential) => (
                  <TableRow key={`${credential.server_id}:${credential.id}`}>
                    <TableCell><div className="font-medium">{credential.server_name}</div><code className="text-xs text-muted-foreground">{credential.server_id}</code></TableCell>
                    <TableCell><div className="font-medium">{credential.name}</div><div className="max-w-xs text-xs text-muted-foreground">{credential.description || credential.id}</div><div className="mt-1 text-xs text-muted-foreground">{c.injection}: {credential.injection.name} · HTTP Header</div></TableCell>
                    <TableCell>
                      <Badge variant={credential.configured ? "success" : credential.required ? "warning" : "secondary"}>
                        {credential.configured ? c.configured : credential.required ? c.missing : c.unconfigured}
                      </Badge><div className="mt-1 text-xs text-muted-foreground">{credential.required ? c.required : c.optional}</div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground"><span className="downstream-mobile-label">{c.lastUsed}: </span>{credential.last_used_at ? formatDateTime(credential.last_used_at) : "-"}</TableCell>
                    <TableCell>
                      <div className="flex gap-2">
                        <Button disabled={busy} size="sm" variant="ghost" onClick={() => openBinding(credential)}>{credential.configured ? c.replace : c.bind}</Button>
                        {credential.configured && <Button disabled={busy} size="sm" variant="ghost" className="text-destructive" onClick={() => void remove(credential)}>{c.remove}</Button>}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            </ListViewport>
            <ListPagination paging={paging} t={t} />
          </RemainingList>
        </CardContent>
      </Card>

      <FormDialog dirty={value.length > 0} open={selected !== null} onClose={() => void closeEditor()} title={c.panelTitle} description={c.panelDescription} closeLabel={t("close")} pending={busy} error={formError}
        footer={<><Button variant="outline" disabled={busy} onClick={() => void closeEditor()}>{t("cancel")}</Button><Button type="submit" form="downstream-credential-editor" disabled={busy || !secureTransport || !value.trim()}><KeyRound />{c.save}</Button></>}>
        <form id="downstream-credential-editor" className="flex flex-col gap-4" onSubmit={event => { event.preventDefault(); void save() }}>
          <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 gap-y-2 text-sm">
            <dt className="text-muted-foreground">{c.service}</dt><dd className="break-words">{selected?.server_name}</dd>
            <dt className="text-muted-foreground">{c.slot}</dt><dd className="break-words">{selected?.name}</dd>
            <dt className="text-muted-foreground">{c.injection}</dt><dd className="break-words">{selected?.injection.name} Header</dd>
            <dt className="text-muted-foreground">{c.accessMode}</dt><dd>{selected?.transport_type === "streamable_http" ? "HTTP" : selected?.transport_type}</dd>
          </dl>
          <div className="flex flex-col gap-2"><Label htmlFor="downstream-credential-value">{c.value}</Label><Input id="downstream-credential-value" type="password" autoComplete="new-password" value={value} onChange={event => setValue(event.target.value)} placeholder={c.valuePlaceholder} disabled={busy || !secureTransport} aria-describedby="downstream-credential-hint" /><p id="downstream-credential-hint" className="text-xs text-muted-foreground">{c.panelDescription}</p></div>
          <div className="flex flex-wrap items-center gap-2 text-sm"><span className="text-muted-foreground">{c.security}</span><Badge variant={secureTransport ? "success" : "warning"}><ShieldAlert className="mr-1 size-3" />{secureTransport ? (window.location.protocol === "https:" ? c.httpsSecure : c.localSecure) : c.httpsRequired}</Badge></div>
          {!secureTransport && <Alert><AlertDescription>{c.insecure}</AlertDescription></Alert>}
        </form>
      </FormDialog>
      {confirmDialog}
      <Toaster toast={message ? { message, tone: "success" } : null} onClose={() => setMessage(null)} />
    </div>
  )
}

import { useEffect, useMemo, useState } from "react"
import { CircleCheck, Globe2, KeyRound, Link2, LockKeyhole, RefreshCcw, ShieldAlert, TriangleAlert } from "lucide-react"
import { api, type UserDownstreamCredential } from "@/api/client"
import { useConfirm } from "@/components/confirm-dialog"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Sheet, SheetContent, SheetDescription, SheetFooter, SheetHeader, SheetTitle } from "@/components/ui/sheet"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Toaster, type ToastState } from "@/components/ui/toast"
import type { Locale, TFunction } from "@/i18n"
import { cn, formatDateTime } from "@/lib/utils"
import { TableEmptyRow } from "@/pages/page-utils"

const copy = {
  "zh-CN": {
    eyebrow: "安全与访问 · 下游身份",
    title: "我的下游凭据",
    description: "管理访问下游 MCP 服务所需的个人 PAT、API Key 或令牌；它们与登录 Lingshu Gate 的 API Token 完全分离。",
    configured: "已配置",
    missing: "缺失必填",
    httpMcp: "可用 HTTP MCP",
    insecure: "当前通过 HTTP 访问，个人秘密提交已禁用；请启用 HTTPS 后再绑定凭据。",
    service: "MCP 服务",
    slot: "凭据槽位",
    injection: "注入方式",
    readonly: "只读",
    accessMode: "访问方式",
    security: "安全状态",
    localSecure: "本地安全预览",
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
    httpMcp: "HTTP MCP available",
    insecure: "This console is using HTTP. Secret submission is disabled until HTTPS is enabled.",
    service: "MCP service",
    slot: "Credential slot",
    injection: "Injection",
    readonly: "Read only",
    accessMode: "Access mode",
    security: "Security",
    localSecure: "Local secure preview",
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
  const { confirm, confirmDialog } = useConfirm(t)
  const secureTransport = useMemo(() => {
    if (typeof window === "undefined") return false
    return window.location.protocol === "https:" || ["localhost", "127.0.0.1", "::1"].includes(window.location.hostname)
  }, [])

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
    setSelected(credential)
    setValue("")
  }

  async function save() {
    if (!selected) return
    setBusy(true)
    setError(null)
    try {
      await api.saveDownstreamCredential(selected.server_id, selected.id, value)
      setMessage(`${t("saved")}: ${selected.server_name} / ${selected.name}`)
      setSelected(null)
      setValue("")
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function remove(credential: UserDownstreamCredential) {
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
  const serverCount = new Set(credentials.map((item) => item.server_id)).size
  const toast: ToastState = error ? { message: error, tone: "error" } : message ? { message, tone: "success" } : null

  return (
    <div className={cn("flex flex-col gap-6 transition-[padding] duration-200", selected && "lg:pr-[440px]")}>
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-[0.16em] text-primary">{c.eyebrow}</div>
          <h2 className="text-2xl font-semibold tracking-tight md:text-[28px]">{c.title}</h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">{c.description}</p>
        </div>
        <Button variant="outline" onClick={load} disabled={busy}><RefreshCcw />{t("refresh")}</Button>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardContent className="flex items-center justify-between p-5">
            <div><div className="text-sm text-muted-foreground">{c.configured}</div><div className="mt-2 text-3xl font-semibold">{configuredCount}</div></div>
            <CircleCheck className="size-9 text-success" />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center justify-between p-5">
            <div><div className="text-sm text-muted-foreground">{c.missing}</div><div className="mt-2 text-3xl font-semibold">{missingCount}</div></div>
            <TriangleAlert className="size-9 text-warning" />
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center justify-between p-5">
            <div><div className="text-sm text-muted-foreground">{c.httpMcp}</div><div className="mt-2 text-3xl font-semibold">{serverCount}</div></div>
            <Globe2 className="size-9 text-primary" />
          </CardContent>
        </Card>
      </div>

      {!secureTransport && (
        <Alert className="border-warning/50 bg-warning/10 text-warning">
          <ShieldAlert className="size-4" />
          <AlertDescription>{c.insecure}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>{c.service}</TableHead>
                  <TableHead>{c.slot}</TableHead>
                  <TableHead>{c.injection}</TableHead>
                  <TableHead>{c.required}</TableHead>
                  <TableHead>{c.status}</TableHead>
                  <TableHead>{c.lastUsed}</TableHead>
                  <TableHead>{t("actions")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {credentials.length === 0 ? <TableEmptyRow colSpan={7} title={c.empty} /> : credentials.map((credential) => (
                  <TableRow key={`${credential.server_id}:${credential.id}`}>
                    <TableCell><div className="font-medium">{credential.server_name}</div><code className="text-xs text-muted-foreground">{credential.server_id}</code></TableCell>
                    <TableCell><div className="font-medium">{credential.name}</div><div className="max-w-xs text-xs text-muted-foreground">{credential.description || credential.id}</div></TableCell>
                    <TableCell><Badge variant="outline">{credential.injection.name} Header</Badge></TableCell>
                    <TableCell><Badge variant={credential.required ? "outline" : "secondary"}>{credential.required ? c.required : c.optional}</Badge></TableCell>
                    <TableCell>
                      <Badge variant={credential.configured ? "success" : credential.required ? "warning" : "secondary"}>
                        {credential.configured ? c.configured : credential.required ? c.missing : c.unconfigured}
                      </Badge>
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{credential.last_used_at ? formatDateTime(credential.last_used_at) : "-"}</TableCell>
                    <TableCell>
                      <div className="flex gap-2">
                        <Button size="sm" variant="ghost" onClick={() => openBinding(credential)}>{credential.configured ? c.replace : c.bind}</Button>
                        {credential.configured && <Button size="sm" variant="ghost" className="text-destructive" onClick={() => void remove(credential)}>{c.remove}</Button>}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Alert className="border-primary/40 bg-primary/[0.03]">
        <LockKeyhole className="size-4" />
        <AlertDescription>
          <div className="mb-2 font-medium">{c.technicalTitle}</div>
          <div className="grid gap-2 text-sm md:grid-cols-2">
            <div className="flex gap-2"><Link2 className="mt-0.5 size-4 shrink-0 text-primary" /><span>{c.httpHint}</span></div>
            <div className="flex gap-2"><KeyRound className="mt-0.5 size-4 shrink-0 text-muted-foreground" /><span>{c.stdioHint}</span></div>
          </div>
        </AlertDescription>
      </Alert>

      <Sheet open={selected !== null} onOpenChange={(open) => { if (!open) { setSelected(null); setValue("") } }}>
        <SheetContent className="w-full sm:max-w-[440px]">
          <SheetHeader className="border-b p-6">
            <SheetTitle>{c.panelTitle}</SheetTitle>
            <SheetDescription>{c.panelDescription}</SheetDescription>
          </SheetHeader>
          <div className="flex flex-1 flex-col gap-5 overflow-y-auto p-6">
            <div className="flex flex-col gap-2"><Label>{c.service}（{c.readonly}）</Label><Input value={selected?.server_name || ""} readOnly /></div>
            <div className="flex flex-col gap-2"><Label>{c.slot}（{c.readonly}）</Label><Input value={selected?.name || ""} readOnly /></div>
            <div className="flex flex-col gap-2">
              <Label>{c.value}{selected?.required ? <span className="ml-1 text-destructive">*</span> : null}</Label>
              <Input type="password" autoComplete="new-password" value={value} onChange={(event) => setValue(event.target.value)} placeholder={c.valuePlaceholder} disabled={!secureTransport} />
              <span className="text-xs text-muted-foreground">{c.panelDescription}</span>
            </div>
            <div className="flex flex-col gap-2"><Label>{c.injection}（{c.readonly}）</Label><Input value={selected ? `${selected.injection.name} Header` : ""} readOnly /></div>
            <div className="flex flex-col gap-2"><Label>{c.accessMode}（{c.readonly}）</Label><Input value={selected?.transport_type === "streamable_http" ? "HTTP" : selected?.transport_type || ""} readOnly /></div>
            <div className="flex flex-col gap-2">
              <Label>{c.security}</Label>
              <Badge variant={secureTransport ? "success" : "warning"} className="w-fit">
                <ShieldAlert className="mr-1 size-3" />{secureTransport ? c.localSecure : c.httpsRequired}
              </Badge>
            </div>
          </div>
          <SheetFooter className="border-t p-6">
            <Button onClick={() => void save()} disabled={busy || !secureTransport || !value.trim()}>{c.save}</Button>
            <Button variant="outline" onClick={() => { setSelected(null); setValue("") }}>{t("cancel")}</Button>
          </SheetFooter>
        </SheetContent>
      </Sheet>
      {confirmDialog}
      <Toaster toast={toast} onClose={() => { setError(null); setMessage(null) }} />
    </div>
  )
}

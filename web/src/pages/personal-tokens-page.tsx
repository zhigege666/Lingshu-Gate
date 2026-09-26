import { usePageRefresh } from "@/components/page-refresh"
import { useEffect, useMemo, useRef, useState } from "react"
import { Copy, Pencil, Plus, ShieldCheck } from "lucide-react"
import { api, type PersonalToken } from "@/api/client"
import { useAuth } from "@/components/auth-gate"
import { FormDialog } from "@/components/form-dialog"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import { useConfirm } from "@/components/confirm-dialog"
import { PageHeader } from "@/components/page-shell"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Toaster } from "@/components/ui/toast"
import { getAvailableTokenScopes, getDefaultTokenScopes, getTokenScopeOptions } from "@/features/personal-token-scopes"
import type { Locale, TFunction } from "@/i18n"
import { formatDateTime } from "@/lib/utils"
import { TableEmptyRow } from "@/pages/page-utils"

const copy = {
  "zh-CN": {
    eyebrow: "安全与访问 · 个人令牌",
    title: "我的 API Token",
    description: "创建用户级 API Token。Token 同时受账号角色、MCP 资源授权和自身 scope 三层约束，不能突破用户已有权限。",
    newToken: "创建凭据",
    name: "凭据名称",
    scopes: "Scope 范围",
    expiresAt: "失效时间",
    noExpiry: "永久有效",
    create: "创建 Token",
    editScopes: "调整范围",
    saveScopes: "保存范围",
    scopeUpdated: "范围已更新",
    expandScopeTitle: "确认扩大 Token 范围",
    expandScopeDescription: "新增范围会立即赋予现有 Token，客户端无需更换 Token。确认继续？",
    tokenOnce: "Token 明文只显示一次，请立即复制并保存在安全位置。",
    copied: "已复制",
    copyToken: "复制 Token",
    copyFailed: "复制失败，请手动复制 Token。",
    prefix: "Token 前缀",
    createdAt: "创建时间",
    lastUsed: "最近使用",
    status: "状态",
    active: "有效",
    revoked: "已吊销",
    expired: "已过期",
    revoke: "吊销凭据",
    noTokens: "暂无个人凭据",
    scopeHint: "scope 是凭据上限，工具调用还受分类与资源授权规则约束。通过 MCP 上传、构建和部署项目需同时选择 tools.invoke 与 operations.manage；确认并发布工具分类还需 classifications.manage。",
  },
  "en-US": {
    eyebrow: "SECURITY & ACCESS · PERSONAL TOKENS",
    title: "My API Tokens",
    description: "Create user-level API tokens. A token is bounded by account roles, MCP resource grants, and its own scopes.",
    newToken: "Create credential",
    name: "Credential name",
    scopes: "Scopes",
    expiresAt: "Expires at",
    noExpiry: "Never",
    create: "Create token",
    editScopes: "Edit scopes",
    saveScopes: "Save scopes",
    scopeUpdated: "Scopes updated",
    expandScopeTitle: "Confirm scope expansion",
    expandScopeDescription: "New scopes take effect immediately for the existing token. Clients do not need a new token. Continue?",
    tokenOnce: "The token value is shown once. Copy it now and store it securely.",
    copied: "Copied",
    copyToken: "Copy token",
    copyFailed: "Copy failed. Copy the token manually.",
    prefix: "Token prefix",
    createdAt: "Created",
    lastUsed: "Last used",
    status: "Status",
    active: "Active",
    revoked: "Revoked",
    expired: "Expired",
    revoke: "Revoke credential",
    noTokens: "No personal credentials",
    scopeHint: "Scopes are a ceiling; tool calls also follow classification and resource grant rules. MCP project uploads, builds, and deployments require both tools.invoke and operations.manage. Confirming and publishing tool classifications also requires classifications.manage.",
  },
} satisfies Record<Locale, Record<string, string>>

export function PersonalTokensPage({ locale, t }: { locale: Locale; t: TFunction }) {
  const c = copy[locale]
  const { user } = useAuth()
  const [tokens, setTokens] = useState<PersonalToken[]>([])
  const [dialogOpen, setDialogOpen] = useState(false)
  const [editingToken, setEditingToken] = useState<PersonalToken | null>(null)
  const [name, setName] = useState("MCP Client")
  const [scopes, setScopes] = useState<string[]>(["tools.read"])
  const [expiresAt, setExpiresAt] = useState("")
  const [newToken, setNewToken] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const baseline = useRef("")
  const saving = useRef(false)
  const { confirm, confirmDialog } = useConfirm(t)

  const draft = JSON.stringify(editingToken ? { scopes: [...scopes].sort() } : { name, scopes: [...scopes].sort(), expiresAt })
  const closeEditor = useDraftCloseGuard({ dirty: !newToken && draft !== baseline.current, pending: busy, locale, confirm, onClose: () => { setDialogOpen(false); setNewToken(null); setFormError(null) } })
  const availableScopes = useMemo(() => getAvailableTokenScopes(user), [user])
  const scopeOptions = useMemo(
    () => getTokenScopeOptions(availableScopes, editingToken?.scopes),
    [availableScopes, editingToken],
  )

  usePageRefresh(load, busy)
  useEffect(() => { void load() }, [])

  async function load() {
    setBusy(true)
    setError(null)
    try {
      const result = await api.personalTokens()
      setTokens(result.tokens)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  function openCreate() {
    if (busy) return
    setFormError(null)
    const initialScopes = getDefaultTokenScopes(availableScopes)
    baseline.current = JSON.stringify({ name: "MCP Client", scopes: [...initialScopes].sort(), expiresAt: "" })
    setEditingToken(null)
    setName("MCP Client")
    setScopes(initialScopes)
    setExpiresAt("")
    setNewToken(null)
    setDialogOpen(true)
  }

  function openEdit(token: PersonalToken) {
    if (busy) return
    setFormError(null)
    baseline.current = JSON.stringify({ scopes: [...token.scopes].sort() })
    setEditingToken(token)
    setScopes([...token.scopes])
    setNewToken(null)
    setDialogOpen(true)
  }

  async function create() {
    if (busy || saving.current || !name.trim() || !scopes.length) return
    saving.current = true
    setBusy(true)
    setFormError(null)
    try {
      const result = await api.createPersonalToken({
        name,
        scopes: [...scopes],
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      })
      setNewToken(result.token)
      setMessage(`${t("saved")}: ${result.name}`)
      await load()
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err))
    } finally {
      saving.current = false
      setBusy(false)
    }
  }

  async function updateScopes() {
    if (!editingToken || busy || saving.current || !scopes.length) return
    const target = editingToken
    const submittedScopes = [...scopes]
    const addedScopes = submittedScopes.filter(scope => !target.scopes.includes(scope))
    saving.current = true
    setBusy(true)
    setFormError(null)
    try {
      if (addedScopes.length > 0 && !(await confirm({ title: c.expandScopeTitle, description: `${c.expandScopeDescription} ${target.scopes.join(", ") || "-"} → ${submittedScopes.join(", ")}` }))) return
      const result = await api.updatePersonalTokenScopes(target.id, submittedScopes)
      setMessage(`${c.scopeUpdated}: ${result.name}`)
      setDialogOpen(false)
      await load()
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err))
    } finally {
      saving.current = false
      setBusy(false)
    }
  }

  async function copyToken() {
    if (!newToken) return
    try {
      await navigator.clipboard.writeText(newToken)
      setMessage(c.copied)
    } catch {
      setFormError(c.copyFailed)
    }
  }

  async function revoke(token: PersonalToken) {
    if (busy || saving.current) return
    if (!(await confirm({ title: c.revoke, description: `${token.name} · ${token.token_prefix}`, destructive: true }))) return
    setBusy(true)
    setError(null)
    try {
      await api.revokePersonalToken(token.id)
      setMessage(`${c.revoked}: ${token.name}`)
      await load()
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  const activeCount = tokens.filter((token) => tokenStatus(token) === "active").length
  const revokedCount = tokens.filter((token) => tokenStatus(token) === "revoked").length
  const expiredCount = tokens.length - activeCount - revokedCount

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        eyebrow={c.eyebrow}
        title={c.title}
        description={c.description}
        helpLabel={t("pageHelp")}
        helpContent={<p>{c.scopeHint}</p>}
        stats={[{ label: c.active, value: activeCount, tone: "success" }, { label: c.expired, value: expiredCount, tone: expiredCount ? "warning" : "default" }, { label: c.revoked, value: revokedCount }]}
        actions={<Button disabled={busy} onClick={openCreate}><Plus />{c.newToken}</Button>}
      />
      {error && <Alert variant="destructive" role="alert"><AlertDescription>{error}</AlertDescription><Button variant="outline" size="sm" className="mt-2" disabled={busy} onClick={() => void load()}>{t("refresh")}</Button></Alert>}
      <Card>
        <CardContent className="flex flex-col gap-3 p-3 md:p-4">
          <div className="overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader><TableRow><TableHead>{c.name}</TableHead><TableHead>{c.prefix}</TableHead><TableHead>{c.scopes}</TableHead><TableHead>{c.lastUsed}</TableHead><TableHead>{c.status}</TableHead><TableHead>{t("actions")}</TableHead></TableRow></TableHeader>
              <TableBody>
                {tokens.length === 0 ? <TableEmptyRow colSpan={6} title={busy ? t("loadingData") : error ? t("error") : c.noTokens} /> : tokens.map((token) => {
                  const status = tokenStatus(token)
                  return <TableRow key={token.id}>
                    <TableCell><div className="font-medium">{token.name}</div><div className="text-xs text-muted-foreground">{formatDateTime(token.created_at)}</div></TableCell>
                    <TableCell><code>{token.token_prefix}</code></TableCell>
                    <TableCell><div className="flex max-w-sm flex-wrap gap-1">{token.scopes.map((scope) => <Badge key={scope} variant="outline">{scope}</Badge>)}</div></TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{token.last_used_at ? formatDateTime(token.last_used_at) : "-"}</TableCell>
                    <TableCell><Badge variant={status === "active" ? "success" : status === "expired" ? "warning" : "secondary"}>{c[status]}</Badge></TableCell>
                    <TableCell>{status === "active" && <div className="flex flex-wrap gap-2"><Button disabled={busy} size="sm" variant="outline" onClick={() => openEdit(token)}><Pencil />{c.editScopes}</Button><Button disabled={busy} size="sm" variant="danger" onClick={() => void revoke(token)}>{c.revoke}</Button></div>}</TableCell>
                  </TableRow>
                })}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <FormDialog dirty={!newToken && draft !== baseline.current} open={dialogOpen} onClose={() => void closeEditor()} title={editingToken ? c.editScopes : c.newToken} description={editingToken ? `${editingToken.name} · ${editingToken.token_prefix}` : undefined} closeLabel={t("close")} pending={busy} error={formError} className="max-w-xl"
        footer={newToken ? <><Button variant="outline" disabled={busy} onClick={() => void closeEditor()}>{t("close")}</Button><Button onClick={() => void copyToken()}><Copy />{c.copyToken}</Button></> : <><Button variant="outline" disabled={busy} onClick={() => void closeEditor()}>{t("cancel")}</Button><Button type="submit" form="personal-token-editor" disabled={busy || scopes.length === 0 || (!editingToken && !name.trim())}>{editingToken ? c.saveScopes : c.create}</Button></>}>
        {newToken ? <Alert><AlertDescription><p className="mb-2 font-medium">{c.tokenOnce}</p><code className="block break-all rounded-md bg-muted p-3 text-xs">{newToken}</code></AlertDescription></Alert> : <form id="personal-token-editor" className="flex flex-col gap-4" onSubmit={event => { event.preventDefault(); void (editingToken ? updateScopes() : create()) }}>
              {!editingToken && <div className="flex flex-col gap-2"><Label htmlFor="token-name">{c.name}</Label><Input id="token-name" disabled={busy} value={name} onChange={(event) => setName(event.target.value)} /></div>}
              <div className="flex flex-col gap-2">
                <Label>{c.scopes}</Label>
                <div className="grid gap-2">
                  {scopeOptions.map((scope) => <label key={scope} className="flex items-center justify-between gap-3 rounded-lg border p-3"><span className="min-w-0"><span className="block break-all text-sm font-medium">{scope}</span><span className="block text-xs text-muted-foreground">{scopeDescription(scope, locale)}</span></span><Switch disabled={busy} aria-label={scope} checked={scopes.includes(scope)} onCheckedChange={(checked) => setScopes((current) => checked ? [...new Set([...current, scope])] : current.filter((item) => item !== scope))} /></label>)}
                </div>
              </div>
              {!editingToken && <div className="flex flex-col gap-2"><Label htmlFor="token-expiry">{c.expiresAt}</Label><Input id="token-expiry" disabled={busy} type="datetime-local" aria-describedby="token-expiry-hint" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} /><div id="token-expiry-hint" className="text-xs text-muted-foreground">{expiresAt || c.noExpiry}</div></div>}
              <Alert><AlertDescription className="flex items-start gap-2"><ShieldCheck className="mt-0.5 size-4 shrink-0" />{c.scopeHint}</AlertDescription></Alert>
        </form>}
      </FormDialog>
      {confirmDialog}
      <Toaster toast={message ? { message, tone: "success" } : null} onClose={() => setMessage(null)} />
    </div>
  )
}

function tokenStatus(token: PersonalToken): "active" | "revoked" | "expired" {
  if (token.revoked_at) return "revoked"
  if (token.expires_at && new Date(token.expires_at).getTime() <= Date.now()) return "expired"
  return "active"
}

function scopeDescription(scope: string, locale: Locale) {
  const values: Record<string, [string, string]> = {
    "tools.read": ["发现并调用已授权的只读 Tool", "Discover and invoke granted read-only tools"],
    "tools.invoke": ["调用已授权的写 Tool（同时包含只读）", "Invoke granted write tools, including read-only access"],
    "audit.read": ["读取调用审计", "Read invocation audits"],
    "console.view": ["读取基础控制面信息", "Read basic control-plane data"],
    "operations.manage": ["管理 MCP 配置与服务，上传、构建、部署和启动项目", "Manage MCP configuration and services; upload, build, deploy, and start projects"],
    "classifications.manage": ["分析、确认并发布工具的只读或读写分类", "Analyze, confirm, and publish tool read/write classifications"],
    "credentials.manage.self": ["管理自己的 API Token 与下游 MCP 凭据", "Manage personal API tokens and downstream MCP credentials"],
    "credentials.manage.all": ["查看并吊销全部用户的 API Token", "View and revoke API tokens for all users"],
    "users.manage": ["审核、启用、停用和维护用户账号", "Review, activate, disable, and maintain user accounts"],
    "roles.manage": ["管理角色、控制面权限与 MCP 权限类型", "Manage roles, control-plane permissions, and MCP permission types"],
    "grants.manage": ["维护用户和角色的 MCP 服务或工具授权", "Manage MCP server and tool grants for users and roles"],
  }
  return values[scope]?.[locale === "zh-CN" ? 0 : 1] || scope
}

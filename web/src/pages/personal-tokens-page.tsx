import { useEffect, useMemo, useState } from "react"
import { Copy, Pencil, Plus, RefreshCcw, ShieldCheck } from "lucide-react"
import { api, type PersonalToken } from "@/api/client"
import { useAuth } from "@/components/auth-gate"
import { useConfirm } from "@/components/confirm-dialog"
import { PageHeader } from "@/components/page-shell"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Toaster, type ToastState } from "@/components/ui/toast"
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
    scopeHint: "scope 是凭据上限；实际能否调用仍取决于 Tool 已发布分类和用户/角色资源授权。",
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
    scopeHint: "Scopes are a ceiling. Invocation still requires a published classification and an effective resource grant.",
  },
} satisfies Record<Locale, Record<string, string>>

const SAFE_SCOPE_ORDER = ["tools.read", "tools.invoke", "audit.read", "console.view"]

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
  const { confirm, confirmDialog } = useConfirm(t)

  const availableScopes = useMemo(() => {
    const permissions = new Set(user.permissions)
    if (user.role === "admin" || user.roles.includes("admin")) SAFE_SCOPE_ORDER.forEach((scope) => permissions.add(scope))
    return [...permissions]
      .filter((scope) => SAFE_SCOPE_ORDER.includes(scope))
      .sort((a, b) => SAFE_SCOPE_ORDER.indexOf(a) - SAFE_SCOPE_ORDER.indexOf(b))
  }, [user.permissions, user.role, user.roles])
  const scopeOptions = useMemo(() => {
    const options = new Set(availableScopes)
    editingToken?.scopes.forEach((scope) => options.add(scope))
    return [...options].sort((a, b) => {
      const left = SAFE_SCOPE_ORDER.indexOf(a)
      const right = SAFE_SCOPE_ORDER.indexOf(b)
      if (left === -1 || right === -1) return left === right ? a.localeCompare(b) : left === -1 ? 1 : -1
      return left - right
    })
  }, [availableScopes, editingToken])

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
    setEditingToken(null)
    setName("MCP Client")
    setScopes(availableScopes.includes("tools.read") ? ["tools.read"] : availableScopes.slice(0, 1))
    setExpiresAt("")
    setNewToken(null)
    setDialogOpen(true)
  }

  function openEdit(token: PersonalToken) {
    setEditingToken(token)
    setScopes([...token.scopes])
    setNewToken(null)
    setDialogOpen(true)
  }

  async function create() {
    setBusy(true)
    setError(null)
    try {
      const result = await api.createPersonalToken({
        name,
        scopes,
        expires_at: expiresAt ? new Date(expiresAt).toISOString() : null,
      })
      setNewToken(result.token)
      setMessage(`${t("saved")}: ${result.name}`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function updateScopes() {
    if (!editingToken) return
    const addedScopes = scopes.filter((scope) => !editingToken.scopes.includes(scope))
    if (addedScopes.length > 0 && !(await confirm({
      title: c.expandScopeTitle,
      description: `${c.expandScopeDescription} ${editingToken.scopes.join(", ") || "-"} → ${scopes.join(", ")}`,
    }))) return

    setBusy(true)
    setError(null)
    try {
      const result = await api.updatePersonalTokenScopes(editingToken.id, scopes)
      setMessage(`${c.scopeUpdated}: ${result.name}`)
      setDialogOpen(false)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function copyToken() {
    if (!newToken) return
    try {
      await navigator.clipboard.writeText(newToken)
      setMessage(c.copied)
    } catch {
      setError(c.copyFailed)
    }
  }

  async function revoke(token: PersonalToken) {
    if (!(await confirm({ title: c.revoke, description: `${token.name} · ${token.token_prefix}`, destructive: true }))) return
    try {
      await api.revokePersonalToken(token.id)
      setMessage(`${c.revoked}: ${token.name}`)
      await load()
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
  }

  const activeCount = tokens.filter((token) => tokenStatus(token) === "active").length
  const toast: ToastState = error ? { message: error, tone: "error" } : message ? { message, tone: "success" } : null

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        eyebrow={c.eyebrow}
        title={c.title}
        description={c.description}
        stats={[{ label: c.active, value: activeCount, tone: "success" }, { label: c.revoked, value: tokens.length - activeCount }]}
        actions={<><Button onClick={openCreate}><Plus />{c.newToken}</Button><Button variant="outline" onClick={load} disabled={busy}><RefreshCcw />{t("refresh")}</Button></>}
      />
      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
      <Card>
        <CardContent className="flex flex-col gap-3 p-3 md:p-4">
          <div className="rounded-lg border border-primary/25 bg-primary/[0.035] p-3 text-xs leading-5 text-muted-foreground">{c.scopeHint}</div>
          <div className="overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader><TableRow><TableHead>{c.name}</TableHead><TableHead>{c.prefix}</TableHead><TableHead>{c.scopes}</TableHead><TableHead>{c.lastUsed}</TableHead><TableHead>{c.status}</TableHead><TableHead>{t("actions")}</TableHead></TableRow></TableHeader>
              <TableBody>
                {tokens.length === 0 ? <TableEmptyRow colSpan={6} title={c.noTokens} /> : tokens.map((token) => {
                  const status = tokenStatus(token)
                  return <TableRow key={token.id}>
                    <TableCell><div className="font-medium">{token.name}</div><div className="text-xs text-muted-foreground">{formatDateTime(token.created_at)}</div></TableCell>
                    <TableCell><code>{token.token_prefix}</code></TableCell>
                    <TableCell><div className="flex max-w-sm flex-wrap gap-1">{token.scopes.map((scope) => <Badge key={scope} variant="outline">{scope}</Badge>)}</div></TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{token.last_used_at ? formatDateTime(token.last_used_at) : "-"}</TableCell>
                    <TableCell><Badge variant={status === "active" ? "success" : status === "expired" ? "warning" : "secondary"}>{c[status]}</Badge></TableCell>
                    <TableCell>{status === "active" && <div className="flex flex-wrap gap-2"><Button size="sm" variant="outline" onClick={() => openEdit(token)}><Pencil />{c.editScopes}</Button><Button size="sm" variant="danger" onClick={() => void revoke(token)}>{c.revoke}</Button></div>}</TableCell>
                  </TableRow>
                })}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader><DialogTitle>{editingToken ? c.editScopes : c.newToken}</DialogTitle><DialogDescription>{editingToken ? `${editingToken.name} · ${editingToken.token_prefix}` : c.description}</DialogDescription></DialogHeader>
          <DialogBody className="flex flex-col gap-4">
            {newToken ? <>
              <Alert><AlertDescription><div className="mb-2 font-medium">{c.tokenOnce}</div><code className="block break-all rounded-md bg-muted p-3 text-xs">{newToken}</code></AlertDescription></Alert>
              <Button onClick={() => void copyToken()}><Copy />{c.copied}</Button>
            </> : <>
              {!editingToken && <div className="flex flex-col gap-2"><Label>{c.name}</Label><Input value={name} onChange={(event) => setName(event.target.value)} /></div>}
              <div className="flex flex-col gap-2">
                <Label>{c.scopes}</Label>
                <div className="grid gap-2">
                  {scopeOptions.map((scope) => <label key={scope} className="flex items-center justify-between rounded-lg border p-3"><span><span className="block text-sm font-medium">{scope}</span><span className="block text-xs text-muted-foreground">{scopeDescription(scope, locale)}</span></span><Switch checked={scopes.includes(scope)} onCheckedChange={(checked) => setScopes((current) => checked ? [...new Set([...current, scope])] : current.filter((item) => item !== scope))} /></label>)}
                </div>
              </div>
              {!editingToken && <div className="flex flex-col gap-2"><Label>{c.expiresAt}</Label><Input type="datetime-local" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} /><div className="text-xs text-muted-foreground">{expiresAt || c.noExpiry}</div></div>}
              <Alert><AlertDescription className="flex items-start gap-2"><ShieldCheck className="mt-0.5 size-4 shrink-0" />{c.scopeHint}</AlertDescription></Alert>
              <div className="flex justify-end gap-2 border-t pt-4"><Button variant="outline" onClick={() => setDialogOpen(false)}>{t("cancel")}</Button><Button onClick={() => void (editingToken ? updateScopes() : create())} disabled={busy || scopes.length === 0 || (!editingToken && !name.trim())}>{editingToken ? c.saveScopes : c.create}</Button></div>
            </>}
          </DialogBody>
        </DialogContent>
      </Dialog>
      {confirmDialog}
      <Toaster toast={toast} onClose={() => { setError(null); setMessage(null) }} />
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
  }
  return values[scope]?.[locale === "zh-CN" ? 0 : 1] || scope
}

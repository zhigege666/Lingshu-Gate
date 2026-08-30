import { useEffect, useMemo, useState } from "react"
import { KeyRound, Plus, RefreshCcw, ShieldAlert, UsersRound } from "lucide-react"
import {
  api,
  type AccessResource,
  type AccessRole,
  type AccessUser,
  type PermissionType,
  type ResourceGrant,
  type ResourceGrantSaveRequest,
} from "@/api/client"
import { ActionMenu, ActionMenuItem } from "@/components/action-menu"
import { useConfirm } from "@/components/confirm-dialog"
import { PageHeader, PageToolbar, WorkflowSteps } from "@/components/page-shell"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Toaster, type ToastState } from "@/components/ui/toast"
import type { Locale, TFunction } from "@/i18n"
import { formatDateTime } from "@/lib/utils"
import { TableEmptyRow } from "@/pages/page-utils"

const copy = {
  "zh-CN": {
    eyebrow: "安全与访问 · 资源授权",
    title: "MCP 资源授权",
    description: "对用户或角色授权整个 MCP 服务，也可以下钻到单个工具。用户级授权优先于角色授权，工具级授权优先于服务级授权。",
    subject: "授权主体",
    selectSubject: "请选择授权主体",
    subjectType: "主体类型",
    user: "用户",
    role: "角色",
    server: "MCP 服务",
    selectServer: "请选择 MCP 服务",
    scope: "授权范围",
    wholeServer: "整个 MCP 服务",
    singleTool: "单个工具",
    tool: "工具",
    selectTool: "请选择工具",
    permissionType: "权限类型",
    expiresAt: "失效时间",
    neverExpires: "永久有效",
    saveGrant: "保存授权",
    grants: "授权记录",
    classification: "工具分类",
    source: "来源",
    noGrants: "暂无授权记录",
    search: "搜索主体、MCP 服务或工具",
    deleteGrant: "删除授权",
    step1: "识别工具读写",
    step2: "选择授权主体",
    step3: "分配资源范围",
    step4: "调用时强制校验",
    unknownWarning: "未发布分类的工具即使获得授权也无法调用；请先到工具分类页完成审核发布。",
    noneLevel: "无权限",
    readLevel: "只读",
    writeLevel: "读写",
    unknownLevel: "待分类",
    pendingStatus: "待发布",
    staleStatus: "已失效",
    missingStatus: "未分类",
    publishedStatus: "已发布",
    gateBuiltin: "Lingshu Gate 内置",
  },
  "en-US": {
    eyebrow: "SECURITY & ACCESS · RESOURCE GRANTS",
    title: "MCP Resource Grants",
    description: "Grant a user or role access to an MCP server or drill down to one tool. User grants override roles; tool grants override server grants.",
    subject: "Subject",
    selectSubject: "Select a subject",
    subjectType: "Subject type",
    user: "User",
    role: "Role",
    server: "MCP Server",
    selectServer: "Select an MCP server",
    scope: "Scope",
    wholeServer: "Entire server",
    singleTool: "Single tool",
    tool: "Tool",
    selectTool: "Select a tool",
    permissionType: "Permission type",
    expiresAt: "Expires at",
    neverExpires: "Never",
    saveGrant: "Save grant",
    grants: "Grants",
    classification: "Tool classification",
    source: "Source",
    noGrants: "No grants",
    search: "Search subject, server, or tool",
    deleteGrant: "Delete grant",
    step1: "Classify tool access",
    step2: "Choose subject",
    step3: "Grant resources",
    step4: "Enforce on invoke",
    unknownWarning: "A tool without a published classification remains blocked even when granted. Review it on the classification page first.",
    noneLevel: "None",
    readLevel: "Read",
    writeLevel: "Read & write",
    unknownLevel: "Unclassified",
    pendingStatus: "Pending",
    staleStatus: "Stale",
    missingStatus: "Missing",
    publishedStatus: "Published",
    gateBuiltin: "Lingshu Gate built-in",
  },
} satisfies Record<Locale, Record<string, string>>

export function AccessGrantsPage({ locale, t }: { locale: Locale; t: TFunction }) {
  const c = copy[locale]
  const [users, setUsers] = useState<AccessUser[]>([])
  const [roles, setRoles] = useState<AccessRole[]>([])
  const [permissionTypes, setPermissionTypes] = useState<PermissionType[]>([])
  const [resources, setResources] = useState<AccessResource[]>([])
  const [grants, setGrants] = useState<ResourceGrant[]>([])
  const [form, setForm] = useState<ResourceGrantSaveRequest>({
    subject_type: "user",
    subject_id: "",
    server_id: "",
    tool_id: null,
    permission_type_code: "read",
    expires_at: null,
  })
  const [scope, setScope] = useState<"server" | "tool">("server")
  const [query, setQuery] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const { confirm, confirmDialog } = useConfirm(t)

  const servers = useMemo(() => [...new Set(resources.map((resource) => resource.server_id))].sort(), [resources])
  const serverTools = useMemo(() => resources.filter((resource) => resource.server_id === form.server_id), [form.server_id, resources])
  const visibleGrants = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return grants
    return grants.filter((grant) => `${subjectLabel(grant, users, roles)} ${grant.server_id} ${grant.tool_id || ""} ${grant.permission_type_name}`.toLowerCase().includes(needle))
  }, [grants, query, roles, users])

  useEffect(() => { void load() }, [])

  async function load() {
    setBusy(true)
    setError(null)
    try {
      const [subjectResult, typeResult, resourceResult, grantResult] = await Promise.all([
        api.accessSubjects(),
        api.permissionTypes(),
        api.accessResources(),
        api.resourceGrants(),
      ])
      setUsers(subjectResult.users)
      setRoles(subjectResult.roles)
      setPermissionTypes(typeResult.permission_types.filter((item) => item.enabled))
      setResources(resourceResult.resources)
      setGrants(grantResult.grants)
      const firstServer = resourceResult.resources[0]?.server_id || ""
      const firstUser = subjectResult.users[0]?.id || ""
      setForm((current) => ({
        ...current,
        subject_id: current.subject_id || firstUser,
        server_id: current.server_id || firstServer,
      }))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await api.saveResourceGrant({
        ...form,
        tool_id: scope === "tool" ? form.tool_id : null,
        expires_at: form.expires_at ? new Date(form.expires_at).toISOString() : null,
      })
      setMessage(`${t("saved")}: ${form.server_id}`)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function remove(grant: ResourceGrant) {
    if (!(await confirm({ title: c.deleteGrant, description: `${subjectLabel(grant, users, roles)} · ${grant.server_id}/${grant.tool_id || "*"}`, destructive: true }))) return
    try {
      await api.deleteResourceGrant(grant.id)
      setMessage(`${t("deleted")}: ${grant.server_id}`)
      await load()
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
  }

  function changeSubjectType(subjectType: "user" | "role") {
    setForm((current) => ({
      ...current,
      subject_type: subjectType,
      subject_id: subjectType === "user" ? users[0]?.id || "" : roles[0]?.id || "",
    }))
  }

  function changeServer(serverId: string) {
    const firstTool = resources.find((resource) => resource.server_id === serverId)?.tool_id || null
    setForm((current) => ({ ...current, server_id: serverId, tool_id: firstTool }))
  }

  const subjectOptions = form.subject_type === "user"
    ? users.map((user) => ({ id: user.id, label: user.display_name ? `${user.display_name} (@${user.username})` : `@${user.username}` }))
    : roles.map((role) => ({ id: role.id, label: `${role.name} (${role.code})` }))
  const selectedResource = resources.find((resource) => resource.server_id === form.server_id && resource.tool_id === form.tool_id)
  const toast: ToastState = error ? { message: error, tone: "error" } : message ? { message, tone: "success" } : null

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        eyebrow={c.eyebrow}
        title={c.title}
        description={c.description}
        stats={[{ label: c.grants, value: grants.length }, { label: c.server, value: servers.length }, { label: c.tool, value: resources.length }]}
        actions={<Button variant="outline" onClick={load} disabled={busy}><RefreshCcw />{t("refresh")}</Button>}
      />
      <WorkflowSteps ariaLabel={c.title} steps={[{ label: c.step1, state: "done" }, { label: c.step2, state: "current" }, { label: c.step3, state: "current" }, { label: c.step4, state: "next" }]} />
      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
      <div className="grid gap-4 xl:grid-cols-[0.82fr_1.18fr]">
        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><KeyRound className="size-5 text-primary" />{c.saveGrant}</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={c.subjectType}><Select value={form.subject_type} onValueChange={(value) => changeSubjectType(value as "user" | "role")}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="user"><span className="flex items-center gap-2"><UsersRound className="size-4" />{c.user}</span></SelectItem><SelectItem value="role"><span className="flex items-center gap-2"><ShieldAlert className="size-4" />{c.role}</span></SelectItem></SelectContent></Select></Field>
              <Field label={c.subject}><Select value={form.subject_id} onValueChange={(subject_id) => setForm((current) => ({ ...current, subject_id }))}><SelectTrigger><SelectValue placeholder={c.selectSubject} /></SelectTrigger><SelectContent>{subjectOptions.map((subject) => <SelectItem key={subject.id} value={subject.id}>{subject.label}</SelectItem>)}</SelectContent></Select></Field>
            </div>
            <Field label={c.server}><Select value={form.server_id} onValueChange={changeServer}><SelectTrigger><SelectValue placeholder={c.selectServer} /></SelectTrigger><SelectContent>{servers.map((server) => <SelectItem key={server} value={server}>{serverLabel(server, c)}</SelectItem>)}</SelectContent></Select></Field>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={c.scope}><Select value={scope} onValueChange={(value) => setScope(value as "server" | "tool")}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="server">{c.wholeServer}</SelectItem><SelectItem value="tool">{c.singleTool}</SelectItem></SelectContent></Select></Field>
              {scope === "tool" && <Field label={c.tool}><Select value={form.tool_id || ""} onValueChange={(tool_id) => setForm((current) => ({ ...current, tool_id }))}><SelectTrigger><SelectValue placeholder={c.selectTool} /></SelectTrigger><SelectContent>{serverTools.map((resource) => <SelectItem key={resource.tool_id} value={resource.tool_id}>{resource.tool_name} · {resource.tool_id}</SelectItem>)}</SelectContent></Select></Field>}
            </div>
            {scope === "tool" && selectedResource && <div className="flex items-center justify-between rounded-lg border bg-muted/30 p-3 text-sm"><span>{c.classification}</span><div className="flex gap-2"><AccessBadge level={selectedResource.classification} labels={c} /><Badge variant="outline">{classificationStatusLabel(selectedResource.classification_status, c)}</Badge></div></div>}
            <Field label={c.permissionType}><Select value={form.permission_type_code} onValueChange={(permission_type_code) => setForm((current) => ({ ...current, permission_type_code }))}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent>{permissionTypes.map((item) => <SelectItem key={item.id} value={item.code}>{permissionTypeLabel(item, c)}</SelectItem>)}</SelectContent></Select></Field>
            <Field label={c.expiresAt}><Input type="datetime-local" value={form.expires_at || ""} onChange={(event) => setForm((current) => ({ ...current, expires_at: event.target.value || null }))} /><div className="text-xs text-muted-foreground">{form.expires_at ? formatDateTime(form.expires_at) : c.neverExpires}</div></Field>
            <Alert><AlertDescription>{c.unknownWarning}</AlertDescription></Alert>
            <Button onClick={() => void save()} disabled={busy || !form.subject_id || !form.server_id || (scope === "tool" && !form.tool_id)}><Plus />{c.saveGrant}</Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle>{c.grants}</CardTitle></CardHeader>
          <CardContent className="flex flex-col gap-3">
            <PageToolbar query={query} onQueryChange={setQuery} placeholder={c.search} resultCount={visibleGrants.length} resultLabel={c.grants} clearLabel={t("clearSearch")} />
            <div className="overflow-x-auto rounded-lg border">
              <Table>
                <TableHeader><TableRow><TableHead>{c.subject}</TableHead><TableHead>{c.server}</TableHead><TableHead>{c.scope}</TableHead><TableHead>{c.permissionType}</TableHead><TableHead>{c.expiresAt}</TableHead><TableHead>{t("actions")}</TableHead></TableRow></TableHeader>
                <TableBody>
                  {visibleGrants.length === 0 ? <TableEmptyRow colSpan={6} title={c.noGrants} /> : visibleGrants.map((grant) => <TableRow key={grant.id}>
                    <TableCell><div className="font-medium">{subjectLabel(grant, users, roles)}</div><div className="text-xs text-muted-foreground">{c[grant.subject_type]}</div></TableCell>
                    <TableCell><div className="font-medium">{serverLabel(grant.server_id, c)}</div>{grant.server_id === "builtin" && <code className="text-xs text-muted-foreground">{grant.server_id}</code>}</TableCell>
                    <TableCell><div className="max-w-72 truncate" title={grant.tool_id || c.wholeServer}>{grant.tool_id || c.wholeServer}</div></TableCell>
                    <TableCell><AccessBadge level={grant.base_level} labels={c} /><div className="mt-1 text-xs text-muted-foreground">{grant.permission_type_name}</div></TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{grant.expires_at ? formatDateTime(grant.expires_at) : c.neverExpires}</TableCell>
                    <TableCell><ActionMenu label={t("actions")}><ActionMenuItem destructive onClick={() => void remove(grant)}>{t("delete")}</ActionMenuItem></ActionMenu></TableCell>
                  </TableRow>)}
                </TableBody>
              </Table>
            </div>
          </CardContent>
        </Card>
      </div>
      {confirmDialog}
      <Toaster toast={toast} onClose={() => { setError(null); setMessage(null) }} />
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="flex flex-col gap-2"><Label>{label}</Label>{children}</div>
}

function AccessBadge({ level, labels }: { level: "none" | "read" | "write" | "unknown"; labels: Record<string, string> }) {
  if (level === "write") return <Badge variant="warning">{labels.writeLevel}</Badge>
  if (level === "read") return <Badge variant="success">{labels.readLevel}</Badge>
  if (level === "unknown") return <Badge variant="danger">{labels.unknownLevel}</Badge>
  return <Badge variant="secondary">{labels.noneLevel}</Badge>
}

function accessLabel(level: "none" | "read" | "write", labels: Record<string, string>) {
  if (level === "write") return labels.writeLevel
  if (level === "read") return labels.readLevel
  return labels.noneLevel
}

function permissionTypeLabel(item: PermissionType, labels: Record<string, string>) {
  const level = accessLabel(item.base_level, labels)
  return item.name === level ? item.name : `${item.name} · ${level}`
}

function classificationStatusLabel(status: AccessResource["classification_status"], labels: Record<string, string>) {
  if (status === "published") return labels.publishedStatus
  if (status === "stale") return labels.staleStatus
  if (status === "missing") return labels.missingStatus
  return labels.pendingStatus
}

function serverLabel(serverId: string, labels: Record<string, string>) {
  return serverId === "builtin" ? labels.gateBuiltin : serverId
}

function subjectLabel(grant: ResourceGrant, users: AccessUser[], roles: AccessRole[]) {
  if (grant.subject_type === "user") {
    const user = users.find((item) => item.id === grant.subject_id)
    return user ? (user.display_name ? `${user.display_name} (@${user.username})` : `@${user.username}`) : grant.subject_id
  }
  const role = roles.find((item) => item.id === grant.subject_id)
  return role ? `${role.name} (${role.code})` : grant.subject_id
}

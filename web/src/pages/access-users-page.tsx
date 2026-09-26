import { usePageRefresh } from "@/components/page-refresh"
import { useEffect, useMemo, useRef, useState } from "react"
import { Plus, ShieldCheck, UserCheck, UserPlus, UserX } from "lucide-react"
import { api, type AccessRole, type AccessUser } from "@/api/client"
import { ActionMenu, ActionMenuItem } from "@/components/action-menu"
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Toaster } from "@/components/ui/toast"
import type { Locale, TFunction } from "@/i18n"
import { formatDateTime } from "@/lib/utils"
import { TableEmptyRow } from "@/pages/page-utils"

const copy = {
  "zh-CN": {
    eyebrow: "安全与访问 · 身份",
    title: "用户管理",
    description: "审核注册申请、维护账号状态并分配控制面角色。MCP 资源读写权限在资源授权页单独配置。",
    newUser: "新建用户",
    createUser: "创建用户",
    username: "登录账号",
    usernamePlaceholder: "例如 zhangsan",
    password: "临时密码",
    passwordHint: "至少 8 位；建议通过安全渠道发送给用户。",
    mustChangePassword: "首次登录强制修改密码",
    createHint: "管理员创建：默认启用 Viewer，可立即登录；首次登录必须修改临时密码。",
    registrationHint: "公开注册：默认进入 Viewer 组并保持待审核，管理员通过后才能登录。",
    pending: "待审核",
    active: "已启用",
    disabled: "已停用",
    displayName: "显示名称",
    account: "账号",
    roles: "角色",
    registeredAt: "注册时间",
    edit: "编辑用户",
    approve: "审核通过",
    disable: "停用",
    disableConfirm: "停用后，该用户的现有会话会立即失效，Token 请求也会被拒绝。",
    enable: "启用",
    save: "保存变更",
    allStatus: "全部状态",
    search: "搜索账号、名称或角色",
    noUsers: "没有符合条件的用户",
    roleHint: "至少保留一个角色。角色决定控制面能力，资源授权决定 MCP 的读写范围。",
    statusFilter: "按用户状态筛选",
  },
  "en-US": {
    eyebrow: "SECURITY & ACCESS · IDENTITY",
    title: "Users",
    description: "Review registrations, manage account status, and assign control-plane roles. MCP read/write access is configured separately.",
    newUser: "New user",
    createUser: "Create user",
    username: "Username",
    usernamePlaceholder: "e.g. zhangsan",
    password: "Temporary password",
    passwordHint: "Use at least 8 characters and share it securely.",
    mustChangePassword: "Require password change on first login",
    createHint: "Admin-created users are active Viewers by default and must change the temporary password.",
    registrationHint: "Public registrations join Viewer in pending status and cannot sign in before approval.",
    pending: "Pending",
    active: "Active",
    disabled: "Disabled",
    displayName: "Display name",
    account: "Account",
    roles: "Roles",
    registeredAt: "Registered",
    edit: "Edit user",
    approve: "Approve",
    disable: "Disable",
    disableConfirm: "Disabling immediately revokes active sessions and rejects token requests.",
    enable: "Enable",
    save: "Save changes",
    allStatus: "All statuses",
    search: "Search account, name, or role",
    noUsers: "No matching users",
    roleHint: "Keep at least one role. Roles control the console; resource grants control MCP read/write scope.",
    statusFilter: "Filter by user status",
  },
} satisfies Record<Locale, Record<string, string>>

export function AccessUsersPage({ locale, t }: { locale: Locale; t: TFunction }) {
  const c = copy[locale]
  const [users, setUsers] = useState<AccessUser[]>([])
  const [roles, setRoles] = useState<AccessRole[]>([])
  const [createOpen, setCreateOpen] = useState(false)
  const [username, setUsername] = useState("")
  const [password, setPassword] = useState("")
  const [createDisplayName, setCreateDisplayName] = useState("")
  const [createStatus, setCreateStatus] = useState<AccessUser["status"]>("active")
  const [createRoleCodes, setCreateRoleCodes] = useState<string[]>(["viewer"])
  const [mustChangePassword, setMustChangePassword] = useState(true)
  const [selected, setSelected] = useState<AccessUser | null>(null)
  const [displayName, setDisplayName] = useState("")
  const [status, setStatus] = useState<AccessUser["status"]>("active")
  const [roleCodes, setRoleCodes] = useState<string[]>([])
  const [query, setQuery] = useState("")
  const [statusFilter, setStatusFilter] = useState("__all")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const createBaseline = useRef("")
  const editBaseline = useRef("")
  const saving = useRef(false)
  const { confirm, confirmDialog } = useConfirm(t)

  const createDraft = JSON.stringify({ username, password, createDisplayName, createStatus, createRoleCodes: [...createRoleCodes].sort(), mustChangePassword })
  const editDraft = JSON.stringify({ displayName, status, roleCodes: [...roleCodes].sort() })
  const closeCreate = useDraftCloseGuard({ dirty: createDraft !== createBaseline.current, pending: busy, locale, confirm, onClose: () => { setCreateOpen(false); setPassword(""); setFormError(null) } })
  const closeEdit = useDraftCloseGuard({ dirty: editDraft !== editBaseline.current, pending: busy, locale, confirm, onClose: () => { setSelected(null); setFormError(null) } })
  const visibleUsers = useMemo(() => {
    const needle = query.trim().toLowerCase()
    return users.filter((user) => {
      if (statusFilter !== "__all" && user.status !== statusFilter) return false
      return !needle || `${user.username} ${user.display_name} ${user.roles.join(" ")}`.toLowerCase().includes(needle)
    })
  }, [query, statusFilter, users])

  usePageRefresh(load, busy)
  useEffect(() => { void load() }, [])

  async function load() {
    setBusy(true)
    setError(null)
    try {
      const [userResult, roleResult] = await Promise.all([api.accessUsers(), api.accessRoles()])
      setUsers(userResult.users)
      setRoles(roleResult.roles.filter((role) => role.enabled))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  function edit(user: AccessUser) {
    if (busy) return
    setFormError(null)
    editBaseline.current = JSON.stringify({ displayName: user.display_name || "", status: user.status, roleCodes: [...(user.roles.length ? user.roles : [user.role])].sort() })
    setSelected(user)
    setDisplayName(user.display_name || "")
    setStatus(user.status)
    setRoleCodes(user.roles.length ? user.roles : [user.role])
  }

  function openCreate() {
    if (busy) return
    setFormError(null)
    const initialRoles = [roles.find(role => role.code === "viewer")?.code || roles[0]?.code || "viewer"]
    createBaseline.current = JSON.stringify({ username: "", password: "", createDisplayName: "", createStatus: "active", createRoleCodes: initialRoles, mustChangePassword: true })
    setUsername("")
    setPassword("")
    setCreateDisplayName("")
    setCreateStatus("active")
    setCreateRoleCodes(initialRoles)
    setMustChangePassword(true)
    setCreateOpen(true)
  }

  async function createUser() {
    if (busy || saving.current || !username.trim() || password.length < 8 || !createRoleCodes.length) return
    saving.current = true
    setBusy(true)
    setFormError(null)
    setMessage(null)
    try {
      const user = await api.createAccessUser({
        username,
        display_name: createDisplayName,
        password,
        status: createStatus,
        roles: [...createRoleCodes],
        must_change_password: mustChangePassword,
      })
      setMessage(`${t("saved")}: ${user.username}`)
      setCreateOpen(false)
      setPassword("")
      await load()
    } catch (err) {
      setFormError(err instanceof Error ? err.message : String(err))
    } finally {
      saving.current = false
      setBusy(false)
    }
  }

  async function update(user: AccessUser, nextStatus?: AccessUser["status"]) {
    if (busy || saving.current) return
    const editing = selected?.id === user.id && !nextStatus
    if (editing && !roleCodes.length) return
    if (editing && status === "disabled" && user.status !== "disabled" && !(await confirm({ title: `${c.disable}: ${user.display_name || user.username}`, description: c.disableConfirm, destructive: true }))) return
    saving.current = true
    setBusy(true)
    if (editing) setFormError(null)
    else setError(null)
    setMessage(null)
    try {
      await api.updateAccessUser(user.id, editing
        ? { display_name: displayName, status, roles: [...roleCodes] }
        : { status: nextStatus })
      setMessage(`${t("saved")}: ${user.username}`)
      setSelected(null)
      await load()
    } catch (err) {
      (editing ? setFormError : setError)(err instanceof Error ? err.message : String(err))
    } finally {
      saving.current = false
      setBusy(false)
    }
  }

  async function disableUser(user: AccessUser) {
    if (!(await confirm({
      title: `${c.disable}: ${user.display_name || user.username}`,
      description: c.disableConfirm,
      destructive: true,
    }))) return
    await update(user, "disabled")
  }

  const statusCounts = {
    pending: users.filter((user) => user.status === "pending").length,
    active: users.filter((user) => user.status === "active").length,
    disabled: users.filter((user) => user.status === "disabled").length,
  }

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        eyebrow={c.eyebrow}
        title={c.title}
        description={c.description}
        helpLabel={t("pageHelp")}
        helpContent={<><p>{c.createHint}</p><p>{c.registrationHint}</p></>}
        toolbar={<PageToolbar query={query} onQueryChange={setQuery} placeholder={c.search} resultCount={visibleUsers.length} resultLabel={c.title} clearLabel={t("clearSearch")}>
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="w-40" aria-label={c.statusFilter}><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="__all">{c.allStatus}</SelectItem>
              <SelectItem value="pending">{c.pending} ({statusCounts.pending})</SelectItem>
              <SelectItem value="active">{c.active} ({statusCounts.active})</SelectItem>
              <SelectItem value="disabled">{c.disabled} ({statusCounts.disabled})</SelectItem>
            </SelectContent>
          </Select>
        </PageToolbar>}
        actions={<Button onClick={openCreate} disabled={busy}><Plus />{c.newUser}</Button>}
      />
      {error && <Alert variant="destructive" role="alert"><AlertDescription>{error}</AlertDescription><Button variant="outline" size="sm" className="mt-2" disabled={busy} onClick={() => void load()}>{t("refresh")}</Button></Alert>}
      <Card>
        <CardContent className="flex flex-col gap-3 p-3 md:p-4">
          <div className="overflow-x-auto rounded-lg border">
            <Table>
              <TableHeader><TableRow><TableHead>{c.account}</TableHead><TableHead>{t("status")}</TableHead><TableHead>{c.roles}</TableHead><TableHead>{c.registeredAt}</TableHead><TableHead>{t("actions")}</TableHead></TableRow></TableHeader>
              <TableBody>
                {visibleUsers.length === 0 ? <TableEmptyRow colSpan={5} title={busy ? t("loadingData") : error ? t("error") : c.noUsers} /> : visibleUsers.map((user) => (
                  <TableRow key={user.id} className="cursor-pointer" onClick={() => edit(user)}>
                    <TableCell><button type="button" className="text-left font-medium text-primary underline-offset-4 hover:underline focus-visible:underline" disabled={busy} onClick={() => edit(user)}>{user.display_name || user.username}</button><div className="text-xs text-muted-foreground">@{user.username}</div></TableCell>
                    <TableCell><UserStatusBadge status={user.status} labels={c} /></TableCell>
                    <TableCell><div className="flex flex-wrap gap-1">{user.roles.map((role) => <Badge key={role} variant="outline">{role}</Badge>)}</div></TableCell>
                    <TableCell className="whitespace-nowrap text-xs text-muted-foreground">{formatDateTime(user.created_at)}</TableCell>
                    <TableCell onClick={(event) => event.stopPropagation()}>
                      <ActionMenu label={t("actions")}>
                        <ActionMenuItem disabled={busy} onClick={() => edit(user)}>{c.edit}</ActionMenuItem>
                        {user.status === "pending" && <ActionMenuItem disabled={busy} onClick={() => void update(user, "active")}>{c.approve}</ActionMenuItem>}
                        {user.status === "disabled" ? <ActionMenuItem disabled={busy} onClick={() => void update(user, "active")}>{c.enable}</ActionMenuItem> : <ActionMenuItem destructive disabled={busy} onClick={() => void disableUser(user)}>{c.disable}</ActionMenuItem>}
                      </ActionMenu>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      <FormDialog dirty={createDraft !== createBaseline.current} open={createOpen} onClose={() => void closeCreate()} title={c.newUser} description={c.createHint} closeLabel={t("close")} pending={busy} error={formError} className="max-w-2xl"
        footer={<><Button variant="outline" disabled={busy} onClick={() => void closeCreate()}>{t("cancel")}</Button><Button type="submit" form="create-user-editor" disabled={busy || !username.trim() || password.length < 8 || createRoleCodes.length === 0}><UserPlus />{c.createUser}</Button></>}>
        <form id="create-user-editor" className="flex flex-col gap-4" onSubmit={event => { event.preventDefault(); void createUser() }}>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-2"><Label htmlFor="new-user-username">{c.username}</Label><Input disabled={busy} id="new-user-username" autoComplete="off" value={username} onChange={(event) => setUsername(event.target.value)} placeholder={c.usernamePlaceholder} /></div>
              <div className="flex flex-col gap-2"><Label htmlFor="new-user-display-name">{c.displayName}</Label><Input disabled={busy} id="new-user-display-name" value={createDisplayName} onChange={(event) => setCreateDisplayName(event.target.value)} /></div>
            </div>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-2"><Label htmlFor="new-user-password">{c.password}</Label><Input disabled={busy} id="new-user-password" aria-describedby="new-user-password-hint" type="password" autoComplete="new-password" value={password} onChange={(event) => setPassword(event.target.value)} /><div id="new-user-password-hint" className="text-xs text-muted-foreground">{c.passwordHint}</div></div>
              <div className="flex flex-col gap-2"><Label htmlFor="create-user-status">{t("status")}</Label><Select disabled={busy} value={createStatus} onValueChange={(value) => setCreateStatus(value as AccessUser["status"])}><SelectTrigger id="create-user-status"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="active">{c.active}</SelectItem><SelectItem value="pending">{c.pending}</SelectItem><SelectItem value="disabled">{c.disabled}</SelectItem></SelectContent></Select></div>
            </div>
            <div className="flex flex-col gap-2">
              <Label>{c.roles}</Label>
              <div className="grid gap-2 sm:grid-cols-2">
                {roles.map((role) => <label key={role.id} className="flex items-start justify-between gap-3 rounded-lg border p-3">
                  <span><span className="block text-sm font-medium">{role.name}</span><span className="block text-xs text-muted-foreground">{role.description}</span></span>
                  <Switch aria-label={role.name} disabled={busy} checked={createRoleCodes.includes(role.code)} onCheckedChange={(checked) => setCreateRoleCodes((current) => checked ? [...new Set([...current, role.code])] : current.filter((item) => item !== role.code))} />
                </label>)}
              </div>
            </div>
            <label className="flex items-center justify-between rounded-lg border bg-muted/20 p-3"><span><span className="block text-sm font-medium">{c.mustChangePassword}</span><span className="block text-xs text-muted-foreground">{c.passwordHint}</span></span><Switch aria-label={c.mustChangePassword} disabled={busy} checked={mustChangePassword} onCheckedChange={setMustChangePassword} /></label>
        </form>
      </FormDialog>
      <FormDialog dirty={editDraft !== editBaseline.current} open={selected !== null} onClose={() => void closeEdit()} title={c.edit} description={selected ? `@${selected.username}` : ""} closeLabel={t("close")} pending={busy} error={formError} className="max-w-xl"
        footer={<><Button variant="outline" disabled={busy} onClick={() => void closeEdit()}>{t("cancel")}</Button><Button type="submit" form="edit-user-editor" disabled={busy || roleCodes.length === 0}><ShieldCheck />{c.save}</Button></>}>
        <form id="edit-user-editor" className="flex flex-col gap-4" onSubmit={event => { event.preventDefault(); if (selected) void update(selected) }}>
            <div className="grid gap-4 sm:grid-cols-2">
              <div className="flex flex-col gap-2"><Label htmlFor="edit-user-display-name">{c.displayName}</Label><Input id="edit-user-display-name" disabled={busy} value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></div>
              <div className="flex flex-col gap-2"><Label htmlFor="edit-user-status">{t("status")}</Label><Select disabled={busy} value={status} onValueChange={(value) => setStatus(value as AccessUser["status"])}><SelectTrigger id="edit-user-status"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="pending">{c.pending}</SelectItem><SelectItem value="active">{c.active}</SelectItem><SelectItem value="disabled">{c.disabled}</SelectItem></SelectContent></Select></div>
            </div>
            <div className="flex flex-col gap-2">
              <Label>{c.roles}</Label>
              <div className="grid gap-2 sm:grid-cols-2">
                {roles.map((role) => <label key={role.id} className="flex items-start justify-between gap-3 rounded-lg border p-3">
                  <span><span className="block text-sm font-medium">{role.name}</span><span className="block text-xs text-muted-foreground">{role.description}</span></span>
                  <Switch aria-label={role.name} disabled={busy} checked={roleCodes.includes(role.code)} onCheckedChange={(checked) => setRoleCodes((current) => checked ? [...new Set([...current, role.code])] : current.filter((item) => item !== role.code))} />
                </label>)}
              </div>
              <div className="rounded-md border bg-muted/30 p-3 text-xs text-muted-foreground">{c.roleHint}</div>
            </div>
        </form>
      </FormDialog>
      {confirmDialog}
      <Toaster toast={message ? { message, tone: "success" } : null} onClose={() => setMessage(null)} />
    </div>
  )
}

function UserStatusBadge({ status, labels }: { status: AccessUser["status"]; labels: Record<string, string> }) {
  if (status === "pending") return <Badge variant="warning"><ShieldCheck />{labels.pending}</Badge>
  if (status === "active") return <Badge variant="success"><UserCheck />{labels.active}</Badge>
  return <Badge variant="secondary"><UserX />{labels.disabled}</Badge>
}

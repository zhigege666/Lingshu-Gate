import { useEffect, useMemo, useState } from "react"
import { KeySquare, Plus, RefreshCcw, Shield, SlidersHorizontal } from "lucide-react"
import {
  api,
  type AccessRole,
  type AccessRoleSaveRequest,
  type ControlPermission,
  type PermissionType,
  type PermissionTypeSaveRequest,
} from "@/api/client"
import { ActionMenu, ActionMenuItem } from "@/components/action-menu"
import { useConfirm } from "@/components/confirm-dialog"
import { PageHeader } from "@/components/page-shell"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { Toaster, type ToastState } from "@/components/ui/toast"
import type { Locale, TFunction } from "@/i18n"
import { TableEmptyRow } from "@/pages/page-utils"

const copy = {
  "zh-CN": {
    eyebrow: "安全与访问 · 策略模型",
    title: "角色与权限类型",
    description: "角色定义控制台能做什么；权限类型定义 MCP 资源授权的语义级别。两者分离，避免把页面管理权限和工具读写权限混在一起。",
    roles: "角色",
    roleDesc: "按菜单和操作能力组合权限，可分配给多个用户。",
    permissionTypes: "权限类型",
    permissionTypeDesc: "映射到无权限 / 只读 / 读写基础级别，供 MCP 服务或工具授权使用。",
    newRole: "新建角色",
    editRole: "编辑角色",
    newType: "新建权限类型",
    editType: "编辑权限类型",
    code: "代码",
    name: "名称",
    descriptionLabel: "说明",
    members: "成员",
    controlPermissions: "菜单与操作权限",
    baseLevel: "基础级别",
    references: "授权引用",
    enabled: "启用",
    system: "系统内置",
    custom: "自定义",
    noRoles: "暂无角色",
    noTypes: "暂无权限类型",
    save: "保存",
    deleteRole: "删除角色",
    deleteType: "删除权限类型",
    noneLevel: "无权限",
    readLevel: "只读",
    writeLevel: "读写",
  },
  "en-US": {
    eyebrow: "SECURITY & ACCESS · POLICY MODEL",
    title: "Roles & Permission Types",
    description: "Roles define console capabilities; permission types define MCP resource access semantics. Keeping them separate avoids mixing administration and tool access.",
    roles: "Roles",
    roleDesc: "Bundle control-plane permissions and assign them to users.",
    permissionTypes: "Permission types",
    permissionTypeDesc: "Map to none / read / write and apply to MCP server or tool grants.",
    newRole: "New role",
    editRole: "Edit role",
    newType: "New permission type",
    editType: "Edit permission type",
    code: "Code",
    name: "Name",
    descriptionLabel: "Description",
    members: "Members",
    controlPermissions: "Control permissions",
    baseLevel: "Base level",
    references: "Grant references",
    enabled: "Enabled",
    system: "System",
    custom: "Custom",
    noRoles: "No roles",
    noTypes: "No permission types",
    save: "Save",
    deleteRole: "Delete role",
    deleteType: "Delete permission type",
    noneLevel: "None",
    readLevel: "Read",
    writeLevel: "Read & write",
  },
} satisfies Record<Locale, Record<string, string>>

const emptyRole: AccessRoleSaveRequest = { code: "", name: "", description: "", permissions: [], enabled: true }
const emptyType: PermissionTypeSaveRequest = { code: "", name: "", base_level: "read", description: "", enabled: true }

type ControlPermissionPresentation = {
  name: string
  description: string
  group: string
}

const controlPermissionPresentations: Record<Locale, Record<string, ControlPermissionPresentation>> = {
  "zh-CN": {
    "console.view": { name: "仪表盘与基础控制台", description: "登录并查看仪表盘及基础控制台信息。", group: "控制台基础" },
    "users.manage": { name: "用户管理", description: "查看用户，并审核、启用、停用或维护账号。", group: "身份与授权" },
    "roles.manage": { name: "角色与权限类型", description: "维护角色、菜单与操作权限，以及 MCP 权限类型。", group: "身份与授权" },
    "grants.manage": { name: "资源授权", description: "维护用户和角色的 MCP 服务或工具授权。", group: "身份与授权" },
    "classifications.manage": { name: "工具读写分类", description: "分析、确认并发布工具的只读或读写分类。", group: "身份与授权" },
    "credentials.manage.self": { name: "我的 API Token 与下游凭据", description: "维护自己的 Lingshu Gate API Token 和下游 MCP 凭据。", group: "凭据与审计" },
    "credentials.manage.all": { name: "全部用户 API Token", description: "查看并吊销全部用户的 API Token，不读取用户下游秘密。", group: "凭据与审计" },
    "audit.read": { name: "调用审计", description: "查看 MCP 调用的授权判定和执行结果。", group: "凭据与审计" },
    "tools.read": { name: "工具", description: "发现获准使用的 MCP 工具。", group: "工具调用与运行态" },
    "tools.invoke": { name: "调用", description: "调用获准使用的只读或写入 MCP 工具。", group: "工具调用与运行态" },
    "operations.manage": { name: "配置与运维管理", description: "管理 MCP 配置、服务、构建部署、运行缓存、上传和诊断等页面。", group: "工具调用与运行态" },
  },
  "en-US": {
    "console.view": { name: "Dashboard & console", description: "Sign in and view the dashboard and basic console information.", group: "Console basics" },
    "users.manage": { name: "User management", description: "Review, activate, disable, and maintain user accounts.", group: "Identity & access" },
    "roles.manage": { name: "Roles & permission types", description: "Manage roles, menu and action permissions, and MCP permission types.", group: "Identity & access" },
    "grants.manage": { name: "Resource grants", description: "Manage MCP server or tool grants for users and roles.", group: "Identity & access" },
    "classifications.manage": { name: "Tool classification", description: "Analyze, confirm, and publish read or write classifications for tools.", group: "Identity & access" },
    "credentials.manage.self": { name: "My API tokens & downstream credentials", description: "Manage personal Lingshu Gate API tokens and downstream MCP credentials.", group: "Credentials & audit" },
    "credentials.manage.all": { name: "All user API tokens", description: "View and revoke user API tokens without reading downstream secrets.", group: "Credentials & audit" },
    "audit.read": { name: "Invocation audit", description: "Review MCP authorization decisions and invocation results.", group: "Credentials & audit" },
    "tools.read": { name: "Tools", description: "Discover MCP tools the user is allowed to access.", group: "Tools & runtime" },
    "tools.invoke": { name: "Invoke", description: "Invoke allowed read-only or write MCP tools.", group: "Tools & runtime" },
    "operations.manage": { name: "Configuration & operations", description: "Manage MCP configuration, services, builds, runtime cache, uploads, and diagnostics.", group: "Tools & runtime" },
  },
}

export function AccessRolesPage({ locale, t }: { locale: Locale; t: TFunction }) {
  const c = copy[locale]
  const [roles, setRoles] = useState<AccessRole[]>([])
  const [permissions, setPermissions] = useState<ControlPermission[]>([])
  const [permissionTypes, setPermissionTypes] = useState<PermissionType[]>([])
  const [editingRole, setEditingRole] = useState<AccessRole | "new" | null>(null)
  const [roleForm, setRoleForm] = useState<AccessRoleSaveRequest>({ ...emptyRole })
  const [editingType, setEditingType] = useState<PermissionType | "new" | null>(null)
  const [typeForm, setTypeForm] = useState<PermissionTypeSaveRequest>({ ...emptyType })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const { confirm, confirmDialog } = useConfirm(t)

  const permissionPresentationByCode = useMemo(() => new Map(permissions.map((permission) => [
    permission.code,
    presentControlPermission(permission, locale),
  ])), [locale, permissions])

  const permissionGroups = useMemo(() => {
    const groups = new Map<string, ControlPermission[]>()
    for (const permission of permissions) {
      const group = presentControlPermission(permission, locale).group
      groups.set(group, [...(groups.get(group) || []), permission])
    }
    return [...groups.entries()]
  }, [locale, permissions])

  useEffect(() => { void load() }, [])

  async function load() {
    setBusy(true)
    setError(null)
    try {
      const [roleResult, permissionResult, typeResult] = await Promise.all([
        api.accessRoles(),
        api.controlPermissions(),
        api.permissionTypes(),
      ])
      setRoles(roleResult.roles)
      setPermissions(permissionResult.permissions)
      setPermissionTypes(typeResult.permission_types)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  function openRole(role?: AccessRole) {
    setEditingRole(role || "new")
    setRoleForm(role
      ? { code: role.code, name: role.name, description: role.description, permissions: [...role.permissions], enabled: role.enabled }
      : { ...emptyRole, permissions: ["console.view"] })
  }

  function openType(item?: PermissionType) {
    setEditingType(item || "new")
    setTypeForm(item
      ? { code: item.code, name: item.name, base_level: item.base_level, description: item.description, enabled: item.enabled }
      : { ...emptyType })
  }

  async function saveRole() {
    setBusy(true)
    setError(null)
    try {
      if (editingRole && editingRole !== "new") await api.updateAccessRole(editingRole.id, roleForm)
      else await api.createAccessRole(roleForm)
      setMessage(`${t("saved")}: ${roleForm.name}`)
      setEditingRole(null)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function saveType() {
    setBusy(true)
    setError(null)
    try {
      if (editingType && editingType !== "new") await api.updatePermissionType(editingType.id, typeForm)
      else await api.createPermissionType(typeForm)
      setMessage(`${t("saved")}: ${typeForm.name}`)
      setEditingType(null)
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  async function removeRole(role: AccessRole) {
    if (!(await confirm({ title: c.deleteRole, description: `${role.name} (${role.code})`, destructive: true }))) return
    try {
      await api.deleteAccessRole(role.id)
      setMessage(`${t("deleted")}: ${role.name}`)
      await load()
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
  }

  async function removeType(item: PermissionType) {
    if (!(await confirm({ title: c.deleteType, description: `${item.name} (${item.code})`, destructive: true }))) return
    try {
      await api.deletePermissionType(item.id)
      setMessage(`${t("deleted")}: ${item.name}`)
      await load()
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
  }

  const toast: ToastState = error ? { message: error, tone: "error" } : message ? { message, tone: "success" } : null

  return (
    <div className="flex flex-col gap-4">
      <PageHeader
        eyebrow={c.eyebrow}
        title={c.title}
        description={c.description}
        stats={[{ label: c.roles, value: roles.length }, { label: c.permissionTypes, value: permissionTypes.length }, { label: c.controlPermissions, value: permissions.length }]}
        actions={<Button variant="outline" onClick={load} disabled={busy}><RefreshCcw />{t("refresh")}</Button>}
      />
      {error && <Alert variant="destructive"><AlertDescription>{error}</AlertDescription></Alert>}
      <div className="grid gap-4">
        <Card>
          <CardHeader className="flex-row items-start justify-between gap-3">
            <div><CardTitle className="flex items-center gap-2"><Shield className="size-5 text-primary" />{c.roles}</CardTitle><CardDescription>{c.roleDesc}</CardDescription></div>
            <Button onClick={() => openRole()}><Plus />{c.newRole}</Button>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader><TableRow><TableHead>{c.name}</TableHead><TableHead>{c.members}</TableHead><TableHead>{c.controlPermissions}</TableHead><TableHead>{t("status")}</TableHead><TableHead>{t("actions")}</TableHead></TableRow></TableHeader>
              <TableBody>
                {roles.length === 0 ? <TableEmptyRow colSpan={5} title={c.noRoles} /> : roles.map((role) => <TableRow key={role.id}>
                  <TableCell><div className="font-medium">{role.name}</div><div className="text-xs text-muted-foreground">{role.code}</div></TableCell>
                  <TableCell>{role.member_count}</TableCell>
                  <TableCell><div className="flex max-w-sm flex-wrap gap-1">{role.permissions.slice(0, 4).map((permission) => <Badge key={permission} variant="outline" title={permission}>{permissionPresentationByCode.get(permission)?.name || permission}</Badge>)}{role.permissions.length > 4 && <Badge variant="secondary">+{role.permissions.length - 4}</Badge>}</div></TableCell>
                  <TableCell><Badge variant={role.enabled ? "success" : "secondary"}>{role.is_system ? c.system : c.custom} · {role.enabled ? c.enabled : t("disabled")}</Badge></TableCell>
                  <TableCell><ActionMenu label={t("actions")}><ActionMenuItem onClick={() => openRole(role)}>{t("edit")}</ActionMenuItem>{!role.is_system && <ActionMenuItem destructive onClick={() => void removeRole(role)}>{t("delete")}</ActionMenuItem>}</ActionMenu></TableCell>
                </TableRow>)}
              </TableBody>
            </Table>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-start justify-between gap-3">
            <div><CardTitle className="flex items-center gap-2"><KeySquare className="size-5 text-primary" />{c.permissionTypes}</CardTitle><CardDescription>{c.permissionTypeDesc}</CardDescription></div>
            <Button onClick={() => openType()}><Plus />{c.newType}</Button>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader><TableRow><TableHead>{c.name}</TableHead><TableHead>{c.baseLevel}</TableHead><TableHead>{c.references}</TableHead><TableHead>{t("actions")}</TableHead></TableRow></TableHeader>
              <TableBody>
                {permissionTypes.length === 0 ? <TableEmptyRow colSpan={4} title={c.noTypes} /> : permissionTypes.map((item) => <TableRow key={item.id}>
                  <TableCell><div className="font-medium">{item.name}</div><div className="text-xs text-muted-foreground">{item.code} · {item.is_system ? c.system : c.custom}</div></TableCell>
                  <TableCell><AccessLevelBadge level={item.base_level} labels={c} /></TableCell>
                  <TableCell>{item.reference_count}</TableCell>
                  <TableCell><ActionMenu label={t("actions")}><ActionMenuItem onClick={() => openType(item)}>{t("edit")}</ActionMenuItem>{!item.is_system && <ActionMenuItem destructive onClick={() => void removeType(item)}>{t("delete")}</ActionMenuItem>}</ActionMenu></TableCell>
                </TableRow>)}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>

      <Dialog open={editingRole !== null} onOpenChange={(open) => { if (!open) setEditingRole(null) }}>
        <DialogContent className="max-w-3xl">
          <DialogHeader><DialogTitle>{editingRole === "new" ? c.newRole : c.editRole}</DialogTitle><DialogDescription>{c.roleDesc}</DialogDescription></DialogHeader>
          <DialogBody className="flex max-h-[72vh] flex-col gap-4 overflow-y-auto">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={c.code}><Input value={roleForm.code} disabled={editingRole !== "new" && Boolean(editingRole && editingRole.is_system)} onChange={(event) => setRoleForm((current) => ({ ...current, code: event.target.value }))} /></Field>
              <Field label={c.name}><Input value={roleForm.name} onChange={(event) => setRoleForm((current) => ({ ...current, name: event.target.value }))} /></Field>
            </div>
            <Field label={c.descriptionLabel}><Textarea value={roleForm.description} onChange={(event) => setRoleForm((current) => ({ ...current, description: event.target.value }))} /></Field>
            <label className="flex items-center justify-between rounded-lg border p-3"><span className="text-sm font-medium">{c.enabled}</span><Switch checked={roleForm.enabled} disabled={editingRole !== "new" && Boolean(editingRole && editingRole.is_system)} onCheckedChange={(enabled) => setRoleForm((current) => ({ ...current, enabled }))} /></label>
            <div>
              <Label>{c.controlPermissions}</Label>
              <div className="mt-2 grid gap-3 md:grid-cols-2">
                {permissionGroups.map(([group, items]) => <div key={group} className="rounded-lg border p-3"><div className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground">{group}</div><div className="flex flex-col gap-2">{items.map((permission) => {
                  const presentation = presentControlPermission(permission, locale)
                  return <label key={permission.code} title={permission.code} className="flex items-start justify-between gap-3 rounded-md bg-muted/30 p-2"><span><span className="block text-sm font-medium">{presentation.name}</span><span className="block text-xs text-muted-foreground">{presentation.description}</span></span><Switch checked={roleForm.permissions.includes(permission.code)} onCheckedChange={(checked) => setRoleForm((current) => ({ ...current, permissions: checked ? [...new Set([...current.permissions, permission.code])] : current.permissions.filter((item) => item !== permission.code) }))} /></label>
                })}</div></div>)}
              </div>
            </div>
            <div className="flex justify-end gap-2 border-t pt-4"><Button variant="outline" onClick={() => setEditingRole(null)}>{t("cancel")}</Button><Button onClick={() => void saveRole()} disabled={busy || !roleForm.code.trim() || !roleForm.name.trim()}><SlidersHorizontal />{c.save}</Button></div>
          </DialogBody>
        </DialogContent>
      </Dialog>

      <Dialog open={editingType !== null} onOpenChange={(open) => { if (!open) setEditingType(null) }}>
        <DialogContent className="max-w-xl">
          <DialogHeader><DialogTitle>{editingType === "new" ? c.newType : c.editType}</DialogTitle><DialogDescription>{c.permissionTypeDesc}</DialogDescription></DialogHeader>
          <DialogBody className="flex flex-col gap-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={c.code}><Input value={typeForm.code} disabled={editingType !== "new" && Boolean(editingType && editingType.is_system)} onChange={(event) => setTypeForm((current) => ({ ...current, code: event.target.value }))} /></Field>
              <Field label={c.name}><Input value={typeForm.name} onChange={(event) => setTypeForm((current) => ({ ...current, name: event.target.value }))} /></Field>
            </div>
            <Field label={c.baseLevel}><Select value={typeForm.base_level} disabled={editingType !== "new" && Boolean(editingType && editingType.is_system)} onValueChange={(value) => setTypeForm((current) => ({ ...current, base_level: value as PermissionTypeSaveRequest["base_level"] }))}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="none">{c.noneLevel}</SelectItem><SelectItem value="read">{c.readLevel}</SelectItem><SelectItem value="write">{c.writeLevel}</SelectItem></SelectContent></Select></Field>
            <Field label={c.descriptionLabel}><Textarea value={typeForm.description} onChange={(event) => setTypeForm((current) => ({ ...current, description: event.target.value }))} /></Field>
            <label className="flex items-center justify-between rounded-lg border p-3"><span className="text-sm font-medium">{c.enabled}</span><Switch checked={typeForm.enabled} disabled={editingType !== "new" && Boolean(editingType && editingType.is_system)} onCheckedChange={(enabled) => setTypeForm((current) => ({ ...current, enabled }))} /></label>
            <div className="flex justify-end gap-2 border-t pt-4"><Button variant="outline" onClick={() => setEditingType(null)}>{t("cancel")}</Button><Button onClick={() => void saveType()} disabled={busy || !typeForm.code.trim() || !typeForm.name.trim()}>{c.save}</Button></div>
          </DialogBody>
        </DialogContent>
      </Dialog>
      {confirmDialog}
      <Toaster toast={toast} onClose={() => { setError(null); setMessage(null) }} />
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="flex flex-col gap-2"><Label>{label}</Label>{children}</div>
}

function presentControlPermission(permission: ControlPermission, locale: Locale): ControlPermissionPresentation {
  return controlPermissionPresentations[locale][permission.code] || {
    name: permission.name || permission.code,
    description: permission.description,
    group: locale === "zh-CN" ? "其他权限" : "Other permissions",
  }
}

function AccessLevelBadge({ level, labels }: { level: PermissionType["base_level"]; labels: Record<string, string> }) {
  if (level === "write") return <Badge variant="warning">{labels.writeLevel}</Badge>
  if (level === "read") return <Badge variant="success">{labels.readLevel}</Badge>
  return <Badge variant="secondary">{labels.noneLevel}</Badge>
}

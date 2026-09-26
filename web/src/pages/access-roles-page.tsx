import { useEffect, useMemo, useRef, useState } from "react"
import { ArrowRight, CheckCircle2, Info, KeySquare, Plus, RefreshCcw, Shield, SlidersHorizontal, X } from "lucide-react"
import { api, type AccessRole, type AccessRoleSaveRequest, type ControlPermission, type PermissionType, type PermissionTypeSaveRequest } from "@/api/client"
import { useConfirm } from "@/components/confirm-dialog"
import { PageHeader, PageToolbar } from "@/components/page-shell"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Textarea } from "@/components/ui/textarea"
import { Toaster, type ToastState } from "@/components/ui/toast"
import { AccessInlineActions } from "@/features/access-roles/inline-actions"
import { canDeleteAccessItem, copyPermissionTypePayload, copyRolePayload, emptyAccessFilters, filterAccessItems, normalizeAccessCode, permissionTypePayload, rolePayload, type AccessFilters, type AccessItem } from "@/features/access-roles/model"
import { accessRolesCopy, presentControlPermission } from "@/features/access-roles/presentation"
import type { Locale, TFunction } from "@/i18n"
import { TableEmptyRow } from "@/pages/page-utils"
import "./access-roles-page.css"

const emptyRole: AccessRoleSaveRequest = { code: "", name: "", description: "", permissions: [], enabled: true }
const emptyType: PermissionTypeSaveRequest = { code: "", name: "", base_level: "read", description: "", enabled: true }
type AccessTab = "roles" | "types"

export function AccessRolesPage({ locale, t }: { locale: Locale; t: TFunction }) {
  const c = accessRolesCopy[locale]
  const [roles, setRoles] = useState<AccessRole[]>([])
  const [permissions, setPermissions] = useState<ControlPermission[]>([])
  const [permissionTypes, setPermissionTypes] = useState<PermissionType[]>([])
  const [tab, setTab] = useState<AccessTab>("roles")
  const [filters, setFilters] = useState<AccessFilters>(emptyAccessFilters)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [editingRole, setEditingRole] = useState<AccessRole | "new" | null>(null)
  const [roleForm, setRoleForm] = useState<AccessRoleSaveRequest>({ ...emptyRole })
  const [editingType, setEditingType] = useState<PermissionType | "new" | null>(null)
  const [typeForm, setTypeForm] = useState<PermissionTypeSaveRequest>({ ...emptyType })
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const { confirm, confirmDialog } = useConfirm(t)
  const wideDetails = useWideDetails()
  const initiallySelected = useRef(false)
  const detailTrigger = useRef<HTMLElement | null>(null)
  const roleTabRef = useRef<HTMLButtonElement>(null)
  const typeTabRef = useRef<HTMLButtonElement>(null)

  const permissionPresentationByCode = useMemo(() => new Map(permissions.map(permission => [permission.code, presentControlPermission(permission, locale)])), [locale, permissions])
  const permissionGroups = useMemo(() => {
    const groups = new Map<string, ControlPermission[]>()
    for (const permission of permissions) {
      const group = presentControlPermission(permission, locale).group
      groups.set(group, [...(groups.get(group) || []), permission])
    }
    return [...groups.entries()]
  }, [locale, permissions])
  const filteredRoles = useMemo(() => filterAccessItems(roles, filters), [roles, filters])
  const filteredTypes = useMemo(() => filterAccessItems(permissionTypes, filters), [permissionTypes, filters])
  const roleMode = tab === "roles"
  const visibleItems: AccessItem[] = roleMode ? filteredRoles : filteredTypes
  const selected = visibleItems.find(item => item.id === selectedId)

  useEffect(() => { void load() }, [])
  useEffect(() => {
    if (selectedId && !selected && !busy) setSelectedId(null)
  }, [selectedId, selected, busy])

  async function load() {
    setBusy(true)
    setError(null)
    try {
      const [roleResult, permissionResult, typeResult] = await Promise.all([api.accessRoles(), api.controlPermissions(), api.permissionTypes()])
      setRoles(roleResult.roles)
      setPermissions(permissionResult.permissions)
      setPermissionTypes(typeResult.permission_types)
      if (!initiallySelected.current) {
        initiallySelected.current = true
        if (window.matchMedia("(min-width: 1440px)").matches) setSelectedId(roleResult.roles.find(role => role.code === "viewer")?.id || null)
      }
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  function switchTab(next: AccessTab) {
    setTab(next)
    setSelectedId(null)
    setFilters(emptyAccessFilters)
  }

  function viewItem(item: AccessItem) {
    detailTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null
    setSelectedId(item.id)
  }

  function closeDetails() {
    setSelectedId(null)
    detailTrigger.current?.focus()
  }

  function openRole(role?: AccessRole, duplicate = false) {
    setFormError(null)
    setEditingRole(duplicate ? "new" : role || "new")
    setRoleForm(role ? duplicate ? copyRolePayload(role, c.copySuffix) : rolePayload(role) : { ...emptyRole, permissions: ["console.view"] })
  }

  function openType(item?: PermissionType, duplicate = false) {
    setFormError(null)
    setEditingType(duplicate ? "new" : item || "new")
    setTypeForm(item ? duplicate ? copyPermissionTypePayload(item, c.copySuffix) : permissionTypePayload(item) : { ...emptyType })
  }

  async function saveRole() {
    if (busy) return
    const payload = { ...roleForm, code: normalizeAccessCode(roleForm.code), name: roleForm.name.trim() }
    if (!payload.code || !payload.name) { setFormError(c.requiredFields); return }
    if (roles.some(role => role.code === payload.code && (editingRole === "new" || role.id !== editingRole?.id))) { setFormError(c.duplicateCode); return }
    setBusy(true)
    setFormError(null)
    try {
      const saved = editingRole && editingRole !== "new" ? await api.updateAccessRole(editingRole.id, payload) : await api.createAccessRole(payload)
      setRoles(current => current.some(item => item.id === saved.id) ? current.map(item => item.id === saved.id ? saved : item) : [...current, saved])
      setFilters(emptyAccessFilters)
      setSelectedId(saved.id)
      setMessage(`${t("saved")}: ${saved.name}`)
      setEditingRole(null)
    } catch (err) { setFormError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  async function saveType() {
    if (busy) return
    const payload = { ...typeForm, code: normalizeAccessCode(typeForm.code), name: typeForm.name.trim() }
    if (!payload.code || !payload.name) { setFormError(c.requiredFields); return }
    if (permissionTypes.some(item => item.code === payload.code && (editingType === "new" || item.id !== editingType?.id))) { setFormError(c.duplicateCode); return }
    setBusy(true)
    setFormError(null)
    try {
      const saved = editingType && editingType !== "new" ? await api.updatePermissionType(editingType.id, payload) : await api.createPermissionType(payload)
      setPermissionTypes(current => current.some(item => item.id === saved.id) ? current.map(item => item.id === saved.id ? saved : item) : [...current, saved])
      setFilters(emptyAccessFilters)
      setSelectedId(saved.id)
      setMessage(`${t("saved")}: ${saved.name}`)
      setEditingType(null)
    } catch (err) { setFormError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  async function toggleItem(item: AccessItem) {
    if (busy || item.is_system) return
    if (item.enabled && !(await confirm({ title: `${c.disable} ${item.name}`, description: "permissions" in item ? c.disableRoleHint : c.disableTypeHint, confirmText: c.disable, destructive: true }))) return
    setBusy(true)
    setError(null)
    try {
      if ("permissions" in item) {
        const saved = await api.updateAccessRole(item.id, { ...rolePayload(item), enabled: !item.enabled })
        setRoles(current => current.map(role => role.id === saved.id ? saved : role))
      } else {
        const saved = await api.updatePermissionType(item.id, { ...permissionTypePayload(item), enabled: !item.enabled })
        setPermissionTypes(current => current.map(type => type.id === saved.id ? saved : type))
      }
      setMessage(`${item.name}: ${item.enabled ? c.disabledStatus : c.enabledStatus}`)
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  async function removeItem(item: AccessItem) {
    if (busy || !canDeleteAccessItem(item)) return
    if (!(await confirm({ title: "permissions" in item ? c.deleteRole : c.deleteType, description: `${item.name} (${item.code})`, destructive: true }))) return
    setBusy(true)
    setError(null)
    try {
      if ("permissions" in item) {
        await api.deleteAccessRole(item.id)
        setRoles(current => current.filter(role => role.id !== item.id))
      } else {
        await api.deletePermissionType(item.id)
        setPermissionTypes(current => current.filter(type => type.id !== item.id))
      }
      if (selectedId === item.id) setSelectedId(null)
      setMessage(`${t("deleted")}: ${item.name}`)
    } catch (err) { setError(err instanceof Error ? err.message : String(err)) }
    finally { setBusy(false) }
  }

  function editItem(item: AccessItem, duplicate = false) {
    if ("permissions" in item) openRole(item, duplicate)
    else openType(item, duplicate)
  }

  const toast: ToastState = error ? { message: error, tone: "error" } : message ? { message, tone: "success" } : null
  const detailContent = selected && <div className="access-role-detail-content">
    <div className="access-role-detail-identity">{"permissions" in selected ? <Shield /> : <KeySquare />}<div><h3>{selected.name}</h3><p>{selected.code}</p></div></div>
    <div className="access-role-detail-badges"><Badge variant="secondary">{selected.is_system ? c.system : c.custom}</Badge><AccessStatus enabled={selected.enabled} locale={locale} /></div>
    <dl className="access-role-detail-stat"><dt>{"permissions" in selected ? c.members : c.references}</dt><dd>{"permissions" in selected ? selected.member_count : selected.reference_count}</dd></dl>
    {"permissions" in selected ? <section className="access-role-detail-section">
      <div className="flex items-center justify-between gap-2"><h4>{c.controlPermissions}</h4><span className="text-xs text-muted-foreground">{selected.permissions.length} {c.permissionCount}</span></div>
      <p>{c.permissionsHint}</p>
      {selected.permissions.length ? <ul>{selected.permissions.map(code => <li key={code}><CheckCircle2 /><span>{permissionPresentationByCode.get(code)?.name || code}<small>{permissionPresentationByCode.get(code)?.description || code}</small></span></li>)}</ul> : <p>{c.noPermissions}</p>}
    </section> : <section className="access-role-detail-section"><div className="flex items-center justify-between gap-2"><h4>{c.baseLevel}</h4><AccessLevelBadge level={selected.base_level} labels={c} /></div><p>{c.permissionTypeDesc}</p></section>}
    <section className="access-role-detail-section"><h4>{c.descriptionLabel}</h4><p>{selected.description || c.emptyDescription}</p></section>
    <Button variant="outline" disabled={busy} onClick={() => editItem(selected)}>{"permissions" in selected ? c.editRole : c.editType}</Button>
  </div>

  return <div className="access-roles-page">
    <div className={`access-roles-layout${selected && wideDetails ? " with-details" : ""}`}>
      <div className="access-roles-directory">
        <PageHeader title={c.title} description={c.description} helpLabel={t("pageHelp")}
          toolbar={<div className="access-role-tabs" role="tablist" aria-label={c.managementTabs} onKeyDown={event => {
            if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return
            event.preventDefault()
            const next = event.key === "Home" ? "roles" : event.key === "End" ? "types" : roleMode ? "types" : "roles"
            switchTab(next)
            ;(next === "roles" ? roleTabRef : typeTabRef).current?.focus()
          }}>
            <button ref={roleTabRef} id="access-roles-tab" type="button" role="tab" aria-selected={roleMode} tabIndex={roleMode ? 0 : -1} aria-controls="access-roles-panel" onClick={() => switchTab("roles")}>{c.roles}<span>{roles.length}</span></button>
            <button ref={typeTabRef} id="access-types-tab" type="button" role="tab" aria-selected={!roleMode} tabIndex={roleMode ? -1 : 0} aria-controls="access-roles-panel" onClick={() => switchTab("types")}>{c.permissionTypes}<span>{permissionTypes.length}</span></button>
          </div>}
          actions={<Button variant="ghost" size="sm" aria-label={t("refresh")} title={t("refresh")} disabled={busy} onClick={() => void load()}><RefreshCcw className={busy ? "animate-spin" : ""} /></Button>} />
        {error && <Alert variant="destructive" role="alert"><AlertDescription>{error}</AlertDescription></Alert>}
        <section id="access-roles-panel" role="tabpanel" aria-labelledby={roleMode ? "access-roles-tab" : "access-types-tab"} aria-busy={busy}>
          <PageToolbar className="access-role-filters" query={filters.query} onQueryChange={query => setFilters(current => ({ ...current, query }))} placeholder={roleMode ? c.searchRoles : c.searchTypes} clearLabel={t("clearSearch")}>
            <Select value={filters.source} onValueChange={source => setFilters(current => ({ ...current, source: source as AccessFilters["source"] }))}><SelectTrigger className="access-filter-select" aria-label={c.source}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">{c.allSources}</SelectItem><SelectItem value="system">{c.system}</SelectItem><SelectItem value="custom">{c.custom}</SelectItem></SelectContent></Select>
            <Select value={filters.status} onValueChange={status => setFilters(current => ({ ...current, status: status as AccessFilters["status"] }))}><SelectTrigger className="access-filter-select" aria-label={t("status")}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">{c.allStatuses}</SelectItem><SelectItem value="enabled">{c.enabledStatus}</SelectItem><SelectItem value="disabled">{c.disabledStatus}</SelectItem></SelectContent></Select>
            {!roleMode && <Select value={filters.level} onValueChange={level => setFilters(current => ({ ...current, level: level as AccessFilters["level"] }))}><SelectTrigger className="access-filter-select" aria-label={c.baseLevel}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="all">{c.allLevels}</SelectItem><SelectItem value="none">{c.noneLevel}</SelectItem><SelectItem value="read">{c.readLevel}</SelectItem><SelectItem value="write">{c.writeLevel}</SelectItem></SelectContent></Select>}
            <Button className="access-create" disabled={busy} onClick={() => roleMode ? openRole() : openType()}><Plus />{roleMode ? c.newRole : c.newType}</Button>
          </PageToolbar>
          <Table className="access-role-table">
            <colgroup><col style={{ width: "20%" }} /><col style={{ width: roleMode ? "7%" : "12%" }} /><col style={{ width: roleMode ? "22%" : "17%" }} /><col style={{ width: "12%" }} /><col style={{ width: "11%" }} /><col style={{ width: "28%" }} /></colgroup>
            <TableHeader><TableRow>{(roleMode ? [c.roles, c.members, c.controlPermissions, c.source, t("status"), t("actions")] : [c.permissionTypes, c.baseLevel, c.references, c.source, t("status"), t("actions")]).map(label => <TableHead key={label} scope="col">{label}</TableHead>)}</TableRow></TableHeader>
            <TableBody>{visibleItems.length === 0 ? <TableEmptyRow colSpan={6} title={busy ? c.loading : error ? t("error") : c.noMatches} description={error || undefined} /> : visibleItems.map(item => <TableRow key={item.id} data-state={selectedId === item.id ? "selected" : undefined}>
              <TableCell><button type="button" className="access-name" aria-label={`${c.view} ${item.name}`} onClick={() => viewItem(item)}>{"permissions" in item ? <Shield /> : <KeySquare />}<span><strong>{item.name}</strong><small title={item.code}>{item.code}</small></span></button></TableCell>
              {"permissions" in item ? <><TableCell>{item.member_count}</TableCell><TableCell><button type="button" className="access-permission-summary" onClick={() => viewItem(item)} aria-label={`${item.name} ${c.controlPermissions}`}><strong>{item.permissions.length} {c.permissionCount}</strong><small>{item.permissions.map(code => permissionPresentationByCode.get(code)?.name || code).join("、") || c.noPermissions}</small></button></TableCell></> : <><TableCell><AccessLevelBadge level={item.base_level} labels={c} /></TableCell><TableCell>{item.reference_count}</TableCell></>}
              <TableCell><Badge variant="secondary" className="whitespace-nowrap text-[11px]">{item.is_system ? c.system : c.custom}</Badge></TableCell>
              <TableCell><AccessStatus enabled={item.enabled} locale={locale} /></TableCell>
              <TableCell><AccessInlineActions item={item} locale={locale} t={t} busy={busy} onView={() => viewItem(item)} onEdit={() => editItem(item)} onCopy={() => editItem(item, true)} onToggle={() => void toggleItem(item)} onDelete={() => void removeItem(item)} /></TableCell>
            </TableRow>)}</TableBody>
          </Table>
          <div className="access-role-count flex items-center gap-3"><span aria-live="polite">{c.total} {visibleItems.length} / {roleMode ? roles.length : permissionTypes.length} {c.items}</span>{!busy && !error && !visibleItems.length && <Button variant="ghost" size="sm" onClick={() => setFilters(emptyAccessFilters)}>{c.resetFilters}</Button>}</div>
        </section>
        <div className="access-role-tip"><Info /><span>{roleMode ? c.rolesHint : c.typesHint}</span><Button variant="ghost" size="sm" onClick={() => switchTab(roleMode ? "types" : "roles")}>{roleMode ? c.manageTypes : c.manageRoles}<ArrowRight /></Button></div>
      </div>
      {selected && wideDetails && <aside className="access-role-detail" aria-label={roleMode ? c.roleDetails : c.typeDetails}><div className="access-role-detail-header"><h2>{roleMode ? c.roleDetails : c.typeDetails}</h2><Button variant="ghost" size="sm" aria-label={c.closeDetails} onClick={closeDetails}><X /></Button></div>{detailContent}</aside>}
    </div>
    <Dialog open={Boolean(selected && !wideDetails && !editingRole && !editingType)} onOpenChange={open => { if (!open) closeDetails() }}>
      <DialogContent className="left-auto right-0 top-0 h-dvh max-h-dvh w-full max-w-md translate-x-0 translate-y-0 rounded-none">
        <DialogHeader><DialogTitle>{roleMode ? c.roleDetails : c.typeDetails}</DialogTitle><DialogDescription className="sr-only">{selected?.name}</DialogDescription></DialogHeader><DialogBody>{detailContent}</DialogBody>
      </DialogContent>
    </Dialog>
      <Dialog open={editingRole !== null} onOpenChange={(open) => { if (!open && !busy) setEditingRole(null) }}>
        <DialogContent className="max-w-3xl">
          <DialogHeader><DialogTitle>{editingRole === "new" ? c.newRole : c.editRole}</DialogTitle><DialogDescription>{c.roleDesc}</DialogDescription></DialogHeader>
          <DialogBody className="flex max-h-[72vh] flex-col gap-4 overflow-y-auto">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={c.code}><Input aria-label={c.code} value={roleForm.code} disabled={editingRole !== "new" && Boolean(editingRole && editingRole.is_system)} onChange={(event) => setRoleForm((current) => ({ ...current, code: event.target.value }))} /></Field>
              <Field label={c.name}><Input aria-label={c.name} value={roleForm.name} onChange={(event) => setRoleForm((current) => ({ ...current, name: event.target.value }))} /></Field>
            </div>
            <Field label={c.descriptionLabel}><Textarea aria-label={c.descriptionLabel} value={roleForm.description} onChange={(event) => setRoleForm((current) => ({ ...current, description: event.target.value }))} /></Field>
            <label className="flex items-center justify-between rounded-lg border p-3"><span className="text-sm font-medium">{c.enabled}</span><Switch aria-label={c.enabled} checked={roleForm.enabled} disabled={editingRole !== "new" && Boolean(editingRole && editingRole.is_system)} onCheckedChange={(enabled) => setRoleForm((current) => ({ ...current, enabled }))} /></label>
            <div>
              <Label>{c.controlPermissions}</Label>
              <div className="mt-2 grid gap-3 md:grid-cols-2">
                {permissionGroups.map(([group, items]) => <div key={group} className="rounded-lg border p-3"><div className="mb-2 text-xs font-semibold tracking-wide text-muted-foreground">{group}</div><div className="flex flex-col gap-2">{items.map((permission) => {
                  const presentation = presentControlPermission(permission, locale)
                  return <label key={permission.code} title={permission.code} className="flex items-start justify-between gap-3 rounded-md bg-muted/30 p-2"><span><span className="block text-sm font-medium">{presentation.name}</span><span className="block text-xs text-muted-foreground">{presentation.description}</span></span><Switch aria-label={presentation.name} checked={roleForm.permissions.includes(permission.code)} onCheckedChange={(checked) => setRoleForm((current) => ({ ...current, permissions: checked ? [...new Set([...current.permissions, permission.code])] : current.permissions.filter((item) => item !== permission.code) }))} /></label>
                })}</div></div>)}
              </div>
            </div>
            {formError && <Alert variant="destructive" role="alert"><AlertDescription>{formError}</AlertDescription></Alert>}
            <div className="flex justify-end gap-2 border-t pt-4"><Button variant="outline" disabled={busy} onClick={() => setEditingRole(null)}>{t("cancel")}</Button><Button onClick={() => void saveRole()} disabled={busy || !roleForm.code.trim() || !roleForm.name.trim()}><SlidersHorizontal />{c.save}</Button></div>
          </DialogBody>
        </DialogContent>
      </Dialog>

      <Dialog open={editingType !== null} onOpenChange={(open) => { if (!open && !busy) setEditingType(null) }}>
        <DialogContent className="max-w-xl">
          <DialogHeader><DialogTitle>{editingType === "new" ? c.newType : c.editType}</DialogTitle><DialogDescription>{c.permissionTypeDesc}</DialogDescription></DialogHeader>
          <DialogBody className="flex flex-col gap-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label={c.code}><Input aria-label={c.code} value={typeForm.code} disabled={editingType !== "new" && Boolean(editingType && editingType.is_system)} onChange={(event) => setTypeForm((current) => ({ ...current, code: event.target.value }))} /></Field>
              <Field label={c.name}><Input aria-label={c.name} value={typeForm.name} onChange={(event) => setTypeForm((current) => ({ ...current, name: event.target.value }))} /></Field>
            </div>
            <Field label={c.baseLevel}><Select value={typeForm.base_level} disabled={editingType !== "new" && Boolean(editingType && editingType.is_system)} onValueChange={(value) => setTypeForm((current) => ({ ...current, base_level: value as PermissionTypeSaveRequest["base_level"] }))}><SelectTrigger aria-label={c.baseLevel}><SelectValue /></SelectTrigger><SelectContent><SelectItem value="none">{c.noneLevel}</SelectItem><SelectItem value="read">{c.readLevel}</SelectItem><SelectItem value="write">{c.writeLevel}</SelectItem></SelectContent></Select></Field>
            <Field label={c.descriptionLabel}><Textarea aria-label={c.descriptionLabel} value={typeForm.description} onChange={(event) => setTypeForm((current) => ({ ...current, description: event.target.value }))} /></Field>
            <label className="flex items-center justify-between rounded-lg border p-3"><span className="text-sm font-medium">{c.enabled}</span><Switch aria-label={c.enabled} checked={typeForm.enabled} disabled={editingType !== "new" && Boolean(editingType && editingType.is_system)} onCheckedChange={(enabled) => setTypeForm((current) => ({ ...current, enabled }))} /></label>
            {formError && <Alert variant="destructive" role="alert"><AlertDescription>{formError}</AlertDescription></Alert>}
            <div className="flex justify-end gap-2 border-t pt-4"><Button variant="outline" disabled={busy} onClick={() => setEditingType(null)}>{t("cancel")}</Button><Button onClick={() => void saveType()} disabled={busy || !typeForm.code.trim() || !typeForm.name.trim()}>{c.save}</Button></div>
          </DialogBody>
        </DialogContent>
      </Dialog>
    {confirmDialog}
    <Toaster toast={toast} onClose={() => { setError(null); setMessage(null) }} />
  </div>
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <div className="flex flex-col gap-2"><Label>{label}</Label>{children}</div>
}

function AccessStatus({ enabled, locale }: { enabled: boolean; locale: Locale }) {
  const c = accessRolesCopy[locale]
  return <span className="access-role-status" data-enabled={enabled}>{enabled ? c.enabledStatus : c.disabledStatus}</span>
}

function AccessLevelBadge({ level, labels }: { level: PermissionType["base_level"]; labels: Record<string, string> }) {
  if (level === "write") return <Badge variant="warning">{labels.writeLevel}</Badge>
  if (level === "read") return <Badge variant="success">{labels.readLevel}</Badge>
  return <Badge variant="secondary">{labels.noneLevel}</Badge>
}

function useWideDetails() {
  const [wide, setWide] = useState(() => typeof window !== "undefined" && window.matchMedia("(min-width: 1440px)").matches)
  useEffect(() => {
    const media = window.matchMedia("(min-width: 1440px)")
    const change = () => setWide(media.matches)
    change()
    media.addEventListener("change", change)
    return () => media.removeEventListener("change", change)
  }, [])
  return wide
}

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { Dropdown, Select, Switch } from "antd"
import { Copy, KeyRound, MoreHorizontal, Plus, RefreshCw } from "lucide-react"
import { businessCredentialsApi, BusinessCredentialRequestError, type BusinessCredential, type BusinessCredentialBinding,
  type BusinessCredentialScope, type BusinessCredentialTargets, type BusinessCredentialSession } from "@/api/business-credentials"
import { businessCredentialDraft, businessCredentialPrompt, businessCredentialWrite, emptyBusinessCredentialDraft,
  filterBusinessCredentials, secureBusinessCredentialTransport, validateBusinessCredentialDraft, type BusinessCredentialDraft } from "@/features/business-credentials"
import { ActionMenu, ActionMenuItem } from "@/components/action-menu"
import { useConfirm } from "@/components/confirm-dialog"
import { FilterRadio } from "@/components/filter-radio"
import { FormDialog } from "@/components/form-dialog"
import { ListPagination, ListViewport, RemainingList, useListPage } from "@/components/list-pagination"
import { PageHeader, PageToolbar } from "@/components/page-shell"
import { usePageRefresh } from "@/components/page-refresh"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogBody, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table"
import { Toaster } from "@/components/ui/toast"
import type { Locale, TFunction } from "@/i18n"
import { formatDateTime } from "@/lib/utils"
import { TableEmptyRow } from "@/pages/page-utils"
import "./business-credentials-panel.css"

type Props = { locale: Locale; t: TFunction; scope: BusinessCredentialScope }
type BindingDraft = { id: string; server_id: string; tool_prefix: "agent_browser_" | ""; enabled: boolean }
const dialogPopupContainer = (trigger: HTMLElement) => trigger.closest<HTMLElement>('[role="dialog"]') || trigger.parentElement!
const emptyBinding = (): BindingDraft => ({ id: "", server_id: "", tool_prefix: "agent_browser_", enabled: true })

/** Used by the shared and personal credential tabs; the server owns authorization and secret resolution. */
export function BusinessCredentialsPanel({ locale, t, scope }: Props) {
  const zh = locale === "zh-CN"
  const tx = (cn: string, en: string) => zh ? cn : en
  const [records, setRecords] = useState<BusinessCredential[]>([])
  const [targets, setTargets] = useState<BusinessCredentialTargets | null>(null)
  const [loading, setLoading] = useState(true)
  const [targetLoading, setTargetLoading] = useState(false)
  const [listError, setListError] = useState<string | null>(null)
  const [targetError, setTargetError] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [mutation, setMutation] = useState("")
  const mutationLock = useRef(false)
  const mounted = useRef(true)
  const loadVersion = useRef(0)
  const targetVersion = useRef(0)
  const loadController = useRef<AbortController | null>(null)
  const targetController = useRef<AbortController | null>(null)
  const [query, setQuery] = useState("")
  const [statusFilter, setStatusFilter] = useState("all")
  const [editor, setEditor] = useState<{ record: BusinessCredential | null } | null>(null)
  const [draft, setDraft] = useState<BusinessCredentialDraft>(emptyBusinessCredentialDraft)
  const draftBaseline = useRef("")
  const [showValidation, setShowValidation] = useState(false)
  const [editorError, setEditorError] = useState<string | null>(null)
  const [bindingCredentialId, setBindingCredentialId] = useState<string | null>(null)
  const [bindingDraft, setBindingDraft] = useState<BindingDraft>(emptyBinding)
  const bindingBaseline = useRef(JSON.stringify(emptyBinding()))
  const [bindingError, setBindingError] = useState<string | null>(null)
  const bindingRevision = useRef(0)
  const bindingCredentialVersion = useRef(0)
  const [sessions, setSessions] = useState<BusinessCredentialSession[]>([])
  const [sessionLoading, setSessionLoading] = useState(false)
  const [sessionError, setSessionError] = useState<string | null>(null)
  const sessionVersion = useRef(0)
  const sessionController = useRef<AbortController | null>(null)
  const [copyFallback, setCopyFallback] = useState<string | null>(null)
  const createTrigger = useRef<HTMLButtonElement>(null)
  const editorReturnFocus = useRef<HTMLButtonElement | null>(null)
  const bindingReturnFocus = useRef<HTMLButtonElement | null>(null)
  const { confirm, confirmDialog } = useConfirm(t, true)
  const secure = typeof window !== "undefined" && secureBusinessCredentialTransport(window.location)
  const pending = mutation !== ""
  const dirty = editor !== null && JSON.stringify(draft) !== draftBaseline.current
  const bindingDirty = bindingCredentialId !== null && JSON.stringify(bindingDraft) !== bindingBaseline.current
  const selectedCredential = records.find(record => record.id === bindingCredentialId)
  const editingBinding = selectedCredential?.bindings.find(binding => binding.id === bindingDraft.id)
  const bindingTarget = targets?.servers.find(server => server.server_id === bindingDraft.server_id)
  const bindingPrefixes: ("agent_browser_" | "")[] = bindingDraft.id ? [bindingDraft.tool_prefix]
    : bindingTarget?.compatible_prefixes ?? (bindingTarget?.managed && bindingTarget.tool_prefix !== undefined ? [bindingTarget.tool_prefix] : ["agent_browser_", ""])
  const errors = validateBusinessCredentialDraft(draft, editor?.record != null)
  const filtered = useMemo(() => filterBusinessCredentials(records, query, statusFilter), [records, query, statusFilter])
  const paging = useListPage(filtered, JSON.stringify([query, statusFilter]))
  const closeEditor = useDraftCloseGuard({ dirty, pending, locale, confirm, onClose: clearEditor })
  const closeBindings = useDraftCloseGuard({ dirty: bindingDirty, pending, locale, confirm, onClose: () => {
    setBindingCredentialId(null); resetBinding(); setBindingError(null)
  } })

  function errorMessage(error: unknown): string {
    if (error instanceof BusinessCredentialRequestError) {
      const known = explainCode(error.code)
      if (known) return known
      if (error.code.endsWith("_timeout")) return tx("请求结果尚未确认。请先刷新核对状态，再决定是否重试；写操作不会自动重发。", "The request outcome is unconfirmed. Refresh its state before retrying; writes are not retried automatically.")
      if (error.status === 403) return tx("当前账号或连接没有执行此操作的权限。请检查凭据范围和 MCP 授权。", "This account or connection is not allowed to perform the operation. Check credential scope and MCP authorization.")
      if (error.status === 409) return tx("记录版本已变化，或节点副本尚未清理。请刷新核对后重试。", "The record changed or a node copy still needs cleanup. Refresh and review before retrying.") + ` (${error.code})`
      return tx("操作未完成，请检查配置并刷新后重试。", "The operation did not complete. Check configuration, refresh, and retry.") + ` (${error.code})`
    }
    return tx("操作未完成，请刷新状态后重试。", "The operation did not complete. Refresh its state before retrying.")
  }

  function explainCode(code: string): string | null {
    const messages: Record<string, [string, string]> = {
      credential_target_user_routing: ["该实例启用了按用户切换的 HTTP 凭据路由，首批受管浏览器不支持。请选择使用固定连接的专用实例。", "Per-user HTTP credential routing is not supported for managed browsers. Choose a dedicated instance with a fixed connection."],
      browser_option_value_denied: ["浏览器账号、表单选择器或相关参数不能以“-”开头，避免被原生工具误当作命令选项。请修改后再同步；密码不受此限制。", "Browser usernames, form selectors, and related options cannot begin with '-'. Update them before synchronizing. Passwords are not subject to this restriction."],
      adapter_tool_missing: ["未发现所需浏览器工具，请启用 agent-browser 的 core、state 工具组并刷新工具发现。", "Required browser tools were not discovered. Enable agent-browser core and state tool groups and refresh discovery."],
      adapter_contract_incompatible: ["实例工具参数不符合适配契约，请核对 agent-browser 版本与已选工具前缀。", "The instance tool contract is incompatible. Check the agent-browser version and selected tool prefix."],
      credential_target_changed: ["实例配置已变化，请应用当前 MCP 配置并刷新工具发现。", "The instance configuration changed. Apply the current MCP configuration and refresh discovery."],
      credential_target_shared_browser: ["此实例配置了共享浏览器或持久化浏览器状态，请使用专用且隔离的浏览器实例。", "This instance shares a browser or persistent browser state. Use a dedicated, isolated browser instance."],
      credential_transport_insecure: ["向浏览器节点派发秘密需要 HTTPS 或本机回环连接。", "Secret transfer to the browser node requires HTTPS or a loopback connection."],
      credential_revision_conflict: ["记录版本已变化。请保留需要的非秘密信息，关闭并重新打开编辑器后再修改；旧输入不会覆盖新版本。", "The record version changed. Keep any needed non-secret notes, then close and reopen the editor before editing again. Old input will not overwrite the new version."],
      remote_copy_cleanup_required: ["节点仍可能保存密码。请先执行“删除节点密码”并确认结果，再删除记录。", "A node may still hold the password. Delete the node password and verify the result before removing the record."],
      browser_session_cleanup_required: ["仍有受管浏览器会话未关闭。请在“浏览器会话”中关闭后再删除记录。", "Managed browser sessions remain open. Close them in Browser sessions before deleting the record."],
      browser_close_unknown: ["尚未确认浏览器会话已关闭。请刷新核对后再决定是否重试；网站登录态也未验证撤销。", "Browser closure remains unconfirmed. Refresh before deciding whether to retry. Website session revocation is also unverified."],
    }
    return messages[code] ? tx(...messages[code]) : null
  }

  useEffect(() => {
    mounted.current = true
    void load()
    return () => { mounted.current = false; loadVersion.current++; targetVersion.current++; sessionVersion.current++; loadController.current?.abort(); targetController.current?.abort(); sessionController.current?.abort() }
  }, [scope])
  useEffect(() => {
    setSessions([]); setSessionError(null)
    if (bindingCredentialId) void loadSessions(bindingCredentialId)
    return () => { sessionVersion.current++; sessionController.current?.abort() }
  }, [bindingCredentialId])
  useEffect(() => {
    if (selectedCredential && !bindingDirty && !bindingDraft.id) bindingCredentialVersion.current = selectedCredential.version
  }, [selectedCredential?.version, bindingCredentialId, bindingDirty, bindingDraft.id])
  usePageRefresh(load, loading || pending)

  async function load() {
    loadController.current?.abort()
    const controller = new AbortController(); loadController.current = controller
    const version = ++loadVersion.current
    setLoading(true); setListError(null)
    try {
      const result = await businessCredentialsApi.list(scope, controller.signal)
      if (mounted.current && version === loadVersion.current) setRecords(result.credentials)
    } catch (error) {
      if (mounted.current && version === loadVersion.current && !controller.signal.aborted) setListError(errorMessage(error))
    } finally { if (mounted.current && version === loadVersion.current) setLoading(false) }
  }

  async function loadTargets() {
    targetController.current?.abort()
    const controller = new AbortController(); targetController.current = controller
    const version = ++targetVersion.current
    setTargetLoading(true); setTargetError(null)
    try {
      const result = await businessCredentialsApi.targets(scope, controller.signal)
      if (mounted.current && version === targetVersion.current) setTargets(result)
    } catch (error) {
      if (mounted.current && version === targetVersion.current && !controller.signal.aborted) setTargetError(errorMessage(error))
    } finally { if (mounted.current && version === targetVersion.current) setTargetLoading(false) }
  }

  async function loadSessions(id: string) {
    sessionController.current?.abort()
    const controller = new AbortController(); sessionController.current = controller
    const version = ++sessionVersion.current
    setSessionLoading(true); setSessionError(null)
    try {
      const result = await businessCredentialsApi.sessions(id, controller.signal)
      if (mounted.current && version === sessionVersion.current) setSessions(result.sessions)
    } catch (error) {
      if (mounted.current && version === sessionVersion.current && !controller.signal.aborted) setSessionError(errorMessage(error))
    } finally { if (mounted.current && version === sessionVersion.current) setSessionLoading(false) }
  }

  function clearEditor() {
    setEditor(null); setDraft(emptyBusinessCredentialDraft()); setEditorError(null); setShowValidation(false); draftBaseline.current = ""
  }

  function openEditor(record: BusinessCredential | null, trigger?: HTMLButtonElement) {
    if (pending) return
    const next = record ? businessCredentialDraft(record) : emptyBusinessCredentialDraft()
    editorReturnFocus.current = trigger || createTrigger.current
    draftBaseline.current = JSON.stringify(next)
    setDraft(next); setEditor({ record }); setEditorError(null); setShowValidation(false)
    if (scope === "shared") void loadTargets()
  }

  function resetBinding() {
    const next = emptyBinding(); setBindingDraft(next); bindingBaseline.current = JSON.stringify(next)
  }

  function openBindings(record: BusinessCredential, trigger: HTMLButtonElement) {
    if (pending) return
    bindingReturnFocus.current = trigger
    bindingCredentialVersion.current = record.version
    setBindingCredentialId(record.id); resetBinding(); setBindingError(null); void loadTargets()
  }

  async function mutate(key: string, action: () => Promise<unknown>, success: string, setFailure: (value: string | null) => void = setActionError): Promise<boolean> {
    if (mutationLock.current) return false
    mutationLock.current = true; setMutation(key); setFailure(null); setMessage(null)
    let ok = false
    try { await action(); ok = true; if (mounted.current) setMessage(success) }
    catch (error) { if (mounted.current) setFailure(errorMessage(error)) }
    finally {
      if (mounted.current) await load()
      if (mounted.current && bindingCredentialId) await loadSessions(bindingCredentialId)
      mutationLock.current = false
      if (mounted.current) setMutation("")
    }
    return ok
  }

  async function saveCredential() {
    if (!editor || mutationLock.current || !secure) return
    setShowValidation(true)
    if (Object.keys(errors).length) { document.getElementById(`business-${Object.keys(errors)[0]}`)?.focus(); return }
    const original = editor.record
    const body = businessCredentialWrite(draft, original !== null, scope)
    const ok = await mutate("credential-save", () => original
      ? businessCredentialsApi.update(original.id, { ...body, expected_version: original.version })
      : businessCredentialsApi.create({ ...body, scope }), tx("业务凭据已保存；各节点需要分别同步。", "Business credential saved; synchronize each bound node separately."), setEditorError)
    if (ok && mounted.current) clearEditor()
  }

  async function toggleCredential(record: BusinessCredential) {
    if (mutationLock.current) return
    if (record.enabled && !(await confirm({ title: tx("停用业务凭据？", "Disable this business credential?"),
      description: `${record.name} — ${tx("阻止后续受控使用；节点密码与已经登录的网站会话仍需分别处理。", "Blocks subsequent managed use. Node passwords and existing website sessions require separate actions.")}`, destructive: true }))) return
    await mutate(`credential-${record.id}`, () => businessCredentialsApi.update(record.id, {
      ...businessCredentialWrite(businessCredentialDraft(record), true, scope), enabled: !record.enabled, expected_version: record.version,
    }), tx("凭据状态已更新。", "Credential state updated."))
  }

  async function removeCredential(record: BusinessCredential) {
    if (mutationLock.current || !(await confirm({ title: tx("删除业务凭据记录？", "Delete this business credential record?"),
      description: `${record.name} — ${tx("请先删除各节点保存的密码，并关闭受管浏览器会话。存在待清理副本或会话时服务端会阻止删除；删除记录不保证网站登录态已撤销。", "Delete saved node passwords and close managed browser sessions first. Remaining copies or sessions block record deletion. Record deletion does not verify website session revocation.")}`, destructive: true }))) return
    await mutate(`credential-${record.id}`, () => businessCredentialsApi.delete(record.id, record.version), tx("业务凭据记录已删除。", "Business credential record deleted."))
  }

  async function saveBinding() {
    if (!selectedCredential || mutationLock.current) return
    if (bindingDraft.id && !editingBinding) { setBindingError(tx("该绑定已不存在，请关闭并刷新后重新选择。", "This binding no longer exists. Close, refresh, and select it again.")); return }
    if (!bindingDraft.server_id) { setBindingError(tx("请选择一个 MCP 实例。", "Choose an MCP instance.")); return }
    const target = targets?.servers.find(server => server.server_id === bindingDraft.server_id)
    if (!editingBinding && !target?.compatible) { setBindingError(tx("该实例尚未满足绑定条件，请刷新目标列表。", "This instance does not meet binding requirements. Refresh the target list.")); return }
    if (!editingBinding && !bindingPrefixes.includes(bindingDraft.tool_prefix)) { setBindingError(tx("请明确选择该实例支持的工具契约。", "Explicitly choose a tool contract supported by this instance.")); return }
    if (!editingBinding && !(await confirm({ title: tx("授权此 MCP 实例使用凭据？", "Authorize this MCP instance to use the credential?"),
      description: `${selectedCredential.name} → ${target?.name || bindingDraft.server_id}. ${managedNotice()}`,
      confirmText: tx("确认绑定", "Confirm binding") }))) return
    const record = selectedCredential
    const body = { server_id: bindingDraft.server_id, adapter: "agent_browser" as const, tool_prefix: bindingDraft.tool_prefix,
      enabled: bindingDraft.enabled, expected_version: bindingCredentialVersion.current,
      ...(editingBinding ? { expected_revision: bindingRevision.current } : { confirm_managed_mode: true as const }) }
    const ok = await mutate("binding-save", () => editingBinding
      ? businessCredentialsApi.updateBinding(record.id, editingBinding.id, body)
      : businessCredentialsApi.createBinding(record.id, body), tx("绑定已保存，尚未下发密码。", "Binding saved. Password synchronization is a separate action."), setBindingError)
    if (ok && mounted.current) resetBinding()
  }

  async function bindingAction(record: BusinessCredential, binding: BusinessCredentialBinding, action: "sync" | "deleteRemote" | "delete" | "toggle") {
    if (mutationLock.current) return
    if (action === "deleteRemote" || action === "delete") {
      const remote = action === "deleteRemote"
      if (!(await confirm({ title: remote ? tx("删除节点保存的密码？", "Delete the password saved on this node?") : tx("移除绑定记录？", "Remove this binding record?"),
        description: `${record.name} → ${binding.server_id}. ${remote
          ? tx("仅删除节点密码库中的这条记录；已经登录的网站会话不会退出。", "Only deletes this node vault entry. Existing website sessions stay signed in.")
          : tx("必须先清理节点密码副本。移除绑定不会关闭浏览器或撤销网站会话。", "Clean up the node password copy first. Removing this binding does not close the browser or revoke website sessions.")}`, destructive: true }))) return
    }
    const call = action === "sync" ? () => businessCredentialsApi.sync(record.id, binding.id, record.version, binding.revision)
      : action === "deleteRemote" ? () => businessCredentialsApi.deleteRemote(record.id, binding.id, record.version, binding.revision)
      : action === "delete" ? () => businessCredentialsApi.deleteBinding(record.id, binding.id, binding.revision)
      : () => businessCredentialsApi.updateBinding(record.id, binding.id, { server_id: binding.server_id, adapter: binding.adapter,
        tool_prefix: binding.tool_prefix, enabled: !binding.enabled, expected_version: record.version, expected_revision: binding.revision })
    await mutate(`binding-${binding.id}`, call, tx("操作已返回，请查看该节点的最新状态。", "Operation returned. Review the node's refreshed state."), setBindingError)
  }

  async function copyPrompt(record: BusinessCredential) {
    const value = businessCredentialPrompt(record)
    try { await navigator.clipboard.writeText(value); setMessage(tx("已复制凭据引用和独立会话示例，不含账号密码。", "Copied the credential reference and isolated session example; no username or password.")) }
    catch { setCopyFallback(value) }
  }

  async function editBinding(record: BusinessCredential, binding: BusinessCredentialBinding) {
    if (pending || bindingDirty && !(await confirm({ title: tx("放弃尚未保存的绑定修改？", "Discard unsaved binding edits?"),
      description: tx("当前绑定表单的输入将被替换。", "The current binding form input will be replaced."), destructive: true }))) return
    const next = { id: binding.id, server_id: binding.server_id, tool_prefix: binding.tool_prefix, enabled: binding.enabled }
    bindingBaseline.current = JSON.stringify(next); bindingRevision.current = binding.revision; bindingCredentialVersion.current = record.version
    setBindingDraft(next); setBindingError(null)
  }

  async function closeSession(record: BusinessCredential, session: BusinessCredentialSession) {
    if (mutationLock.current || !(await confirm({ title: tx("关闭受管浏览器会话？", "Close this managed browser session?"),
      description: `${session.server_id} / ${session.logical_session}. ${tx("仅关闭 Gate 管理的浏览器会话，不保证网站服务端登录态已经撤销。", "Only closes the browser session managed by Gate. It does not verify that the website has revoked its server-side login session.")}`, destructive: true }))) return
    await mutate(`session-${session.id}`, () => businessCredentialsApi.closeSession(record.id, session.id),
      tx("浏览器会话已关闭；网站退出状态未验证。", "Browser session closed; website sign-out was not verified."), setBindingError)
  }

  function managedNotice() { return tx("此实例将使用受管浏览器模式：每次调用必须指定 session，密码库直读和可跨会话、导出秘密的工具会被限制。建议使用专用 MCP 实例。", "This instance uses managed browser mode: every call needs an explicit session; direct vault access and tools that cross sessions or export secrets are restricted. Use a dedicated MCP instance.") }
  function fieldError(key: string) {
    if (!showValidation || !errors[key]) return null
    return <span id={`business-${key}-error`} className="text-xs text-destructive">{errors[key] === "required" ? t("required")
      : errors[key] === "http" ? tx("使用 HTTP 需要显式开启下方允许项。", "Explicitly allow HTTP below before using an HTTP site.")
      : errors[key] === "mask" ? tx("请填写真实的新值，不能提交掩码。", "Enter a replacement value; do not submit a mask.")
      : tx("请填写完整 HTTP(S) 地址，不含账号、密码或查询参数；允许 #/login 这类页面路径。", "Enter an absolute HTTP(S) URL without user info or query parameters. A route fragment such as #/login is allowed.")}</span>
  }
  function input(key: "name" | "environment" | "business_role" | "login_url" | "username" | "password", label: string, help?: string) {
    const secret = key === "password" || key === "username"
    return <BusinessField id={`business-${key}`} label={label} help={help} zh={zh}>
      <Input id={`business-${key}`} type={key === "password" ? "password" : "text"} value={draft[key]} disabled={pending || secret && !secure}
        maxLength={key === "password" ? 16384 : key === "login_url" ? 2048 : key === "username" ? 1024 : key === "name" ? 120 : 80}
        autoComplete={key === "password" ? "new-password" : key === "username" ? "off" : undefined}
        aria-invalid={showValidation && Boolean(errors[key]) || undefined} aria-describedby={showValidation && errors[key] ? `business-${key}-error` : undefined}
        aria-required={secret ? !editor?.record : key === "name" || key === "login_url"}
        placeholder={secret && editor?.record ? tx("留空保持现有值", "Leave empty to keep current value") : key === "login_url" ? "https://app.example.test/login" : undefined}
        onChange={event => setDraft(current => ({ ...current, [key]: event.target.value }))} />{fieldError(key)}
    </BusinessField>
  }
  const syncLabel = (binding: BusinessCredentialBinding, version: number) => {
    if (binding.sync_status === "synced" && binding.synced_version !== version) return tx("版本待更新", "Update pending")
    return ({ pending: tx("待同步", "Pending"), synced: tx("已同步", "Synchronized"), failed: tx("同步失败", "Failed"),
      unknown: tx("结果待核对", "Outcome unconfirmed"), deleted: tx("节点密码已删除", "Node password deleted") })[binding.sync_status]
  }

  return <div className="business-credentials-panel flex min-w-0 flex-col gap-4">
    <PageHeader title={scope === "shared" ? tx("共享业务账号", "Shared business accounts") : tx("我的业务账号", "My business accounts")}
      description={tx("录入一次业务账号，明确授权可使用的 MCP 实例。模型只使用凭据引用；密码只在后端受控派发时解密。", "Save a business account once and authorize specific MCP instances. Agents use references; the backend resolves passwords only for controlled dispatch.")}
      helpLabel={t("pageHelp")} closeLabel={t("close")} helpContent={<><p>{managedNotice()}</p><p>{tx("停用 Gate 凭据、删除节点密码、退出网站登录态是三件不同的事。同步成功只表示节点保存了该版本，登录动作执行也不等于业务认证已经成功。", "Disabling a Gate credential, deleting a node password, and signing out of a website are separate actions. Synchronization confirms a saved version; an executed login action does not verify website authentication.")}</p></>}
      toolbar={<PageToolbar query={query} onQueryChange={setQuery} placeholder={tx("搜索名称、环境、角色、登录地址", "Search name, environment, role, or login URL")} resultCount={filtered.length}
        resultLabel={tx("项业务账号", "business accounts")} clearLabel={t("clearSearch")}
        resetFilters={{ label: t("resetFilters"), disabled: !query && statusFilter === "all", onReset: () => { setQuery(""); setStatusFilter("all") } }}>
        <FilterRadio label={tx("状态", "State")} value={statusFilter} onChange={setStatusFilter} options={[{ value: "all", label: t("all") }, { value: "enabled", label: tx("启用", "Enabled") }, { value: "disabled", label: tx("停用", "Disabled") }]} />
      </PageToolbar>}
      actions={<Button ref={createTrigger} disabled={pending} onClick={() => openEditor(null)}><Plus aria-hidden />{tx("新增业务账号", "New business account")}</Button>} />
    {!secure && <Alert variant="destructive"><AlertDescription>{tx("当前控制台不是 HTTPS 或本机地址，账号密码提交已禁用。", "Username and password submission requires HTTPS or a loopback console address.")}</AlertDescription></Alert>}
    {listError && <Alert variant="destructive" role="alert"><AlertDescription>{listError}</AlertDescription><Button variant="outline" size="sm" disabled={loading || pending} onClick={() => void load()}>{t("refresh")}</Button></Alert>}
    {actionError && <Alert variant="destructive" role="alert"><AlertDescription>{actionError}</AlertDescription></Alert>}
    <Card><CardContent className="p-0"><RemainingList><ListViewport viewport={paging.viewport} label={t("toolShowing")}>
      <Table className="business-credentials-table"><TableHeader><TableRow>
        <TableHead>{tx("业务账号", "Business account")}</TableHead><TableHead>{tx("环境 / 角色", "Environment / role")}</TableHead>
        <TableHead>{tx("账号 / 版本", "Username / version")}</TableHead><TableHead>{tx("授权节点", "Authorized nodes")}</TableHead>
        <TableHead>{tx("状态", "State")}</TableHead><TableHead>{t("actions")}</TableHead>
      </TableRow></TableHeader><TableBody>
        {!filtered.length ? <TableEmptyRow colSpan={6} title={loading ? t("loadingData") : listError ? t("error") : query || statusFilter !== "all" ? t("noMatchingRecords") : tx("还没有业务账号，可通过“新增业务账号”录入。", "No business accounts yet. Choose New business account to add one.")} /> : paging.items.map(record => <TableRow key={record.id}>
          <TableCell><button type="button" className="text-left font-medium text-primary hover:underline" onClick={event => openBindings(record, event.currentTarget)} disabled={pending}>{record.name}</button><div className="business-credential-url">{record.login_url}</div></TableCell>
          <TableCell><div>{record.environment || "—"}</div><div className="text-xs text-muted-foreground">{record.business_role || "—"}</div></TableCell>
          <TableCell><code>{record.username_masked}</code><div className="text-xs text-muted-foreground">{tx("当前版本", "Current version")} v{record.version}</div></TableCell>
          <TableCell><Button size="sm" variant="ghost" disabled={pending} onClick={event => openBindings(record, event.currentTarget)}>{record.bindings.length} {tx("个节点", "nodes")}</Button><div className="text-xs text-muted-foreground">{record.bindings.filter(binding => binding.sync_status === "synced" && binding.synced_version === record.version).length} {tx("个版本一致", "up to date")}</div></TableCell>
          <TableCell><Badge variant={record.enabled ? "success" : "secondary"}>{record.enabled ? tx("启用", "Enabled") : tx("停用", "Disabled")}</Badge></TableCell>
          <TableCell><ActionMenu inline label={t("actions")}><ActionMenuItem disabled={pending} onClick={event => openEditor(record, event.currentTarget)}>{t("edit")}</ActionMenuItem>
            <ActionMenuItem disabled={pending} onClick={event => openBindings(record, event.currentTarget)}>{tx("管理节点", "Manage nodes")}</ActionMenuItem>
            <ActionMenuItem onClick={() => void copyPrompt(record)}>{tx("复制引用", "Copy reference")}</ActionMenuItem>
            <ActionMenuItem disabled={pending} onClick={() => void toggleCredential(record)}>{record.enabled ? tx("停用", "Disable") : tx("启用", "Enable")}</ActionMenuItem>
            <ActionMenuItem destructive disabled={pending} onClick={() => void removeCredential(record)}>{t("delete")}</ActionMenuItem>
          </ActionMenu></TableCell>
        </TableRow>)}
      </TableBody></Table>
    </ListViewport><ListPagination paging={paging} t={t} /></RemainingList></CardContent></Card>
    <FormDialog open={editor !== null} onClose={() => void closeEditor()} dirty={dirty} pending={pending} closeLabel={t("close")}
      title={editor?.record ? tx("编辑业务账号", "Edit business account") : tx("新增业务账号", "New business account")}
      description={scope === "shared" ? tx("共享凭据仅允许明确选择的用户、角色和绑定实例使用。", "Shared credentials may be used only by explicitly selected users, roles, and bound instances.") : tx("个人凭据归当前 Gate 用户所有，保存后不会返回明文。", "Personal credentials belong to the current Gate user. Saved secrets are never returned.")}
      error={editorError} className="business-credential-editor"
      onCloseAutoFocus={event => { event.preventDefault(); (editorReturnFocus.current?.isConnected ? editorReturnFocus.current : createTrigger.current)?.focus() }}
      footer={<><Button variant="outline" disabled={pending} onClick={() => void closeEditor()}>{t("cancel")}</Button><Button form="business-credential-form" type="submit" disabled={pending || !secure}><KeyRound aria-hidden />{pending ? tx("保存中…", "Saving…") : t("save")}</Button></>}>
      <form id="business-credential-form" onSubmit={event => { event.preventDefault(); void saveCredential() }} className="business-credential-form">
        {input("name", tx("凭据名称", "Credential name"))}
        <BusinessField id="business-enabled" label={tx("启用", "Enabled")} help={tx("停用立即阻止后续受控使用，不自动删除节点密码或退出网站。", "Disabling blocks subsequent managed use; node passwords and website sessions require separate cleanup.")} zh={zh}><Switch id="business-enabled" checked={draft.enabled} disabled={pending} onChange={enabled => setDraft(current => ({ ...current, enabled }))} /></BusinessField>
        {input("environment", tx("环境", "Environment"), tx("可选分类，例如测试或生产。", "Optional classification, such as test or production."))}{input("business_role", tx("业务角色", "Business role"), tx("可选分类，用于区分医生、护士、管理员等业务账号，不等于 Gate 的授权角色。", "Optional classification for accounts such as doctor, nurse, or administrator; this is separate from Gate authorization roles."))}
        <div className="business-full-row">{input("login_url", tx("登录地址", "Login URL"), tx("密码仅用于此固定登录地址，不允许模型覆盖目标站点。不要在地址中加入账号密码或查询参数。", "Credentials are used for this fixed login URL. Agents cannot override the destination. Do not include credentials or query parameters."))}</div>
        {input("username", tx("账号", "Username"), editor?.record ? tx("留空保留原账号，页面只回读掩码。", "Leave empty to keep the username; the page reads only a mask.") : undefined)}
        {input("password", tx("密码", "Password"), editor?.record ? tx("留空保留原密码；更改后各节点将显示待同步。", "Leave empty to keep the password. Replacing it makes bound nodes pending synchronization.") : tx("只通过安全连接提交，不写入浏览器存储，也不进入模型请求。", "Submitted over a secure connection; never persisted in browser storage or sent to a model."))}
        <div className="business-full-row"><BusinessField id="business-allow-http" label={tx("允许 HTTP 站点", "Allow HTTP site")} help={tx("仅用于受信内网或本机测试站点。HTTP 登录可能明文传输业务账号密码；这不会放宽控制台提交密码的 HTTPS 要求。", "For trusted private-network or loopback test sites. HTTP login can transmit business credentials in cleartext. This does not relax the console's HTTPS requirement.")} zh={zh}><Switch id="business-allow-http" checked={draft.allow_http} disabled={pending} onChange={allow_http => setDraft(current => ({ ...current, allow_http }))} /></BusinessField></div>
        {scope === "shared" && <section className="business-full-row business-form-section">
          <h3>{tx("允许使用的用户和角色", "Users and roles allowed to use this credential")}</h3>
          {targetError && <Alert variant="destructive" role="alert"><AlertDescription>{targetError}</AlertDescription><Button type="button" size="sm" variant="outline" disabled={targetLoading || pending} onClick={() => void loadTargets()}>{t("refresh")}</Button></Alert>}
          <BusinessField id="business-users" label={tx("Gate 用户", "Gate users")} zh={zh}><Select getPopupContainer={dialogPopupContainer} id="business-users" mode="multiple" showSearch optionFilterProp="label" loading={targetLoading} disabled={pending || targetLoading || !targets} value={draft.allowed_user_ids} onChange={allowed_user_ids => setDraft(current => ({ ...current, allowed_user_ids }))} options={(targets?.users || []).map(user => ({ value: user.id, label: user.label }))} /></BusinessField>
          <BusinessField id="business-roles" label={tx("Gate 角色", "Gate roles")} zh={zh}><Select getPopupContainer={dialogPopupContainer} id="business-roles" mode="multiple" showSearch optionFilterProp="label" loading={targetLoading} disabled={pending || targetLoading || !targets} value={draft.allowed_role_ids} onChange={allowed_role_ids => setDraft(current => ({ ...current, allowed_role_ids }))} options={(targets?.roles || []).map(role => ({ value: role.id, label: role.label }))} /></BusinessField>
          <p className="text-xs text-muted-foreground">{tx("留空不会授权所有人。使用者仍须拥有目标 MCP 工具权限。", "Empty lists do not grant access to everyone. Callers also need permission for the target MCP tools.")}</p>
        </section>}
        <details className="business-full-row business-form-section"><summary>{tx("登录表单选择器（可选）", "Login form selectors (optional)")}</summary>
          {(["username", "password", "submit"] as const).map(key => <BusinessField key={key} id={`business-selector-${key}`} label={key === "username" ? tx("账号控件", "Username field") : key === "password" ? tx("密码控件", "Password field") : tx("提交按钮", "Submit button")} zh={zh}><Input id={`business-selector-${key}`} maxLength={512} value={draft.selectors[key] || ""} disabled={pending} onChange={event => setDraft(current => ({ ...current, selectors: { ...current.selectors, [key]: event.target.value } }))} /></BusinessField>)}
        </details>
      </form>
    </FormDialog>

    <FormDialog open={bindingCredentialId !== null} onClose={() => void closeBindings()} dirty={bindingDirty} pending={pending} closeLabel={t("close")}
      title={`${tx("授权节点", "Authorized nodes")} · ${selectedCredential?.name || ""}`} description={managedNotice()} error={bindingError}
      className="business-binding-dialog" onCloseAutoFocus={event => { event.preventDefault(); bindingReturnFocus.current?.isConnected ? bindingReturnFocus.current.focus() : createTrigger.current?.focus() }}
      footer={<><Button variant="outline" disabled={pending} onClick={() => void closeBindings()}>{t("close")}</Button><Button type="submit" form="business-binding-form" disabled={pending || !selectedCredential || targetLoading || !targets}>{bindingDraft.id ? t("save") : tx("添加绑定", "Add binding")}</Button></>}>
      {selectedCredential ? <div className="flex min-w-0 flex-col gap-4">
        <div className="business-binding-summary"><span>{tx("当前凭据版本", "Current credential version")} <strong>v{selectedCredential.version}</strong></span><Button size="sm" variant="outline" onClick={() => void copyPrompt(selectedCredential)}><Copy aria-hidden />{tx("复制调用示例", "Copy call example")}</Button><Button size="sm" variant="ghost" disabled={pending || loading || sessionLoading} onClick={() => { void load(); void loadSessions(selectedCredential.id) }}><RefreshCw aria-hidden />{t("refresh")}</Button></div>
        <p className="text-xs text-muted-foreground">{tx("Agent 使用 auth_login 的 name=gate:凭据ID 和独立 session。节点同步状态不代表业务登录已验证。凭据或节点密码版本变化后，请关闭旧会话并重新登录。", "Agents pass name=gate:credentialID and an isolated session to auth_login. Node synchronization does not verify website sign-in. After a credential or node password version changes, close old sessions and sign in again.")}</p>
        <div className="business-binding-list"><Table><TableHeader><TableRow><TableHead>{tx("MCP 实例", "MCP instance")}</TableHead><TableHead>{tx("版本与同步结果", "Version and synchronization")}</TableHead><TableHead>{tx("最近同步", "Last sync")}</TableHead><TableHead>{t("actions")}</TableHead></TableRow></TableHeader><TableBody>
          {!selectedCredential.bindings.length ? <TableEmptyRow colSpan={4} title={tx("尚未绑定节点，密码未下发。", "No nodes are bound; the password has not been distributed.")} /> : selectedCredential.bindings.map(binding => <TableRow key={binding.id}>
            <TableCell><div className="font-medium">{targets?.servers.find(server => server.server_id === binding.server_id)?.name || binding.server_id}</div><code className="text-xs text-muted-foreground">{binding.server_id}</code><div className="text-xs">{binding.enabled ? tx("绑定启用", "Binding enabled") : tx("绑定停用", "Binding disabled")}</div></TableCell>
            <TableCell><Badge variant={binding.sync_status === "synced" && binding.synced_version === selectedCredential.version ? "success" : binding.sync_status === "failed" || binding.sync_status === "unknown" ? "warning" : "secondary"}>{syncLabel(binding, selectedCredential.version)}</Badge><div className="mt-1 text-xs">{tx("节点版本", "Node version")} {binding.synced_version == null ? "—" : `v${binding.synced_version}`} / {tx("目标", "Target")} v{selectedCredential.version}</div>{binding.last_error_code && <code className="text-xs text-destructive">{binding.last_error_code}</code>}</TableCell>
            <TableCell className="text-xs">{binding.last_sync_at ? formatDateTime(binding.last_sync_at) : "—"}</TableCell>
            <TableCell><div className="business-binding-actions"><Button variant="outline" size="sm" disabled={pending || !binding.enabled || !selectedCredential.enabled} onClick={() => void bindingAction(selectedCredential, binding, "sync")}>{mutation === `binding-${binding.id}` ? tx("处理中…", "Working…") : tx("同步密码", "Sync password")}</Button>
              <Dropdown trigger={["click"]} disabled={pending} getPopupContainer={dialogPopupContainer} menu={{ items: [
                { key: "edit", label: t("edit") }, { key: "copy", label: tx("复制调用示例", "Copy call example") },
                { key: "toggle", label: binding.enabled ? tx("停用绑定", "Disable binding") : tx("启用绑定", "Enable binding") },
                { key: "deleteRemote", label: tx("删除节点密码", "Delete node password"), danger: true },
                { key: "delete", label: tx("移除绑定记录", "Remove binding record"), danger: true },
              ], onClick: ({ key }) => { if (key === "edit") void editBinding(selectedCredential, binding); else if (key === "copy") void copyPrompt(selectedCredential); else void bindingAction(selectedCredential, binding, key as "toggle" | "deleteRemote" | "delete") } }}>
                <Button type="button" variant="outline" size="sm" disabled={pending}><MoreHorizontal aria-hidden />{t("actions")}</Button>
              </Dropdown></div></TableCell>
          </TableRow>)}
        </TableBody></Table></div>
        {sessionError && <Alert variant="destructive" role="alert"><AlertDescription>{sessionError}</AlertDescription><Button variant="outline" size="sm" disabled={sessionLoading || pending} onClick={() => void loadSessions(selectedCredential.id)}>{t("refresh")}</Button></Alert>}
        <details className="business-form-section">
          <summary>{tx("浏览器会话", "Browser sessions")} · {sessionLoading ? tx("读取中…", "Loading…") : sessions.length}</summary>
          {!sessions.length ? <p className="text-xs text-muted-foreground">{sessionError ? tx("会话状态未能读取。", "Session state could not be read.") : tx("当前没有可见的受管会话。", "No managed sessions are visible.")}</p> : <div className="business-binding-list"><Table><TableHeader><TableRow><TableHead>{tx("节点 / 会话", "Node / session")}</TableHead><TableHead>{tx("状态", "State")}</TableHead><TableHead>{tx("凭据版本", "Credential version")}</TableHead><TableHead>{t("actions")}</TableHead></TableRow></TableHeader><TableBody>{sessions.map(session => <TableRow key={session.id}>
            <TableCell><div>{session.server_id}</div><code>{session.logical_session}</code></TableCell><TableCell>{session.status === "active" ? tx("浏览器打开", "Browser open") : session.status === "unknown" ? tx("状态待核对", "State unconfirmed") : tx("已关闭", "Closed")}</TableCell><TableCell>v{session.credential_version}{session.status !== "closed" && session.credential_version !== selectedCredential.version && <div className="text-xs text-amber-700 dark:text-amber-400">{tx("凭据已更新，关闭后重新登录", "Credential updated; close and sign in again")}</div>}</TableCell><TableCell><Button size="sm" variant="outline" disabled={pending || session.status === "closed"} onClick={() => void closeSession(selectedCredential, session)}>{tx("关闭浏览器会话", "Close browser session")}</Button></TableCell>
          </TableRow>)}</TableBody></Table></div>}
        </details>
        <form id="business-binding-form" className="business-form-section" onSubmit={event => { event.preventDefault(); void saveBinding() }}>
          <div className="flex items-center justify-between gap-3"><h3>{bindingDraft.id ? tx("编辑绑定", "Edit binding") : tx("绑定一个 MCP 实例", "Bind an MCP instance")}</h3>{bindingDraft.id && <Button type="button" size="sm" variant="ghost" disabled={pending} onClick={async () => { if (!bindingDirty || await confirm({ title: tx("放弃绑定修改？", "Discard binding edits?"), description: tx("清除当前绑定表单中未保存的修改。", "Clears unsaved changes in the binding form."), destructive: true })) resetBinding() }}>{tx("取消编辑", "Cancel edit")}</Button>}</div>
          {targetError && <Alert variant="destructive" role="alert"><AlertDescription>{targetError}</AlertDescription><Button type="button" variant="outline" size="sm" disabled={pending || targetLoading} onClick={() => void loadTargets()}>{t("refresh")}</Button></Alert>}
          <BusinessField id="business-target" label={tx("MCP 实例", "MCP instance")} zh={zh}><Select getPopupContainer={dialogPopupContainer} id="business-target" showSearch optionFilterProp="label" value={bindingDraft.server_id || undefined} disabled={pending || Boolean(bindingDraft.id) || targetLoading || !targets} loading={targetLoading}
            onChange={server_id => setBindingDraft(current => ({ ...current, server_id }))} placeholder={tx("选择已授权的目标实例", "Choose an authorized target instance")}
            options={(targets?.servers || []).filter(server => bindingDraft.id || !selectedCredential.bindings.some(binding => binding.server_id === server.server_id)).map(server => ({ value: server.server_id, label: `${server.name} · ${server.server_id}${!server.compatible && server.reason ? ` · ${explainCode(server.reason) || server.reason}` : ""}`, disabled: !server.compatible }))} /></BusinessField>
          <BusinessField id="business-contract" label={tx("工具契约", "Tool contract")} help={tx("只显示该实例兼容的工具契约，请明确选择。保存时后端再次校验。原生需要启用 state 工具组。已保存绑定的实例与契约固定，变更时需清理旧绑定后新建。", "Choose explicitly from this instance's compatible tool contracts. The backend verifies it again on save. Native agent-browser requires the state tool group. Saved instance and contract pins are immutable; clean up the old binding before creating a replacement.")} zh={zh}><FilterRadio id="business-contract" hideLabel label={tx("工具契约", "Tool contract")} value={bindingDraft.tool_prefix || "short"} disabled={pending || Boolean(bindingDraft.id)} onChange={value => setBindingDraft(current => ({ ...current, tool_prefix: value === "short" ? "" : "agent_browser_" }))} options={bindingPrefixes.map(prefix => ({ value: prefix || "short", label: prefix ? "agent_browser_auth_*" : "auth_*" }))} /></BusinessField>
          <BusinessField id="business-binding-enabled" label={tx("启用绑定", "Enable binding")} zh={zh}><Switch id="business-binding-enabled" checked={bindingDraft.enabled} disabled={pending} onChange={enabled => setBindingDraft(current => ({ ...current, enabled }))} /></BusinessField>
          <p className="text-xs text-muted-foreground">{tx("保存绑定不会自动下发密码。每个节点使用独立同步结果；停用不会删除节点密码，也不会退出网站。", "Saving a binding does not send its password. Each node tracks its own synchronization; disabling does not delete node passwords or sign out of websites.")}</p>
        </form>
      </div> : <p role="status">{loading ? t("loadingData") : tx("该凭据记录已不可用，请关闭并刷新列表。", "This credential is no longer available. Close and refresh the list.")}</p>}
    </FormDialog>
    <Dialog open={copyFallback !== null} onOpenChange={open => { if (!open) setCopyFallback(null) }}><DialogContent closeLabel={t("close")}><DialogHeader><DialogTitle>{tx("凭据引用调用示例", "Credential reference example")}</DialogTitle><DialogDescription>{tx("剪贴板不可用，请手动复制。按目标实例选择 auth_login 工具，session 请改为本轮独立名称。", "Clipboard access is unavailable. Copy manually, choose the target auth_login tool, and replace session with an isolated name for this task.")}</DialogDescription></DialogHeader><DialogBody><pre className="whitespace-pre-wrap break-all rounded-md bg-muted p-4 text-sm">{copyFallback}</pre></DialogBody></DialogContent></Dialog>
    {confirmDialog}<Toaster toast={message ? { message, tone: "success" } : null} onClose={() => setMessage(null)} />
  </div>
}

function BusinessField({ id, label, help, zh, children }: { id: string; label: string; help?: ReactNode; zh: boolean; children: ReactNode }) {
  return <div className="business-field"><Label htmlFor={id} help={help} helpLabel={label} zh={zh}>{label}</Label><div className="business-field-control">{children}</div></div>
}

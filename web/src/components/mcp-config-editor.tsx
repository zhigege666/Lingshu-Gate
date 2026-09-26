import { useEffect, useMemo, useRef, useState, type ReactNode } from "react"
import { Modal, Popover } from "antd"
import { Braces, Code2, Globe, Heart, KeyRound, Plus, Save, Search, Server, ShieldCheck, Terminal, Trash2, X } from "lucide-react"
import { api, type Credential, type ManifestValidationResponse } from "@/api/client"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { ConfigField, ConfigHelp, ConfigValue } from "@/components/mcp-config-fields"
import { FORM_COPY } from "@/features/mcp-config/copy"
import { changeRuntimeMode, manifestFingerprint, PROTECTED_HEADERS, updateManifestPath } from "@/features/mcp-config/draft"
import { credentialRef, getRecord, parseManifest, precheckManifest, runtimeModeFromManifest, withoutUserCredentialValues, type RuntimeMode } from "@/features/mcp-config/model"
import type { Locale } from "@/i18n"
import { prettyJson } from "@/lib/utils"

type Props = {
  locale: Locale
  selectedConfigId: string
  value: string
  onChange: (value: string) => void
  onSave: (nextValue?: string) => void | Promise<void>
  onClose?: () => void
  busy: boolean
}
const sectionNames = [
  ["basic", "基本信息", "Basic information", Server],
  ["connection", "连接设置", "Connection", Globe],
  ["credentials", "认证与凭据", "Credentials", KeyRound],
  ["launch", "启动与环境", "Launch & environment", Terminal],
  ["recovery", "健康与恢复", "Health & recovery", Heart],
  ["permissions", "权限与目录", "Permissions & roots", ShieldCheck],
] as const
const selectClass = "h-9 w-full min-w-0 rounded-md border border-input bg-background px-3 text-sm"

export function McpConfigEditor({ locale, selectedConfigId, value, onChange, onSave, onClose, busy }: Props) {
  const zh = locale === "zh-CN"
  const t = (cn: string, en: string) => zh ? cn : en
  const copy = FORM_COPY[locale]
  const initialValue = useRef(value)
  const scrollRef = useRef<HTMLDivElement>(null)
  const savedScroll = useRef(0)
  const [jsonMode, setJsonMode] = useState(false)
  const [activeSection, setActiveSection] = useState("basic")
  const [query, setQuery] = useState("")
  const [modeOpen, setModeOpen] = useState(false)
  const pendingAnchor = useRef<string | null>(null)
  const [modeChoice, setModeChoice] = useState<Exclude<RuntimeMode, "advanced">>("external_http")
  const [credentials, setCredentials] = useState<Credential[]>([])
  const [credentialError, setCredentialError] = useState("")
  const [validation, setValidation] = useState<ManifestValidationResponse | null>(null)
  const [error, setError] = useState("")
  const [validating, setValidating] = useState(false)
  const locked = busy || validating
  // value 是表单和 JSON 的唯一草稿。JSON 无效时保留原文，禁止回退到旧表单保存。
  const parsed = useMemo(() => {
    try { return { manifest: parseManifest(value), error: "" } }
    catch (reason) { return { manifest: null, error: reason instanceof Error ? reason.message : String(reason) } }
  }, [value])
  const manifest = parsed.manifest
  const draft = manifest || {}
  const launch = getRecord(draft.launch)
  const transport = getRecord(draft.transport)
  const policy = getRecord(draft.restart_policy)
  const health = getRecord(policy.health_check)
  const mode = runtimeModeFromManifest(draft)
  const managed = launch.type === "managed_process"
  const container = launch.type === "managed_container"
  const external = launch.type === "external"
  const http = transport.type === "streamable_http"
  const dirty = manifestFingerprint(value) !== manifestFingerprint(initialValue.current)
  const precheck = manifest ? precheckManifest(manifest, key => copy[key]) : { errors: [parsed.error], warnings: [] }
  const headers = getRecord(transport.headers)
  const slots = Array.isArray(draft.user_credentials) ? draft.user_credentials.map(getRecord) : []
  const roots = Array.isArray(draft.roots) ? draft.roots.map(String) : []
  const modeLabel = mode === "external_http" ? t("外部 HTTP", "External HTTP") : mode === "managed_http" ? t("受管 HTTP", "Managed HTTP") : mode === "managed_stdio" ? t("受管 Stdio", "Managed Stdio") : container ? t("受管容器", "Managed container") : t("其他运行组合", "Other runtime")

  useEffect(() => {
    let cancelled = false
    void api.credentials().then(items => { if (!cancelled) setCredentials(items) }).catch(() => { if (!cancelled) setCredentialError(t("凭据列表加载失败，现有引用仍会保留。", "Could not load credentials; existing references are preserved.")) })
    return () => { cancelled = true }
  }, [])
  useEffect(() => { setValidation(null); setError("") }, [value])
  useEffect(() => {
    if (error && scrollRef.current) scrollRef.current.scrollTop = 0
  }, [error])
  useEffect(() => {
    if (!jsonMode && scrollRef.current) scrollRef.current.scrollTop = savedScroll.current
  }, [jsonMode])

  function update(path: string[], next: unknown) {
    if (manifest && !locked) onChange(prettyJson(updateManifestPath(manifest, path, next)))
  }
  function close() {
    if (locked) return
    if (!dirty) { onClose?.(); return }
    Modal.confirm({ title: t("放弃未保存的修改？", "Discard unsaved changes?"), okText: t("放弃修改", "Discard"), cancelText: t("继续编辑", "Keep editing"), onOk: onClose })
  }
  function switchView() {
    if (jsonMode && !manifest) { setError(t("请先修正 JSON 格式，再返回表单。", "Fix JSON before returning to the form.")); return }
    if (!jsonMode) savedScroll.current = scrollRef.current?.scrollTop || 0
    setJsonMode(!jsonMode)
  }
  function jump(id: string) {
    const pane = scrollRef.current
    const section = pane?.querySelector<HTMLElement>(`#config-${id}`)
    if (!pane || !section) return
    const previous = pane.scrollTop
    pendingAnchor.current = id
    pane.scrollTo({ top: pane.scrollTop + section.getBoundingClientRect().top - pane.getBoundingClientRect().top - 20, behavior: "auto" })
    if (pane.scrollTop === previous) pendingAnchor.current = null
    setActiveSection(id)
    section.focus({ preventScroll: true })
  }
  function trackScroll() {
    const pane = scrollRef.current
    if (!pane) return
    if (pendingAnchor.current) { setActiveSection(pendingAnchor.current); pendingAnchor.current = null; return }
    const top = pane.getBoundingClientRect().top + 72
    let current = "basic"
    pane.querySelectorAll<HTMLElement>("[data-config-section]").forEach(section => {
      if (section.getBoundingClientRect().top <= top) current = section.dataset.configSection || current
    })
    if (pane.scrollTop + pane.clientHeight >= pane.scrollHeight - 4) current = "permissions"
    setActiveSection(current)
  }
  function findField() {
    const needle = query.trim().toLowerCase()
    if (!needle) return
    const field = Array.from(scrollRef.current?.querySelectorAll<HTMLElement>("[data-config-field], [data-config-section]") || []).find(node => (node.dataset.configField || node.dataset.search || "").toLowerCase().includes(needle))
    if (!field || !scrollRef.current) { setError(t("没有找到匹配的配置项", "No matching setting")); return }
    setError("")
    let parent = field.parentElement
    while (parent && parent !== scrollRef.current) {
      if (parent instanceof HTMLDetailsElement) parent.open = true
      parent = parent.parentElement
    }
    scrollRef.current.scrollTo({ top: scrollRef.current.scrollTop + field.getBoundingClientRect().top - scrollRef.current.getBoundingClientRect().top - 24, behavior: "auto" })
    field.querySelector<HTMLElement>("input, select, button, textarea")?.focus({ preventScroll: true })
  }
  async function save() {
    if (!manifest || locked) return
    const invalid = scrollRef.current?.querySelector<HTMLInputElement>("input:invalid")
    if (!jsonMode && invalid) { invalid.reportValidity(); invalid.focus(); return }
    if (precheck.errors.length) { setError(precheck.errors.join("；")); return }
    setValidating(true); setError("")
    try {
      const result = await api.validateConfig(withoutUserCredentialValues(manifest), selectedConfigId || null)
      setValidation(result)
      if (result.summary.errors) { setError(t("配置校验未通过，请查看错误详情。", "Validation failed. Review the errors.")); return }
      await onSave(value)
      initialValue.current = value
    } catch (reason) { setError(reason instanceof Error ? reason.message : String(reason)) }
    finally { setValidating(false) }
  }
  function section(id: string, children: ReactNode) {
    const entry = sectionNames.find(item => item[0] === id)!
    const Icon = entry[3]
    return <section id={`config-${id}`} data-config-section={id} data-search={`${entry[1]} ${entry[2]}`} tabIndex={-1} className="scroll-mt-5 border-b border-border/70 py-5 first:pt-1 last:border-0 focus:outline-none">
      <h2 className="mb-4 flex items-center gap-3 text-lg font-semibold"><Icon className="size-5 text-primary" />{zh ? entry[1] : entry[2]}</h2>{children}
    </section>
  }
  function textField(label: string, path: string[], current: unknown, help?: string, placeholder?: string) {
    return <ConfigField label={label} help={help} search={path.join(".")}><Input value={String(current ?? "")} placeholder={placeholder} onChange={event => update(path, event.target.value)} /></ConfigField>
  }
  function numberField(label: string, path: string[], current: unknown, fallback: number, min: number, help?: string, step = 1) {
    return <ConfigField label={label} help={help} search={path.join(".")}><Input type="number" min={min} step={step} value={current === undefined ? fallback : String(current)} onChange={event => update(path, event.target.value === "" ? "" : Number(event.target.value))} /></ConfigField>
  }
  function toggle(label: string, path: string[], current: unknown, fallback = false, help?: string) {
    return <ConfigField label={label} help={help} search={path.join(".")}><Switch checked={Boolean(current ?? fallback)} onCheckedChange={next => update(path, next)} /></ConfigField>
  }
  function arrayField(label: string, path: string[], current: unknown, help?: string) {
    const items = Array.isArray(current) ? current : []
    return <div data-config-field={`${label} ${path.join(".")}`} className="space-y-2">
      <div className="flex items-center gap-1 text-sm font-medium">{label}{help && <ConfigHelp label={label}>{help}</ConfigHelp>}</div>
      {items.map((item, index) => <div key={index} className="flex gap-2"><Input aria-label={`${label} ${index + 1}`} value={String(item)} onChange={event => update(path, items.map((old, i) => i === index ? event.target.value : old))} /><Button type="button" variant="ghost" size="sm" aria-label={`${t("删除", "Remove")} ${label} ${index + 1}`} onClick={() => update(path, items.filter((_, i) => i !== index))}><Trash2 className="size-4" /></Button></div>)}
      <Button type="button" size="sm" variant="outline" onClick={() => update(path, [...items, ""])}><Plus className="mr-1 size-4" />{t("添加", "Add")} {label}</Button>
    </div>
  }

  return <div className="flex h-full min-h-0 flex-col bg-background text-foreground" onKeyDown={event => { if (event.key === "Escape" && !event.defaultPrevented) { event.stopPropagation(); close() } }}>
    <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b px-5 py-3">
      <div className="flex min-w-0 items-center gap-3"><Code2 className="size-8 rounded-md bg-primary/10 p-1 text-primary" /><h1 className="truncate text-lg font-semibold">{selectedConfigId ? `${selectedConfigId} ${t("配置", "configuration")}` : t("新建 MCP 配置", "New MCP configuration")}</h1>{dirty && <span className="rounded border border-amber-500/30 px-2 py-0.5 text-xs text-amber-700 dark:text-amber-400">{t("未保存", "Unsaved")}</span>}</div>
      <div className="flex items-center gap-2"><span className="hidden rounded border border-primary/20 px-3 py-1.5 text-sm text-primary sm:inline-flex">{modeLabel}</span><ConfigHelp label={t("运行方式", "Runtime mode")}>{external ? copy.externalManagedHint : copy.runtimeModeDesc}</ConfigHelp>
        <Popover trigger="click" open={modeOpen} onOpenChange={setModeOpen} content={<div className="max-w-sm space-y-3"><p className="text-sm">{t("切换会移除不兼容的启动字段；保存前请核对配置。", "Switching removes incompatible launch fields. Review before saving.")}</p><select aria-label={t("运行方式", "Runtime mode")} className={selectClass} value={modeChoice} onChange={event => setModeChoice(event.target.value as typeof modeChoice)}><option value="external_http">{copy.externalHttp}</option><option value="managed_http">{copy.managedHttp}</option><option value="managed_stdio">{copy.managedStdio}</option></select><Button size="sm" disabled={locked || !manifest} onClick={() => { if (manifest) onChange(prettyJson(changeRuntimeMode(manifest, modeChoice))); setModeOpen(false) }}>{t("更改运行方式", "Change runtime mode")}</Button></div>}><Button size="sm" variant="outline" disabled={locked || !manifest}>{t("更改运行方式", "Change runtime mode")}</Button></Popover>
        <Button size="sm" variant="outline" onClick={switchView} disabled={locked}><Braces className="mr-1 size-4" />{jsonMode ? t("返回表单", "Back to form") : "JSON"}</Button><Button size="sm" variant="ghost" aria-label={t("关闭配置编辑器", "Close configuration editor")} onClick={close} disabled={locked}><X className="size-5" /></Button>
      </div>
    </header>
    <div className="flex min-h-0 flex-1">
      {!jsonMode && <aside className="flex w-44 shrink-0 flex-col border-r bg-muted/10 p-3 md:w-56">
        <form className="relative mb-4" onSubmit={event => { event.preventDefault(); findField() }}><Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-muted-foreground" /><Input aria-label={t("搜索配置项", "Search settings")} placeholder={t("搜索配置项…", "Search settings…")} value={query} onChange={event => setQuery(event.target.value)} className="pl-8" /><button type="submit" className="sr-only">{t("搜索", "Search")}</button></form>
        <nav aria-label={t("配置目录", "Configuration sections")} className="space-y-1 overflow-y-auto">{sectionNames.map(([id, cn, en, Icon]) => <button type="button" key={id} aria-current={activeSection === id ? "location" : undefined} onClick={() => jump(id)} className={`flex w-full items-center gap-3 rounded-md border-l-2 px-3 py-3 text-left text-sm ${activeSection === id ? "border-primary bg-primary/10 font-medium text-primary" : "border-transparent hover:bg-muted"}`}><Icon className="size-5 shrink-0" />{zh ? cn : en}</button>)}</nav>
      </aside>}
      <div ref={scrollRef} onScroll={jsonMode ? undefined : trackScroll} className="relative min-w-0 flex-1 overflow-y-auto px-5 py-4 md:px-7" data-testid="config-scroll-pane">
        {(error || parsed.error) && <div role="alert" className="mb-3 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">{error || parsed.error}</div>}
        {precheck.errors.length > 0 && !error && !parsed.error && <div role="alert" className="mb-3 rounded-md border border-destructive/30 p-3 text-sm text-destructive">{precheck.errors.join("；")}</div>}
        {validation && validation.summary.errors > 0 && <ul className="mb-3 list-inside list-disc text-sm text-destructive">{validation.checks.filter(check => check.severity === "error").map(check => <li key={`${check.name}-${check.message}`}>{check.message}</li>)}</ul>}
        {jsonMode ? <div className="flex h-full min-h-96 flex-col gap-3"><div className="flex items-center justify-between"><h2 className="font-semibold">{t("完整配置 JSON", "Full configuration JSON")}</h2><Button size="sm" variant="outline" disabled={!manifest || locked} onClick={() => { if (manifest) onChange(prettyJson(manifest)) }}>{t("格式化", "Format")}</Button></div><Textarea aria-label={t("配置 JSON", "Configuration JSON")} spellCheck={false} readOnly={locked} value={value} onChange={event => onChange(event.target.value)} className="min-h-80 flex-1 resize-none font-mono text-sm" /></div> : manifest ? <fieldset disabled={locked} className="min-w-0">
          {section("basic", <div className="grid items-end gap-4 sm:grid-cols-2 xl:grid-cols-[1fr_1.3fr_140px]">
            {textField(copy.serverId, ["id"], draft.id, copy.serverIdDesc)}{textField(copy.name, ["name"], draft.name)}{toggle(t("启用", "Enabled"), ["enabled"], draft.enabled, true)}
          </div>)}
          {section("connection", <div className="grid gap-4 sm:grid-cols-2">
            {http && <div className="sm:col-span-2">{textField(copy.endpoint, ["transport", "endpoint"], transport.endpoint, copy.endpointDesc, "https://graph.example.com/mcp")}</div>}
            {numberField(t("请求超时（秒）", "Request timeout (seconds)"), ["timeout_seconds"], draft.timeout_seconds, 30, 1, copy.timeoutSecondsDesc)}
            <ConfigField label={t("MCP 协议版本", "MCP protocol version")} help={t("留空或 auto 使用自动协商；指定值由后端校验支持范围。", "Empty or auto negotiates the protocol. The backend validates explicit versions.")}><Input placeholder="auto" value={String(transport.protocol_version ?? "")} onChange={event => update(["transport", "protocol_version"], event.target.value || undefined)} /></ConfigField>
          </div>)}
          {section("credentials", <div className="space-y-4">
            {credentialError && <p role="status" className="text-sm text-amber-700 dark:text-amber-400">{credentialError}</p>}
            {http ? <StringMap label={t("HTTP 请求头", "HTTP headers")} value={headers} credentials={credentials} zh={zh} headers onChange={next => update(["transport", "headers"], next)} /> : <p className="text-sm text-muted-foreground">{t("Stdio 凭据通过下方环境变量引用。", "Stdio credentials are referenced through environment variables below.")}</p>}
            {external && http && <details className="rounded-md border p-3"><summary className="cursor-pointer text-sm font-medium">{t("用户凭据槽位", "Per-user credential slots")} ({slots.length})</summary><div className="mt-3 space-y-4">{slots.map((slot, index) => {
              const injection = getRecord(slot.injection)
              const edit = (key: string, next: unknown) => update(["user_credentials"], slots.map((old, i) => i === index ? { ...old, [key]: next } : old))
              return <div key={index} className="grid gap-3 border-b pb-4 sm:grid-cols-2 xl:grid-cols-3">{[['id', '槽位 ID', 'Slot ID'], ['name', '名称', 'Name'], ['description', '说明', 'Description']].map(([key, cn, en]) => <ConfigField key={key} label={`${t(cn, en)} ${index + 1}`}><Input value={String(slot[key] ?? "")} onChange={event => edit(key, event.target.value)} /></ConfigField>)}<ConfigField label={t("请求头名称", "Header name")}><Input value={String(injection.name ?? "")} onChange={event => edit("injection", { ...injection, type: "http_header", name: event.target.value })} /></ConfigField><ConfigField label={t("注入模板", "Injection template")}><Input value={String(injection.template ?? "{value}")} onChange={event => edit("injection", { ...injection, template: event.target.value })} /></ConfigField><div className="flex items-center justify-between"><ConfigField label={t("必填", "Required")}><Switch checked={Boolean(slot.required ?? true)} onCheckedChange={next => edit("required", next)} /></ConfigField><Button variant="ghost" size="sm" aria-label={`${t("删除槽位", "Remove slot")} ${index + 1}`} onClick={() => update(["user_credentials"], slots.filter((_, i) => i !== index))}><Trash2 className="size-4" /></Button></div></div>
            })}<Button size="sm" variant="outline" onClick={() => update(["user_credentials"], [...slots, { id: "", name: "", required: true, injection: { type: "http_header", name: "Authorization", template: "Bearer {value}" } }])}><Plus className="mr-1 size-4" />{t("添加槽位", "Add slot")}</Button></div></details>}
          </div>)}
          {section("launch", external ? <div className="flex items-center gap-2 text-sm text-muted-foreground">{t("外部 HTTP 模式不适用", "Not applicable to external HTTP")}<ConfigHelp label={t("启动与环境", "Launch & environment")}>{copy.externalManagedHint}</ConfigHelp></div> : <div className="space-y-4">
            {(managed || container) && toggle(copy.autoStart, ["auto_start"], draft.auto_start, false, copy.autoStartDesc)}
            {managed && <><div className="grid gap-4 sm:grid-cols-2">{textField(copy.command, ["launch", "command"], launch.command, copy.commandDesc)}{textField(copy.cwd, ["launch", "cwd"], launch.cwd, copy.cwdDesc)}</div>{arrayField(copy.args, ["launch", "args"], launch.args, copy.argsDesc)}<StringMap label={copy.env} value={getRecord(launch.env)} credentials={credentials} zh={zh} onChange={next => update(["launch", "env"], next)} />
              <details className="rounded-md border p-3"><summary className="cursor-pointer text-sm font-medium">{t("NPM 包配置", "NPM package")}</summary><div className="mt-3 space-y-3"><Button size="sm" variant="outline" onClick={() => update(["launch", "package"], launch.package ? undefined : { manager: "npm", name: "", cache: true })}>{launch.package ? t("移除包配置", "Remove package") : t("添加包配置", "Add package")}</Button>{launch.package ? <div className="grid gap-3 sm:grid-cols-2">{textField(t("包名称", "Package name"), ["launch", "package", "name"], getRecord(launch.package).name)}{textField(t("版本", "Version"), ["launch", "package", "version"], getRecord(launch.package).version)}{textField(t("可执行名称", "Binary"), ["launch", "package", "bin"], getRecord(launch.package).bin)}{toggle(t("缓存", "Cache"), ["launch", "package", "cache"], getRecord(launch.package).cache, true)}</div> : null}</div></details>
            </>}
            {container && <>{textField(t("镜像（固定摘要）", "Image (pinned digest)"), ["launch", "image"], launch.image)}<StringMap label={copy.env} value={getRecord(launch.environment)} credentials={credentials} zh={zh} onChange={next => update(["launch", "environment"], next)} /><div className="grid gap-3 sm:grid-cols-3">{textField(t("内存限制", "Memory limit"), ["launch", "resources", "memory"], getRecord(launch.resources).memory ?? "512m")}{numberField("CPU", ["launch", "resources", "cpus"], getRecord(launch.resources).cpus, 1, 0.1, undefined, 0.1)}{numberField(t("进程上限", "PID limit"), ["launch", "resources", "pids_limit"], getRecord(launch.resources).pids_limit, 128, 16)}</div><ConfigValue label="launch.mounts" value={launch.mounts ?? []} zh={zh} onChange={next => update(["launch", "mounts"], next)} /></>}
            {!managed && !container && <ConfigValue label="launch" value={launch} zh={zh} onChange={next => update(["launch"], next)} />}
          </div>)}
          {section("recovery", external ? <div className="flex items-center gap-2 text-sm text-muted-foreground">{t("会话过期时自动重新连接", "Automatically reconnect expired sessions")}<ConfigHelp label={t("健康与恢复", "Health & recovery")}>{t("请求发现会话过期时重连一次；仅已发布为只读且定义未变的工具会自动重试。失败后需手动重连；不定时探活或重启外部服务。", "An expired session triggers one reconnect. Only published read-only tools with unchanged definitions are retried. Reconnect manually if recovery fails; no periodic probe or external process restart.")}</ConfigHelp></div> : <div className="space-y-4">
            {toggle(copy.restartPolicy, ["restart_policy", "enabled"], policy.enabled, false, copy.restartPolicyDesc)}
            {Boolean(policy.enabled) && <><div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {numberField(copy.maxAttempts, ["restart_policy", "max_attempts"], policy.max_attempts, 3, 0, copy.maxAttemptsDesc)}{numberField(copy.delaySeconds, ["restart_policy", "delay_seconds"], policy.delay_seconds, 5, 0, copy.delaySecondsDesc)}{toggle(copy.restartOnExit, ["restart_policy", "restart_on_exit"], policy.restart_on_exit, true, copy.restartOnExitDesc)}
            </div><details className="rounded-md border p-3"><summary className="cursor-pointer text-sm">{t("高级重试设置", "Advanced retry settings")}</summary><div className="mt-3 grid gap-4 sm:grid-cols-2 xl:grid-cols-3">{numberField(copy.backoff, ["restart_policy", "backoff_multiplier"], policy.backoff_multiplier, 2, 1, copy.backoffDesc, 0.1)}{numberField(copy.maxDelay, ["restart_policy", "max_delay_seconds"], policy.max_delay_seconds, 60, 0, copy.maxDelayDesc)}{numberField(copy.resetAfterSeconds, ["restart_policy", "reset_after_seconds"], policy.reset_after_seconds, 300, 0, copy.resetAfterSecondsDesc)}{['exit_code_allowlist', 'exit_code_blocklist'].map(key => <div key={key}><span className="text-sm">{key === 'exit_code_allowlist' ? copy.exitAllowlist : copy.exitBlocklist}</span><ConfigValue label={key} value={policy[key] ?? []} zh={zh} onChange={next => update(["restart_policy", key], next)} /></div>)}</div></details>
              {toggle(copy.healthCheck, ["restart_policy", "health_check", "enabled"], health.enabled, false, copy.healthCheckDesc)}{Boolean(health.enabled) && <div className="grid gap-4 sm:grid-cols-3">{numberField(copy.intervalSeconds, ["restart_policy", "health_check", "interval_seconds"], health.interval_seconds, 30, 1, copy.intervalSecondsDesc)}{numberField(copy.healthTimeoutSeconds, ["restart_policy", "health_check", "timeout_seconds"], health.timeout_seconds, 10, 1, copy.healthTimeoutSecondsDesc)}{numberField(copy.failureThreshold, ["restart_policy", "health_check", "failure_threshold"], health.failure_threshold, 3, 1, copy.failureThresholdDesc)}</div>}
            </>}
          </div>)}
          {section("permissions", <div className="space-y-4">{arrayField(t("根目录", "Roots"), ["roots"], roots, t("传递给下游的 MCP 根目录声明，不代表授予文件系统权限。", "MCP root declarations sent downstream; these do not grant filesystem access."))}{['permissions', 'analysis'].map(key => <details key={key} className="rounded-md border p-3"><summary className="cursor-pointer text-sm font-medium">{key === 'permissions' ? t("权限声明", "Permission declarations") : t("分析元数据", "Analysis metadata")}</summary><div className="mt-3"><ConfigValue label={key} value={draft[key] ?? {}} zh={zh} onChange={next => update([key], next)} /></div></details>)}</div>)}
        </fieldset> : <Button variant="outline" onClick={() => setJsonMode(true)}>{t("打开 JSON 修正配置", "Fix configuration in JSON")}</Button>}
      </div>
    </div>
    <footer className="flex shrink-0 items-center justify-between gap-3 border-t bg-background px-5 py-3">
      <div className="flex items-center gap-2 text-sm"><span className={`size-2 rounded-full ${dirty ? "bg-amber-500" : "bg-muted-foreground"}`} /><span>{dirty ? t("未保存", "Unsaved") : t("无未保存修改", "No unsaved changes")}<span className="hidden sm:inline"> · {t("保存后需应用", "Apply after saving")}</span></span><ConfigHelp label={t("保存与应用", "Save and apply")}>{t("保存只更新配置文件。应用配置和连接或启动服务是独立操作。", "Saving updates the configuration file only. Applying and connecting or starting are separate actions.")}</ConfigHelp></div>
      <div className="flex items-center gap-2"><Button variant="outline" onClick={close} disabled={locked}>{t("取消", "Cancel")}</Button><Button onClick={() => void save()} disabled={locked || !manifest}><Save className="mr-2 size-4" />{validating ? t("校验并保存中…", "Validating…") : t("保存配置", "Save configuration")}</Button></div>
    </footer>
  </div>
}

function StringMap({ label, value, onChange, credentials, zh, headers = false }: { label: string; value: Record<string, unknown>; onChange: (next: Record<string, string>) => void; credentials: Credential[]; zh: boolean; headers?: boolean }) {
  const [newKey, setNewKey] = useState("")
  const [error, setError] = useState("")
  const entries = Object.entries(value)
  function edit(key: string, next: string) { onChange({ ...value, [key]: next } as Record<string, string>) }
  return <div data-config-field={`${label} ${headers ? 'transport.headers' : 'launch.env'}`} className="space-y-2">
    <div className="flex items-center gap-1 text-sm font-medium">{label}<ConfigHelp label={label}>{zh ? '敏感值使用凭据引用；不会在此读取凭据明文。可在值中组合 Bearer 等前缀。' : 'Use credential references for secrets. Values may include a Bearer prefix.'}</ConfigHelp></div>
    {entries.map(([key, raw], index) => {
      const text = String(raw ?? "")
      const ref = text.match(/\$\{credential:([a-zA-Z0-9_.-]+)\}/)?.[1]
      return <div key={index} className="grid items-center gap-2 rounded border border-border/60 p-2 sm:grid-cols-[minmax(100px,1fr)_minmax(0,2fr)_minmax(120px,1fr)_32px]">
        <Input aria-label={`${label} ${zh ? '名称' : 'name'} ${index + 1}`} className="font-mono" value={key} onChange={event => {
          const nextKey = event.target.value
          if (!nextKey.trim() || Object.keys(value).some(old => old !== key && (headers ? old.toLowerCase() === nextKey.toLowerCase() : old === nextKey)) || (headers && (PROTECTED_HEADERS.has(nextKey.toLowerCase()) || !/^[A-Za-z0-9-]+$/.test(nextKey)))) { setError(zh ? '名称无效、重复或属于系统保留请求头。' : 'Invalid, duplicate or reserved name.'); return }
          onChange(Object.fromEntries(entries.map(([old, item]) => [old === key ? nextKey : old, String(item)]))); setError("")
        }} /><Input aria-label={`${label} ${key}`} value={text} onChange={event => edit(key, event.target.value)} />
        <select aria-label={`${label} ${key} ${zh ? '凭据引用' : 'credential reference'}`} value={ref || ""} className={selectClass} onChange={event => { if (event.target.value) edit(key, ref ? text.replace(credentialRef(ref), credentialRef(event.target.value)) : credentialRef(event.target.value)) }}><option value="">{zh ? '插入凭据引用' : 'Insert credential'}</option>{ref && !credentials.some(item => item.id === ref) && <option value={ref}>{ref}</option>}{credentials.map(item => <option key={item.id} value={item.id}>{item.id}</option>)}</select>
        <Button variant="ghost" size="sm" aria-label={`${zh ? '删除' : 'Remove'} ${label} ${index + 1}`} onClick={() => { const next = { ...value }; delete next[key]; onChange(next as Record<string, string>) }}><Trash2 className="size-4" /></Button>
      </div>
    })}
    <div className="flex flex-wrap gap-2"><Input aria-label={`${label} ${zh ? '新名称' : 'new name'}`} className="max-w-72" value={newKey} placeholder={headers ? 'X-Client' : 'SERVICE_TOKEN'} onChange={event => { setNewKey(event.target.value); setError("") }} /><Button variant="outline" size="sm" onClick={() => {
      const key = newKey.trim()
      const duplicate = Object.keys(value).some(old => headers ? old.toLowerCase() === key.toLowerCase() : old === key)
      if (!key || duplicate || (headers && (PROTECTED_HEADERS.has(key.toLowerCase()) || !/^[A-Za-z0-9-]+$/.test(key)))) { setError(zh ? '名称为空、重复或属于系统保留请求头。' : 'Name is empty, duplicate, invalid or reserved.'); return }
      edit(key, ""); setNewKey(""); setError("")
    }}><Plus className="mr-1 size-4" />{zh ? '添加' : 'Add'}</Button></div>{error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </div>
}

import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react"
import { Braces, Plus, Save, ShieldCheck, Trash2 } from "lucide-react"
import { createPortal } from "react-dom"
import { api, type Credential, type ManifestValidationResponse } from "@/api/client"
import { ValidationErrors } from "@/components/validation-errors"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import {
  REDACTED_ENDPOINT, canKeepMaskedEndpoint, changeRuntimeMode, credentialRef, envKeyFromCredential,
  formatManifestJson, getRecord, isStringMap, parseManifest, patchManifestField,
  precheckManifest, runtimeModeFromManifest, withoutUserCredentialValues,
  manifestValidationIssues,
  type ManifestEditContext, type ManifestLike, type ManifestPrecheckMessageKey, type RuntimeMode,
} from "@/features/mcp-config/model"
import type { Locale } from "@/i18n"
import { JSON_SYNTAX_MESSAGE, type ValidationIssue } from "@/lib/validation"
import { prettyJson } from "@/lib/utils"
import "@/features/mcp-config/editor.css"

type McpConfigEditorProps = {
  locale: Locale
  selectedConfigId: string
  value: string
  onChange: (value: string) => void
  onSave: (nextValue?: string) => void | Promise<void>
  onClose?: () => void
  onPendingChange?: (pending: boolean) => void
  onDraftDirtyChange?: (dirty: boolean) => void
  backendPrecheck?: boolean
  loadCredentials?: boolean
  footerContainer?: HTMLElement | null
  busy: boolean
}

const FORM_COPY = {
  "zh-CN": {
    localErrors: "保存前本地预检查错误",
    serverId: "服务 ID",
    serverIdDesc: "MCP Server 的唯一标识，只能包含字母、数字、点、下划线和短横线。",
    name: "名称",
    runtimeMode: "运行方式",
    managedStdio: "受管 Stdio",
    externalHttp: "外部 HTTP",
    managedHttp: "受管 HTTP",
    advancedMode: "高级模式",
    endpoint: "MCP 地址",
    endpointDesc: "streamable_http 地址，例如 http://127.0.0.1:3120/mcp。",
    externalManagedHint: "该服务由外部进程管理，Lingshu Gate 只负责连接或断开，不负责启动、停止或自动重启。",
    command: "启动命令",
    commandDesc: "managed_process 要执行的已安装可执行文件或绝对路径。",
    cwd: "工作目录",
    cwdDesc: "可选。命令启动时的工作目录，例如 /workspace。",
    args: "启动参数",
    env: "环境变量",
    timeoutSeconds: "超时秒数",
    autoStart: "开机自启",
    autoStartDesc: "仅记录运行意图；保存与应用配置均不会直接启动服务。",
    restartPolicy: "崩溃重启策略",
    maxAttempts: "最大尝试次数",
    delaySeconds: "初始延迟",
    backoff: "退避倍数",
    maxDelay: "最大延迟",
    resetAfterSeconds: "重置计数",
    restartOnExit: "进程退出后重启",
    restartOnExitDesc: "开启后，非策略排除的退出会触发自动重启。",
    exitAllowlist: "退出码允许列表",
    exitBlocklist: "退出码阻止列表",
    healthCheck: "健康检查探活",
    healthCheckDesc: "当前通过 MCP tools/list 检查已连接服务是否健康。",
    intervalSeconds: "检查间隔",
    healthTimeoutSeconds: "检查超时",
    failureThreshold: "失败阈值",
    endpointRequired: "HTTP 运行方式需要填写 transport.endpoint",
    endpointInvalid: "MCP 地址必须是有效的 HTTP/HTTPS URL",
    formatJson: "格式化 JSON",
    backendPrecheck: "后端预检查",
    saveAndApply: "保存配置",
    rawJson: "Manifest JSON",
    rawJsonDesc: "表单修改自动同步到 JSON；未修改的字段和原有值会保留。",
    backendCheck: "后端预检查",
    notRecommended: "不建议应用",
    saveWithWarning: "可以保存，但建议确认警告",
    saveOk: "可以保存",
    errors: "错误",
    warnings: "警告",
    info: "信息",
    ok: "正常",
    idRequired: "id 不能为空",
    idPattern: "id 只能包含字母、数字、下划线、点和短横线",
    launchRequired: "launch 配置不能为空",
    transportRequired: "transport 配置不能为空",
    launchTypeRequired: "launch.type 不能为空",
    commandRequired: "managed_process 需要填写 launch.command",
    containerImageDigestError: "managed_container 镜像必须固定到小写 SHA-256 Digest",
    containerVolumesUnsupported: "不支持旧的 launch.volumes；请使用结构化只读 launch.mounts",
    containerMountsError: "launch.mounts 必须包含绝对 Source、非根且非受保护的绝对 Target，并且不能关闭 read_only；后端还会校验 Allowed Root",
    containerEnvironmentProtected: "managed_container Environment 不能覆盖 LINGSHU_GATE_* 或 Docker 进程控制",
    launchTypeWarning: "此运行方式的专有字段需在 Manifest JSON 中维护。",
    argsWarning: "launch.args 建议全部使用字符串",
    transportTypeRequired: "transport.type 不能为空",
    stdioLaunchError: "transport.type=stdio 要求 launch.type 为 managed_process 或 managed_container",
    streamableEndpointError: "streamable_http 需要填写 transport.endpoint",
    timeoutWarning: "timeout_seconds 建议设置为大于 0 的数字",
  },
  "en-US": {
    localErrors: "Local precheck errors before saving",
    serverId: "Server ID",
    serverIdDesc: "Unique MCP Server identifier. Use letters, numbers, dots, underscores, and hyphens only.",
    name: "Name",
    runtimeMode: "Runtime Mode",
    managedStdio: "Managed Stdio",
    externalHttp: "External HTTP",
    managedHttp: "Managed HTTP",
    advancedMode: "Advanced Mode",
    endpoint: "MCP Endpoint",
    endpointDesc: "Streamable HTTP endpoint, for example http://127.0.0.1:3120/mcp.",
    externalManagedHint: "This service is externally managed. Lingshu Gate only connects or disconnects and does not start, stop, or restart the process.",
    command: "Command",
    commandDesc: "Installed executable or absolute path used by managed_process.",
    cwd: "Working Directory",
    cwdDesc: "Optional command working directory, for example /workspace.",
    args: "Arguments",
    env: "Environment Variables",
    timeoutSeconds: "Timeout Seconds",
    autoStart: "Auto Start",
    autoStartDesc: "Records runtime intent only; saving or applying does not directly start the server.",
    restartPolicy: "Restart Policy",
    maxAttempts: "Max Attempts",
    delaySeconds: "Initial Delay",
    backoff: "Backoff Multiplier",
    maxDelay: "Max Delay",
    resetAfterSeconds: "Reset After",
    restartOnExit: "Restart On Exit",
    restartOnExitDesc: "Restart automatically when the exit code is not excluded by policy.",
    exitAllowlist: "Exit Code Allowlist",
    exitBlocklist: "Exit Code Blocklist",
    healthCheck: "Health Check",
    healthCheckDesc: "Uses MCP tools/list to check whether the connected service is healthy.",
    intervalSeconds: "Interval",
    healthTimeoutSeconds: "Timeout",
    failureThreshold: "Failure Threshold",
    endpointRequired: "HTTP runtime modes require transport.endpoint",
    endpointInvalid: "MCP endpoint must be a valid HTTP/HTTPS URL",
    formatJson: "Format JSON",
    backendPrecheck: "Backend Precheck",
    saveAndApply: "Save Config",
    rawJson: "Manifest JSON",
    rawJsonDesc: "Form edits sync to JSON automatically; untouched fields and values are preserved.",
    backendCheck: "Backend Precheck",
    notRecommended: "Not recommended to apply",
    saveWithWarning: "Can save, but review warnings first",
    saveOk: "Can save",
    errors: "Errors",
    warnings: "Warnings",
    info: "Info",
    ok: "OK",
    idRequired: "id is required",
    idPattern: "id may only contain letters, numbers, underscores, dots, and hyphens",
    launchRequired: "launch config is required",
    transportRequired: "transport config is required",
    launchTypeRequired: "launch.type is required",
    commandRequired: "managed_process requires launch.command",
    containerImageDigestError: "managed_container images must be pinned by a lowercase SHA-256 digest",
    containerVolumesUnsupported: "launch.volumes is not supported; use structured read-only launch.mounts",
    containerMountsError: "launch.mounts requires absolute sources, non-root absolute targets outside protected paths, and read_only cannot be disabled; the backend also enforces the allowed root",
    containerEnvironmentProtected: "managed_container environment cannot override LINGSHU_GATE_* or Docker process controls",
    launchTypeWarning: "Maintain fields specific to this runtime in Manifest JSON.",
    argsWarning: "launch.args should all be strings",
    transportTypeRequired: "transport.type is required",
    stdioLaunchError: "transport.type=stdio requires launch.type to be managed_process or managed_container",
    streamableEndpointError: "streamable_http requires transport.endpoint",
    timeoutWarning: "timeout_seconds should be greater than 0",
  },
} satisfies Record<Locale, Record<string, string>>

type CopyKey = keyof typeof FORM_COPY["zh-CN"]
type CopyFn = (key: CopyKey) => string

const PRECHECK_PATHS: Record<ManifestPrecheckMessageKey, string> = {
  idRequired: "/id", idPattern: "/id", launchRequired: "/launch", transportRequired: "/transport",
  launchTypeRequired: "/launch/type", commandRequired: "/launch/command",
  containerImageDigestError: "/launch/image", containerVolumesUnsupported: "/launch/volumes",
  containerMountsError: "/launch/mounts", containerEnvironmentProtected: "/launch/environment",
  launchTypeWarning: "/launch/type", argsWarning: "/launch/args", transportTypeRequired: "/transport/type",
  stdioLaunchError: "/transport/type", streamableEndpointError: "/transport/endpoint",
  endpointRequired: "/transport/endpoint", endpointInvalid: "/transport/endpoint", timeoutWarning: "/timeout_seconds",
}

function Field({ id, label, desc, error, children }: {
  id: string; label: string; desc?: string; error?: string; children: ReactNode
}) {
  return <div className="manifest-field">
    <Label htmlFor={id}>{label}</Label>
    {children}
    {desc && <p id={`${id}-help`} className="text-xs text-muted-foreground">{desc}</p>}
    {error && <p id={`${id}-error`} className="text-xs text-destructive">{error}</p>}
  </div>
}

function StringMapEditor({ value, label, disabled, onChange, zh, id, credentials = [], onDraftDirtyChange }: {
  value: Record<string, string>; label: string; disabled: boolean; onChange: (value: Record<string, string>) => void
  zh: boolean; id: string; credentials?: Credential[]; onDraftDirtyChange: (dirty: boolean) => void
}) {
  const [key, setKey] = useState("")
  const [entryValue, setEntryValue] = useState("")
  const [error, setError] = useState("")
  const reportDirty = useRef(onDraftDirtyChange)
  reportDirty.current = onDraftDirtyChange
  useEffect(() => { reportDirty.current(Boolean(key || entryValue)) }, [key, entryValue])
  useEffect(() => () => reportDirty.current(false), [])
  function add(nextKey = key, nextValue = entryValue) {
    if (!nextKey.trim()) { setError(zh ? "请填写键名。" : "Enter a key."); return }
    if (Object.prototype.hasOwnProperty.call(value, nextKey)) { setError(zh ? "键名已存在，请直接修改已有值。" : "This key already exists. Edit its value below."); return }
    onChange({ ...value, [nextKey]: nextValue })
    setKey(""); setEntryValue(""); setError("")
  }
  return <fieldset className="manifest-map" disabled={disabled}>
    <legend className="sr-only">{label}</legend>
    {Object.entries(value).map(([name, item], index) => <div className="manifest-map-row" key={name}>
      <label className="break-all font-mono text-xs" htmlFor={`${id}-${index}`}>{name || (zh ? "空键名" : "Empty key")}</label>
      <Input id={`${id}-${index}`} value={item} onChange={(event) => onChange({ ...value, [name]: event.target.value })} />
      <Button type="button" variant="ghost" size="sm" className="size-9 shrink-0 px-0" aria-label={`${zh ? "移除" : "Remove"} ${name}`} onClick={() => {
        const next = { ...value }; delete next[name]; onChange(next)
      }}><Trash2 className="size-4" /></Button>
    </div>)}
    <div className="manifest-map-row">
      <Input id={id} aria-label={`${label} ${zh ? "新键名" : "new key"}`} placeholder={zh ? "新键名" : "New key"} value={key} onChange={(event) => { setKey(event.target.value); setError("") }} />
      <Input aria-label={`${label} ${zh ? "新值" : "new value"}`} placeholder={zh ? "值（可为空）" : "Value (may be empty)"} value={entryValue} onChange={(event) => setEntryValue(event.target.value)} />
      <Button type="button" variant="outline" size="sm" className="size-9 shrink-0 px-0" aria-label={`${zh ? "添加" : "Add"} ${label}`} onClick={() => add()}><Plus className="size-4" /></Button>
    </div>
    {(key || entryValue) && <div className="flex items-center justify-between gap-2"><p className="text-xs text-muted-foreground">{zh ? "点击添加后写入配置；键名的空格和空值会原样保留。" : "Select Add to include this entry; spaces in keys and empty values are preserved."}</p><Button type="button" size="sm" variant="ghost" onClick={() => { setKey(""); setEntryValue(""); setError("") }}>{zh ? "清除待添加项" : "Clear pending entry"}</Button></div>}
    {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
    {credentials.length > 0 && <details>
      <summary className="text-xs cursor-pointer">{zh ? "插入凭据引用" : "Insert credential reference"}</summary>
      <div className="mt-2 flex flex-wrap gap-2">{credentials.map((item) => <Button key={item.id} type="button" variant="outline" size="sm" onClick={() => add(envKeyFromCredential(item.id), credentialRef(item.id))}>{item.id}</Button>)}</div>
    </details>}
  </fieldset>
}

export function McpConfigEditor({ locale, selectedConfigId, value, onChange, onSave, onClose, onPendingChange, onDraftDirtyChange, backendPrecheck = true, loadCredentials = true, footerContainer, busy }: McpConfigEditorProps) {
  const c: CopyFn = (key) => FORM_COPY[locale][key]
  const zh = locale === "zh-CN"
  const editorId = useId()
  const root = useRef<HTMLDivElement>(null)
  const [activeTab, setActiveTab] = useState<"form" | "json">("form")
  const [attempted, setAttempted] = useState(false)
  const [touched, setTouched] = useState<Set<string>>(new Set())
  const [validation, setValidation] = useState<ManifestValidationResponse | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const [validating, setValidating] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [credentials, setCredentials] = useState<Credential[]>([])
  const [pendingEntries, setPendingEntries] = useState<Set<string>>(new Set())
  const requestPending = useRef(false)
  const latest = useRef({ value, revision: 0 })
  if (latest.current.value !== value) latest.current = { value, revision: latest.current.revision + 1 }
  const revision = latest.current.revision
  const initialContext = useRef<ManifestEditContext>({ existingConfigId: selectedConfigId, originalEndpointMasked: (() => {
    try { return getRecord(parseManifest(value).transport).endpoint === REDACTED_ENDPOINT } catch { return false }
  })() })
  const parsed = useMemo(() => {
    try { return { manifest: parseManifest(value), error: null, syntax: false } }
    catch (err) { return { manifest: null, syntax: err instanceof SyntaxError, error: err instanceof SyntaxError ? JSON_SYNTAX_MESSAGE[zh ? "zh-CN" : "en"] : (zh ? "配置必须是 JSON 对象。当前输入已保留。" : "The configuration must be a JSON object. Your input has been retained.") } }
  }, [value, zh])
  const manifest = parsed.manifest
  const locked = busy || validating || submitting
  const rawChecks = manifest ? precheckManifest(manifest, (key) => key, initialContext.current) : { errors: [], warnings: [] }
  const issues: ValidationIssue[] = [
    ...rawChecks.errors.map((key) => ({ code: key, messageKey: key, message: c(key as CopyKey), severity: "error" as const, source: "domain" as const, path: PRECHECK_PATHS[key as ManifestPrecheckMessageKey], revision })),
    ...rawChecks.warnings.map((key) => ({ code: key, messageKey: key, message: c(key as CopyKey), severity: "warning" as const, source: "domain" as const, path: PRECHECK_PATHS[key as ManifestPrecheckMessageKey], revision })),
  ].filter((issue, index, all) => all.findIndex((other) => other.path === issue.path && other.message === issue.message) === index)
  const visibleIssues = issues.filter((issue) => attempted || touched.has(issue.path))
  const backendIssues = validation ? manifestValidationIssues(validation.checks, revision) : []
  const mode = manifest ? runtimeModeFromManifest(manifest) : "advanced"
  const launch = getRecord(manifest?.launch)
  const transport = getRecord(manifest?.transport)
  const policy = getRecord(manifest?.restart_policy)
  const health = getRecord(policy.health_check)
  const managed = mode === "managed_stdio" || mode === "managed_http"
  const http = mode === "external_http" || mode === "managed_http"
  const endpointKept = manifest ? canKeepMaskedEndpoint(manifest, initialContext.current) : false

  useEffect(() => {
    let active = true
    if (loadCredentials) void api.credentials().then((items) => { if (active) setCredentials(items) }).catch(() => { /* References can always be entered manually. */ })
    return () => { active = false }
  }, [loadCredentials])
  useEffect(() => { setValidation(null); setRequestError(null) }, [value])
  useEffect(() => { onPendingChange?.(locked); return () => onPendingChange?.(false) }, [locked, onPendingChange])
  useEffect(() => { onDraftDirtyChange?.(pendingEntries.size > 0) }, [pendingEntries, onDraftDirtyChange])

  function fieldId(path: string) { return `${editorId}-${path.replace(/\//g, "-")}` }
  function switchToJson() {
    if (pendingEntries.size) { setRequestError(zh ? "请先添加或清除键值列表中尚未添加的项，再切换 JSON。" : "Add or clear the pending key/value entry before switching to JSON."); return false }
    setActiveTab("json")
    return true
  }
  function focusIssue(issue: ValidationIssue) {
    const field = Array.from(root.current?.querySelectorAll<HTMLElement>("[data-manifest-path]") || []).find((element) => element.getAttribute("data-manifest-path") === issue.path)
    if (activeTab === "form" && field && !field.hasAttribute("disabled")) {
      let parent = field.parentElement
      while (parent && parent !== root.current) { if (parent instanceof HTMLDetailsElement) parent.open = true; parent = parent.parentElement }
      field.focus(); field.scrollIntoView({ block: "center" }); return
    }
    if (!switchToJson()) return
    window.setTimeout(() => {
      const area = root.current?.querySelector<HTMLTextAreaElement>("[data-manifest-json]")
      if (!area) return
      area.focus()
      // A repeated key name is not a source location. Keep the full pointer in
      // the diagnostic and focus JSON without selecting an unrelated property.
      area.scrollIntoView({ block: "center" })
    }, 0)
  }
  function write(next: ManifestLike) { if (!locked) onChange(prettyJson(next)) }
  function set(path: string[], next: unknown) {
    if (!manifest || locked) return
    write(patchManifestField(manifest, path, { kind: "set", value: next }))
  }
  function remove(path: string[]) {
    if (!manifest || locked) return
    write(patchManifestField(manifest, path, { kind: "remove" }))
  }
  function touch(path: string) { setTouched((current) => new Set(current).add(path)) }
  function fieldError(path: string) { return [...visibleIssues, ...backendIssues].find((issue) => issue.path === path && issue.severity === "error")?.message }
  function unsupported(label: string) {
    return <p className="text-xs text-muted-foreground">{zh ? `${label} 的当前结构需在 JSON 中维护，未修改的值会保留。` : `Edit the current ${label} structure in JSON. Its value is preserved.`} <button type="button" className="text-primary underline" disabled={locked} onClick={switchToJson}>JSON</button></p>
  }
  function textField(path: string[], label: string, current: unknown, desc?: string, disabled = false) {
    const pointer = `/${path.join("/")}`
    const id = fieldId(pointer)
    return <Field id={id} label={label} desc={desc} error={fieldError(pointer)}>
      {current !== undefined && current !== null && typeof current !== "string" ? unsupported(label) : <Input id={id} data-manifest-path={pointer} value={typeof current === "string" ? current : ""} disabled={locked || disabled} aria-invalid={Boolean(fieldError(pointer))} aria-describedby={`${id}-help${fieldError(pointer) ? ` ${id}-error` : ""}`} onBlur={() => touch(pointer)} onChange={(event) => set(path, event.target.value)} />}
    </Field>
  }
  function numberField(path: string[], label: string, current: unknown, min: number, fallback: number, step = 1) {
    const pointer = `/${path.join("/")}`
    const id = fieldId(pointer)
    return <Field id={id} label={label} error={fieldError(pointer)}>
      {current !== undefined && current !== null && typeof current !== "number" ? unsupported(label) : <Input id={id} data-manifest-path={pointer} type="number" min={min} step={step} value={typeof current === "number" ? current : ""} placeholder={current === null ? "null" : String(fallback)} disabled={locked} onBlur={() => touch(pointer)} onChange={(event) => event.target.value === "" ? remove(path) : set(path, Number(event.target.value))} />}
    </Field>
  }
  function toggle(path: string[], label: string, current: unknown, fallback: boolean, desc?: string) {
    const pointer = `/${path.join("/")}`
    const id = fieldId(pointer)
    if (current !== undefined && typeof current !== "boolean") return <Field id={id} label={label}>{unsupported(label)}</Field>
    return <div className="manifest-toggle"><div><Label htmlFor={id}>{label}</Label>{desc && <p className="text-xs text-muted-foreground">{desc}</p>}</div><Switch id={id} data-manifest-path={pointer} checked={typeof current === "boolean" ? current : fallback} disabled={locked} onCheckedChange={(checked) => set(path, checked)} /></div>
  }
  function mapField(path: string[], label: string, current: unknown, withCredentials = false) {
    const id = fieldId(`/${path.join("/")}`)
    return <Field id={id} label={label} desc={withCredentials ? (zh ? "敏感值使用 ${credential:ID} 引用；已有键名需删除后重新添加。" : "Use ${credential:ID} for secrets. Remove and add an entry to change its key.") : undefined}>
      {current !== undefined && !isStringMap(current) ? unsupported(label) : <StringMapEditor id={id} label={label} value={(current || {}) as Record<string, string>} disabled={locked} onChange={(next) => set(path, next)} zh={zh} credentials={withCredentials ? credentials : []} onDraftDirtyChange={(dirty) => setPendingEntries((current) => {
        if (current.has(id) === dirty) return current
        const next = new Set(current); if (dirty) next.add(id); else next.delete(id); return next
      })} />}
    </Field>
  }
  function arrayField(path: string[], label: string, current: unknown, numeric = false) {
    const pointer = `/${path.join("/")}`
    const supported = current === undefined || (Array.isArray(current) && current.every((item) => numeric ? typeof item === "number" && Number.isInteger(item) : typeof item === "string"))
    const items = supported && Array.isArray(current) ? current : []
    return <Field id={fieldId(pointer)} label={label} desc={numeric ? undefined : (zh ? "每行是一个完整参数；空参数和前后空格原样保留。" : "Each row is one complete argument; empty arguments and spaces are preserved.")}>
      {!supported ? unsupported(label) : <div className="manifest-array" id={fieldId(pointer)} data-manifest-path={pointer} tabIndex={-1}>
        {items.map((item, index) => <div className="manifest-array-row" key={index}>
          <Input type={numeric ? "number" : "text"} aria-label={`${label} ${index + 1}`} value={item} disabled={locked} onChange={(event) => {
            const next = [...items]; next[index] = numeric ? Number(event.target.value) : event.target.value; set(path, next)
          }} />
          <Button type="button" variant="ghost" size="sm" className="size-9 shrink-0 px-0" disabled={locked} aria-label={`${zh ? "移除" : "Remove"} ${label} ${index + 1}`} onClick={() => set(path, items.filter((_, i) => i !== index))}><Trash2 className="size-4" /></Button>
        </div>)}
        <Button type="button" variant="outline" size="sm" disabled={locked} onClick={() => set(path, [...items, numeric ? 0 : ""])}><Plus className="size-4" />{zh ? "添加一行" : "Add row"}</Button>
      </div>}
    </Field>
  }
  async function check(snapshot: ManifestLike, snapshotRevision: number) {
    const result = await api.validateConfig(withoutUserCredentialValues(snapshot), selectedConfigId || null)
    if (latest.current.revision !== snapshotRevision) return null
    setValidation(result)
    return result
  }
  async function validate(save: boolean) {
    if (requestPending.current || locked || !manifest) return
    if (pendingEntries.size > 0) { setRequestError(zh ? "请先添加或清除键值列表中尚未添加的项，再保存或检查。" : "Add or clear the pending key/value entry before saving or checking."); return }
    setAttempted(true)
    const first = issues.find((issue) => issue.severity === "error")
    if (backendPrecheck && first) { focusIssue(first); return }
    requestPending.current = true
    setRequestError(null)
    if (save) setSubmitting(true)
    else setValidating(true)
    const snapshotRevision = revision
    const snapshot = manifest
    try {
      if (!backendPrecheck) { await onSave(value); return }
      const result = await check(snapshot, snapshotRevision)
      if (!result || result.summary.errors > 0 || !save) return
      await onSave(prettyJson(snapshot))
    } catch (err) { setRequestError(err instanceof Error ? err.message : String(err)) }
    finally { requestPending.current = false; setValidating(false); setSubmitting(false) }
  }

  const footer = <div className="manifest-editor-footer">
    {requestError && <Alert variant="destructive"><AlertDescription>{requestError}</AlertDescription></Alert>}
    <div className="manifest-editor-actions">
      {backendPrecheck && <Button type="button" variant="outline" disabled={locked || !manifest} onClick={() => void validate(false)}><ShieldCheck className="size-4" />{validating ? (zh ? "检查中…" : "Checking…") : c("backendPrecheck")}</Button>}
      <div className="ml-auto flex gap-2">
        {onClose && <Button type="button" variant="ghost" disabled={locked} onClick={onClose}>{zh ? "取消" : "Cancel"}</Button>}
        <Button type="button" disabled={locked || !manifest} onClick={() => void validate(true)}><Save className="size-4" />{submitting || busy ? (zh ? "保存中…" : "Saving…") : c("saveAndApply")}</Button>
      </div>
    </div>
  </div>

  return <div ref={root} className="manifest-editor">
    <div className="manifest-editor-toolbar">
      <div role="group" aria-label={zh ? "编辑模式" : "Editor mode"} className="flex gap-1">
        <Button type="button" size="sm" variant={activeTab === "form" ? "secondary" : "ghost"} aria-pressed={activeTab === "form"} disabled={locked || !manifest} onClick={() => setActiveTab("form")}>{zh ? "表单" : "Form"}</Button>
        <Button type="button" size="sm" variant={activeTab === "json" ? "secondary" : "ghost"} aria-pressed={activeTab === "json"} disabled={locked} onClick={switchToJson}>JSON</Button>
      </div>
      {activeTab === "json" && <Button type="button" size="sm" variant="ghost" disabled={locked || !manifest} onClick={() => onChange(formatManifestJson(value))}><Braces className="size-4" />{c("formatJson")}</Button>}
    </div>
    <div className="manifest-editor-body">
      {parsed.error && <ValidationErrors title={parsed.syntax ? (zh ? "JSON 语法错误" : "JSON syntax error") : (zh ? "配置格式错误" : "Invalid configuration structure")} issues={[{ code: parsed.syntax ? "invalid_json" : "object_required", messageKey: parsed.syntax ? "invalid_json" : "object_required", message: parsed.error, severity: "error", source: parsed.syntax ? "syntax" : "schema", path: "", revision }]} onSelect={focusIssue} />}
      {visibleIssues.length > 0 && <ValidationErrors title={c("localErrors")} issues={visibleIssues} onSelect={focusIssue} />}
      {backendIssues.length > 0 && <ValidationErrors title={c("backendCheck")} issues={backendIssues} onSelect={focusIssue} />}
      {validation && <ValidationPanel validation={validation} c={c} />}
      {activeTab === "form" && manifest ? <div className="manifest-form">
        <div className="manifest-form-pair">
          {textField(["id"], c("serverId"), manifest.id, c("serverIdDesc"), Boolean(selectedConfigId))}
          {textField(["name"], c("name"), manifest.name)}
        </div>
        <Field id={fieldId("/launch/type")} label={c("runtimeMode")} desc={mode === "external_http" ? c("externalManagedHint") : undefined}>
          <select id={fieldId("/launch/type")} data-manifest-path="/launch/type" className="manifest-select" value={mode} disabled={locked || mode === "advanced" || pendingEntries.size > 0} onChange={(event) => {
            const nextMode = event.target.value as RuntimeMode
            write(changeRuntimeMode(manifest, nextMode))
          }}>
            <option value="managed_stdio">{c("managedStdio")}</option><option value="external_http">{c("externalHttp")}</option><option value="managed_http">{c("managedHttp")}</option>{mode === "advanced" && <option value="advanced" disabled>{c("advancedMode")}</option>}
          </select>
          {mode === "advanced" && unsupported(c("runtimeMode"))}
        </Field>
        {managed && <>
          <div className="manifest-form-pair">{textField(["launch", "command"], c("command"), launch.command, c("commandDesc"))}{textField(["launch", "cwd"], c("cwd"), launch.cwd, c("cwdDesc"))}</div>
          {arrayField(["launch", "args"], c("args"), launch.args)}
          {mapField(["launch", "env"], c("env"), launch.env, true)}
        </>}
        {http && <>
          <Field id={fieldId("/transport/endpoint")} label={c("endpoint")} desc={endpointKept ? (zh ? "保留此配置已保存的地址；服务端不会返回完整地址。" : "Keep this config’s saved endpoint; the server does not return the full value.") : c("endpointDesc")} error={fieldError("/transport/endpoint")}>
            {endpointKept ? <div className="manifest-toggle"><span className="text-sm">{zh ? "使用已保存的地址" : "Use saved endpoint"}</span><Button type="button" variant="outline" size="sm" disabled={locked} onClick={() => set(["transport", "endpoint"], "")}>{zh ? "替换地址" : "Replace endpoint"}</Button></div> : <>
              <Input id={fieldId("/transport/endpoint")} data-manifest-path="/transport/endpoint" aria-invalid={Boolean(fieldError("/transport/endpoint"))} value={typeof transport.endpoint === "string" ? transport.endpoint : ""} disabled={locked} onBlur={() => touch("/transport/endpoint")} onChange={(event) => set(["transport", "endpoint"], event.target.value)} />
              {initialContext.current.originalEndpointMasked && <Button type="button" size="sm" variant="ghost" disabled={locked} onClick={() => set(["transport", "endpoint"], REDACTED_ENDPOINT)}>{zh ? "保留原地址" : "Keep original endpoint"}</Button>}
            </>}
          </Field>
          {mapField(["transport", "headers"], zh ? "HTTP 请求头" : "HTTP headers", transport.headers)}
        </>}
        {numberField(["timeout_seconds"], c("timeoutSeconds"), manifest.timeout_seconds, 1, 30)}
        {managed && <>
          {toggle(["auto_start"], c("autoStart"), manifest.auto_start, false, c("autoStartDesc"))}
          <details className="manifest-section" open={Boolean(policy.enabled) || undefined}>
            <summary>{c("restartPolicy")}</summary>
            <div className="manifest-section-content">
              {toggle(["restart_policy", "enabled"], zh ? "启用自动重启" : "Enable automatic restart", policy.enabled, false)}
              <div className="manifest-form-pair">
                {numberField(["restart_policy", "max_attempts"], c("maxAttempts"), policy.max_attempts, 0, 3)}
                {numberField(["restart_policy", "delay_seconds"], `${c("delaySeconds")} (s)`, policy.delay_seconds, 0, 5, 0.1)}
                {numberField(["restart_policy", "backoff_multiplier"], c("backoff"), policy.backoff_multiplier, 1, 2, 0.1)}
                {numberField(["restart_policy", "max_delay_seconds"], `${c("maxDelay")} (s)`, policy.max_delay_seconds, 0, 60, 0.1)}
                {numberField(["restart_policy", "reset_after_seconds"], `${c("resetAfterSeconds")} (s)`, policy.reset_after_seconds, 0, 300, 0.1)}
              </div>
              {toggle(["restart_policy", "restart_on_exit"], c("restartOnExit"), policy.restart_on_exit, true, c("restartOnExitDesc"))}
              <div className="manifest-form-pair">{arrayField(["restart_policy", "exit_code_allowlist"], c("exitAllowlist"), policy.exit_code_allowlist, true)}{arrayField(["restart_policy", "exit_code_blocklist"], c("exitBlocklist"), policy.exit_code_blocklist, true)}</div>
              {toggle(["restart_policy", "health_check", "enabled"], c("healthCheck"), health.enabled, false, c("healthCheckDesc"))}
              <div className="manifest-form-pair">
                {numberField(["restart_policy", "health_check", "interval_seconds"], `${c("intervalSeconds")} (s)`, health.interval_seconds, 1, 30, 0.1)}
                {numberField(["restart_policy", "health_check", "timeout_seconds"], `${c("healthTimeoutSeconds")} (s)`, health.timeout_seconds, 1, 10, 0.1)}
                {numberField(["restart_policy", "health_check", "failure_threshold"], c("failureThreshold"), health.failure_threshold, 1, 3)}
              </div>
            </div>
          </details>
        </>}
        <p className="text-xs text-muted-foreground">{zh ? "未展示字段原样保留；需要维护时切换 JSON。清空可选数字会移除该字段，使用服务默认值。" : "Unshown fields are preserved; edit them in JSON. Clearing an optional number removes the field and uses the server default."}</p>
      </div> : <Field id={fieldId("json")} label={c("rawJson")} desc={c("rawJsonDesc")}>
        <Textarea id={fieldId("json")} data-manifest-json className="manifest-json" spellCheck={false} value={value} disabled={locked} onChange={(event) => onChange(event.target.value)} />
      </Field>}
    </div>
    {footerContainer ? createPortal(footer, footerContainer) : footer}
  </div>
}

function ValidationPanel({ validation, c }: { validation: ManifestValidationResponse; c: CopyFn }) {
  const status = validation.summary.errors > 0 ? c("notRecommended") : validation.summary.warnings > 0 ? c("saveWithWarning") : c("saveOk")
  return <div className="manifest-validation" role="status">
    <div className="flex flex-wrap items-center justify-between gap-2"><span className="text-sm">{c("backendCheck")}: {status}</span><Badge variant={validation.summary.errors > 0 ? "danger" : validation.summary.warnings > 0 ? "warning" : "success"}>{c("errors")} {validation.summary.errors} · {c("warnings")} {validation.summary.warnings}</Badge></div>
    <details className="mt-2 text-xs"><summary className="cursor-pointer">{c("info")} / {c("ok")}</summary><ul className="mt-2 space-y-1">{validation.checks.filter((check) => check.severity === "ok" || check.severity === "info").map((check, i) => <li key={i}>{check.name} · {check.message}</li>)}</ul></details>
  </div>
}

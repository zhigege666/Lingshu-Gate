import { useEffect, useId, useMemo, useRef, useState, type ReactNode } from "react"
import { Braces, Plus, Save, ShieldCheck, Trash2 } from "lucide-react"
import { createPortal } from "react-dom"
import { Radio, Select } from "antd"
import { api, type Credential, type HttpTrustSaveOptions, type ManifestValidationResponse } from "@/api/client"
import { testHttpConnection, type HttpConnectionResult } from "@/api/http-connection-test"
import { McpConnectionTestResult } from "@/components/mcp-connection-test-result"
import { ValidationErrors } from "@/components/validation-errors"
import { FieldLabel } from "@/components/field-help"
import { McpHttpTrustControl, httpTrustTargetKey, type HttpTrustEditorState } from "@/components/mcp-http-trust-control"
import { privateHttpOrigin } from "@/features/mcp-config/http-trust"
import { McpHttpAuthEditor, type HttpAuthDraftReason } from "@/components/mcp-http-auth-editor"
import { homeMcpEndpoint } from "@/features/mcp-config/http-auth"
import { Alert, AlertDescription } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import {
  REDACTED_ENDPOINT, canKeepMaskedEndpoint, changeRuntimeMode, changeStartupPolicy, credentialRef, envKeyFromCredential,
  formatManifestJson, getRecord, isStringMap, parseManifest, patchManifestField,
  precheckManifest, runtimeModeFromManifest, withoutUserCredentialValues,
  manifestValidationIssues, manifestValidationStatus,
  type ManifestEditContext, type ManifestLike, type ManifestPrecheckMessageKey, type RuntimeMode,
} from "@/features/mcp-config/model"
import type { Locale } from "@/i18n"
import { JSON_SOURCE_MESSAGE, JSON_SYNTAX_MESSAGE, type ValidationIssue } from "@/lib/validation"
import { JsonSourceError } from "@/lib/json-source"
import { prettyJson } from "@/lib/utils"
import "@/features/mcp-config/editor.css"

type McpConfigEditorProps = {
  locale: Locale
  selectedConfigId: string
  savedConfigDigest?: string
  value: string
  onChange: (value: string) => void
  onSave: (nextValue?: string, httpTrust?: HttpTrustSaveOptions) => void | Promise<void>
  saveLabel?: string
  onClose?: () => void
  onPendingChange?: (pending: boolean) => void
  onDraftDirtyChange?: (dirty: boolean) => void
  backendPrecheck?: boolean
  loadCredentials?: boolean
  footerContainer?: HTMLElement | null
  busy: boolean
  canManageHttpTrust?: boolean
  canManageCredentials?: boolean
}

const FORM_COPY = {
  "zh-CN": {
    serverId: "服务 ID",
    serverIdDesc: "MCP Server 的唯一标识，只能包含字母、数字、点、下划线和短横线。",
    name: "名称",
    enabled: "启用服务",
    enabledDesc: "关闭时不能连接或启动；仅保存不会改变当前运行实例。",
    permissions: "权限声明",
    permissionsDesc: "声明供审查使用，不授予用户权限，也不替代工具分类和连接授权。",
    runtimeSwitchHint: "切换只改运行/传输类型，地址和其它字段保留；不兼容项需明确修正。",
    restartUnsupported: "此运行方式不支持进程自动重启，请将 restart_policy.enabled 设为 false。",
    healthRestartUnsupported: "此运行方式不支持重启探活，请将 restart_policy.health_check.enabled 设为 false。",
    toolchainModeUnsupported: "固定工具链仅支持 managed_process。当前值已保留，请在 JSON 中明确移除或恢复受管方式。",
    legacyExternalAutoStart: "旧策略不支持自动连接；明确修改自启开关以选择 gate_start_v1。",
    runtimeMode: "运行方式",
    managedStdio: "受管 Stdio",
    externalHttp: "外部 HTTP",
    managedHttp: "受管 HTTP",
    containerStdio: "容器 Stdio",
    containerImage: "容器镜像",
    containerImageDesc: "填写固定摘要的镜像，例如 registry.example/mcp@sha256:…（64 位小写十六进制）。容器使用 Stdio；运行执行节点需要已配置容器环境。",
    containerAutoStartDesc: "自动启动 MCP 容器并连接。",
    containerTransportUnsupported: "当前容器运行时仅支持 Stdio，不支持 HTTP。请在 JSON 中将 transport.type 改为 stdio，或选择受支持的运行方式。",
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
    autoStart: "Gate 启动时自动启动",
    autoStartDesc: "自动启动 MCP 进程并连接。",
    externalAutoStartDesc: "自动建立连接，不启动远端进程。",
    legacyStartup: "旧策略：恢复上次状态；修改开关后切换为自动启动策略。",
    legacyStartupState: "旧策略 · 恢复上次状态",
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
    backendPrecheck: "校验配置",
    saveAndApply: "保存配置",
    rawJson: "Manifest JSON",
    rawJsonDesc: "表单修改自动同步到 JSON；未修改的字段和原有值会保留。",
    backendCheck: "后端预检查",
    notRecommended: "检查未通过",
    saveWithWarning: "检查完成",
    saveOk: "检查通过",
    diagnostics: "补充检查项",
    issues: "错误与警告",
    saveBlocked: "请修正当前草稿的错误后保存。",
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
    serverId: "Server ID",
    serverIdDesc: "Unique MCP Server identifier. Use letters, numbers, dots, underscores, and hyphens only.",
    name: "Name",
    enabled: "Enable service",
    enabledDesc: "Disabled services cannot connect or start. Saving alone does not change the current runtime.",
    permissions: "Access declarations",
    permissionsDesc: "Declarations are for review; they do not grant user access or replace tool classification and connection grants.",
    runtimeSwitchHint: "Switching changes only runtime/transport types. The endpoint and other fields are retained; resolve incompatible values explicitly.",
    restartUnsupported: "This runtime does not support process restart; set restart_policy.enabled=false.",
    healthRestartUnsupported: "This runtime does not support restart health checks; set restart_policy.health_check.enabled=false.",
    toolchainModeUnsupported: "Pinned toolchains require managed_process. The value is retained; remove it explicitly in JSON or return to a managed runtime.",
    legacyExternalAutoStart: "The legacy policy does not support automatic connection. Explicitly change the startup switch to select gate_start_v1.",
    runtimeMode: "Runtime Mode",
    managedStdio: "Managed Stdio",
    externalHttp: "External HTTP",
    managedHttp: "Managed HTTP",
    containerStdio: "Container Stdio",
    containerImage: "Container image",
    containerImageDesc: "Use a digest-pinned image, for example registry.example/mcp@sha256:… (64 lowercase hexadecimal digits). Containers use Stdio and require a configured container runtime on the execution node.",
    containerAutoStartDesc: "Start the MCP container automatically and connect.",
    containerTransportUnsupported: "The container runtime supports Stdio only, not HTTP. Set transport.type to stdio in JSON or choose a supported runtime.",
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
    autoStart: "Start automatically when Gate starts",
    autoStartDesc: "Start the MCP process automatically and connect.",
    externalAutoStartDesc: "Connect automatically without starting a remote process.",
    legacyStartup: "Legacy policy: restore the last state. Edit the switch to adopt the startup policy.",
    legacyStartupState: "Legacy policy · Restore last state",
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
    backendPrecheck: "Validate configuration",
    saveAndApply: "Save Config",
    rawJson: "Manifest JSON",
    rawJsonDesc: "Form edits sync to JSON automatically; untouched fields and values are preserved.",
    backendCheck: "Backend Precheck",
    notRecommended: "Check failed",
    saveWithWarning: "Check completed",
    saveOk: "Check passed",
    diagnostics: "Additional checks",
    issues: "Errors and warnings",
    saveBlocked: "Correct the current draft errors before saving.",
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
  containerTransportUnsupported: "/transport/type",
  launchTypeWarning: "/launch/type", argsWarning: "/launch/args", transportTypeRequired: "/transport/type",
  stdioLaunchError: "/transport/type", streamableEndpointError: "/transport/endpoint",
  endpointRequired: "/transport/endpoint", endpointInvalid: "/transport/endpoint", timeoutWarning: "/timeout_seconds",
  restartUnsupported: "/restart_policy/enabled",
  healthRestartUnsupported: "/restart_policy/health_check/enabled", toolchainModeUnsupported: "/launch/toolchain",
  legacyExternalAutoStart: "/auto_start",
}

function Field({ id, label, desc, error, readOnly = false, children }: {
  id: string; label: string; desc?: ReactNode; error?: string; readOnly?: boolean; children: ReactNode
}) {
  return <div className="manifest-field">
    {readOnly ? <FieldLabel label={label} help={desc} /> : <Label htmlFor={id} help={desc} helpId={desc ? `${id}-help` : undefined}>{label}</Label>}
    <div className="manifest-field-control">
      {children}
      {error && <p id={`${id}-error`} role="alert" className="text-xs text-destructive">{error}</p>}
    </div>
  </div>
}

function StringMapEditor({ value, label, disabled, onChange, zh, id, credentials = [], credentialKeyMode = "environment", onDraftDirtyChange }: {
  value: Record<string, string>; label: string; disabled: boolean; onChange: (value: Record<string, string>) => void
  zh: boolean; id: string; credentials?: Credential[]; credentialKeyMode?: "environment" | "header"; onDraftDirtyChange: (dirty: boolean) => void
}) {
  const [key, setKey] = useState("")
  const [entryValue, setEntryValue] = useState("")
  const [error, setError] = useState("")
  const [referenceId, setReferenceId] = useState<string | undefined>()
  const [referencePrefix, setReferencePrefix] = useState("Bearer ")
  const reportDirty = useRef(onDraftDirtyChange)
  reportDirty.current = onDraftDirtyChange
  useEffect(() => { reportDirty.current(Boolean(key || entryValue)) }, [key, entryValue])
  useEffect(() => () => reportDirty.current(false), [])
  function add(nextKey = key, nextValue = entryValue) {
    if (!nextKey.trim()) { setError(zh ? "请填写键名。" : "Enter a key."); return }
    if (Object.prototype.hasOwnProperty.call(value, nextKey)) { setError(zh ? "键名已存在，请直接修改已有值。" : "This key already exists. Edit its value below."); return }
    onChange({ ...value, [nextKey]: nextValue })
    setKey(""); setEntryValue(""); setError(""); setReferenceId(undefined)
  }
  function chooseCredential(credentialId: string, prefix = referencePrefix) {
    setReferenceId(credentialId)
    setEntryValue((credentialKeyMode === "header" ? prefix : "") + credentialRef(credentialId))
    if (!key) setKey(credentialKeyMode === "environment" ? envKeyFromCredential(credentialId) : "Authorization")
    setError("")
    document.getElementById(id)?.focus()
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
    {(key || entryValue) && <div className="flex items-center justify-between gap-2"><p className="text-xs text-muted-foreground">{zh ? "点击添加后写入配置；键名的空格和空值会原样保留。" : "Select Add to include this entry; spaces in keys and empty values are preserved."}</p><Button type="button" size="sm" variant="ghost" onClick={() => { setKey(""); setEntryValue(""); setError(""); setReferenceId(undefined) }}>{zh ? "清除待添加项" : "Clear pending entry"}</Button></div>}
    {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
    {credentials.length > 0 && <section className="space-y-2">
      <Label htmlFor={`${id}-credential`} className="text-xs">{zh ? "插入凭据引用" : "Insert credential reference"}</Label>
      <Select id={`${id}-credential`} className="w-full" showSearch optionFilterProp="label" aria-label={zh ? "插入凭据引用" : "Insert credential reference"} disabled={disabled} value={referenceId} placeholder={zh ? "搜索凭据 ID 或名称" : "Search credential ID or name"} options={credentials.map(item => ({ value: item.id, label: `${item.name} · ${item.id}` }))} onChange={id => chooseCredential(id)} />
      {credentialKeyMode === "header" && <Radio.Group size="small" aria-label={zh ? "引用格式" : "Reference format"} disabled={disabled} value={referencePrefix} options={[{ value: "Bearer ", label: "Bearer token" }, { value: "", label: zh ? "原始值" : "Raw value" }]} onChange={event => {
        const prefix = event.target.value as string; setReferencePrefix(prefix)
        if (referenceId) chooseCredential(referenceId, prefix)
      }} />}
    </section>}
  </fieldset>
}

export function McpConfigEditor({ locale, selectedConfigId, savedConfigDigest, value, onChange, onSave, onClose, onPendingChange, onDraftDirtyChange, backendPrecheck = true, loadCredentials = true, footerContainer, busy, saveLabel, canManageHttpTrust = false, canManageCredentials = false }: McpConfigEditorProps) {
  const c: CopyFn = (key) => FORM_COPY[locale][key]
  const zh = locale === "zh-CN"
  const editorId = useId()
  const root = useRef<HTMLDivElement>(null)
  const [activeTab, setActiveTab] = useState<"form" | "json">("form")
  const [attempted, setAttempted] = useState(false)
  const [touched, setTouched] = useState<Set<string>>(new Set())
  const [checked, setChecked] = useState<{ response: ManifestValidationResponse; revision: number } | null>(null)
  const [requestError, setRequestError] = useState<string | null>(null)
  const savedDigest = useRef(savedConfigDigest)
  const [testing, setTesting] = useState(false)
  const [tested, setTested] = useState<{ response: HttpConnectionResult; revision: number } | null>(null)
  const testController = useRef<AbortController | null>(null)
  const mounted = useRef(true)
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; testController.current?.abort() } }, [])
  const [validating, setValidating] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [trustBusy, setTrustBusy] = useState(false)
  const [credentialBusy, setCredentialBusy] = useState(false)
  const [trustState, setTrustState] = useState<HttpTrustEditorState | null>(null)
  const [credentials, setCredentials] = useState<Credential[]>([])
  const [credentialsLoading, setCredentialsLoading] = useState(loadCredentials)
  const [credentialsError, setCredentialsError] = useState(false)
  const [credentialsReload, setCredentialsReload] = useState(0)
  const localCredentialWrites = useRef<Array<{ sequence: number; credential: Credential }>>([])
  const [authDraftReason, setAuthDraftReason] = useState<HttpAuthDraftReason>(null)
  const advancedHeaders = useRef<HTMLDetailsElement>(null)
  const connectionResult = useRef<HTMLDivElement>(null)
  const [pendingEntries, setPendingEntries] = useState<Set<string>>(new Set())
  const [pendingNumbers, setPendingNumbers] = useState<Record<string, string>>({})
  const hasPendingNumbers = Object.keys(pendingNumbers).length > 0
  const hasPendingEdits = pendingEntries.size > 0 || hasPendingNumbers || authDraftReason !== null
  const requestPending = useRef(false)
  const precheckSequence = useRef(0)
  const latest = useRef({ value, revision: 0 })
  if (latest.current.value !== value) latest.current = { value, revision: latest.current.revision + 1 }
  const revision = latest.current.revision
  const validation = !hasPendingEdits && checked?.revision === revision ? checked.response : null
  const initialContext = useRef<ManifestEditContext>({ existingConfigId: selectedConfigId, originalEndpointMasked: (() => {
    try { return getRecord(parseManifest(value).transport).endpoint === REDACTED_ENDPOINT } catch { return false }
  })(), originalMaskedMountTargets: (() => {
    try {
      const mounts = getRecord(parseManifest(value).launch).mounts
      return Array.isArray(mounts) ? mounts.filter(mount => getRecord(mount).source === "***").map(mount => String(getRecord(mount).target || "")) : []
    } catch { return [] }
  })() })
  const parsed = useMemo(() => {
    try { return { manifest: parseManifest(value), error: null, syntax: false, sourceError: null } }
    catch (err) { return { manifest: null, syntax: err instanceof SyntaxError, sourceError: err instanceof JsonSourceError ? err : null, error: err instanceof JsonSourceError ? JSON_SOURCE_MESSAGE[zh ? "zh-CN" : "en"][err.code] : err instanceof SyntaxError ? JSON_SYNTAX_MESSAGE[zh ? "zh-CN" : "en"] : (zh ? "配置必须是 JSON 对象。当前输入已保留。" : "The configuration must be a JSON object. Your input has been retained.") } }
  }, [value, zh])
  const manifest = parsed.manifest
  const locked = busy || validating || submitting || trustBusy || credentialBusy || testing
  const rawChecks = manifest ? precheckManifest(manifest, (key) => key, initialContext.current) : { errors: [], warnings: [] }
  const issues: ValidationIssue[] = [
    ...rawChecks.errors.map((key) => ({ code: key, messageKey: key, message: c(key as CopyKey), severity: "error" as const, source: "domain" as const, path: PRECHECK_PATHS[key as ManifestPrecheckMessageKey], revision })),
    ...rawChecks.warnings.map((key) => ({ code: key, messageKey: key, message: c(key as CopyKey), severity: "warning" as const, source: "domain" as const, path: PRECHECK_PATHS[key as ManifestPrecheckMessageKey], revision })),
  ].filter((issue, index, all) => all.findIndex((other) => other.path === issue.path && other.message === issue.message) === index)
  const visibleIssues = issues.filter((issue) => attempted || touched.has(issue.path)
    || ["restartUnsupported", "healthRestartUnsupported", "toolchainModeUnsupported", "legacyExternalAutoStart", "containerTransportUnsupported"].includes(issue.code))
  const backendIssues = validation ? manifestValidationIssues(validation.checks, revision) : []
  const mode = manifest ? runtimeModeFromManifest(manifest) : "advanced"
  const launch = getRecord(manifest?.launch)
  const transport = getRecord(manifest?.transport)
  const policy = getRecord(manifest?.restart_policy)
  const health = getRecord(policy.health_check)
  const managedProcess = mode === "managed_stdio" || mode === "managed_http"
  const managedContainer = mode === "managed_container_stdio"
  const managed = managedProcess || managedContainer
  const http = mode === "external_http" || mode === "managed_http"
  const endpointKept = manifest ? canKeepMaskedEndpoint(manifest, initialContext.current) : false
  const privateOrigin = http && privateHttpOrigin(transport.endpoint)
  const needsTrustSnapshot = privateOrigin || http && endpointKept
  const trustTarget = httpTrustTargetKey(typeof manifest?.id === "string" ? manifest.id : "", transport.endpoint)
  const trustReady = !needsTrustSnapshot || !canManageHttpTrust || Boolean(trustState?.targetKey === trustTarget && trustState.ready)
  const httpTrust: HttpTrustSaveOptions = needsTrustSnapshot && trustState?.targetKey === trustTarget ? trustState.options : {}
  const credentialEndpoint = endpointKept && trustState?.targetKey === trustTarget ? trustState.credentialOrigin : transport.endpoint
  const reservedHeaders = Object.keys(getRecord(transport.headers)).filter(key => ["content-type", "accept", "mcp-session-id", "mcp-protocol-version", "mcp-method", "mcp-name", "traceparent", "tracestate", "baggage", "x-correlation-id"].includes(key.toLowerCase()))

  useEffect(() => {
    let active = true
    const writeSequence = localCredentialWrites.current.length
    if (loadCredentials) {
      setCredentialsLoading(true); setCredentialsError(false)
      void api.credentials().then(items => {
        if (!active) return
        const newer = localCredentialWrites.current.filter(write => write.sequence > writeSequence).map(write => write.credential)
        setCredentials([...items.filter(item => !newer.some(created => created.id === item.id)), ...newer])
      })
        .catch(() => { if (active) setCredentialsError(true) })
        .finally(() => { if (active) setCredentialsLoading(false) })
    }
    return () => { active = false }
  }, [loadCredentials, credentialsReload])
  useEffect(() => { setChecked(null); setRequestError(null) }, [value])
  useEffect(() => { onPendingChange?.(locked); return () => onPendingChange?.(false) }, [locked, onPendingChange])
  useEffect(() => { onDraftDirtyChange?.(hasPendingEdits) }, [hasPendingEdits, onDraftDirtyChange])

  useEffect(() => {
    if (!testing && !tested) return
    const frame = requestAnimationFrame(() => connectionResult.current?.scrollIntoView({ block: "nearest" }))
    return () => cancelAnimationFrame(frame)
  }, [testing, tested])
  const authDraftHint = authDraftReason === "credential"
    ? (zh ? "请先保存或取消正在编辑的凭据，再测试连接或保存配置。" : "Save or cancel the credential being edited before testing or saving the configuration.")
    : (zh ? "请完成鉴权方式的凭据和头名称选择，或选择无鉴权。" : "Complete the credential and header selection, or choose no authentication.")
  function showAdvancedHeaders() {
    if (advancedHeaders.current) {
      advancedHeaders.current.open = true
      requestAnimationFrame(() => { advancedHeaders.current?.scrollIntoView({ block: "nearest" }); advancedHeaders.current?.querySelector<HTMLElement>("input,button")?.focus() })
    }
  }
  function updateAuthHeaders(headers: Record<string, string>) {
    // Completion of the explicit credential write is allowed to attach its
    // reference while credentialBusy locks the surrounding form.
    if (!manifest || busy || validating || submitting || trustBusy || testing) return false
    let current: ManifestLike
    try { current = parseManifest(latest.current.value) } catch { return false }
    const currentTransport = getRecord(current.transport)
    if (current.id !== manifest.id || currentTransport.endpoint !== transport.endpoint
      || JSON.stringify(currentTransport.headers) !== JSON.stringify(transport.headers)) return false
    onChange(prettyJson(patchManifestField(current, ["transport", "headers"], { kind: "set", value: headers })))
    return true
  }
  function credentialCreated(credential: Credential) {
    localCredentialWrites.current.push({ sequence: localCredentialWrites.current.length + 1, credential })
    setCredentials(items => [...items.filter(item => item.id !== credential.id), credential])
  }
  function applyHomeTemplate() {
    if (!manifest || locked) return
    const endpoint = homeMcpEndpoint(transport.endpoint)
    if (endpoint) write(patchManifestField(manifest, ["transport", "endpoint"], { kind: "set", value: endpoint }))
  }
  function fieldId(path: string) { return `${editorId}-${path.replace(/\//g, "-")}` }
  function switchToJson() {
    if (authDraftReason) { setRequestError(authDraftHint); return false }
    if (hasPendingNumbers) { setRequestError(zh ? "请先修正未完成的数值；列表空行可明确移除，再切换 JSON。" : "Complete unfinished numbers or explicitly remove empty list rows before switching to JSON."); return false }
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
      if (issue.range) area.setSelectionRange(issue.range.start, issue.range.end)
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
      {current !== undefined && current !== null && typeof current !== "string" ? unsupported(label) : <Input id={id} data-manifest-path={pointer} value={typeof current === "string" ? current : ""} disabled={locked || disabled} aria-invalid={Boolean(fieldError(pointer))} aria-describedby={[desc && `${id}-help`, fieldError(pointer) && `${id}-error`].filter(Boolean).join(" ") || undefined} onBlur={() => touch(pointer)} onChange={(event) => set(path, event.target.value)} />}
    </Field>
  }
  function numberField(path: string[], label: string, current: unknown, min: number, fallback: number, step = 1) {
    const pointer = `/${path.join("/")}`
    const id = fieldId(pointer)
    const unfinished = Object.prototype.hasOwnProperty.call(pendingNumbers, pointer)
    const error = unfinished ? (zh ? `请输入${step === 1 ? "完整整数" : "完整数值"}，或明确清空以使用默认值；未完成输入已保留。` : `Enter a complete ${step === 1 ? "integer" : "number"}, or clear the field to use its default. Unfinished input is retained.`) : fieldError(pointer)
    return <Field id={id} label={label} desc={zh ? `最小值 ${min}；留空会移除此字段，保存时使用服务默认值 ${fallback}。显式 0 与留空不同。` : `Minimum ${min}. Clearing removes this field and uses the server default ${fallback} when saved. Explicit 0 is different from an omitted value.`} error={error}>
      {current !== undefined && current !== null && typeof current !== "number" ? unsupported(label) : <Input id={id} data-manifest-path={pointer} type="text" inputMode={step === 1 ? "numeric" : "decimal"} value={pendingNumbers[pointer] ?? (typeof current === "number" ? current : "")} placeholder={current === null ? "null" : String(fallback)} disabled={locked} aria-invalid={Boolean(error)} aria-describedby={`${id}-help${error ? ` ${id}-error` : ""}`} onBlur={() => touch(pointer)} onChange={(event) => {
        const raw = event.target.value
        const number = Number(raw)
        const valid = /^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(raw) && Number.isFinite(number) && (!Number.isInteger(number) || Number.isSafeInteger(number)) && (step !== 1 || Number.isInteger(number))
        setPendingNumbers(previous => { const next = { ...previous }; if (raw === "" || valid) delete next[pointer]; else next[pointer] = raw; return next })
        if (raw === "") remove(path)
        else if (valid) set(path, number)
      }} />}
    </Field>
  }
  function toggle(path: string[], label: string, current: unknown, fallback: boolean, desc?: string) {
    const pointer = `/${path.join("/")}`
    const id = fieldId(pointer)
    if (current !== undefined && typeof current !== "boolean") return <Field id={id} label={label}>{unsupported(label)}</Field>
    return <Field id={id} label={label} desc={desc} error={fieldError(pointer)}>
      <Switch className="manifest-switch" id={id} data-manifest-path={pointer} checked={typeof current === "boolean" ? current : fallback} disabled={locked} aria-invalid={Boolean(fieldError(pointer))} aria-describedby={[desc && `${id}-help`, fieldError(pointer) && `${id}-error`, pointer === "/auto_start" && manifest?.startup_policy !== "gate_start_v1" && `${id}-state`].filter(Boolean).join(" ") || undefined} onCheckedChange={(checked) => { touch(pointer); if (pointer === "/auto_start" && manifest) write(changeStartupPolicy(manifest, checked)); else set(path, checked) }} />
      {pointer === "/auto_start" && manifest?.startup_policy !== "gate_start_v1" && <p id={`${id}-state`} className="text-xs text-muted-foreground">{c("legacyStartupState")}</p>}
    </Field>
  }
  function mapField(path: string[], label: string, current: unknown, withCredentials = false) {
    const id = fieldId(`/${path.join("/")}`)
    const headers = path[0] === "transport" && path[1] === "headers"
    return <Field id={id} label={label} desc={withCredentials ? <><p>{zh ? "敏感值使用 ${credential:ID} 引用。插入后请确认键名和值，再点击添加；已有键名需删除后重新添加。" : "Use ${credential:ID} for secrets. Review the key and value, then select Add; remove and add an entry to change its key."}</p><p>{zh ? "*** 仅保留原配置同一键的旧值，不是可复制的秘密；改键名时请重新填写值或凭据引用。" : "*** keeps the saved value only for the same key in the original configuration. It is not a copyable secret; supply a value or credential reference when changing keys."}</p>{headers && <p>{zh ? "请明确填写 HTTP 头名，例如 Authorization。协议与追踪保留头由客户端生成，手工配置不会覆盖它们。" : "Enter the HTTP header name explicitly, for example Authorization. The client generates reserved protocol and tracing headers; configured values do not override them."}</p>}</> : undefined}>
      {current !== undefined && !isStringMap(current) ? unsupported(label) : <StringMapEditor id={id} label={label} value={(current || {}) as Record<string, string>} disabled={locked || headers && authDraftReason !== null} onChange={(next) => set(path, next)} zh={zh} credentials={withCredentials ? credentials : []} credentialKeyMode={headers ? "header" : "environment"}
        onDraftDirtyChange={(dirty) => setPendingEntries((current) => {
        if (current.has(id) === dirty) return current
        const next = new Set(current); if (dirty) next.add(id); else next.delete(id); return next
      })} />}
      {headers && reservedHeaders.length > 0 && <p role="status" className="text-xs text-warning">{zh ? "以下请求头由客户端生成，配置值不会生效：" : "The client generates these headers; configured values are not used: "}{reservedHeaders.join(", ")}</p>}
    </Field>
  }
  function arrayField(path: string[], label: string, current: unknown, numeric = false) {
    const pointer = `/${path.join("/")}`
    const supported = current === undefined || (Array.isArray(current) && current.every((item) => numeric ? typeof item === "number" && Number.isInteger(item) : typeof item === "string"))
    const items = supported && Array.isArray(current) ? current : []
    const incomplete = Object.keys(pendingNumbers).some(key => key.startsWith(`${pointer}/`))
    const numberError = incomplete ? (zh ? "请输入完整的退出码整数，或移除此行；空白不会写成 0。" : "Enter a complete exit-code integer or remove its row. Blank input is not written as 0.") : undefined
    return <Field id={fieldId(pointer)} label={label} desc={numeric ? undefined : (zh ? "每行是一个完整参数；空参数和前后空格原样保留。" : "Each row is one complete argument; empty arguments and spaces are preserved.")}>
      {!supported ? unsupported(label) : <div className="manifest-array" id={fieldId(pointer)} data-manifest-path={pointer} tabIndex={-1}>
        {items.map((item, index) => <div className="manifest-array-row" key={index}>
          <Input type="text" inputMode={numeric ? "numeric" : undefined} aria-label={`${label} ${index + 1}`} value={pendingNumbers[`${pointer}/${index}`] ?? item} disabled={locked}
            aria-invalid={numeric && Object.prototype.hasOwnProperty.call(pendingNumbers, `${pointer}/${index}`)} aria-describedby={numeric && Object.prototype.hasOwnProperty.call(pendingNumbers, `${pointer}/${index}`) ? `${fieldId(pointer)}-number-error` : undefined} onChange={(event) => {
            const raw = event.target.value
            if (numeric) {
              const valid = /^-?\d+$/.test(raw) && Number.isSafeInteger(Number(raw))
              setPendingNumbers(previous => { const next = { ...previous }; if (valid) delete next[`${pointer}/${index}`]; else next[`${pointer}/${index}`] = raw; return next })
              if (!valid) return
            }
            const next = [...items]; next[index] = numeric ? Number(raw) : raw; set(path, next)
          }} />
          <Button type="button" variant="ghost" size="sm" className="size-9 shrink-0 px-0" disabled={locked} aria-label={`${zh ? "移除" : "Remove"} ${label} ${index + 1}`} onClick={() => {
            if (numeric) setPendingNumbers(previous => Object.fromEntries(Object.entries(previous).flatMap(([key, raw]) => {
              if (!key.startsWith(`${pointer}/`)) return [[key, raw]]
              const oldIndex = Number(key.slice(pointer.length + 1))
              return oldIndex === index ? [] : [[`${pointer}/${oldIndex > index ? oldIndex - 1 : oldIndex}`, raw]]
            })))
            set(path, items.filter((_, i) => i !== index))
          }}><Trash2 className="size-4" /></Button>
        </div>)}
        {numberError && <p id={`${fieldId(pointer)}-number-error`} role="alert" className="text-xs text-destructive">{numberError}</p>}
        <Button type="button" variant="outline" size="sm" disabled={locked} onClick={() => set(path, [...items, numeric ? 0 : ""])}><Plus className="size-4" />{zh ? "添加一行" : "Add row"}</Button>
      </div>}
    </Field>
  }
  async function check(snapshot: ManifestLike, snapshotRevision: number) {
    const result = await api.validateConfig(withoutUserCredentialValues(snapshot), selectedConfigId || null, httpTrust)
    if (latest.current.revision !== snapshotRevision) return null
    precheckSequence.current += 1
    setChecked({ response: result, revision: snapshotRevision })
    return result
  }
  async function validate(save: boolean) {
    if (requestPending.current || locked || !manifest || !trustReady) return
    if (authDraftReason) { setRequestError(authDraftHint); return }
    if (hasPendingNumbers) { setRequestError(zh ? "请先修正未完成的数值；列表空行可明确移除，再保存或检查。" : "Complete unfinished numbers or explicitly remove empty list rows before saving or checking."); return }
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
      if (!backendPrecheck) { await onSave(value, httpTrust); return }
      const result = await check(snapshot, snapshotRevision)
      if (!result || manifestValidationStatus(result) === "error" || !save) return
      await onSave(prettyJson(snapshot), httpTrust)
    } catch (err) { if (latest.current.revision === snapshotRevision) setRequestError(err instanceof Error ? err.message : String(err)) }
    finally { requestPending.current = false; setValidating(false); setSubmitting(false) }
  }

  async function testConnection() {
    if (requestPending.current || locked || !manifest || hasPendingEdits || mode !== "external_http") return
    setAttempted(true)
    const first = issues.find(issue => issue.severity === "error")
    if (first) { focusIssue(first); return }
    if (selectedConfigId && !savedDigest.current) {
      setRequestError(zh ? "缺少已保存配置版本，请重新打开编辑器后测试。" : "The saved configuration version is missing. Reopen the editor before testing."); return
    }
    requestPending.current = true
    setTesting(true); setTested(null); setRequestError(null)
    const snapshotRevision = revision
    const controller = new AbortController()
    testController.current = controller
    try {
      const response = await testHttpConnection(withoutUserCredentialValues(manifest), selectedConfigId || undefined, savedDigest.current, controller.signal)
      if (mounted.current && latest.current.revision === snapshotRevision) setTested({ response, revision: snapshotRevision })
    } catch (err) {
      if (mounted.current && latest.current.revision === snapshotRevision) setRequestError(controller.signal.aborted
        ? (zh ? "等待联通测试超时。服务端测试仍受自身时限约束；请检查当前状态再重试。" : "Waiting for the test timed out. The server test remains bounded by its deadline; check the state before retrying.")
        : err instanceof Error ? err.message : (zh ? "无法执行联通测试。" : "The connection test could not run."))
    } finally {
      requestPending.current = false
      if (mounted.current) setTesting(false)
      if (testController.current === controller) testController.current = null
    }
  }

  const saveBlocked = !manifest || !trustReady || hasPendingEdits || visibleIssues.some(issue => issue.severity === "error")
    || Boolean(validation && manifestValidationStatus(validation) === "error")
  const saveBlockedHint = authDraftReason ? authDraftHint : !trustReady
    ? (zh ? "请先读取当前连接许可，再保存配置。" : "Read the current connection permission before saving.")
    : pendingEntries.size > 0
    ? (zh ? "请先填写键名并点击添加，或清除待添加项，再保存。" : "Enter a key and add the pending entry, or clear it before saving.")
    : c("saveBlocked")
  const connectionFeedback = <div ref={connectionResult} className="manifest-connection-feedback">
    {testing && <p role="status" className="text-xs text-muted-foreground">{zh ? "正在使用独立连接检查 HTTP、请求鉴权、MCP 握手与工具发现；不保存配置。" : "Testing HTTP, request authentication, MCP handshake and tool discovery in an isolated connection; no configuration is saved."}</p>}
    {tested && <McpConnectionTestResult result={tested.response} stale={tested.revision !== revision || hasPendingEdits} zh={zh} />}
  </div>
  const validationButton = backendPrecheck && <Button type="button" variant="outline" disabled={locked || !manifest || !trustReady || hasPendingEdits} onClick={() => void validate(false)}><ShieldCheck aria-hidden="true" className="size-4" />{validating ? (zh ? "检查中…" : "Checking…") : c("backendPrecheck")}</Button>
  const footer = <div className="manifest-editor-footer">
    {requestError && <Alert variant="destructive"><AlertDescription>{requestError}</AlertDescription></Alert>}
    <div className="manifest-editor-actions">
      <span className="text-xs text-muted-foreground">{mode === "external_http" && backendPrecheck && canManageHttpTrust ? (zh ? "保存前自动校验，连接测试可选。" : "Validated before saving. Connection testing is optional.") : backendPrecheck ? (zh ? "保存前自动校验配置。" : "Configuration is validated before saving.") : (zh ? "保存草稿不会启动服务。" : "Saving a draft does not start the service.")}</span>
      {!http && validationButton}
      <div className="ml-auto flex gap-2">
        {onClose && <Button type="button" variant="ghost" disabled={locked} onClick={onClose}>{zh ? "取消" : "Cancel"}</Button>}
        {backendPrecheck && mode === "external_http" && canManageHttpTrust && <Button type="button" variant="outline" disabled={locked || !manifest || hasPendingEdits} onClick={() => void testConnection()}>{testing ? (zh ? "测试中…" : "Testing…") : (zh ? "测试连接" : "Test connection")}</Button>}
        <Button type="button" disabled={locked || saveBlocked} aria-describedby={saveBlocked ? fieldId("save-block-reason") : undefined} onClick={() => void validate(true)}><Save aria-hidden="true" className="size-4" />{submitting || busy ? (zh ? "保存中…" : "Saving…") : saveLabel || c("saveAndApply")}</Button>
      </div>
    </div>
    {saveBlocked && <p id={fieldId("save-block-reason")} className={authDraftReason ? "text-xs text-muted-foreground" : "text-xs text-destructive"}>{saveBlockedHint}</p>}
  </div>

  return <div ref={root} lang={locale} className={`manifest-editor manifest-editor-${activeTab}`}>
    <div className="manifest-editor-toolbar">
      <div role="group" aria-label={zh ? "编辑模式" : "Editor mode"} className="flex gap-1">
        <Button type="button" size="sm" variant={activeTab === "form" ? "secondary" : "ghost"} aria-pressed={activeTab === "form"} disabled={locked || !manifest} onClick={() => setActiveTab("form")}>{zh ? "表单" : "Form"}</Button>
        <Button type="button" size="sm" variant={activeTab === "json" ? "secondary" : "ghost"} aria-pressed={activeTab === "json"} disabled={locked} onClick={switchToJson}>JSON</Button>
      </div>
      {activeTab === "json" && http && validationButton}
      {activeTab === "json" && <Button type="button" size="sm" variant="ghost" disabled={locked || !manifest} onClick={() => onChange(formatManifestJson(value))}><Braces aria-hidden="true" className="size-4" />{c("formatJson")}</Button>}
    </div>
    <div className="manifest-editor-body">
      {parsed.error && <ValidationErrors title={parsed.sourceError ? (zh ? "JSON 需要修正" : "JSON needs correction") : parsed.syntax ? (zh ? "JSON 语法错误" : "JSON syntax error") : (zh ? "配置格式错误" : "Invalid configuration structure")} issues={[{ code: parsed.sourceError?.code ?? (parsed.syntax ? "invalid_json" : "object_required"), messageKey: parsed.sourceError?.code ?? (parsed.syntax ? "invalid_json" : "object_required"), message: parsed.error, severity: "error", source: parsed.syntax || parsed.sourceError ? "syntax" : "schema", path: parsed.sourceError?.path ?? "", range: parsed.sourceError?.range, revision }]} onSelect={focusIssue} />}
      {(visibleIssues.length > 0 || validation) && <ValidationPanel validation={validation} issues={[...backendIssues, ...visibleIssues].filter((issue, index, all) => all.findIndex(other => other.path === issue.path && other.message === issue.message) === index)} onSelect={focusIssue} c={c} />}
      {activeTab === "json" && http && manifest && <McpHttpTrustControl serverId={typeof manifest.id === "string" ? manifest.id : ""} endpoint={transport.endpoint}
        draftRevision={revision} precheckSequence={precheckSequence.current} canManage={canManageHttpTrust} saved={selectedConfigId === manifest.id} locked={locked} zh={zh}
        denied={Boolean(validation?.checks.some(item => item.metadata?.code === "private_http_untrusted"))}
        onBusyChange={setTrustBusy} onStateChange={setTrustState} onPolicyUpdated={async () => { setChecked(null) }} />}
      {activeTab === "json" && connectionFeedback}
      {activeTab === "form" && manifest ? <div className="manifest-form">
        <div className="manifest-form-pair">
          {textField(["id"], c("serverId"), manifest.id, c("serverIdDesc"), Boolean(selectedConfigId))}
          {textField(["name"], c("name"), manifest.name)}
        </div>
        <Field id={fieldId("/launch/type")} label={c("runtimeMode")} desc={<><p>{c("runtimeSwitchHint")}</p>{mode === "external_http" && <p>{c("externalManagedHint")}</p>}</>}>
          {mode === "advanced" ? <p>{c("advancedMode")}</p> : <Radio.Group id={fieldId("/launch/type")} data-manifest-path="/launch/type" aria-label={c("runtimeMode")} aria-describedby={`${fieldId("/launch/type")}-help`} value={mode} disabled={locked || hasPendingEdits} onChange={(event) => {
            const nextMode = event.target.value as RuntimeMode
            write(changeRuntimeMode(manifest, nextMode))
          }} options={[{ value: "managed_stdio", label: c("managedStdio") }, { value: "external_http", label: c("externalHttp") }, { value: "managed_http", label: c("managedHttp") }, { value: "managed_container_stdio", label: c("containerStdio") }]} />}
          {mode === "advanced" && unsupported(c("runtimeMode"))}
        </Field>
        <div className="manifest-form-pair manifest-startup-pair">
          {toggle(["enabled"], c("enabled"), manifest.enabled, true, c("enabledDesc"))}
          {(managed || mode === "external_http") && toggle(["auto_start"], c("autoStart"), manifest.auto_start, false, `${mode === "external_http" ? c("externalAutoStartDesc") : managedContainer ? c("containerAutoStartDesc") : c("autoStartDesc")} ${manifest.startup_policy !== "gate_start_v1" ? c("legacyStartup") : ""}`.trim())}
        </div>
        {managedProcess && <>
          <div className="manifest-form-pair">{textField(["launch", "command"], c("command"), launch.command, c("commandDesc"))}{textField(["launch", "cwd"], c("cwd"), launch.cwd, c("cwdDesc"))}</div>
          {arrayField(["launch", "args"], c("args"), launch.args)}
          {mapField(["launch", "env"], c("env"), launch.env, true)}
        </>}
        {managedContainer && <>
          {textField(["launch", "image"], c("containerImage"), launch.image, c("containerImageDesc"))}
          {arrayField(["launch", "args"], c("args"), launch.args)}
          {mapField(["launch", "environment"], c("env"), launch.environment, true)}
        </>}
        {http && <>
          <Field id={fieldId("/transport/endpoint")} label={c("endpoint")} desc={endpointKept ? (zh ? "保留此配置已保存的地址；服务端不会返回完整地址。" : "Keep this config’s saved endpoint; the server does not return the full value.") : c("endpointDesc")} error={fieldError("/transport/endpoint")}>
            {endpointKept ? <div className="manifest-toggle"><span className="text-sm">{zh ? "使用已保存的地址" : "Use saved endpoint"}</span><Button type="button" variant="outline" size="sm" disabled={locked} onClick={() => set(["transport", "endpoint"], "")}>{zh ? "替换地址" : "Replace endpoint"}</Button></div> : <>
              <Input id={fieldId("/transport/endpoint")} data-manifest-path="/transport/endpoint" aria-invalid={Boolean(fieldError("/transport/endpoint"))} aria-describedby={`${fieldId("/transport/endpoint")}-help${fieldError("/transport/endpoint") ? ` ${fieldId("/transport/endpoint")}-error` : ""}`} value={typeof transport.endpoint === "string" ? transport.endpoint : ""} disabled={locked} onBlur={() => touch("/transport/endpoint")} onChange={(event) => set(["transport", "endpoint"], event.target.value)} />
              {initialContext.current.originalEndpointMasked && <Button type="button" size="sm" variant="ghost" disabled={locked} onClick={() => set(["transport", "endpoint"], REDACTED_ENDPOINT)}>{zh ? "保留原地址" : "Keep original endpoint"}</Button>}
            </>}
            <McpHttpTrustControl serverId={typeof manifest.id === "string" ? manifest.id : ""} endpoint={transport.endpoint}
              draftRevision={revision} precheckSequence={precheckSequence.current} canManage={canManageHttpTrust} saved={selectedConfigId === manifest.id} locked={locked} zh={zh}
              denied={Boolean(validation?.checks.some(item => item.metadata?.code === "private_http_untrusted"))}
              onBusyChange={setTrustBusy} onStateChange={setTrustState} onPolicyUpdated={async () => { setChecked(null) }} />
          </Field>
        </>}
        {numberField(["timeout_seconds"], c("timeoutSeconds"), manifest.timeout_seconds, 1, 30)}
        {http && <>
          <McpHttpAuthEditor value={transport.headers} serverId={typeof manifest.id === "string" ? manifest.id : ""}
            endpoint={credentialEndpoint} zh={zh} disabled={locked} credentials={credentials} loading={credentialsLoading}
            loadError={credentialsError} canCreate={canManageCredentials} onReload={() => setCredentialsReload(sequence => sequence + 1)}
            onChange={updateAuthHeaders} onPendingChange={setCredentialBusy} onDraftChange={setAuthDraftReason}
            onCreated={credentialCreated}
            onAdvanced={showAdvancedHeaders} onHomeTemplate={applyHomeTemplate} />
          {connectionFeedback}
          <details ref={advancedHeaders} className="manifest-section">
            <summary>{zh ? "高级请求头" : "Advanced headers"}<span className="ml-2 text-xs text-muted-foreground">{Object.keys(getRecord(transport.headers)).length || (zh ? "可选" : "Optional")}</span></summary>
            <div className="manifest-section-content">{mapField(["transport", "headers"], zh ? "HTTP 请求头" : "HTTP headers", transport.headers, true)}<p className="text-xs text-muted-foreground">{zh ? "Content-Type、Accept 与 MCP 协议头由 Gate 生成，无需手动填写。" : "Gate generates Content-Type, Accept and MCP protocol headers; do not enter them manually."}</p></div>
          </details>
        </>}
        {mode === "external_http" && [
          { path: ["restart_policy", "enabled"], value: policy.enabled, label: c("restartPolicy"), reason: c("restartUnsupported") },
          { path: ["restart_policy", "health_check", "enabled"], value: health.enabled, label: c("healthCheck"), reason: c("healthRestartUnsupported") },
        ].filter(item => item.value === true).map(item => <Field key={item.path.join(".")} id={fieldId(`/${item.path.join("/")}`)} label={item.label} error={item.reason}>
          <Button type="button" data-manifest-path={`/${item.path.join("/")}`} disabled={locked} variant="outline" onClick={() => set(item.path, false)}>{zh ? "明确关闭不支持的配置" : "Turn off the unsupported setting"}</Button>
        </Field>)}
        {managed && <>
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
        <details className="manifest-section">
          <summary>{zh ? "高级配置" : "Advanced configuration"}{[launch.mounts, launch.resources, launch.toolchain, launch.package, transport.protocol_version, manifest.roots, manifest.user_credentials, manifest.analysis].some(item => item != null && (Array.isArray(item) ? item.length > 0 : typeof item === "object" ? Object.keys(item).length > 0 : true)) && <span className="ml-2 text-xs text-muted-foreground">{zh ? "含 JSON 配置" : "Contains JSON settings"}</span>}</summary>
          <div className="manifest-section-content">
            {http && validationButton}
            <AdvancedManifestSummary manifest={manifest} container={managedContainer} zh={zh} onEdit={switchToJson} disabled={locked} />
            <Field id={fieldId("/permissions")} label={c("permissions")} desc={c("permissionsDesc")} error={fieldError("/permissions")} readOnly>
              <pre tabIndex={0} data-manifest-path="/permissions" className="overflow-x-auto whitespace-pre-wrap text-xs">{manifest.permissions === undefined ? (zh ? "未声明" : "Not declared") : prettyJson(manifest.permissions)}</pre>
              <Button type="button" size="sm" variant="ghost" disabled={locked} onClick={switchToJson}>{zh ? "在 JSON 中编辑权限声明" : "Edit access declarations in JSON"}</Button>
            </Field>
          </div>
        </details>
      </div> : <Field id={fieldId("json")} label={c("rawJson")} desc={c("rawJsonDesc")}>
        <Textarea id={fieldId("json")} data-manifest-json aria-describedby={`${fieldId("json")}-help`} className="manifest-json" spellCheck={false} value={value} disabled={locked} onChange={(event) => onChange(event.target.value)} />
      </Field>}
    </div>
    {footerContainer ? createPortal(footer, footerContainer) : footer}
  </div>
}

/** Known JSON-only configuration stays discoverable without reproducing a second editor. */
function AdvancedManifestSummary({ manifest, container, zh, onEdit, disabled }: {
  manifest: ManifestLike; container: boolean; zh: boolean; onEdit: () => unknown; disabled: boolean
}) {
  const launch = getRecord(manifest.launch), transport = getRecord(manifest.transport)
  const resources = getRecord(launch.resources), toolchain = getRecord(launch.toolchain)
  const resourceStructureValid = launch.resources == null || typeof launch.resources === "object" && !Array.isArray(launch.resources)
  const resourceLimit = (key: string, fallback: string, kind: "string" | "number") => !Object.prototype.hasOwnProperty.call(resources, key) ? fallback : typeof resources[key] === kind ? String(resources[key]) : (zh ? "需校验" : "Needs validation")
  const count = (value: unknown) => Array.isArray(value) ? String(value.length) : value == null ? "0" : (zh ? "需校验" : "Needs validation")
  const scalar = (value: unknown, fallback: string) => typeof value === "string" || typeof value === "number" ? String(value) : value == null ? fallback : (zh ? "需校验" : "Needs validation")
  const rows: { path: string; label: string; value: string; help: string }[] = []
  if (container || Array.isArray(launch.mounts) && launch.mounts.length) rows.push({ path: "launch.mounts", label: zh ? "容器挂载" : "Container mounts", value: `${count(launch.mounts)} ${zh ? "项" : "mounts"}`, help: zh ? "在 JSON 中配置来源路径和容器目标；挂载仅支持只读，并须通过执行节点的路径检查。" : "Configure source and target paths in JSON. Mounts support read-only access and must pass execution-node path checks." })
  if (container || launch.resources != null) rows.push({ path: "launch.resources", label: zh ? "容器资源上限" : "Container resource limits", value: resourceStructureValid ? `${resourceLimit("memory", "512m", "string")} · ${resourceLimit("cpus", "1", "number")} CPU · ${resourceLimit("pids_limit", "128", "number")} ${zh ? "进程" : "PIDs"}${launch.resources == null ? zh ? "（默认）" : " (defaults)" : ""}` : (zh ? "需校验" : "Needs validation"), help: zh ? "高级 JSON 可配置内存、CPU 和进程数上限。未指定时采用服务端默认值；实际范围由服务端校验。" : "Advanced JSON configures memory, CPU and PID limits. Omitted values use server defaults; the server validates supported ranges." })
  if (launch.toolchain != null) rows.push({ path: "launch.toolchain", label: zh ? "固定工具链" : "Pinned toolchain", value: `${scalar(toolchain.manager, "—")}@${scalar(toolchain.version, "—")}`, help: zh ? "版本、管理器和启动命令共同约束执行环境。修改时请在 JSON 中一并校验，普通名称编辑不会改动它们。" : "The manager, exact version and command jointly constrain execution. Edit them together in JSON; changing the display name preserves them." })
  if (launch.package != null) rows.push({ path: "launch.package", label: zh ? "包缓存元数据" : "Package cache metadata", value: getRecord(launch.package).cache === false ? (zh ? "已配置 · 缓存关闭" : "Configured · Cache off") : (zh ? "已配置" : "Configured"), help: zh ? "这是包缓存与诊断元数据；实际执行仍由启动命令和参数决定。" : "This metadata supports package caching and diagnostics. The command and arguments still determine what executes." })
  if (transport.protocol_version != null) rows.push({ path: "transport.protocol_version", label: zh ? "协议版本" : "Protocol version", value: scalar(transport.protocol_version, "—"), help: zh ? "显式协议版本保留在 JSON 中，保存及连接仍须满足服务端支持范围。" : "An explicit protocol version remains in JSON and must be supported by server validation and connection handling." })
  if (Array.isArray(manifest.user_credentials) && manifest.user_credentials.length) rows.push({ path: "user_credentials", label: zh ? "用户凭据槽位" : "User credential slots", value: `${count(manifest.user_credentials)} ${zh ? "项" : "slots"}`, help: zh ? "定义需要的 HTTP 凭据槽位及注入模板；秘密值在独立凭据流程中填写，不保存在此声明里。" : "Defines HTTP credential slots and injection templates. Secret values belong to the separate credential flow, not this declaration." })
  if (Array.isArray(manifest.roots) && manifest.roots.length) rows.push({ path: "roots", label: zh ? "根路径声明" : "Root declarations", value: `${count(manifest.roots)} ${zh ? "项" : "roots"}`, help: zh ? "当前用于路径预检查，不等于容器挂载或用户文件访问授权。" : "Currently used by path prechecks. These declarations do not configure container mounts or grant users file access." })
  if (manifest.analysis != null && Object.keys(getRecord(manifest.analysis)).length) rows.push({ path: "analysis", label: zh ? "分析元数据" : "Analysis metadata", value: zh ? "已配置" : "Configured", help: zh ? "任意结构的分析结果保留在 JSON，避免表单重建时丢失嵌套值。" : "Structured analysis metadata remains in JSON so nested values survive form edits." })
  return rows.length ? <div className="space-y-4">{rows.map(row => <Field key={row.path} id={`advanced-${row.path}`} label={row.label} desc={row.help} readOnly>
    <div className="flex flex-wrap items-center gap-2"><span className="min-w-0 break-all text-sm">{row.value}</span><Button type="button" size="sm" variant="ghost" disabled={disabled} aria-label={`${zh ? "在 JSON 中编辑" : "Edit in JSON"} ${row.label}`} onClick={onEdit}>JSON</Button></div>
  </Field>)}</div> : null
}

function ValidationPanel({ validation, issues, onSelect, c }: { validation: ManifestValidationResponse | null; issues: ValidationIssue[]; onSelect: (issue: ValidationIssue) => void; c: CopyFn }) {
  const backendState = validation ? manifestValidationStatus(validation) : "success"
  const errors = Math.max(backendState === "error" ? 1 : 0, validation?.summary.errors || 0, issues.filter(issue => issue.severity === "error").length)
  const warnings = Math.max(validation?.summary.warnings || 0, issues.filter(issue => issue.severity === "warning").length)
  const state = errors > 0 ? "error" : warnings > 0 || backendState === "warning" ? "warning" : "success"
  const status = state === "error" ? `${c("notRecommended")} · ${errors} ${c("errors")}` : state === "warning" ? `${c("saveWithWarning")} · ${warnings} ${c("warnings")}` : c("saveOk")
  const additional = validation?.checks.filter(check => check.severity === "ok" || check.severity === "info") || []
  return <div className="manifest-validation" role="status">
    <Badge variant={state === "error" ? "danger" : state === "warning" ? "warning" : "success"}>{status}</Badge>
    {issues.length > 0 && <ValidationErrors title={c("issues")} issues={issues} onSelect={onSelect} />}
    {state !== "error" && additional.length > 0 && <details className="mt-2 text-xs"><summary className="cursor-pointer">{c("diagnostics")}</summary><ul className="mt-2 space-y-1">{additional.map((check, i) => <li key={i}>{check.name} · {check.message}</li>)}</ul></details>}
  </div>
}

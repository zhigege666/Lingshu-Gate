import { useEffect, useMemo, useState, type ReactNode } from "react"
import {
  AlertCircle,
  Braces,
  Check,
  Cpu,
  FileCode2,
  Globe,
  Info,
  Key,
  LayoutTemplate,
  RefreshCw,
  Save,
  Server,
  ShieldCheck,
  Sliders,
  Terminal,
  Wand2,
  X,
} from "lucide-react"
import { api, type Credential, type ManifestValidationResponse } from "@/api/client"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import {
  credentialRef,
  envKeyFromCredential,
  formatManifestJson,
  getRecord,
  parseArgs,
  parseEnv,
  parseManifest,
  parseNumberList,
  precheckManifest,
  runtimeModeFromManifest,
  sensitiveEnvKeys,
  stringifyArgs,
  stringifyEnv,
  stringifyNumberList,
  withoutUserCredentialValues,
  type ManifestLike,
  type PrecheckResult,
  type RuntimeMode,
} from "@/features/mcp-config/model"
import type { Locale } from "@/i18n"
import { prettyJson } from "@/lib/utils"

type McpConfigEditorProps = {
  locale: Locale
  selectedConfigId: string
  value: string
  onChange: (value: string) => void
  onSave: (nextValue?: string) => void | Promise<void>
  onClose?: () => void
  busy: boolean
}

const FORM_COPY = {
  "zh-CN": {
    newConfig: "新增 MCP Config",
    editConfig: "编辑",
    formDesc: "表单支持受管 Stdio、外部 HTTP 和受管 HTTP；复杂字段仍可在 JSON 中保留。",
    parseErrorPrefix: "JSON / 预检查失败：",
    credentialErrorPrefix: "凭据列表加载失败：",
    localErrors: "保存前本地预检查错误",
    localWarnings: "本地配置提醒",
    sensitiveEnv: "已识别敏感环境变量",
    sensitiveEnvHint: "建议使用凭据引用，避免把明文密钥写入 Manifest。",
    serverId: "服务 ID",
    serverIdDesc: "MCP Server 的唯一标识，只能包含字母、数字、点、下划线和短横线。",
    name: "名称",
    nameDesc: "Console 中展示的服务名称，建议使用容易识别的业务名称。",
    runtimeMode: "运行方式",
    runtimeModeDesc: "选择 Lingshu Gate 如何获得服务，以及使用哪种 MCP 传输连接。",
    managedStdio: "受管 Stdio",
    managedStdioDesc: "由 Lingshu Gate 启动本地可执行进程，通过标准输入输出交互。",
    externalHttp: "外部 HTTP",
    externalHttpDesc: "服务独立运行在外部，Lingshu Gate 仅负责 streamable_http 连接。",
    managedHttp: "受管 HTTP",
    managedHttpDesc: "由 Lingshu Gate 启动后台服务，并等待其 HTTP 端口就绪建立连接。",
    advancedMode: "高级模式",
    advancedModeDesc: "保留当前 Manifest 的复杂运行与传输配置，仅在 JSON 中直接编辑。",
    advancedModeHint: "当前 Manifest 使用表单尚未覆盖的运行组合。应用表单时会原样保留 launch、transport、auto_start 与 restart_policy，避免静默改写。",
    endpoint: "MCP 地址",
    endpointDesc: "streamable_http 地址，例如 http://127.0.0.1:3120/mcp。",
    externalManagedHint: "该服务由外部进程管理，Lingshu Gate 只负责连接或断开，不负责启动、停止或自动重启。",
    command: "启动命令",
    commandDesc: "managed_process 要执行的已安装可执行文件或绝对路径。",
    cwd: "工作目录",
    cwdDesc: "可选。命令启动时的工作目录，例如 /workspace。",
    args: "启动参数",
    argsDesc: "一行一个参数，保存时会同步到 launch.args。",
    env: "环境变量",
    envDesc: "一行一个 KEY=VALUE，敏感值建议使用 ${credential:ID}。",
    insertCredential: "插入凭据引用",
    insertCredentialDesc: "点击凭据后会插入一行 KEY=${credential:ID} 到环境变量。",
    timeoutSeconds: "超时秒数",
    timeoutSecondsDesc: "MCP 初始化和请求等待的默认超时时间。",
    autoStart: "开机自启",
    autoStartDesc: "仅记录运行意图；保存与应用配置均不会直接启动服务。",
    restartPolicy: "崩溃重启策略",
    restartPolicyDesc: "进程退出、启动失败、健康检查失败后的自动恢复策略。",
    maxAttempts: "最大尝试次数",
    maxAttemptsDesc: "达到次数后停止自动重启，0 表示不重试。",
    delaySeconds: "初始延迟",
    delaySecondsDesc: "第一次自动重启前等待的秒数。",
    backoff: "退避倍数",
    backoffDesc: "每次失败后的延迟增长倍数。",
    maxDelay: "最大延迟",
    maxDelayDesc: "退避后允许等待的最大秒数。",
    resetAfterSeconds: "重置计数",
    resetAfterSecondsDesc: "服务稳定运行超过该秒数后，重置当前重启尝试次数。",
    restartOnExit: "进程退出后重启",
    restartOnExitDesc: "开启后，非策略排除的退出会触发自动重启。",
    exitAllowlist: "退出码允许列表",
    exitAllowlistDesc: "逗号分隔。填写后只有这些退出码会触发重启。",
    exitBlocklist: "退出码阻止列表",
    exitBlocklistDesc: "逗号分隔。命中后不会自动重启，常用 0 表示正常退出不重启。",
    healthCheck: "健康检查探活",
    healthCheckDesc: "当前通过 MCP tools/list 检查已连接服务是否健康。",
    intervalSeconds: "检查间隔",
    intervalSecondsDesc: "两次健康检查之间的等待时间。",
    healthTimeoutSeconds: "检查超时",
    healthTimeoutSecondsDesc: "单次健康检查最多等待的时间。",
    failureThreshold: "失败阈值",
    failureThresholdDesc: "连续失败达到该次数后触发恢复策略。",
    endpointRequired: "HTTP 运行方式需要填写 transport.endpoint",
    endpointInvalid: "MCP 地址必须是有效的 HTTP/HTTPS URL",
    applyForm: "应用表单到 JSON",
    formatJson: "格式化 JSON",
    backendPrecheck: "后端预检查",
    saveAndApply: "保存配置",
    rawJson: "Manifest JSON",
    rawJsonDesc: "复杂字段可以继续在 JSON 中编辑；应用表单时会保留未在表单中展示的字段。",
    precheckFailed: "预检查失败：",
    backendPrecheckFailed: "后端预检查失败：",
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
    launchTypeWarning: "当前表单主要覆盖 managed_process；其它 launch.type 请检查 Manifest JSON",
    argsWarning: "launch.args 建议全部使用字符串",
    transportTypeRequired: "transport.type 不能为空",
    stdioLaunchError: "transport.type=stdio 要求 launch.type 为 managed_process 或 managed_container",
    streamableEndpointError: "streamable_http 需要填写 transport.endpoint",
    timeoutWarning: "timeout_seconds 建议设置为大于 0 的数字",
  },
  "en-US": {
    newConfig: "New MCP Config",
    editConfig: "Edit",
    formDesc: "The form supports managed Stdio, external HTTP, and managed HTTP. Complex fields remain available in JSON.",
    parseErrorPrefix: "JSON / precheck failed: ",
    credentialErrorPrefix: "Failed to load credentials: ",
    localErrors: "Local precheck errors before saving",
    localWarnings: "Local config warnings",
    sensitiveEnv: "Sensitive env detected",
    sensitiveEnvHint: "Use credential references instead of storing plaintext secrets in the Manifest.",
    serverId: "Server ID",
    serverIdDesc: "Unique MCP Server identifier. Use letters, numbers, dots, underscores, and hyphens only.",
    name: "Name",
    nameDesc: "Display name in Console. Use a clear business name.",
    runtimeMode: "Runtime Mode",
    runtimeModeDesc: "Choose how Lingshu Gate obtains the service and connects to its MCP transport.",
    managedStdio: "Managed Stdio",
    managedStdioDesc: "Lingshu Gate starts the process and connects over standard input/output.",
    externalHttp: "External HTTP",
    externalHttpDesc: "The service runs independently. Lingshu Gate only connects or disconnects.",
    managedHttp: "Managed HTTP",
    managedHttpDesc: "Lingshu Gate starts the process and waits for the HTTP MCP endpoint.",
    advancedMode: "Advanced Mode",
    advancedModeDesc: "Preserve the current runtime and transport configuration; edit it in JSON.",
    advancedModeHint: "This Manifest uses a runtime combination not covered by the form. Applying the form preserves launch, transport, auto_start, and restart_policy without silently rewriting them.",
    endpoint: "MCP Endpoint",
    endpointDesc: "Streamable HTTP endpoint, for example http://127.0.0.1:3120/mcp.",
    externalManagedHint: "This service is externally managed. Lingshu Gate only connects or disconnects and does not start, stop, or restart the process.",
    command: "Command",
    commandDesc: "Installed executable or absolute path used by managed_process.",
    cwd: "Working Directory",
    cwdDesc: "Optional command working directory, for example /workspace.",
    args: "Arguments",
    argsDesc: "One argument per line. Saved into launch.args.",
    env: "Environment Variables",
    envDesc: "One KEY=VALUE per line. Use ${credential:ID} for sensitive values.",
    insertCredential: "Insert Credential Reference",
    insertCredentialDesc: "Click a credential to insert KEY=${credential:ID} into env.",
    timeoutSeconds: "Timeout Seconds",
    timeoutSecondsDesc: "Default timeout for MCP initialization and requests.",
    autoStart: "Auto Start",
    autoStartDesc: "Records runtime intent only; saving or applying does not directly start the server.",
    restartPolicy: "Restart Policy",
    restartPolicyDesc: "Auto recovery policy after process exit, startup failure, or health-check failure.",
    maxAttempts: "Max Attempts",
    maxAttemptsDesc: "Stop auto restart after this count. 0 means no retry.",
    delaySeconds: "Initial Delay",
    delaySecondsDesc: "Seconds to wait before the first auto restart.",
    backoff: "Backoff Multiplier",
    backoffDesc: "Delay growth multiplier after each failure.",
    maxDelay: "Max Delay",
    maxDelayDesc: "Maximum delay after backoff.",
    resetAfterSeconds: "Reset After",
    resetAfterSecondsDesc: "Reset restart attempts after the server stays stable for this duration.",
    restartOnExit: "Restart On Exit",
    restartOnExitDesc: "Restart automatically when the exit code is not excluded by policy.",
    exitAllowlist: "Exit Code Allowlist",
    exitAllowlistDesc: "Comma separated. When set, only these exit codes trigger restart.",
    exitBlocklist: "Exit Code Blocklist",
    exitBlocklistDesc: "Comma separated. Matching codes will not restart. 0 usually means normal exit.",
    healthCheck: "Health Check",
    healthCheckDesc: "Uses MCP tools/list to check whether the connected service is healthy.",
    intervalSeconds: "Interval",
    intervalSecondsDesc: "Delay between health checks.",
    healthTimeoutSeconds: "Timeout",
    healthTimeoutSecondsDesc: "Maximum wait time for one health check.",
    failureThreshold: "Failure Threshold",
    failureThresholdDesc: "Trigger recovery after this many consecutive failures.",
    endpointRequired: "HTTP runtime modes require transport.endpoint",
    endpointInvalid: "MCP endpoint must be a valid HTTP/HTTPS URL",
    applyForm: "Apply Form to JSON",
    formatJson: "Format JSON",
    backendPrecheck: "Backend Precheck",
    saveAndApply: "Save Config",
    rawJson: "Manifest JSON",
    rawJsonDesc: "Complex fields remain editable in JSON. Applying the form preserves fields not represented above.",
    precheckFailed: "Precheck failed: ",
    backendPrecheckFailed: "Backend precheck failed: ",
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
    launchTypeWarning: "This form mainly covers managed_process. Check Manifest JSON for other launch.type values.",
    argsWarning: "launch.args should all be strings",
    transportTypeRequired: "transport.type is required",
    stdioLaunchError: "transport.type=stdio requires launch.type to be managed_process or managed_container",
    streamableEndpointError: "streamable_http requires transport.endpoint",
    timeoutWarning: "timeout_seconds should be greater than 0",
  },
} satisfies Record<Locale, Record<string, string>>

type CopyKey = keyof typeof FORM_COPY["zh-CN"]
type CopyFn = (key: CopyKey) => string

function Field({
  label,
  desc,
  children,
  className = "",
  extra,
}: {
  label: string
  desc?: string
  children: ReactNode
  className?: string
  extra?: ReactNode
}) {
  return (
    <div className={`flex flex-col gap-1.5 ${className}`}>
      <div className="flex items-center justify-between">
        <Label className="font-medium text-xs text-foreground/90">{label}</Label>
        {extra}
      </div>
      {children}
      {desc && <div className="text-[11px] text-muted-foreground/80 leading-tight">{desc}</div>}
    </div>
  )
}

function NumberField({
  label,
  desc,
  value,
  onChange,
  min = 0,
  step = 1,
  suffix,
  className = "",
}: {
  label: string
  desc?: string
  value: number
  onChange: (val: number) => void
  min?: number
  step?: number
  suffix: string
  className?: string
}) {
  return (
    <Field label={label} desc={desc} className={className}>
      <div className="relative flex items-center">
        <Input
          type="number"
          min={min}
          step={step}
          value={value}
          onChange={(e) => onChange(Number(e.target.value || min))}
          className="h-9 pr-10 font-mono text-xs bg-muted/20 border-border/70"
        />
        <span className="absolute right-3 text-xs font-medium text-muted-foreground pointer-events-none select-none">
          {suffix}
        </span>
      </div>
    </Field>
  )
}

function SwitchRow({
  title,
  desc,
  checked,
  onCheckedChange,
  disabled = false,
  className = "",
}: {
  title: string
  desc?: string
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  disabled?: boolean
  className?: string
}) {
  return (
    <div
      className={`flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/15 transition-colors ${
        disabled ? "opacity-60 cursor-not-allowed" : "hover:bg-muted/25"
      } ${className}`}
    >
      <div className="flex flex-col gap-0.5">
        <span className="text-xs font-medium text-foreground">{title}</span>
        {desc && <span className="text-[11px] text-muted-foreground">{desc}</span>}
      </div>
      <Switch checked={checked} disabled={disabled} onCheckedChange={onCheckedChange} />
    </div>
  )
}

export function McpConfigEditor({ locale, selectedConfigId, value, onChange, onSave, onClose, busy }: McpConfigEditorProps) {
  const copy = FORM_COPY[locale]
  const c: CopyFn = (key) => copy[key]
  const zh = locale === "zh-CN"
  const [activeTab, setActiveTab] = useState<"form" | "json">("form")
  const [id, setId] = useState("")
  const [name, setName] = useState("")
  const [runtimeMode, setRuntimeMode] = useState<RuntimeMode>("managed_stdio")
  const [command, setCommand] = useState("")
  const [argsText, setArgsText] = useState("")
  const [envText, setEnvText] = useState("")
  const [cwd, setCwd] = useState("")
  const [endpoint, setEndpoint] = useState("")
  const [timeoutSeconds, setTimeoutSeconds] = useState(120)
  const [autoStart, setAutoStart] = useState(false)
  const [restartEnabled, setRestartEnabled] = useState(false)
  const [restartMaxAttempts, setRestartMaxAttempts] = useState(3)
  const [restartDelaySeconds, setRestartDelaySeconds] = useState(5)
  const [restartBackoffMultiplier, setRestartBackoffMultiplier] = useState(2)
  const [restartMaxDelaySeconds, setRestartMaxDelaySeconds] = useState(60)
  const [restartOnExit, setRestartOnExit] = useState(true)
  const [restartResetAfterSeconds, setRestartResetAfterSeconds] = useState(300)
  const [exitCodeAllowlistText, setExitCodeAllowlistText] = useState("")
  const [exitCodeBlocklistText, setExitCodeBlocklistText] = useState("")
  const [healthCheckEnabled, setHealthCheckEnabled] = useState(false)
  const [healthIntervalSeconds, setHealthIntervalSeconds] = useState(30)
  const [healthTimeoutSeconds, setHealthTimeoutSeconds] = useState(10)
  const [healthFailureThreshold, setHealthFailureThreshold] = useState(3)
  const [parseError, setParseError] = useState<string | null>(null)
  const [validation, setValidation] = useState<ManifestValidationResponse | null>(null)
  const [validating, setValidating] = useState(false)
  const [credentials, setCredentials] = useState<Credential[]>([])
  const [credentialError, setCredentialError] = useState<string | null>(null)

  const manifest = useMemo(() => {
    try {
      return parseManifest(value)
    } catch {
      return null
    }
  }, [value])

  const precheck = useMemo<PrecheckResult>(() => {
    if (!manifest) return { errors: parseError ? [parseError] : [], warnings: [] }
    return precheckManifest(manifest, c)
  }, [manifest, parseError, locale])
  const sensitiveKeys = useMemo(() => sensitiveEnvKeys(envText), [envText])
  const canSave = Boolean(manifest) && precheck.errors.length === 0

  useEffect(() => {
    void api.credentials().then(setCredentials).catch((err) => setCredentialError(err instanceof Error ? err.message : String(err)))
  }, [])

  useEffect(() => {
    try {
      const next = parseManifest(value)
      const launch = getRecord(next.launch)
      const transport = getRecord(next.transport)
      const policy = getRecord(next.restart_policy)
      const health = getRecord(policy.health_check)
      setId(String(next.id || ""))
      setName(String(next.name || ""))
      setRuntimeMode(runtimeModeFromManifest(next))
      setCommand(String(launch.command || ""))
      setArgsText(stringifyArgs(launch.args))
      setEnvText(stringifyEnv(launch.env))
      setCwd(String(launch.cwd || ""))
      setEndpoint(String(transport.endpoint || ""))
      setTimeoutSeconds(Number(next.timeout_seconds || 120))
      setAutoStart(Boolean(next.auto_start ?? false))
      setRestartEnabled(Boolean(policy.enabled ?? false))
      setRestartMaxAttempts(Number(policy.max_attempts ?? 3))
      setRestartDelaySeconds(Number(policy.delay_seconds ?? 5))
      setRestartBackoffMultiplier(Number(policy.backoff_multiplier ?? 2))
      setRestartMaxDelaySeconds(Number(policy.max_delay_seconds ?? 60))
      setRestartOnExit(Boolean(policy.restart_on_exit ?? true))
      setRestartResetAfterSeconds(Number(policy.reset_after_seconds ?? 300))
      setExitCodeAllowlistText(stringifyNumberList(policy.exit_code_allowlist))
      setExitCodeBlocklistText(stringifyNumberList(policy.exit_code_blocklist))
      setHealthCheckEnabled(Boolean(health.enabled ?? false))
      setHealthIntervalSeconds(Number(health.interval_seconds ?? 30))
      setHealthTimeoutSeconds(Number(health.timeout_seconds ?? 10))
      setHealthFailureThreshold(Number(health.failure_threshold ?? 3))
      setParseError(null)
      setValidation(null)
    } catch (err) {
      setParseError(err instanceof Error ? err.message : String(err))
    }
  }, [value])

  function buildManifestFromForm(): ManifestLike {
    const current = parseManifest(value)
    const currentLaunch = getRecord(current.launch)
    const currentTransport = getRecord(current.transport)
    const currentPolicy = getRecord(current.restart_policy)
    const currentHealth = getRecord(currentPolicy.health_check)
    const advanced = runtimeMode === "advanced"
    const managedProcess = runtimeMode === "managed_stdio" || runtimeMode === "managed_http"
    const http = runtimeMode === "external_http" || runtimeMode === "managed_http"
    const nextLaunch: Record<string, unknown> = advanced
      ? { ...currentLaunch }
      : { ...currentLaunch, type: managedProcess ? "managed_process" : "external" }
    if (managedProcess) {
      nextLaunch.command = command.trim()
      nextLaunch.args = parseArgs(argsText)
      nextLaunch.env = parseEnv(envText)
      if (cwd.trim()) nextLaunch.cwd = cwd.trim()
      else delete nextLaunch.cwd
    }

    const nextTransport: Record<string, unknown> = advanced
      ? { ...currentTransport }
      : { ...currentTransport, type: http ? "streamable_http" : "stdio" }
    if (!advanced) {
      if (http) nextTransport.endpoint = endpoint.trim()
      else delete nextTransport.endpoint
    }

    const policyEnabled = managedProcess && restartEnabled
    const nextPolicy = advanced ? currentPolicy : {
      ...currentPolicy,
      enabled: policyEnabled,
      max_attempts: Number(restartMaxAttempts || 0),
      delay_seconds: Number(restartDelaySeconds || 0),
      backoff_multiplier: Number(restartBackoffMultiplier || 1),
      max_delay_seconds: Number(restartMaxDelaySeconds || 0),
      restart_on_exit: restartOnExit,
      reset_after_seconds: Number(restartResetAfterSeconds || 0),
      exit_code_allowlist: parseNumberList(exitCodeAllowlistText),
      exit_code_blocklist: parseNumberList(exitCodeBlocklistText),
      health_check: {
        ...currentHealth,
        enabled: policyEnabled && healthCheckEnabled,
        method: "tools_list",
        interval_seconds: Number(healthIntervalSeconds || 30),
        timeout_seconds: Number(healthTimeoutSeconds || 10),
        failure_threshold: Number(healthFailureThreshold || 3),
      },
    }

    return {
      ...current,
      id: id.trim(),
      name: name.trim(),
      launch: nextLaunch,
      transport: nextTransport,
      timeout_seconds: Number(timeoutSeconds || 120),
      auto_start: advanced ? current.auto_start : managedProcess ? autoStart : false,
      restart_policy: nextPolicy,
    }
  }

  function insertCredentialRef(credential: Credential) {
    const line = `${envKeyFromCredential(credential.id)}=${credentialRef(credential.id)}`
    setEnvText((current) => current.trim() ? `${current.trim()}\n${line}` : line)
    setValidation(null)
  }

  function applyFormToJson() {
    try {
      const next = buildManifestFromForm()
      onChange(prettyJson(next))
      setParseError(null)
      setValidation(null)
    } catch (err) {
      setParseError(err instanceof Error ? err.message : String(err))
    }
  }

  function formatJson() {
    try {
      onChange(formatManifestJson(value))
      setParseError(null)
      setValidation(null)
    } catch (err) {
      setParseError(err instanceof Error ? err.message : String(err))
    }
  }

  async function validateWithBackend(): Promise<ManifestValidationResponse | null> {
    setValidating(true)
    setValidation(null)
    setParseError(null)
    try {
      const next = buildManifestFromForm()
      const nextText = prettyJson(next)
      onChange(nextText)
      const result = await api.validateConfig(withoutUserCredentialValues(next) as Record<string, unknown>, selectedConfigId || null)
      setValidation(result)
      return result
    } catch (err) {
      setParseError(err instanceof Error ? err.message : String(err))
      return null
    } finally {
      setValidating(false)
    }
  }

  async function saveAfterPrecheck() {
    try {
      const next = buildManifestFromForm()
      const latestPrecheck = precheckManifest(next, c)
      if (latestPrecheck.errors.length > 0) {
        setParseError(`${c("precheckFailed")}${latestPrecheck.errors.join("; ")}`)
        return
      }
      const result = await validateWithBackend()
      if (!result) return
      if (result.summary.errors > 0) {
        setParseError(`${c("backendPrecheckFailed")}${result.summary.errors}`)
        return
      }
      const nextText = prettyJson(next)
      onChange(nextText)
      setParseError(null)
      await onSave(nextText)
    } catch (err) {
      setParseError(err instanceof Error ? err.message : String(err))
    }
  }

  const RUNTIME_MODES: Array<{
    id: RuntimeMode
    title: string
    desc: string
    icon: typeof Terminal
  }> = [
    { id: "managed_stdio", title: c("managedStdio"), desc: c("managedStdioDesc"), icon: Terminal },
    { id: "external_http", title: c("externalHttp"), desc: c("externalHttpDesc"), icon: Globe },
    { id: "managed_http", title: c("managedHttp"), desc: c("managedHttpDesc"), icon: Cpu },
    { id: "advanced", title: c("advancedMode"), desc: c("advancedModeDesc"), icon: Sliders },
  ]

  return (
    <div className="flex h-full flex-col bg-background text-foreground">
      {/* 顶部 Tab 切换与概要状态 */}
      <div className="flex items-center justify-between border-b px-8 py-3 bg-muted/20 shrink-0">
        <div className="flex items-center gap-1.5 rounded-lg bg-muted/80 p-1">
          <button
            type="button"
            className={`flex items-center gap-2 rounded-md px-3.5 py-1.5 text-xs font-medium transition-all ${
              activeTab === "form"
                ? "bg-background text-foreground shadow-xs font-semibold"
                : "text-muted-foreground hover:text-foreground"
            }`}
            onClick={() => setActiveTab("form")}
          >
            <LayoutTemplate className="size-3.5" />
            {zh ? "可视化表单" : "Visual Form"}
          </button>
          <button
            type="button"
            className={`flex items-center gap-2 rounded-md px-3.5 py-1.5 text-xs font-medium transition-all ${
              activeTab === "json"
                ? "bg-background text-foreground shadow-xs font-semibold"
                : "text-muted-foreground hover:text-foreground"
            }`}
            onClick={() => setActiveTab("json")}
          >
            <FileCode2 className="size-3.5" />
            {zh ? "JSON 源码编辑" : "Raw JSON Editor"}
          </button>
        </div>

        <div className="flex items-center gap-3">
          {validation && (
            <Badge variant={validation.summary.errors > 0 ? "danger" : validation.summary.warnings > 0 ? "warning" : "success"}>
              {validation.summary.errors > 0
                ? (zh ? "预检查未通过" : "Precheck Failed")
                : (zh ? "后端预检查通过" : "Precheck OK")}
            </Badge>
          )}
        </div>
      </div>

      {/* 中间滚动区 */}
      <div className="flex-1 overflow-y-auto px-8 py-6 space-y-6">
        {parseError && (
          <Alert variant="destructive" className="border-destructive/30 bg-destructive/10">
            <AlertCircle className="size-4" />
            <AlertDescription className="ml-2 font-medium">
              {c("parseErrorPrefix")}{parseError}
            </AlertDescription>
          </Alert>
        )}
        {credentialError && (
          <Alert className="border-warning/30 bg-warning/10 text-warning-foreground">
            <AlertCircle className="size-4" />
            <AlertDescription className="ml-2">{c("credentialErrorPrefix")}{credentialError}</AlertDescription>
          </Alert>
        )}
        {precheck.errors.length > 0 && (
          <Alert variant="destructive" className="border-destructive/30 bg-destructive/5">
            <AlertCircle className="size-4" />
            <div className="ml-2">
              <AlertTitle className="font-semibold text-xs">{c("localErrors")}</AlertTitle>
              <AlertDescription>
                <ul className="list-disc pl-4 text-xs space-y-0.5 mt-1">
                  {precheck.errors.map((item) => <li key={item}>{item}</li>)}
                </ul>
              </AlertDescription>
            </div>
          </Alert>
        )}
        {precheck.warnings.length > 0 && (
          <Alert className="border-warning/30 bg-warning/5 text-warning-foreground">
            <Info className="size-4" />
            <div className="ml-2">
              <AlertTitle className="font-semibold text-xs">{c("localWarnings")}</AlertTitle>
              <AlertDescription>
                <ul className="list-disc pl-4 text-xs space-y-0.5 mt-1">
                  {precheck.warnings.map((item) => <li key={item}>{item}</li>)}
                </ul>
              </AlertDescription>
            </div>
          </Alert>
        )}
        {sensitiveKeys.length > 0 && (
          <Alert className="border-blue-500/20 bg-blue-500/5 text-foreground text-xs">
            <Info className="size-4 text-blue-500" />
            <AlertDescription className="ml-2">
              <span className="font-semibold">{c("sensitiveEnv")}:</span> {sensitiveKeys.join(", ")}。{c("sensitiveEnvHint")}
            </AlertDescription>
          </Alert>
        )}
        {validation && <ValidationPanel validation={validation} c={c} />}

        {activeTab === "form" ? (
          <div className="space-y-6">
            {/* 核心单选卡片组：运行方式 */}
            <div className="flex flex-col gap-2">
              <div className="flex items-center justify-between">
                <div>
                  <Label className="text-sm font-semibold text-foreground">{c("runtimeMode")}</Label>
                  <p className="text-xs text-muted-foreground">{c("runtimeModeDesc")}</p>
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 pt-1">
                {RUNTIME_MODES.map((mode) => {
                  const isSelected = runtimeMode === mode.id
                  const Icon = mode.icon
                  return (
                    <button
                      key={mode.id}
                      type="button"
                      onClick={() => { setRuntimeMode(mode.id); setValidation(null) }}
                      className={`relative flex flex-col gap-2.5 p-4 rounded-xl border text-left transition-all ${
                        isSelected
                          ? "border-primary bg-primary/5 shadow-xs ring-1 ring-primary/25"
                          : "border-border/70 bg-card hover:border-border hover:bg-muted/30"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <div className={`size-8 rounded-lg flex items-center justify-center ${
                          isSelected ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"
                        }`}>
                          <Icon className="size-4.5" />
                        </div>
                        {isSelected && (
                          <span className="size-5 rounded-full bg-primary text-primary-foreground flex items-center justify-center shadow-xs">
                            <Check className="size-3 stroke-[3]" />
                          </span>
                        )}
                      </div>
                      <div>
                        <div className="text-xs font-semibold text-foreground">{mode.title}</div>
                        <div className="text-[11px] text-muted-foreground leading-relaxed mt-1">{mode.desc}</div>
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>

            {runtimeMode === "external_http" && (
              <Alert className="bg-muted/40 border-border/70 text-xs">
                <Info className="size-3.5 text-muted-foreground" />
                <AlertDescription className="ml-1.5">{c("externalManagedHint")}</AlertDescription>
              </Alert>
            )}
            {runtimeMode === "advanced" && (
              <Alert className="bg-amber-500/10 border-amber-500/20 text-xs">
                <Info className="size-3.5 text-amber-600" />
                <AlertDescription className="ml-1.5">{c("advancedModeHint")}</AlertDescription>
              </Alert>
            )}

            {/* 双栏布局：左栏（基础与进程） + 右栏（环境变量与高可用） */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* 左栏 */}
              <div className="space-y-6">
                {/* 基础属性 */}
                <Card className="border-border/70 shadow-xs">
                  <CardHeader className="pb-3 pt-4 px-5 border-b bg-muted/20">
                    <div className="flex items-center gap-2">
                      <Server className="size-4 text-primary" />
                      <CardTitle className="text-sm font-semibold">{zh ? "基础信息" : "Basic Information"}</CardTitle>
                    </div>
                    <CardDescription className="text-xs">
                      {zh ? "MCP Server 的唯一标识与展示名称" : "Server unique identifier and display name"}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="p-5 grid gap-4 sm:grid-cols-2">
                    <Field label={c("serverId")} desc={c("serverIdDesc")}>
                      <Input value={id} onChange={(event) => setId(event.target.value)} placeholder="mcp-server" className="h-9 font-mono text-xs bg-muted/20 border-border/70" />
                    </Field>
                    <Field label={c("name")} desc={c("nameDesc")}>
                      <Input value={name} onChange={(event) => setName(event.target.value)} placeholder="MCP Server" className="h-9 bg-muted/20 border-border/70" />
                    </Field>
                    <NumberField
                      label={c("timeoutSeconds")}
                      desc={c("timeoutSecondsDesc")}
                      value={timeoutSeconds}
                      onChange={setTimeoutSeconds}
                      min={1}
                      suffix={zh ? "秒" : "s"}
                    />
                    {runtimeMode !== "advanced" && (
                      <div className="flex flex-col justify-end">
                        <SwitchRow
                          title={c("autoStart")}
                          desc={runtimeMode === "external_http" ? c("externalManagedHint") : c("autoStartDesc")}
                          checked={runtimeMode === "external_http" ? false : autoStart}
                          disabled={runtimeMode === "external_http"}
                          onCheckedChange={setAutoStart}
                        />
                      </div>
                    )}
                  </CardContent>
                </Card>

                {/* 进程命令与连接 */}
                {(runtimeMode === "managed_stdio" || runtimeMode === "managed_http" || runtimeMode === "external_http") && (
                  <Card className="border-border/70 shadow-xs">
                    <CardHeader className="pb-3 pt-4 px-5 border-b bg-muted/20">
                      <div className="flex items-center gap-2">
                        <Terminal className="size-4 text-primary" />
                        <CardTitle className="text-sm font-semibold">{zh ? "进程与执行命令" : "Process & Execution"}</CardTitle>
                      </div>
                      <CardDescription className="text-xs">
                        {zh ? "可执行文件命令路径、启动参数与工作目录" : "Executable command path, parameters, and working directory"}
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="p-5 flex flex-col gap-4">
                      {(runtimeMode === "managed_stdio" || runtimeMode === "managed_http") && (
                        <>
                          <div className="grid gap-4 sm:grid-cols-2">
                            <Field label={c("command")} desc={c("commandDesc")}>
                              <Input value={command} onChange={(event) => setCommand(event.target.value)} placeholder="/path/to/mcp-server" className="h-9 font-mono text-xs bg-muted/20 border-border/70" />
                            </Field>
                            <Field label={c("cwd")} desc={c("cwdDesc")}>
                              <Input value={cwd} onChange={(event) => setCwd(event.target.value)} placeholder="/workspace" className="h-9 font-mono text-xs bg-muted/20 border-border/70" />
                            </Field>
                          </div>
                          <Field label={c("args")} desc={c("argsDesc")}>
                            <Textarea
                              className="min-h-[110px] font-mono text-xs leading-relaxed bg-slate-900/[0.03] dark:bg-slate-950/40 border-border/70 resize-y"
                              value={argsText}
                              onChange={(event) => setArgsText(event.target.value)}
                              placeholder={'--config\n/path/to/config.json\n--verbose'}
                            />
                          </Field>
                        </>
                      )}
                      {(runtimeMode === "external_http" || runtimeMode === "managed_http") && (
                        <Field label={c("endpoint")} desc={c("endpointDesc")}>
                          <Input
                            value={endpoint}
                            onChange={(event) => { setEndpoint(event.target.value); setValidation(null) }}
                            placeholder="http://127.0.0.1:3120/mcp"
                            className="h-9 font-mono text-xs bg-muted/20 border-border/70"
                          />
                        </Field>
                      )}
                    </CardContent>
                  </Card>
                )}
              </div>

              {/* 右栏 */}
              <div className="space-y-6">
                {/* 环境变量与凭据 */}
                {(runtimeMode === "managed_stdio" || runtimeMode === "managed_http") && (
                  <Card className="border-border/70 shadow-xs">
                    <CardHeader className="pb-3 pt-4 px-5 border-b bg-muted/20">
                      <div className="flex items-center gap-2">
                        <Key className="size-4 text-primary" />
                        <CardTitle className="text-sm font-semibold">{c("env")}</CardTitle>
                      </div>
                      <CardDescription className="text-xs">{c("envDesc")}</CardDescription>
                    </CardHeader>
                    <CardContent className="p-5 flex flex-col gap-4">
                      <Field label={c("env")} desc={c("envDesc")}>
                        <Textarea
                          className="min-h-[130px] font-mono text-xs leading-relaxed bg-slate-900/[0.03] dark:bg-slate-950/40 border-border/70 resize-y"
                          value={envText}
                          onChange={(event) => setEnvText(event.target.value)}
                          placeholder={'SERVICE_TOKEN=${credential:SERVICE_TOKEN}\nSERVICE_MODE=production\nLOG_LEVEL=debug'}
                        />
                      </Field>
                      {credentials.length > 0 && (
                        <div className="flex flex-col gap-2 rounded-lg border border-border/60 bg-muted/15 p-3.5">
                          <div className="flex items-center justify-between">
                            <span className="text-xs font-medium text-foreground">{c("insertCredential")}</span>
                            <span className="text-[11px] text-muted-foreground">{c("insertCredentialDesc")}</span>
                          </div>
                          <div className="flex flex-wrap gap-1.5 pt-1">
                            {credentials.map((credential) => (
                              <Button
                                key={credential.id}
                                size="sm"
                                variant="secondary"
                                className="h-7 text-xs font-mono bg-background hover:bg-muted border border-border/60 shadow-2xs"
                                onClick={() => insertCredentialRef(credential)}
                              >
                                + {credential.id}
                              </Button>
                            ))}
                          </div>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                )}

                {/* 高可用与健康探活 */}
                {(runtimeMode === "managed_stdio" || runtimeMode === "managed_http") && (
                  <Card className="border-border/70 shadow-xs">
                    <CardHeader className="pb-3 pt-4 px-5 border-b bg-muted/20">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <RefreshCw className="size-4 text-primary" />
                          <CardTitle className="text-sm font-semibold">{c("restartPolicy")}</CardTitle>
                        </div>
                        <Switch checked={restartEnabled} onCheckedChange={setRestartEnabled} />
                      </div>
                      <CardDescription className="text-xs">{c("restartPolicyDesc")}</CardDescription>
                    </CardHeader>
                    {restartEnabled && (
                      <CardContent className="p-5 flex flex-col gap-5">
                        <div className="grid gap-4 sm:grid-cols-2">
                          <NumberField
                            label={c("maxAttempts")}
                            desc={c("maxAttemptsDesc")}
                            value={restartMaxAttempts}
                            onChange={setRestartMaxAttempts}
                            min={0}
                            suffix={zh ? "次" : "times"}
                          />
                          <NumberField
                            label={c("delaySeconds")}
                            desc={c("delaySecondsDesc")}
                            value={restartDelaySeconds}
                            onChange={setRestartDelaySeconds}
                            min={0}
                            suffix={zh ? "秒" : "s"}
                          />
                          <NumberField
                            label={c("backoff")}
                            desc={c("backoffDesc")}
                            value={restartBackoffMultiplier}
                            onChange={setRestartBackoffMultiplier}
                            min={1}
                            step={0.1}
                            suffix="x"
                          />
                          <NumberField
                            label={c("maxDelay")}
                            desc={c("maxDelayDesc")}
                            value={restartMaxDelaySeconds}
                            onChange={setRestartMaxDelaySeconds}
                            min={0}
                            suffix={zh ? "秒" : "s"}
                          />
                          <NumberField
                            label={c("resetAfterSeconds")}
                            desc={c("resetAfterSecondsDesc")}
                            value={restartResetAfterSeconds}
                            onChange={setRestartResetAfterSeconds}
                            min={0}
                            suffix={zh ? "秒" : "s"}
                          />
                          <div className="flex flex-col justify-end">
                            <SwitchRow
                              title={c("restartOnExit")}
                              desc={c("restartOnExitDesc")}
                              checked={restartOnExit}
                              onCheckedChange={setRestartOnExit}
                            />
                          </div>
                          <Field label={c("exitAllowlist")} desc={c("exitAllowlistDesc")}>
                            <Input value={exitCodeAllowlistText} onChange={(event) => setExitCodeAllowlistText(event.target.value)} placeholder="1,2,130" className="h-9 font-mono text-xs bg-muted/20 border-border/70" />
                          </Field>
                          <Field label={c("exitBlocklist")} desc={c("exitBlocklistDesc")}>
                            <Input value={exitCodeBlocklistText} onChange={(event) => setExitCodeBlocklistText(event.target.value)} placeholder="0" className="h-9 font-mono text-xs bg-muted/20 border-border/70" />
                          </Field>
                        </div>

                        {/* 健康检查探活区 */}
                        <div className="rounded-xl border border-border/70 p-4 bg-muted/10 space-y-3">
                          <div className="flex items-center justify-between">
                            <div className="flex flex-col">
                              <span className="font-semibold text-xs text-foreground">{c("healthCheck")}</span>
                              <span className="text-[11px] text-muted-foreground">{c("healthCheckDesc")}</span>
                            </div>
                            <Switch checked={healthCheckEnabled} onCheckedChange={setHealthCheckEnabled} />
                          </div>
                          {healthCheckEnabled && (
                            <div className="grid gap-3 sm:grid-cols-3 pt-2">
                              <NumberField
                                label={c("intervalSeconds")}
                                desc={c("intervalSecondsDesc")}
                                value={healthIntervalSeconds}
                                onChange={setHealthIntervalSeconds}
                                min={1}
                                suffix={zh ? "秒" : "s"}
                              />
                              <NumberField
                                label={c("healthTimeoutSeconds")}
                                desc={c("healthTimeoutSecondsDesc")}
                                value={healthTimeoutSeconds}
                                onChange={setHealthTimeoutSeconds}
                                min={1}
                                suffix={zh ? "秒" : "s"}
                              />
                              <NumberField
                                label={c("failureThreshold")}
                                desc={c("failureThresholdDesc")}
                                value={healthFailureThreshold}
                                onChange={setHealthFailureThreshold}
                                min={1}
                                suffix={zh ? "次" : "times"}
                              />
                            </div>
                          )}
                        </div>
                      </CardContent>
                    )}
                  </Card>
                )}
              </div>
            </div>
          </div>
        ) : (
          <Card className="border-border/70 shadow-xs h-full flex flex-col">
            <CardHeader className="pb-3 pt-4 px-6 border-b bg-muted/20">
              <div className="flex items-center gap-2">
                <FileCode2 className="size-4 text-primary" />
                <CardTitle className="text-sm font-semibold">{c("rawJson")}</CardTitle>
              </div>
              <CardDescription className="text-xs">{c("rawJsonDesc")}</CardDescription>
            </CardHeader>
            <CardContent className="p-6 flex-1">
              <Textarea
                className="h-[580px] font-mono text-xs leading-relaxed bg-slate-900/[0.03] dark:bg-slate-950/50 border-border/70 resize-none"
                value={value}
                onChange={(event) => onChange(event.target.value)}
              />
            </CardContent>
          </Card>
        )}
      </div>

      {/* 底部吸底操作栏 */}
      <div className="flex items-center justify-between border-t bg-card/95 backdrop-blur-sm px-8 py-3.5 shadow-sm shrink-0">
        <div className="flex items-center gap-2.5">
          {activeTab === "form" && (
            <Button size="sm" variant="outline" onClick={applyFormToJson} className="h-8.5 text-xs">
              <Wand2 className="size-3.5 mr-1.5" />
              {c("applyForm")}
            </Button>
          )}
          <Button size="sm" variant="outline" onClick={formatJson} className="h-8.5 text-xs">
            <Braces className="size-3.5 mr-1.5" />
            {c("formatJson")}
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={validateWithBackend}
            disabled={validating || !manifest}
            className="h-8.5 text-xs"
          >
            <ShieldCheck className="size-3.5 mr-1.5" />
            {validating ? (zh ? "检查中..." : "Checking...") : c("backendPrecheck")}
          </Button>
        </div>

        <div className="flex items-center gap-3">
          {onClose && (
            <Button size="sm" variant="ghost" onClick={onClose} className="h-8.5 px-4 text-xs">
              {zh ? "取消" : "Cancel"}
            </Button>
          )}
          <Button
            size="sm"
            onClick={saveAfterPrecheck}
            disabled={busy || validating || !canSave}
            className="h-8.5 px-5 text-xs shadow-xs font-medium"
          >
            <Save className="size-3.5 mr-1.5" />
            {c("saveAndApply")}
          </Button>
        </div>
      </div>
    </div>
  )
}

function ValidationPanel({ validation, c }: { validation: ManifestValidationResponse; c: CopyFn }) {
  const statusText = validation.summary.errors > 0 ? c("notRecommended") : validation.summary.warnings > 0 ? c("saveWithWarning") : c("saveOk")
  return (
    <div className="rounded-lg border border-border/70 bg-muted/30 p-4 text-xs">
      <div className="mb-2.5 flex flex-wrap items-center justify-between gap-2">
        <div className="font-semibold text-foreground">{c("backendCheck")}: {statusText}</div>
        <div className="flex flex-wrap gap-1.5 text-xs">
          <Badge variant={validation.summary.errors > 0 ? "danger" : "outline"}>{c("errors")} {validation.summary.errors}</Badge>
          <Badge variant={validation.summary.warnings > 0 ? "warning" : "outline"}>{c("warnings")} {validation.summary.warnings}</Badge>
          <Badge variant="outline">{c("info")} {validation.summary.info}</Badge>
          <Badge variant="success">{c("ok")} {validation.summary.ok}</Badge>
        </div>
      </div>
      <div className="flex max-h-60 flex-col gap-2 overflow-auto">
        {validation.checks.map((check) => (
          <div key={`${check.name}-${check.message}`} className="rounded-md border border-border/60 bg-card p-2.5 shadow-2xs">
            <div className="mb-1 flex flex-wrap items-center gap-2">
              <Badge variant={check.severity === "error" ? "danger" : check.severity === "warning" ? "warning" : check.severity === "ok" ? "success" : "outline"}>
                {check.severity}
              </Badge>
              <code className="text-xs font-semibold">{check.name}</code>
            </div>
            <div className="text-muted-foreground">{check.message}</div>
            {Object.keys(check.metadata || {}).length > 0 && (
              <pre className="mt-1.5 max-h-28 overflow-auto rounded bg-muted/50 p-2 text-[11px] font-mono">
                {JSON.stringify(check.metadata, null, 2)}
              </pre>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

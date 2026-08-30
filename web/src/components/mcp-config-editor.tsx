import { useEffect, useMemo, useState, type ReactNode } from "react"
import { Braces, Save, ShieldCheck, Wand2 } from "lucide-react"
import { api, type Credential, type ManifestValidationResponse } from "@/api/client"
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
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
  onSave: (nextValue?: string) => void
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
    managedStdioDesc: "由 Lingshu Gate 启动进程，通过标准输入输出连接。",
    externalHttp: "外部 HTTP",
    externalHttpDesc: "服务独立运行，Lingshu Gate 只负责连接或断开。",
    managedHttp: "受管 HTTP",
    managedHttpDesc: "由 Lingshu Gate 启动进程，并等待 HTTP MCP 地址就绪。",
    advancedMode: "高级模式",
    advancedModeDesc: "保留当前 Manifest 的运行与传输配置，仅在 JSON 中编辑。",
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
    autoStart: "自动启动",
    autoStartDesc: "仅记录运行意图；保存与应用配置均不会直接启动服务。",
    restartPolicy: "重启策略",
    restartPolicyDesc: "进程退出、启动失败、健康检查失败后的自动恢复策略。",
    maxAttempts: "最大尝试次数",
    maxAttemptsDesc: "达到次数后停止自动重启，0 表示不重试。",
    delaySeconds: "初始延迟秒数",
    delaySecondsDesc: "第一次自动重启前等待的秒数。",
    backoff: "退避倍数",
    backoffDesc: "每次失败后的延迟增长倍数。",
    maxDelay: "最大延迟秒数",
    maxDelayDesc: "退避后允许等待的最大秒数。",
    resetAfterSeconds: "重置计数秒数",
    resetAfterSecondsDesc: "服务稳定运行超过该秒数后，重置当前重启尝试次数。",
    restartOnExit: "进程退出后重启",
    restartOnExitDesc: "开启后，非策略排除的退出会触发自动重启。",
    exitAllowlist: "退出码允许列表",
    exitAllowlistDesc: "逗号或换行分隔。填写后只有这些退出码会触发重启。",
    exitBlocklist: "退出码阻止列表",
    exitBlocklistDesc: "逗号或换行分隔。命中后不会自动重启，常用 0 表示正常退出不重启。",
    healthCheck: "健康检查",
    healthCheckDesc: "当前通过 MCP tools/list 检查已连接服务是否健康。",
    intervalSeconds: "检查间隔秒数",
    intervalSecondsDesc: "两次健康检查之间的等待时间。",
    healthTimeoutSeconds: "检查超时秒数",
    healthTimeoutSecondsDesc: "单次健康检查最多等待的时间。",
    failureThreshold: "失败阈值",
    failureThresholdDesc: "连续失败达到该次数后触发恢复策略。",
    endpointRequired: "HTTP 运行方式需要填写 transport.endpoint",
    endpointInvalid: "MCP 地址必须是有效的 HTTP/HTTPS URL",
    applyForm: "应用表单到 JSON",
    formatJson: "格式化 JSON",
    backendPrecheck: "后端预检查",
    saveAndApply: "仅保存配置",
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
    delaySeconds: "Initial Delay Seconds",
    delaySecondsDesc: "Seconds to wait before the first auto restart.",
    backoff: "Backoff Multiplier",
    backoffDesc: "Delay growth multiplier after each failure.",
    maxDelay: "Max Delay Seconds",
    maxDelayDesc: "Maximum delay after backoff.",
    resetAfterSeconds: "Reset After Seconds",
    resetAfterSecondsDesc: "Reset restart attempts after the server stays stable for this duration.",
    restartOnExit: "Restart On Exit",
    restartOnExitDesc: "Restart automatically when the exit code is not excluded by policy.",
    exitAllowlist: "Exit Code Allowlist",
    exitAllowlistDesc: "Comma or newline separated. When set, only these exit codes trigger restart.",
    exitBlocklist: "Exit Code Blocklist",
    exitBlocklistDesc: "Comma or newline separated. Matching codes will not restart. 0 usually means normal exit.",
    healthCheck: "Health Check",
    healthCheckDesc: "Uses MCP tools/list to check whether the connected service is healthy.",
    intervalSeconds: "Interval Seconds",
    intervalSecondsDesc: "Delay between health checks.",
    healthTimeoutSeconds: "Timeout Seconds",
    healthTimeoutSecondsDesc: "Maximum wait time for one health check.",
    failureThreshold: "Failure Threshold",
    failureThresholdDesc: "Trigger recovery after this many consecutive failures.",
    endpointRequired: "HTTP runtime modes require transport.endpoint",
    endpointInvalid: "MCP endpoint must be a valid HTTP/HTTPS URL",
    applyForm: "Apply Form to JSON",
    formatJson: "Format JSON",
    backendPrecheck: "Backend Precheck",
    saveAndApply: "Save Config Only",
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

function Field({ label, desc, children, className = "" }: { label: string; desc: string; children: ReactNode; className?: string }) {
  return <div className={`flex flex-col gap-2 ${className}`}><Label>{label}</Label><div className="text-xs text-muted-foreground">{desc}</div>{children}</div>
}

export function McpConfigEditor({ locale, selectedConfigId, value, onChange, onSave, busy }: McpConfigEditorProps) {
  const copy = FORM_COPY[locale]
  const c: CopyFn = (key) => copy[key]
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

  const title = selectedConfigId ? `${c("editConfig")} ${selectedConfigId}` : c("newConfig")
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
      if (result && result.summary.errors > 0) {
        setParseError(`${c("backendPrecheckFailed")}${result.summary.errors}`)
        return
      }
      const nextText = prettyJson(next)
      onChange(nextText)
      setParseError(null)
      onSave(nextText)
    } catch (err) {
      setParseError(err instanceof Error ? err.message : String(err))
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{c("formDesc")}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {parseError && <Alert variant="destructive"><AlertDescription>{c("parseErrorPrefix")}{parseError}</AlertDescription></Alert>}
        {credentialError && <Alert><AlertDescription>{c("credentialErrorPrefix")}{credentialError}</AlertDescription></Alert>}
        {precheck.errors.length > 0 && <Alert variant="destructive"><AlertTitle>{c("localErrors")}</AlertTitle><AlertDescription><ul className="list-disc pl-5">{precheck.errors.map((item) => <li key={item}>{item}</li>)}</ul></AlertDescription></Alert>}
        {precheck.warnings.length > 0 && <Alert><AlertTitle>{c("localWarnings")}</AlertTitle><AlertDescription><ul className="list-disc pl-5">{precheck.warnings.map((item) => <li key={item}>{item}</li>)}</ul></AlertDescription></Alert>}
        {sensitiveKeys.length > 0 && <Alert><AlertDescription>{c("sensitiveEnv")}: {sensitiveKeys.join(", ")}。{c("sensitiveEnvHint")}</AlertDescription></Alert>}
        {validation && <ValidationPanel validation={validation} c={c} />}

        <div className="grid gap-3 md:grid-cols-2">
          <Field label={c("serverId")} desc={c("serverIdDesc")}><Input value={id} onChange={(event) => setId(event.target.value)} placeholder="mcp-server" /></Field>
          <Field label={c("name")} desc={c("nameDesc")}><Input value={name} onChange={(event) => setName(event.target.value)} placeholder="MCP Server" /></Field>
          <Field className="md:col-span-2" label={c("runtimeMode")} desc={c("runtimeModeDesc")}>
            <Select value={runtimeMode} onValueChange={(next) => { setRuntimeMode(next as RuntimeMode); setValidation(null) }}>
              <SelectTrigger><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="managed_stdio"><div><div>{c("managedStdio")}</div><div className="text-xs text-muted-foreground">{c("managedStdioDesc")}</div></div></SelectItem>
                <SelectItem value="external_http"><div><div>{c("externalHttp")}</div><div className="text-xs text-muted-foreground">{c("externalHttpDesc")}</div></div></SelectItem>
                <SelectItem value="managed_http"><div><div>{c("managedHttp")}</div><div className="text-xs text-muted-foreground">{c("managedHttpDesc")}</div></div></SelectItem>
                <SelectItem value="advanced"><div><div>{c("advancedMode")}</div><div className="text-xs text-muted-foreground">{c("advancedModeDesc")}</div></div></SelectItem>
              </SelectContent>
            </Select>
          </Field>
          {runtimeMode === "external_http" ? <Alert className="md:col-span-2"><AlertDescription>{c("externalManagedHint")}</AlertDescription></Alert> : null}
          {runtimeMode === "advanced" ? <Alert className="md:col-span-2"><AlertDescription>{c("advancedModeHint")}</AlertDescription></Alert> : null}
          {runtimeMode === "managed_stdio" || runtimeMode === "managed_http" ? <>
            <Field label={c("command")} desc={c("commandDesc")}><Input value={command} onChange={(event) => setCommand(event.target.value)} placeholder="/path/to/mcp-server" /></Field>
            <Field label={c("cwd")} desc={c("cwdDesc")}><Input value={cwd} onChange={(event) => setCwd(event.target.value)} placeholder="/workspace" /></Field>
            <Field className="md:col-span-2" label={c("args")} desc={c("argsDesc")}><Textarea className="min-h-[120px] font-mono text-xs" value={argsText} onChange={(event) => setArgsText(event.target.value)} placeholder={'--config\n/path/to/config.json'} /></Field>
            <Field className="md:col-span-2" label={c("env")} desc={c("envDesc")}><Textarea className="min-h-[120px] font-mono text-xs" value={envText} onChange={(event) => setEnvText(event.target.value)} placeholder={'SERVICE_TOKEN=${credential:SERVICE_TOKEN}\nSERVICE_MODE=production'} /></Field>
            {credentials.length > 0 && <Field className="md:col-span-2" label={c("insertCredential")} desc={c("insertCredentialDesc")}><div className="flex flex-wrap gap-2">{credentials.map((credential) => <Button key={credential.id} size="sm" variant="secondary" onClick={() => insertCredentialRef(credential)}>{credential.id}</Button>)}</div></Field>}
          </> : null}
          {runtimeMode === "external_http" || runtimeMode === "managed_http" ? <Field className="md:col-span-2" label={c("endpoint")} desc={c("endpointDesc")}><Input value={endpoint} onChange={(event) => { setEndpoint(event.target.value); setValidation(null) }} placeholder="http://127.0.0.1:3120/mcp" /></Field> : null}
          <Field label={c("timeoutSeconds")} desc={c("timeoutSecondsDesc")}><Input type="number" min={1} value={timeoutSeconds} onChange={(event) => setTimeoutSeconds(Number(event.target.value || 120))} /></Field>
          {runtimeMode !== "advanced" ? <div className="flex items-end gap-2"><Switch checked={runtimeMode === "external_http" ? false : autoStart} disabled={runtimeMode === "external_http"} onCheckedChange={setAutoStart} /><div><Label>{c("autoStart")}</Label><div className="text-xs text-muted-foreground">{runtimeMode === "external_http" ? c("externalManagedHint") : c("autoStartDesc")}</div></div></div> : null}

          {runtimeMode === "managed_stdio" || runtimeMode === "managed_http" ? <div className="flex flex-col gap-3 rounded-lg border p-3 md:col-span-2">
            <div className="flex items-center justify-between gap-3"><div><Label>{c("restartPolicy")}</Label><div className="text-xs text-muted-foreground">{c("restartPolicyDesc")}</div></div><Switch checked={restartEnabled} onCheckedChange={setRestartEnabled} /></div>
            <div className="grid gap-3 md:grid-cols-4">
              <Field label={c("maxAttempts")} desc={c("maxAttemptsDesc")}><Input type="number" min={0} value={restartMaxAttempts} onChange={(event) => setRestartMaxAttempts(Number(event.target.value || 0))} /></Field>
              <Field label={c("delaySeconds")} desc={c("delaySecondsDesc")}><Input type="number" min={0} value={restartDelaySeconds} onChange={(event) => setRestartDelaySeconds(Number(event.target.value || 0))} /></Field>
              <Field label={c("backoff")} desc={c("backoffDesc")}><Input type="number" min={1} step="0.1" value={restartBackoffMultiplier} onChange={(event) => setRestartBackoffMultiplier(Number(event.target.value || 1))} /></Field>
              <Field label={c("maxDelay")} desc={c("maxDelayDesc")}><Input type="number" min={0} value={restartMaxDelaySeconds} onChange={(event) => setRestartMaxDelaySeconds(Number(event.target.value || 0))} /></Field>
              <Field label={c("resetAfterSeconds")} desc={c("resetAfterSecondsDesc")}><Input type="number" min={0} value={restartResetAfterSeconds} onChange={(event) => setRestartResetAfterSeconds(Number(event.target.value || 0))} /></Field>
              <div className="flex items-end gap-2"><Switch checked={restartOnExit} onCheckedChange={setRestartOnExit} /><div><Label>{c("restartOnExit")}</Label><div className="text-xs text-muted-foreground">{c("restartOnExitDesc")}</div></div></div>
              <Field label={c("exitAllowlist")} desc={c("exitAllowlistDesc")}><Input value={exitCodeAllowlistText} onChange={(event) => setExitCodeAllowlistText(event.target.value)} placeholder="1,2,130" /></Field>
              <Field label={c("exitBlocklist")} desc={c("exitBlocklistDesc")}><Input value={exitCodeBlocklistText} onChange={(event) => setExitCodeBlocklistText(event.target.value)} placeholder="0" /></Field>
            </div>
            <div className="rounded-md border p-3">
              <div className="mb-3 flex items-center justify-between gap-3"><div><Label>{c("healthCheck")}</Label><div className="text-xs text-muted-foreground">{c("healthCheckDesc")}</div></div><Switch checked={healthCheckEnabled} onCheckedChange={setHealthCheckEnabled} /></div>
              <div className="grid gap-3 md:grid-cols-3">
                <Field label={c("intervalSeconds")} desc={c("intervalSecondsDesc")}><Input type="number" min={1} value={healthIntervalSeconds} onChange={(event) => setHealthIntervalSeconds(Number(event.target.value || 30))} /></Field>
                <Field label={c("healthTimeoutSeconds")} desc={c("healthTimeoutSecondsDesc")}><Input type="number" min={1} value={healthTimeoutSeconds} onChange={(event) => setHealthTimeoutSeconds(Number(event.target.value || 10))} /></Field>
                <Field label={c("failureThreshold")} desc={c("failureThresholdDesc")}><Input type="number" min={1} value={healthFailureThreshold} onChange={(event) => setHealthFailureThreshold(Number(event.target.value || 3))} /></Field>
              </div>
            </div>
          </div> : null}
        </div>

        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={applyFormToJson}><Wand2 />{c("applyForm")}</Button>
          <Button variant="outline" onClick={formatJson}><Braces />{c("formatJson")}</Button>
          <Button variant="outline" onClick={validateWithBackend} disabled={validating || !manifest}><ShieldCheck />{c("backendPrecheck")}</Button>
          <Button onClick={saveAfterPrecheck} disabled={busy || validating || !canSave}><Save />{c("saveAndApply")}</Button>
        </div>

        <Field label={c("rawJson")} desc={c("rawJsonDesc")}><Textarea className="min-h-[360px] font-mono text-xs" value={value} onChange={(event) => onChange(event.target.value)} /></Field>
      </CardContent>
    </Card>
  )
}

function ValidationPanel({ validation, c }: { validation: ManifestValidationResponse; c: CopyFn }) {
  const statusText = validation.summary.errors > 0 ? c("notRecommended") : validation.summary.warnings > 0 ? c("saveWithWarning") : c("saveOk")
  return <div className="rounded-lg border bg-muted p-3 text-sm">
    <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
      <div className="font-medium">{c("backendCheck")}: {statusText}</div>
      <div className="flex flex-wrap gap-2 text-xs">
        <Badge variant={validation.summary.errors > 0 ? "danger" : "outline"}>{c("errors")} {validation.summary.errors}</Badge>
        <Badge variant={validation.summary.warnings > 0 ? "warning" : "outline"}>{c("warnings")} {validation.summary.warnings}</Badge>
        <Badge variant="outline">{c("info")} {validation.summary.info}</Badge>
        <Badge variant="success">{c("ok")} {validation.summary.ok}</Badge>
      </div>
    </div>
    <div className="flex max-h-80 flex-col gap-2 overflow-auto">
      {validation.checks.map((check) => <div key={`${check.name}-${check.message}`} className="rounded-md border bg-card p-2">
        <div className="mb-1 flex flex-wrap items-center gap-2"><Badge variant={check.severity === "error" ? "danger" : check.severity === "warning" ? "warning" : check.severity === "ok" ? "success" : "outline"}>{check.severity}</Badge><code className="text-xs">{check.name}</code></div>
        <div>{check.message}</div>
        {Object.keys(check.metadata || {}).length > 0 && <pre className="mt-1 max-h-32 overflow-auto rounded bg-muted p-2 text-xs">{JSON.stringify(check.metadata, null, 2)}</pre>}
      </div>)}
    </div>
  </div>
}

export type ManifestLike = Record<string, unknown> & {
  id?: unknown
  name?: unknown
  auto_start?: unknown
  timeout_seconds?: unknown
  launch?: Record<string, unknown>
  transport?: Record<string, unknown>
  restart_policy?: Record<string, unknown>
}

export type RuntimeMode = "managed_stdio" | "external_http" | "managed_http" | "advanced"

export type PrecheckResult = { errors: string[]; warnings: string[] }

export type ManifestPrecheckMessageKey =
  | "idRequired"
  | "idPattern"
  | "launchRequired"
  | "transportRequired"
  | "launchTypeRequired"
  | "commandRequired"
  | "containerImageDigestError"
  | "containerVolumesUnsupported"
  | "containerMountsError"
  | "containerEnvironmentProtected"
  | "launchTypeWarning"
  | "argsWarning"
  | "transportTypeRequired"
  | "stdioLaunchError"
  | "streamableEndpointError"
  | "endpointRequired"
  | "endpointInvalid"
  | "timeoutWarning"

const SENSITIVE_ENV_PATTERN = /(KEY|TOKEN|SECRET|PASSWORD|PASS|CREDENTIAL|AUTH|COOKIE)/i
const CONTAINER_IMAGE_DIGEST_PATTERN = /^[a-z0-9][a-z0-9._:/-]*@sha256:[a-f0-9]{64}$/
const CONTAINER_PROTECTED_TARGET_PATTERN = /^\/(?:dev|proc|run|sys|tmp)(?:\/|$)/
const DOCKER_PROCESS_CONTROL_NAMES = new Set([
  "ALL_PROXY", "BASH_ENV", "BUILDKIT_HOST", "BUILDKIT_PROGRESS", "CONTAINER_HOST",
  "ENV", "HOME", "HTTP_PROXY", "HTTPS_PROXY", "IFS", "NODE_OPTIONS", "NO_PROXY",
  "PATH", "PATHEXT", "PERL5OPT", "RUBYOPT", "SHELL", "SSH_AUTH_SOCK",
  "SSL_CERT_DIR", "SSL_CERT_FILE", "TEMP", "TMP", "TMPDIR", "USERPROFILE",
  "XDG_CONFIG_HOME", "XDG_RUNTIME_DIR",
])

export function parseManifest(value: string): ManifestLike {
  const parsed = JSON.parse(value || "{}")
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Manifest root must be a JSON object")
  }
  return parsed as ManifestLike
}

export function stringifyArgs(value: unknown): string {
  if (!Array.isArray(value)) return ""
  return value.map((item) => String(item)).join("\n")
}

export function parseArgs(value: string): string[] {
  return value.split("\n").map((item) => item.trim()).filter(Boolean)
}

export function stringifyEnv(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) return ""
  return Object.entries(value as Record<string, unknown>).map(([key, item]) => `${key}=${String(item ?? "")}`).join("\n")
}

export function parseEnv(value: string): Record<string, string> {
  const result: Record<string, string> = {}
  for (const line of value.split("\n")) {
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith("#")) continue
    const index = trimmed.indexOf("=")
    if (index <= 0) continue
    result[trimmed.slice(0, index).trim()] = trimmed.slice(index + 1).trim()
  }
  return result
}

export function stringifyNumberList(value: unknown): string {
  if (!Array.isArray(value)) return ""
  return value.map((item) => String(item)).join(",")
}

export function parseNumberList(value: string): number[] {
  return value.split(/[\n,]/).map((item) => item.trim()).filter(Boolean).map((item) => Number(item)).filter((item) => Number.isInteger(item))
}

export function getRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

export function runtimeModeFromManifest(manifest: ManifestLike): RuntimeMode {
  const launchType = String(getRecord(manifest.launch).type || "")
  const transportType = String(getRecord(manifest.transport).type || "")
  if (launchType === "external" && transportType === "streamable_http") return "external_http"
  if (launchType === "managed_process" && transportType === "streamable_http") return "managed_http"
  if (launchType === "managed_process" && transportType === "stdio") return "managed_stdio"
  return "advanced"
}

export function parseHttpUrl(value: string): URL | null {
  try {
    const parsed = new URL(value)
    if (!["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password || parsed.hash) return null
    return parsed
  } catch {
    return null
  }
}

export function formatManifestJson(value: string): string {
  return JSON.stringify(parseManifest(value), null, 2)
}

export function withoutUserCredentialValues(manifest: ManifestLike): ManifestLike {
  const safe = { ...manifest }
  delete safe.user_credential_values
  return safe
}

export function sensitiveEnvKeys(envText: string): string[] {
  return Object.keys(parseEnv(envText)).filter((key) => SENSITIVE_ENV_PATTERN.test(key))
}

export function credentialRef(id: string): string {
  return `\${credential:${id}}`
}

export function envKeyFromCredential(id: string): string {
  return id.replace(/[^a-zA-Z0-9_]+/g, "_").toUpperCase()
}

export function precheckManifest(
  manifest: ManifestLike,
  copy: (key: ManifestPrecheckMessageKey) => string,
): PrecheckResult {
  const errors: string[] = []
  const warnings: string[] = []
  const id = String(manifest.id || "").trim()
  const launch = manifest.launch && typeof manifest.launch === "object" && !Array.isArray(manifest.launch) ? manifest.launch : null
  const transport = manifest.transport && typeof manifest.transport === "object" && !Array.isArray(manifest.transport) ? manifest.transport : null

  if (!id) errors.push(copy("idRequired"))
  else if (!/^[a-zA-Z0-9_.-]+$/.test(id)) errors.push(copy("idPattern"))
  if (!launch) errors.push(copy("launchRequired"))
  if (!transport) errors.push(copy("transportRequired"))

  if (launch) {
    const launchType = String(launch.type || "")
    const command = String(launch.command || "").trim()
    if (!launchType) errors.push(copy("launchTypeRequired"))
    if (launchType === "managed_process" && !command) errors.push(copy("commandRequired"))
    if (launchType === "managed_container") {
      const image = String(launch.image || "")
      if (!CONTAINER_IMAGE_DIGEST_PATTERN.test(image)) errors.push(copy("containerImageDigestError"))
      if (Object.prototype.hasOwnProperty.call(launch, "volumes")) errors.push(copy("containerVolumesUnsupported"))

      if (launch.mounts !== undefined) {
        const mounts = launch.mounts
        const validMounts = Array.isArray(mounts) && mounts.every((value) => {
          const mount = getRecord(value)
          const source = String(mount.source || "")
          const target = String(mount.target || "")
          const absoluteSource = source.startsWith("/") || /^[A-Za-z]:[\\/]/.test(source)
          return absoluteSource
            && !source.includes(",")
            && target.startsWith("/")
            && !target.startsWith("//")
            && target !== "/"
            && !target.includes(",")
            && !target.split("/").includes("..")
            && !CONTAINER_PROTECTED_TARGET_PATTERN.test(target)
            && mount.read_only !== false
        })
        if (!validMounts) errors.push(copy("containerMountsError"))
      }

      const environment = getRecord(launch.environment)
      const protectedEnvironment = Object.keys(environment).some((name) => {
        const normalized = name.toUpperCase()
        return normalized.startsWith("LINGSHU_GATE_")
          || normalized.startsWith("DOCKER_")
          || normalized.startsWith("BUILDX_")
          || normalized.startsWith("DYLD_")
          || normalized.startsWith("LD_")
          || normalized.startsWith("PYTHON")
          || DOCKER_PROCESS_CONTROL_NAMES.has(normalized)
      })
      if (protectedEnvironment) errors.push(copy("containerEnvironmentProtected"))
    }
    if (launchType !== "managed_process") warnings.push(copy("launchTypeWarning"))
    if (Array.isArray(launch.args) && launch.args.some((item) => typeof item !== "string")) warnings.push(copy("argsWarning"))
  }

  if (transport) {
    const transportType = String(transport.type || "")
    if (!transportType) errors.push(copy("transportTypeRequired"))
    if (transportType === "stdio" && launch && !["managed_process", "managed_container"].includes(String(launch.type || ""))) errors.push(copy("stdioLaunchError"))
    if (transportType === "streamable_http" && !transport.endpoint) errors.push(copy("streamableEndpointError"))
  }

  const runtimeMode = runtimeModeFromManifest(manifest)
  const endpoint = String(transport?.endpoint || "").trim()
  if (runtimeMode === "external_http" || runtimeMode === "managed_http") {
    if (!endpoint) errors.push(copy("endpointRequired"))
    else if (!parseHttpUrl(endpoint)) errors.push(copy("endpointInvalid"))
  }

  const timeout = Number(manifest.timeout_seconds || 0)
  if (!Number.isFinite(timeout) || timeout <= 0) warnings.push(copy("timeoutWarning"))
  return { errors, warnings }
}

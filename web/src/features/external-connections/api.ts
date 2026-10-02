// Preserve structured policy/conflict errors for the form; never retry a write.
export async function externalRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "include", ...init, headers: { "Content-Type": "application/json", ...init?.headers } })
  const text = await response.text()
  let payload: Record<string, unknown>
  try { payload = text ? JSON.parse(text) : {} } catch { throw new Error(`HTTP ${response.status}: invalid response; refresh before retrying a write`) }
  if (!response.ok) {
    const detail = payload.detail
    const errors = detail && typeof detail === "object" && "activation_errors" in detail ? (detail as { activation_errors: string[] }).activation_errors : null
    const message = errors ? errors.join(", ") : typeof detail === "string" ? detail : Array.isArray(detail) ? detail.map(item => typeof item?.msg === "string" ? item.msg : "Invalid field").join("; ") : `HTTP ${response.status}`
    throw new Error(message)
  }
  return payload as T
}
const reasons: Record<string, [string, string]> = {
  "Canonical resource must be an HTTPS URL without credentials, query or fragment.": ["canonical resource 必须为不含用户名、密码、查询参数和片段的 HTTPS URL。", "Canonical resource must be an HTTPS URL without credentials, query or fragment."],
  "At most 20 issuers and mappings are supported.": ["签发方和资源映射各最多支持 20 项。", "At most 20 issuers and mappings are supported."],
  "Issuer and audience mappings require HTTPS URLs without credentials, query or fragment.": ["签发方和 audience 映射必须为不含用户名、密码、查询参数和片段的 HTTPS URL。", "Issuer and audience mappings require HTTPS URLs without credentials, query or fragment."],
  "Client allowlist must contain exact client IDs, not secrets.": ["客户端允许名单须填写准确的客户端 ID，不能填写秘密值。", "Client allowlist must contain exact client IDs, not secrets."],
  "Unexpected enablement state": ["服务端返回的启停状态不一致，请刷新确认。", "Unexpected enablement state; refresh to confirm."],
  "Disable state unknown": ["关闭状态未知，请刷新确认。", "Disable state unknown; refresh to confirm."],
  "Revocation state unknown": ["撤销状态未知，请刷新确认。", "Revocation state unknown; refresh to confirm."],
  "Identity binding state unknown": ["身份绑定状态未知，请刷新确认。", "Identity binding state unknown; refresh to confirm."],
  "subject target user is not active": ["绑定目标用户不存在或未激活。", "The target user is missing or inactive."],
  "subject trust or target user is not active": ["签发方已不受信或目标用户未激活。", "The issuer is no longer trusted or the target user is inactive."],
  "subject issuer is not configured": ["此签发方尚未加入受信配置。", "The subject issuer is not configured."],
  "configuration changed; reload before saving": ["配置已被其他操作修改，请关闭后刷新再保存。", "Configuration changed; reload before saving."],
  "grant changed; reload before saving": ["个人授权已改变，请关闭后刷新再保存。", "Grant changed; reload before saving."],
  "subject link changed; reload before saving": ["身份绑定已改变，请刷新后重试。", "Subject link changed; reload before saving."],

  "HTTPS URL: no credentials, query or fragment.": ["请输入不含用户名、密码、查询参数和片段的 HTTPS URL。", "HTTPS URL: no credentials, query or fragment."],
  "Use tunnel:ID; never enter a key.": ["使用 tunnel:ID 引用，不能输入密钥。", "Use tunnel:ID; never enter a key."],
  "Use credential:ID; never enter a secret.": ["使用 credential:ID 引用，不能输入秘密值。", "Use credential:ID; never enter a secret."],
  "Enter a client ID, not a secret.": ["请输入客户端 ID，不是秘密值。", "Enter a client ID, not a secret."],
  "Choose a future expiry.": ["请选择未来的到期时间。", "Choose a future expiry."],
  "Choose an access level.": ["请选择获准工具以确定访问级别。", "Choose an access level."],
  "Select currently authorized published tools; unavailable selections must be removed.": ["请选择当前获准且已发布的工具，并移除失效选项。", "Select currently authorized published tools; unavailable selections must be removed."],
  "Select tools from at most 100 services.": ["最多选择 100 个服务中的工具。", "Select tools from at most 100 services."],
  "Access must match the selected tools.": ["访问级别必须与所选工具一致。", "Access must match the selected tools."],
  "Service scope must match the selected tools.": ["服务范围必须与所选工具一致。", "Service scope must match the selected tools."],
  "Rate and concurrency must be whole numbers within the displayed bounds.": ["速率和并发必须为界面所示范围内的整数。", "Rate and concurrency must be whole numbers within the displayed bounds."],
  "Each external audience must have exactly one canonical resource.": ["每个外部 audience 必须唯一映射到一个 canonical resource。", "Each external audience must have exactly one canonical resource."],
  "Each issuer needs one fixed HTTPS JWKS URL.": ["每个签发方必须对应一个固定 HTTPS JWKS URL。", "Each issuer needs one fixed HTTPS JWKS URL."],

  transport_not_configured: ["选择传输方式", "Choose a transport"],
  https_endpoint_required: ["填写 HTTPS endpoint", "Set the HTTPS endpoint"],
  tunnel_reference_required: ["填写隧道引用", "Set the tunnel reference"],
  runtime_secret_reference_required: ["填写运行秘密引用（不是秘密值）", "Set a runtime secret reference, not its value"],
  tunnel_references_required: ["填写隧道和运行秘密引用", "Set tunnel and runtime secret references"],
  trusted_issuer_required: ["配置受信签发方", "Configure trusted issuers"],
  trusted_resource_mapping_required: ["配置受信 audience 映射", "Configure trusted audience mappings"],
  ambiguous_resource_mapping: ["每个 audience 只能映射到一个资源", "Each audience must map to one resource"],
  canonical_resource_required: ["所有映射必须指向同一 Gate canonical resource", "All mappings must target the same Gate canonical resource"],
  trusted_jwks_mapping_required: ["为每个受信签发方配置固定 JWKS URL", "Map each trusted issuer to a fixed JWKS URL"],
  trusted_client_required: ["配置允许的客户端 ID", "Configure allowed client IDs"],
  external_connection_disabled: ["管理员尚未启用外部令牌验证", "External token verification is disabled by an administrator"],
  client_not_allowed: ["此客户端 ID 不在允许名单中", "This client ID is not allowed"],
  subject_link_required: ["管理员尚未为本人启用身份绑定", "An administrator must enable your identity binding"],
  scope_not_currently_authorized: ["当前角色或资源授权不允许此范围", "Current role or resource permissions do not allow this scope"],
  invalid_configuration: ["请修正配置字段", "Correct invalid configuration fields"],
  too_many_trust_entries: ["受信配置项超过上限", "Too many trust entries"],
}
export function activationReason(code: string, zh: boolean): string { return reasons[code]?.[zh ? 0 : 1] ?? code }

export function externalError(cause: unknown, zh: boolean): string {
  const message = cause instanceof Error ? cause.message : String(cause)
  if (reasons[message]) return activationReason(message, zh)
  return message.split(", ").map(part => activationReason(part, zh)).join(" · ")
}

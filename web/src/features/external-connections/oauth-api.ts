export type OAuthTool = { id: string; name: string; server_id: string; server_name?: string | null; access: "read" | "write"; snapshot: string; currently_authorized?: boolean }
export type OAuthClient = { id: string; name: string; redirect_uris: string[]; scopes: string[]; resources?: string[]; enabled: boolean; revision: number; created_at: number }
export type OAuthConfig = { enabled: boolean; issuer: string; resource: string; revision: number; metadata_url: string; authorization_endpoint: string; token_endpoint: string; jwks_uri: string; signing_keys: { kid: string; active: boolean; retire_at: number | null }[] }
export type OAuthGrant = { id: string; client_id: string; client_name: string; resource: string; resource_kind?: "business" | "management"; management_targets?: Record<string, string[]>; target_revision?: number; scopes: string[]; tools: OAuthTool[]; state: string; created_at?: number; expires_at: number; rate_per_minute: number; concurrency: number; revision: number; scope_currently_authorized: boolean; effective_tool_count: number }
export type ScopeSnapshot = Pick<OAuthTool, "id" | "server_id" | "access" | "snapshot"> & Partial<Pick<OAuthTool, "name" | "server_name">>
export type OAuthScopeOptions = { csrf: string; expires_at: number; grant_revision: number; scopes: string[]; effective_scopes: string[]; family_scope_limits: { scopes: string[]; count: number }[]; tools: OAuthTool[] }
export type OAuthScopePreview = { confirmation: string; confirmation_expires_at: number; expires_at: number; tool_ids: string[]; added: string[]; removed: string[]; previous_tools: ScopeSnapshot[]; tools: OAuthTool[]; rate_per_minute: number; concurrency: number }
export type ConsentContext = { csrf: string; completed: boolean; phase: "preauth" | "authenticated" | "completed"; expires_at: number; client: { id: string; name: string }; resource: string; resource_kind?: "business" | "management"; scopes: string[]; user: { id: string; username: string; display_name: string } | null; tools: OAuthTool[]; max_grant_days: number; access_seconds: number; refresh_days: number }
export type OAuthManagementConfig = { enabled: boolean; active: boolean; revision: number; resource: string }
export type ManagementTargetOptions = { csrf: string; expires_at: number; expected_revision: number; expected_target_revision: number; targets: Record<string, string[]>; scopes: string[]; tool_ids: string[] }
export type ManagementTargetPreview = { confirmation: string; confirmation_expires_at: number; expected_revision: number; expected_target_revision: number; previous_targets: Record<string, string[]>; targets: Record<string, string[]>; scopes_unchanged: boolean; tools_unchanged: boolean }
export class OAuthRequestError extends Error {
  constructor(public code: string, public status = 0) { super(code) }
}
export async function oauthRequest<T>(path: string, body?: unknown, method = "POST", headers: Record<string, string> = {}): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 15000)
  try {
    const response = await fetch(path, { credentials: "same-origin", cache: "no-store", signal: controller.signal,
      method: body === undefined ? "GET" : method, headers: { ...(body === undefined ? {} : { "Content-Type": "application/json" }), ...headers },
      body: body === undefined ? undefined : JSON.stringify(body) })
    let payload: Record<string, unknown>
    try { payload = await response.json() } catch { throw new OAuthRequestError("invalid_response", response.status) }
    if (!response.ok) throw new OAuthRequestError(typeof payload.error === "string" ? payload.error : "request_failed", response.status)
    return payload as T
  } catch (error) {
    if (error instanceof OAuthRequestError) throw error
    throw new OAuthRequestError(controller.signal.aborted ? "request_timeout" : "connection_failed")
  } finally { window.clearTimeout(timeout) }
}
const errors: Record<string, [string, string]> = {
  oauth_management_disabled: ["管理员尚未启用独立的管理 OAuth 资源。", "The separate management OAuth resource has not been enabled."],
  management_admin_required: ["管理连接需要当前有效的管理员身份和 operations.manage 权限。", "A management connection requires a currently active administrator with operations.manage permission."],
  invalid_management_targets: ["逐项填写精确服务 ID 和创建/更新操作；不支持重复 ID、通配符或其他操作。", "Enter exact server IDs and create/update actions. Duplicate IDs, wildcards and other actions are unsupported."],
  invalid_management_confirmation: ["目标确认不属于此会话或已过期。重新读取并核对目标。", "Target confirmation belongs to another session or expired. Reload and review the targets."],
  management_confirmation_changed: ["授权或目标版本已改变，或确认被替换。重新读取目标并确认。", "The grant or target revision changed, or confirmation was replaced. Reload targets and confirm again."],
  management_scope_insufficient: ["当前管理员缺少此次管理操作需要的权限。", "The current administrator lacks permission for this management action."],
  oauth_disabled: ["管理员尚未启用内置 OAuth。", "Built-in OAuth has not been enabled by an administrator."],
  invalid_client_configuration: ["填写客户端名称、精确 HTTPS 回调和允许范围；回调不可含片段、通配符或 OAuth 响应参数。", "Enter a client name, exact HTTPS callbacks and allowed scopes. Callbacks cannot contain fragments, wildcards or OAuth response parameters."],
  invalid_configuration: ["Issuer 必须是无末尾斜线的 HTTPS 域名；资源必须是固定 HTTPS URL。", "Issuer must be an HTTPS origin without a trailing slash; resource must be a fixed HTTPS URL."],
  resource_must_use_mcp_path: ["资源 URL 必须使用 /mcp 路径。", "The resource URL must use the /mcp path."],
  signing_key_required: ["先生成加密签名密钥，再启用 OAuth。", "Generate an encrypted signing key before enabling OAuth."],
  signing_key_unavailable: ["签名密钥不可用，请联系管理员恢复加密密钥与数据库。", "Signing key is unavailable. Ask an administrator to restore the encryption key and database."],
  disable_before_changing_urls: ["先关闭内置 OAuth，再修改可信 URL；已有连接需要重新授权。", "Disable built-in OAuth before changing trusted URLs. Existing connections will need new authorization."],
  resource_configuration_conflict: ["内置与外部模式必须使用同一个固定 MCP 资源。", "Built-in and external modes must use the same fixed MCP resource."],
  issuer_configuration_conflict: ["内置与外部模式不能使用相同 issuer；请分别配置可信签发方。", "Built-in and external modes cannot share an issuer. Configure distinct trusted issuers."],
  revision_conflict: ["对象已改变。刷新后核对，再保存。", "This item changed. Refresh and review before saving."],
  invalid_origin: ["请求来源校验失败，请从原连接重新打开此页面。", "Request origin check failed. Reopen this page from the original connection."],
  invalid_csrf: ["页面校验已过期，刷新授权信息后重试。", "Page verification expired. Refresh authorization details before retrying."],
  authorization_expired: ["授权请求已过期。请回到客户端重新发起连接。", "Authorization request expired. Start the connection again from the client."],
  authorization_changed: ["客户端配置已改变。请回到客户端重新发起连接。", "Client configuration changed. Start the connection again from the client."],
  invalid_browser: ["此授权请求属于另一个浏览器。请重新发起连接。", "This request belongs to another browser. Start a new connection."],
  authorization_completed: ["此请求已处理。请返回客户端；连接失败时重新发起授权。", "This request was already processed. Return to the client; start a new authorization if the connection failed."],
  tool_scope_changed: ["工具或用户权限已改变。刷新后重新选择范围。", "Tools or user permissions changed. Refresh and select the scope again."],
  grant_can_only_narrow: ["旧接口只允许缩小范围、有效期和配额；请在本人控制台确认调整工具范围。", "The legacy endpoint only reduces tools, expiry and quotas. Confirm tool changes in your own console."],
  grant_limits_can_only_narrow: ["有效期、调用次数和并发上限只能维持或收紧。", "Expiry, rate and concurrency limits can only stay unchanged or decrease."],
  session_required: ["此操作需要本人在控制台登录；API Token 不能更新连接范围。", "Sign in to the console with your own account. API tokens cannot update connection scope."],
  grant_scope_unavailable: ["授权、客户端或资源已失效。关闭后刷新授权列表，再重试。", "The grant, client or resource is unavailable. Close and refresh the grant list before retrying."],
  grant_scope_insufficient: ["此工具需要连接未持有的 OAuth scope。Gate 内可增加现有 scope 内的工具，但不能补造令牌的读写能力。", "This tool requires an OAuth scope the connection does not hold. Gate can add tools within existing scopes, but cannot invent a token's read/write capability."],
  scope_confirmation_changed: ["确认已过期、被替换，或与本次范围不符。刷新信息后重新核对并确认。", "Confirmation expired, was replaced, or does not match this change. Refresh, review and confirm again."],
  scope_confirmation_capacity: ["待确认更新达到短时上限。请完成其他确认或稍后重试。", "The short-term confirmation limit was reached. Finish other confirmations or retry later."],
  grant_limit: ["本人保留授权记录已达上限，当前无法创建新授权。请联系管理员处理，历史不会自动删除。", "Your retained grant limit was reached, so a new grant cannot be created. Ask an administrator for help; history is not deleted automatically."],
  login_failed: ["登录失败，请核对已有 Gate 用户名、密码和账号状态。", "Sign-in failed. Check the existing Gate username, password and account status."],
  login_required: ["登录已过期，请重新登录；已选范围会在校验后保留。", "Sign-in expired. Sign in again; selected scope is retained after validation."],
  user_authorization_unavailable: ["此用户需要在内部控制台修改初始密码，或缺少个人凭据管理权限。", "This user must change their initial password in the private console, or lacks permission to manage personal credentials."],
  rate_limit_exceeded: ["请求过于频繁，请在一分钟后重试。", "Too many requests. Retry in one minute."],
  authorization_capacity: ["当前用户或客户端的待处理授权已达上限。请完成其他授权或稍后重试；不要重复登录。", "Pending authorizations for this user or client reached their limit. Finish other authorizations or retry later; avoid repeated sign-ins."],
  key_rotation_limit: ["轮换次数达到短时上限，请在旧访问令牌过期后重试。", "Key rotation reached its short-term limit. Retry after old access tokens expire."],
  request_timeout: ["请求超时，结果未知。请刷新状态后再决定是否重试。", "Request timed out; its result is unknown. Refresh status before deciding whether to retry."],
  connection_failed: ["连接失败，结果未知。请刷新状态后再决定是否重试。", "Connection failed; its result is unknown. Refresh status before deciding whether to retry."],
  invalid_request: ["请求字段无效，请检查表单并重试。", "Request fields are invalid. Check the form and retry."],
  invalid_response: ["响应无法读取，请刷新状态；不要自动重复写入。", "The response could not be read. Refresh status before repeating a write."],
  permission_denied: ["当前用户没有执行此操作的权限。", "The current user does not have permission for this action."],
}
export function oauthError(error: unknown, zh: boolean): string {
  const code = error instanceof OAuthRequestError ? error.code : "request_failed"
  return errors[code]?.[zh ? 0 : 1] ?? (zh ? "请求失败。请检查配置或刷新后重试。" : "Request failed. Check configuration or refresh before retrying.")
}
export function toolFilter(tools: OAuthTool[], query: string, server: string, access: string) {
  const q = query.trim().toLocaleLowerCase()
  return tools.filter(tool => (!server || tool.server_id === server) && (!access || tool.access === access) && `${tool.name} ${tool.id} ${tool.server_name || ""} ${tool.server_id}`.toLocaleLowerCase().includes(q))
}

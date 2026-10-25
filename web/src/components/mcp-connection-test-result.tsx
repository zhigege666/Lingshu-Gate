import { CheckCircle2, CircleDashed, CircleX } from "lucide-react"
import type { HttpConnectionResult } from "@/api/http-connection-test"

const names = {
  configuration: ["配置", "Configuration"], http: ["HTTP 联通", "HTTP connection"],
  authentication: ["请求鉴权", "Request authentication"], handshake: ["MCP 握手", "MCP handshake"], tools: ["工具发现", "Tool discovery"],
}
const remedies: Record<string, [string, string]> = {
  authentication_required: ["服务要求鉴权或拒绝了令牌。请检查令牌是否由目标服务签发、是否过期或已被撤销。", "The service requires authentication or rejected the token. Check its issuer, expiry and revocation status."],
  access_denied: ["请求被拒绝。请检查账号/令牌权限、服务的 Origin 策略或反向代理限制；不能仅据 403 判断令牌已过期。", "Access was denied. Check account/token permissions, Origin policy and reverse proxy restrictions. HTTP 403 alone does not prove token expiry."],
  endpoint_not_found: ["地址不存在。请核对服务实际提供的 MCP 路径，不要填写普通网页或 API 首页。", "The endpoint was not found. Check the actual MCP path, not a normal webpage or API homepage."],
  http_method_not_allowed: ["地址不接受 MCP 的 POST 请求。请检查路径和代理规则，不要用浏览器能否打开来判断 MCP 联通。", "The endpoint rejects MCP POST requests. Check its path and proxy rules; a page opening in a browser is not an MCP test."],
  redirect_blocked: ["服务返回重定向。为避免凭据被转发，测试已停止；请直接填写最终 MCP 地址。", "A redirect was blocked to avoid forwarding credentials. Enter the final MCP endpoint directly."],
  rate_limited: ["服务限流，请稍后手动重试；测试不会自动重复请求。", "The service rate-limited the test. Retry manually later; no automatic retry is performed."],
  upstream_failed: ["下游服务或反向代理出错，请检查服务状态和日志。", "The downstream service or reverse proxy failed. Check its status and logs."],
  network_failed: ["Gate 所在机器无法连接目标。检查 DNS、端口、防火墙和容器网络；不是从你的浏览器发起连接。", "The Gate host could not reach the target. Check DNS, port, firewall and container networking. The request is not sent from your browser."],
  tls_failed: ["TLS 证书校验失败，请修正证书链或主机名；不要关闭验证。", "TLS certificate verification failed. Correct the chain or hostname; do not disable verification."],
  timeout: ["本次测试超时。检查网络和服务响应时间后再试。", "The connection test timed out. Check network and server response time before retrying."],
  mcp_protocol_failed: ["收到的响应未通过 MCP 协议校验。检查是否填了网页地址、是否支持 Streamable HTTP，以及服务协议版本。", "The response did not pass MCP validation. Check the endpoint, Streamable HTTP support and protocol version."],
  http_trust_revoked: ["连接许可已撤销或需要复核。测试不会恢复许可，请先明确恢复并保存。", "Connection permission was revoked or needs review. A test cannot restore it; explicitly restore and save first."],
  credential_scope_denied: ["凭据未授权给当前服务和地址。请选择匹配的凭据或为此目标新增凭据，不能复用其他服务的令牌。", "The credential is not bound to this service and address. Select a matching credential or create one for this target."],
  credential_changed: ["测试期间凭据发生变更。重新读取凭据状态后再试，旧结果不再有效。", "The credential changed during the test. Reload its state and test again; the previous result is no longer valid."],
  credential_unavailable: ["引用的凭据不可用，请检查是否已删除或没有访问权限。", "The referenced credential is unavailable. Check deletion and access permissions."],
  credential_reference_required: ["请先加密保存凭据，再通过 ${credential:ID} 引用。测试不会把新明文令牌保存到配置。", "Save the credential encrypted first and use ${credential:ID}. The test does not persist a new plaintext token in configuration."],
  config_changed: ["已保存配置或许可发生变化。重新打开编辑器核对当前版本，再测试。", "The saved configuration or permission changed. Reopen the editor to review the current version before testing."],
  invalid_headers: ["请求头重复、格式无效或覆盖协议保留头。请在高级请求头中修正。", "Headers are duplicated, malformed or reserved. Correct advanced headers."],
  service_disabled: ["当前草稿为停用状态。测试不会隐式启用服务。", "This draft is disabled. Testing does not implicitly enable it."],
  external_http_required: ["此测试仅连接外部 HTTP MCP，不会启动受管进程。", "This test connects only to external HTTP MCP services and never starts a managed process."],
  personal_credentials_required: ["此配置使用个人下游凭据槽。请使用对应用户的连接流程；管理员测试不会借用用户的个人凭据。", "This configuration uses personal downstream credential slots. Use the caller-owned connection flow; an administrator test will not borrow personal credentials."],
  invalid_manifest: ["配置格式无效，请先修正配置并执行静态校验。", "The configuration is invalid. Correct it and run static validation first."],
  http_policy_unavailable: ["HTTP 连接策略不可用，测试已停止。", "HTTP connection policy is unavailable; the test was stopped."],
}

export function McpConnectionTestResult({ result, stale, zh }: { result: HttpConnectionResult; stale: boolean; zh: boolean }) {
  if (stale) return <p role="status" className="manifest-test-stale text-sm text-warning">{zh ? "配置草稿已变化，上次联通测试结果已过期，请重新测试。" : "The draft changed. The previous connection test is stale; test again."}</p>
  const OverallIcon = result.ok ? CheckCircle2 : CircleX
  return <section aria-label={zh ? "联通测试结果" : "Connection test result"} aria-live="polite" className={`manifest-test-result ${result.ok ? "is-success" : "is-failed"}`}>
    <div className="manifest-test-heading">
      <OverallIcon aria-hidden="true" className={`size-5 ${result.ok ? "text-success" : "text-destructive"}`} />
      <h3 className="font-semibold text-sm">{result.ok ? (zh ? "连接成功" : "Connection successful") : (zh ? "连接未通过" : "Connection failed")}</h3>
      <span className="text-sm text-muted-foreground">{result.elapsed_ms} ms{typeof result.tool_count === "number" && ` · ${zh ? "发现 " : "Discovered "}${result.tool_count} ${zh ? "个工具" : "tools"}`}</span>
    </div>
    <div className="manifest-test-stages" role="list">
      {result.stages.map(stage => {
        const Icon = stage.status === "passed" ? CheckCircle2 : stage.status === "failed" ? CircleX : CircleDashed
        const label = stage.status === "passed" ? (zh ? "通过" : "Passed") : stage.status === "failed" ? (zh ? "失败" : "Failed") : (zh ? "未验证" : "Not verified")
        return <span role="listitem" className="manifest-test-stage" key={stage.id}><Icon aria-hidden="true" className={`size-4 ${stage.status === "passed" ? "text-success" : stage.status === "failed" ? "text-destructive" : "text-muted-foreground"}`} />{names[stage.id][zh ? 0 : 1]}<span className="text-xs text-muted-foreground">{label}</span></span>
      })}
    </div>
    {result.code && <p role="alert" className="text-sm text-destructive">{remedies[result.code]?.[zh ? 0 : 1] || (zh ? "测试未完成，请检查配置后重试。" : "The test did not complete. Review the configuration and retry.")}</p>}
    <p className="text-xs text-muted-foreground">{zh ? "尚未保存配置或发布工具；实际业务权限尚未验证。" : "Configuration is not saved and tools are not published. Business permissions remain unverified."}</p>
    <details className="text-xs manifest-test-details"><summary>{zh ? "查看技术详情" : "Technical details"}</summary>
      <p>{result.protocol_version && `MCP ${result.protocol_version}`}{result.http_status && ` · HTTP ${result.http_status}`}{result.code && <> · <code>{result.code}</code></>}</p>
      {result.auth_scheme && !result.ok && <p>{zh ? "服务声明的鉴权方式：" : "Authentication advertised by the service: "}{result.auth_scheme}{result.oauth_advertised ? (zh ? "；声明了 OAuth 元数据。当前测试不会自动登录或获取令牌。" : "; OAuth metadata was advertised. This test does not sign in or obtain tokens automatically.") : ""}</p>}
      <p>{zh ? "本次只检查连接、MCP 握手与工具目录，不修改持久许可、现有连接，也不调用业务工具。" : "This test checks the connection, MCP handshake and tool catalog. It does not change persistent permission or existing connections, or invoke business tools."}</p>
    </details>
  </section>
}

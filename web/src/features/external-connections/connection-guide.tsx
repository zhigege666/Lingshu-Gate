import { Alert, Steps } from "antd"
import type { ReactNode } from "react"
import { connectionReadiness, type ConnectionDraft } from "./model"
import { activationReason } from "./api"
import "./connection-guide.css"

const docs = {
  tunnel: "https://github.com/zhigege666/Lingshu-Gate/blob/main/docs/external-connections.md",
  chatgpt: "https://github.com/zhigege666/Lingshu-Gate/blob/main/docs/external-connections.md",
  cloudflare: "https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/get-started/create-remote-tunnel/",
  keycloak: "https://www.keycloak.org/securing-apps/oidc-layers",
  frp: "https://github.com/fatedier/frp",
  npm: "https://nginxproxymanager.com/guide/",
}
function Doc({ href, children }: { href: string; children: ReactNode }) { return <a href={href} target="_blank" rel="noreferrer" className="underline underline-offset-4">{children}</a> }

export function ConnectionGuide({ step, onStep, zh, children, disabled, mode = "direct" }: { step: number; onStep: (step: number) => void; zh: boolean; children: ReactNode; disabled: boolean; mode?: ConnectionDraft["mode"] }) {
  const titles = zh ? ["选择接入方式", "配置身份验证", "用户绑定与授权", "检查与连接验证"] : ["Network path", "Token verification", "Users and grants", "Check and connect"]
  return <div className="connection-guide">
    <Steps current={step} onChange={disabled ? undefined : onStep} responsive items={titles.map((title,index)=>({title,status:index === step ? "process" as const : "wait" as const}))} />
    <div className="connection-guide-layout">
      <section className="connection-guide-main" aria-label={titles[step]}>{children}</section>
      <aside className="connection-guide-help">
        <h2>{zh ? "在哪里找配置" : "Where to find the settings"}</h2>
        {step === 0 && <>
          {mode === "direct" && <>
          <h3>{zh ? "公网 HTTPS / 自建中转" : "HTTPS / your own relay"}</h3>
          <p>{zh ? "已有反向代理时，填写对外 MCP 地址，例如 https://gate.example.com/mcp。内网地址不等于外部接入地址。" : "Use the externally reachable MCP URL, for example https://gate.example.com/mcp. A private origin address is not a public endpoint."}</p>
          <p>{zh ? "Cloudflare 控制台 → Networking → Tunnels → 选择隧道 → Routes → Add route → Published application。Service URL 填 Gate 的内网 HTTP 地址；对外域名加 /mcp 填入本页 HTTPS 接入地址。" : "Cloudflare dashboard → Networking → Tunnels → your tunnel → Routes → Add route → Published application. Service URL points to Gate's private HTTP origin. Enter the public hostname plus /mcp as Gate's HTTPS endpoint."} <Doc href={docs.cloudflare}>{zh ? "配置指南" : "Routing guide"}</Doc></p>
          <p>{zh ? "使用 frp + Nginx Proxy Manager：frp 负责内网到公网的转发，NPM 负责域名与 TLS。Gate 不启动或管理这两个服务。" : "With frp + Nginx Proxy Manager, frp provides forwarding and NPM provides the hostname and TLS. Gate does not manage either service."} <Doc href={docs.frp}>frp</Doc> · <Doc href={docs.npm}>NPM</Doc></p>
          </>}
          {mode === "secure_mcp_tunnel" && <>
          <h3>Secure MCP Tunnel</h3>
          <p>{zh ? "在 Platform 的 Tunnel settings 创建或查看隧道，并关联目标 ChatGPT 工作区。将 tunnel_id 填成 tunnel:ID；运行密钥放在运维秘密存储中，这里只填 credential:ID 引用。" : "Create or inspect the tunnel in Platform Tunnel settings and associate the target ChatGPT workspace. Enter tunnel_id as tunnel:ID. Store the runtime key outside Gate; enter only its credential:ID reference here."} <Doc href={docs.tunnel}>{zh ? "权限、客户端与排错" : "Permissions, client and troubleshooting"}</Doc></p>
          </>}
          {mode === "disabled" && <p>{zh ? "先在左侧选择方式：已有公网域名或自建反向代理选择 HTTPS；不公开内网 Gate、且账号具备 隧道权限时选择 Secure MCP Tunnel。" : "Choose a path first: HTTPS for a public hostname or your own proxy; Secure MCP Tunnel for a private Gate when your account has tunnel access."}</p>}
          <Alert type="warning" showIcon title={zh ? "只公开 /mcp 与所需发现路径，不要连带公开控制台和 /v1 管理接口。" : "Expose only /mcp and required discovery paths, not the console or /v1 administration routes."} />
        </>}
        {step === 1 && <>
          <p>{zh ? "Gate 是令牌验证方，不是 OAuth 登录/发证平台。先在你的身份提供方配置应用、授权流程和适合该资源的 JWT；不要把 Gate API Token 或客户端密钥填入这些字段。" : "Gate validates tokens; it is not an OAuth login/token issuer. Configure the client, consent flow and resource JWT at your identity provider first. Do not paste a Gate API token or client secret into these fields."}</p>
          <dl>
            <dt>Issuer / JWKS</dt><dd>{zh ? "从身份提供方的 OpenID discovery 文档读取 issuer 和 jwks_uri。以 Keycloak 为例：身份平台地址 /realms/你的Realm/.well-known/openid-configuration。原样对应到受信 issuer 与固定 JWKS URL。" : "Read issuer and jwks_uri from your provider's OpenID discovery document. For Keycloak: provider origin /realms/your-realm/.well-known/openid-configuration. Copy these exact values to trusted issuer and fixed JWKS URL."} <Doc href={docs.keycloak}>{zh ? "Keycloak 端点说明" : "Keycloak endpoints"}</Doc></dd>
            <dt>Client ID</dt><dd>{zh ? "从身份平台中为 ChatGPT 接入登记的客户端读取 Client ID，并核对签发 JWT 的 client_id / azp；它不是 Client Secret，也不是用户 ID。" : "Read the registered integration's Client ID at the identity provider and check the JWT client_id / azp. This is neither Client Secret nor user ID."}</dd>
            <dt>Audience → canonical resource</dt><dd>{zh ? "填写该集成实际收到的 aud 与 Gate 规范资源 URL 的精确对应。不能用通配符，也不能靠关闭 audience 校验解决不匹配。" : "Map the integration's actual aud exactly to Gate's canonical resource URL. Do not use wildcards or disable audience validation."}</dd>
          </dl>
          <Alert type="info" title={zh ? "当前支持 RS256 JWT 与固定 HTTPS JWKS，不支持 opaque token / introspection。" : "Supports RS256 JWTs and fixed HTTPS JWKS, not opaque tokens or introspection."} />
        </>}
        {step === 2 && <>
          <p>{zh ? "管理员在此把签名验证后的 (issuer, subject) 绑定到已有 Gate 用户。subject 来自身份提供方的 sub，不要把显示名或邮箱猜作 sub。" : "Bind a signature-verified (issuer, subject) pair to an existing Gate user. Subject is the provider's sub; do not guess it from a display name or email."}</p>
          <p>{zh ? "然后让该用户进入“我的连接”，选择客户端、允许的 MCP/工具、读写范围、有效期和配额。个人授权仍与用户原有权限取交集，不会因连接成功而获得所有工具。" : "The user then opens My connections and chooses client, MCP/tools, access level, expiry and quotas. Delegation is intersected with existing user permissions; connectivity does not grant every tool."}</p>
          <p>{zh ? "绑定身份不等于完成提供方登录或同意授权；两边都需要独立配置。" : "An identity link does not complete provider sign-in or consent. Both sides require separate setup."}</p>
        </>}
        {step === 3 && <>
          <ol>
            <li>{zh ? "ChatGPT → Settings → Security and login → Developer mode；入口可受账号与工作区策略影响。" : "ChatGPT → Settings → Security and login → Developer mode; account/workspace policy may restrict availability."}</li>
            <li>{zh ? "进入 ChatGPT Plugins，添加开发者应用。HTTPS 模式填写 MCP 地址；隧道模式选择 Tunnel 和目标隧道。OAuth 登录在身份提供方完成。" : "Open ChatGPT Plugins and add a developer app. Use the MCP endpoint for HTTPS, or select Tunnel and your tunnel. Complete OAuth at the identity provider."}</li>
            <li>{zh ? "重新发现工具，用只读工具验证；核对“我的调用”和调用审计的授权决定、执行结果与关联 ID。" : "Refresh discovery and test a read-only tool. Check My invocations and audit records for decision, outcome and correlation ID."}</li>
          </ol>
          <p><Doc href={docs.chatgpt}>{zh ? "ChatGPT 接入步骤" : "ChatGPT setup"}</Doc> · <Doc href={docs.tunnel}>{zh ? "隧道排错" : "Tunnel troubleshooting"}</Doc></p>
          <p>{zh ? "401：检查签名、issuer、aud、客户端及过期时间；403：检查身份绑定、个人授权、工具发布状态与用户权限；找不到隧道：检查工作区关联及 Tunnels Read + Use。" : "401: inspect signature, issuer, aud, client and expiry. 403: inspect identity link, personal grant, tool publication and user access. Missing tunnel: check workspace association and Tunnels Read + Use."}</p>
        </>}
        <p className="text-xs text-muted-foreground">{zh ? "外部路径按 2026-10-01 官方文档核对，版本变化时以链接说明为准。" : "External paths checked against official documentation on 2026-10-01; consult links if the UI changes."}</p>
      </aside>
    </div>
  </div>
}

export function ConnectionGuideChecks({ draft, zh }: { draft: ConnectionDraft; zh: boolean }) {
  const missing = connectionReadiness(draft)
  return <div className="space-y-3"><Alert type={missing.length ? "warning" : "success"} title={missing.length ? (zh ? "配置仍有缺项" : "Configuration is incomplete") : (zh ? "本地配置格式检查通过" : "Local configuration checks passed")} />
    {missing.length > 0 && <ul className="list-disc pl-5">{missing.map(reason=><li key={reason}>{activationReason(reason,zh)}</li>)}</ul>}
    <Alert type="info" title={zh ? "尚未验证外部连通与 ChatGPT 调用" : "External reachability and ChatGPT calls are not verified"} description={zh ? "这里不进行网络探测、不自动登录或发起工具调用。配置保存与格式检查不能证明端到端接入成功。" : "This view does not probe the network, sign in or invoke tools. Saving valid configuration does not establish an end-to-end connection."} />
  </div>
}

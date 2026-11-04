import { Button, Card, Tabs, Typography } from "antd"
import { PageHeader } from "@/components/page-shell"
import { NetworkSettingsPanel } from "@/features/network/network-settings-panel"
import { ReleaseUpdatesPanel } from "@/features/release-updates-panel"
import type { TFunction } from "@/i18n"

export function SystemSettingsPage({ t }: { t: TFunction }) {
  const zh = t("uploads") === "项目上传"
  return <div className="flex min-w-0 flex-col gap-3">
    <PageHeader title={zh ? "系统设置" : "System settings"} helpLabel={t("pageHelp")} closeLabel={t("close")} helpContent={<p>{zh ? "管理网络配置、GitHub 版本检查与更新代理。配置权限与网络调用权限独立；凭据使用共享存储引用。" : "Manage network settings, GitHub release checks and the update proxy. Configuration and invocation permissions are independent; credentials reference shared storage."}</p>} />
    <Tabs defaultActiveKey="network" items={[
      { key: "network", label: zh ? "网络与依赖" : "Network and dependencies", children: <div className="flex flex-col gap-3">
        <NetworkSettingsPanel t={t} />
        <Card title="Cloudflare Tunnel" extra={<span className="text-xs text-muted-foreground">Sidecar</span>}>
          <div className="flex flex-col gap-2">
            <Typography.Text type="secondary">{zh
              ? "通过独立 cloudflared 容器建立隧道，不需要开放 Gate 公网入站端口。Token 由部署环境以只读文件挂载，不进入 Gate Core。"
              : "Run a separate cloudflared sidecar to publish Gate without opening inbound ports. The tunnel token is mounted read-only by the deployment environment and never enters Gate Core."}</Typography.Text>
            <div><Button type="link" href="https://github.com/zhigege666/Lingshu-Gate/blob/v0.5.11/docs/cloudflare-tunnel.md" target="_blank">{zh ? "查看配置说明" : "Setup guide"}</Button></div>
          </div>
        </Card>
      </div> },
      { key: "updates", label: zh ? "版本更新" : "Updates", children: <ReleaseUpdatesPanel t={t} /> },
    ]} />
  </div>
}
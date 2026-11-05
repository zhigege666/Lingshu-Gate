import { Tabs, Typography } from "antd"
import { PageHeader } from "@/components/page-shell"
import { NetworkSettingsPanel } from "@/features/network/network-settings-panel"
import { ReleaseUpdatesPanel } from "@/features/release-updates-panel"
import type { TFunction } from "@/i18n"

export function SystemSettingsPage({ t }: { t: TFunction }) {
  const zh = t("uploads") === "项目上传"
  return <div className="flex min-w-0 flex-col gap-3">
    <PageHeader title={zh ? "系统设置" : "System settings"} helpLabel={t("pageHelp")} closeLabel={t("close")} helpContent={<p>{zh ? "管理交付网络、Cloudflare Tunnel 与版本更新。" : "Manage delivery networking, Cloudflare Tunnel and release updates."}</p>} />
    <PageHeader title={zh ? "系统设置" : "System settings"} helpLabel={t("pageHelp")} closeLabel={t("close")} helpContent={<p>{zh ? "管理交付网络、Cloudflare Tunnel 与版本更新。" : "Manage delivery networking, Cloudflare Tunnel and release updates."}</p>} />
    <Tabs defaultActiveKey="network" items={[
      { key: "network", label: zh ? "网络与依赖" : "Network and dependencies", children: <NetworkSettingsPanel t={t} /> },
      { key: "tunnel", label: "Cloudflare Tunnel", children: <div className="flex min-w-0 flex-col gap-3">
        <p>{zh ? "在部署主机的 Compose 目录运行命令。首次启动前，请配置路由和 Token 文件。" : "Run these commands in the deployment host’s Compose directory. Configure the route and token file before the first start."}{" "}
          <a href={`https://github.com/zhigege666/Lingshu-Gate/blob/main/docs/${zh ? "zh-CN/" : ""}cloudflare-tunnel.md`} target="_blank" rel="noreferrer">{zh ? "配置指南" : "Setup guide"}</a>
        </p>
        <dl className="grid gap-2">
          {[
            [zh ? "启动" : "Start", "docker compose --profile cloudflare-tunnel up -d cloudflared"],
            [zh ? "状态" : "Status", "docker compose ps --all cloudflared"],
            [zh ? "日志" : "Logs", "docker compose logs --tail=100 cloudflared"],
            [zh ? "停止" : "Stop", "docker compose stop cloudflared"],
          ].map(([label, command]) => <div key={command} className="flex flex-wrap items-baseline gap-2">
            <dt>{label}</dt>
            <dd className="min-w-0 break-words"><Typography.Text code copyable={{ text: command }}>{command}</Typography.Text></dd>
          </div>)}
        </dl>
      </div> },
      { key: "updates", label: zh ? "版本更新" : "Updates", children: <ReleaseUpdatesPanel t={t} /> },
    ]} />
  </div>
}

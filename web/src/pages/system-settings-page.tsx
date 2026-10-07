import { Tabs } from "antd"
import { PageHeader } from "@/components/page-shell"
import { NetworkSettingsPanel } from "@/features/network/network-settings-panel"
import type { TFunction } from "@/i18n"

export function SystemSettingsPage({ t }: { t: TFunction }) {
  const zh = t("uploads") === "项目上传"
  return <div className="flex min-w-0 flex-col gap-3">
    <PageHeader title={zh ? "系统设置" : "System settings"} helpLabel={t("pageHelp")} closeLabel={t("close")} helpContent={<p>{zh ? "管理交付网络配置。配置权限与网络调用权限独立；凭据使用共享存储引用。" : "Manage delivery network configuration. Configuration and invocation permissions are independent; credentials reference shared storage."}</p>} />
    <Tabs defaultActiveKey="network" items={[{ key: "network", label: zh ? "网络与依赖" : "Network and dependencies", children: <NetworkSettingsPanel t={t} /> }]} />
  </div>
}

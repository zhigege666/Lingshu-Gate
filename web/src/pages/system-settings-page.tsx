import { PageHeader } from "@/components/page-shell"
import { NetworkSettingsPanel } from "@/features/network/network-settings-panel"
import type { TFunction } from "@/i18n"

export function SystemSettingsPage({ t }: { t: TFunction }) {
  const zh = t("uploads") === "项目上传"
  return <div className="flex min-w-0 flex-col gap-3">
    <PageHeader title={zh ? "系统设置" : "System settings"} helpLabel={t("pageHelp")} closeLabel={t("close")} helpContent={<p>{zh ? "配置 Git 与依赖安装的网络、代理和软件源。" : "Configure networking, proxies and package sources for Git and dependency installation."}</p>} />
    <NetworkSettingsPanel t={t} />
  </div>
}

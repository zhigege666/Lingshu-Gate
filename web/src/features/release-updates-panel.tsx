import { useEffect, useState } from "react"
import { Alert, Button, Card, Select, Space, Tag, Typography } from "antd"
import { networkApi, type NetworkProfile } from "@/api/network"
import { releaseUpdatesApi, type ReleaseUpdateResult, type ReleaseUpdateSettings } from "@/api/release-updates"
import type { TFunction } from "@/i18n"

export function ReleaseUpdatesPanel({ t }: { t: TFunction }) {
  const zh = t("uploads") === "项目上传"
  const copy = (cn: string, en: string) => zh ? cn : en
  const [settings, setSettings] = useState<ReleaseUpdateSettings | null>(null)
  const [profiles, setProfiles] = useState<NetworkProfile[]>([])
  const [selected, setSelected] = useState("direct")
  const [result, setResult] = useState<ReleaseUpdateResult | null>(null)
  const [loading, setLoading] = useState(true)
  const [checking, setChecking] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    try {
      const [next, network] = await Promise.all([releaseUpdatesApi.settings(), networkApi.settings()])
      setSettings(next)
      setProfiles(network.profiles || [])
      setSelected(next.proxy_profile ? `${next.proxy_profile.id}:${next.proxy_profile.version}` : "direct")
      setError(null)
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { setLoading(false) }
  }
  useEffect(() => { void load().then(() => { void check() }) }, [])

  async function save() {
    if (!settings) return
    const [id, version] = selected === "direct" ? [null, null] : selected.split(":")
    setSaving(true); setError(null)
    try {
      const next = await releaseUpdatesApi.save(settings.revision, id, version ? Number(version) : null)
      setSettings({ ...settings, ...next })
    } catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { setSaving(false) }
  }
  async function check() {
    setChecking(true); setError(null)
    try { setResult(await releaseUpdatesApi.check()) }
    catch (cause) { setError(cause instanceof Error ? cause.message : String(cause)) }
    finally { setChecking(false) }
  }

  return <div className="flex flex-col gap-3" aria-busy={loading || checking || saving}>
    {error && <Alert type="error" showIcon message={error} />}
    <Card title={copy("GitHub 版本检查", "GitHub release checks")} extra={settings && <Tag>{`v${settings.current_version}`}</Tag>}>
      <div className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">{copy("检查 zhigege666/Lingshu-Gate 的最新正式 Release。检查请求可单独指定代理，不会改变 Git、npm 或其他服务的网络策略。", "Check the latest stable release of zhigege666/Lingshu-Gate. This proxy applies only to release checks and does not change Git, npm or other network policies.")}</p>
        <div className="gate-form-row">
          <span className="gate-form-label">{copy("检查代理", "Check proxy")}</span>
          <div className="gate-form-control">
            <Select className="w-full" value={selected} disabled={loading || saving} onChange={setSelected} options={[
              { value: "direct", label: copy("直连 GitHub", "Direct to GitHub") },
              ...profiles.filter(profile => profile.enabled && ["http", "https"].includes(profile.scheme)).map(profile => ({
                value: `${profile.id}:${profile.version}`,
                label: `${profile.name} · v${profile.version}`,
              })),
            ]} />
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button type="primary" loading={saving} disabled={loading || checking || !settings || selected === (settings.proxy_profile ? `${settings.proxy_profile.id}:${settings.proxy_profile.version}` : "direct")} onClick={() => void save()}>{copy("保存代理设置", "Save proxy")}</Button>
          <Button loading={checking} disabled={loading || saving} onClick={() => void check()}>{copy("立即检查更新", "Check for updates")}</Button>
        </div>
        {result && <div className="rounded-md border p-3 flex flex-col gap-2">
          <Space wrap>
            <Typography.Text strong>{result.update_available ? copy("发现新版本", "Update available") : copy("已是最新版本", "Up to date")}</Typography.Text>
            <Tag color={result.update_available ? "blue" : "green"}>{`v${result.latest_version}`}</Tag>
          </Space>
          <Typography.Text>{result.release_name}</Typography.Text>
          <Typography.Text type="secondary">{copy("当前版本", "Current")}: v{result.current_version} · {copy("检查路径", "Route")}: {result.proxy === "configured" ? copy("代理", "Proxy") : copy("直连", "Direct")}</Typography.Text>
          {result.release_url && <a href={result.release_url} target="_blank" rel="noreferrer">{copy("查看 GitHub Release", "View GitHub release")}</a>}
          {result.release_notes && <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded bg-muted p-3 text-xs">{result.release_notes}</pre>}
          {result.update_available && <Alert type="info" showIcon message={copy("更新安装由部署环境执行", "Installation is handled by the deployment environment")} description={copy("当前版本提供检查与更新说明；不会让 Gate Core 获取 Docker Socket 权限。请按对应部署方式更新镜像或程序。", "This release provides update discovery and release notes. Gate Core does not receive Docker Socket access; update the image or binary using your deployment environment.")} />}
        </div>}
      </div>
    </Card>
  </div>
}
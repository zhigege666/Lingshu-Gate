import { useEffect, useId, useState } from "react"
import { Alert, Button, Card, Select, Space, Tag, Typography } from "antd"
import { networkApi, type NetworkProfile } from "@/api/network"
import { releaseUpdatesApi, type ReleaseUpdateResult, type ReleaseUpdateSettings } from "@/api/release-updates"
import type { TFunction } from "@/i18n"

export function ReleaseUpdatesPanel({ t }: { t: TFunction }) {
  const zh = t("uploads") === "项目上传"
  const copy = (cn: string, en: string) => zh ? cn : en
  const field = useId()
  const [settings, setSettings] = useState<ReleaseUpdateSettings | null>(null)
  const [profiles, setProfiles] = useState<NetworkProfile[]>([])
  const [selected, setSelected] = useState("direct")
  const [result, setResult] = useState<ReleaseUpdateResult | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const pinned = settings?.proxy_profile
  const saved = pinned ? `${pinned.id}:${pinned.version}` : "direct"
  const options = profiles.filter(p => p.enabled && ["http", "https"].includes(p.scheme)).map(p => ({
    value: `${p.id}:${p.version}`, label: `${p.name} · v${p.version}`, disabled: false,
  }))
  if (pinned && !options.some(p => p.value === saved)) {
    options.push({ value: saved, label: `${pinned.name} · v${pinned.version}`, disabled: true })
  }

  async function loadSettings() {
    const [next, network] = await Promise.all([releaseUpdatesApi.settings(), networkApi.settings()])
    setSettings(next)
    setProfiles(network.profiles || [])
    setSelected(next.proxy_profile ? `${next.proxy_profile.id}:${next.proxy_profile.version}` : "direct")
  }

  async function check(reload = false) {
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      if (reload || !settings) {
        await loadSettings()
      } else if (selected !== saved) {
        const profile = profiles.find(p => `${p.id}:${p.version}` === selected)
        const next = await releaseUpdatesApi.save(settings.revision, profile?.id ?? null, profile?.version ?? null)
        setSettings({ ...settings, ...next })
      }
      setResult(await releaseUpdatesApi.check())
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => { void check(true) }, [])

  return <Card title={copy("GitHub 版本检查", "GitHub release checks")} extra={settings && <Tag>v{settings.current_version}</Tag>}>
    <div className="flex min-w-0 flex-col gap-3" aria-busy={busy}>
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor={field}>{copy("检查代理", "Check proxy")}</label>
        <Select id={field} className="min-w-48 max-w-full" value={selected} disabled={busy || !settings}
          onChange={setSelected} options={[{ value: "direct", label: copy("直连 GitHub", "Direct to GitHub") }, ...options]} />
        <Button type="primary" loading={busy} onClick={() => void check()}>
          {selected === saved ? copy("检查更新", "Check for updates") : copy("保存并检查", "Save and check")}
        </Button>
      </div>
      <details><summary>{copy("原生包自动更新", "Native automatic updates")}</summary>
        <p>{copy("宿主机安装 GitHub CLI 后，使用以下命令启动 Gate。Windows 使用 .\\\\lingshu-gate.exe。", "Install GitHub CLI on the host, then use this command to start Gate. On Windows use .\\\\lingshu-gate.exe.")}</p>
        <Typography.Text code copyable>./lingshu-gate native-update update-start</Typography.Text>
      </details>
      {error && <Alert type="error" showIcon title={error}
        action={<Button onClick={() => void check(true)} disabled={busy}>{copy("重新加载", "Reload")}</Button>} />}
      {result && <div className="flex min-w-0 flex-col items-start gap-2" role="status">
        <Space wrap>
          <Typography.Text strong>{result.update_available ? copy("发现新版本", "Update available") : copy("暂无可用更新", "No update available")}</Typography.Text>
          <Tag color={result.update_available ? "blue" : "green"}>v{result.latest_version}</Tag>
          {result.published_at && <time dateTime={result.published_at}>{result.published_at.slice(0, 10)}</time>}
        </Space>
        <Typography.Text type="secondary">{copy("本次检查", "Checked via")} · {result.proxy === "configured" ? copy("代理", "Proxy") : copy("直连", "Direct")}</Typography.Text>
        {result.release_url && <a href={result.release_url} target="_blank" rel="noreferrer">{result.release_name || copy("查看发行版本", "View release")}</a>}
        {result.release_notes && <details className="w-full min-w-0"><summary>{copy("发行说明", "Release notes")}</summary>
          <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded bg-muted p-3 text-xs">{result.release_notes}</pre></details>}
      </div>}
    </div>
  </Card>
}

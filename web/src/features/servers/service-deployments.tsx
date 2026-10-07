import { useEffect, useState } from "react"
import { Alert, Button, Table, Tag } from "antd"
import { buildApi, type DeploymentRecord } from "@/api/builds"
import type { Locale } from "@/i18n"

export function ServiceDeployments({ serverId, locale }: { serverId: string; locale: Locale }) {
  const [rows, setRows] = useState<DeploymentRecord[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)
  const zh = locale === "zh-CN"
  useEffect(() => {
    let active = true
    setLoading(true); setError(null); setRows([])
    void buildApi.deployments().then(result => { if (active) setRows(result.deployments.filter(item => item.server_id === serverId)) })
      .catch(err => { if (active) setError(String(err)) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [serverId, revision])
  return <div className="service-panel-stack">
    <Button onClick={() => setRevision(value => value + 1)} disabled={loading}>{zh ? "刷新部署记录" : "Refresh deployments"}</Button>
    {error && <Alert type="error" showIcon title={error} />}
    <Table rowKey="id" dataSource={rows} loading={loading} size="small" pagination={{ pageSize: 10 }} scroll={{ x: 560 }} columns={[
      { title: zh ? "部署" : "Deployment", dataIndex: "id", ellipsis: true },
      { title: zh ? "构建版本" : "Build version", dataIndex: "build_id", render: value => <a href={`#/builds/${encodeURIComponent(value)}`}>{value}</a> },
      { title: zh ? "状态" : "Status", dataIndex: "status", render: value => <Tag>{value}</Tag> },
      { title: zh ? "手动回滚" : "Manual rollback", dataIndex: "rollback_available", render: (value, row) => value ? <a href={`#/builds/${encodeURIComponent(row.build_id)}`}>{zh ? "查看有效快照" : "View valid snapshot"}</a> : "—" },
    ]} />
  </div>
}

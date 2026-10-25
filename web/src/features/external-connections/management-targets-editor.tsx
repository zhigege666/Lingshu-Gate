import { Button, Checkbox, Input, Table } from "antd"
import { managementActions, newManagementTarget, type ManagementTargetRow } from "./management-targets-model"

const actionLabels: Record<string, [string, string]> = {
  test: ["测试连接", "Test connection"],
  create: ["创建服务", "Create service"], update: ["更新服务", "Update service"], delete: ["删除服务", "Delete service"],
  revoke_trust: ["撤销 HTTP 许可", "Revoke HTTP"], restore_trust: ["恢复 HTTP 许可", "Restore HTTP"],
  "credential.read": ["查看凭据", "View credential"], "credential.create": ["创建凭据", "Create credential"],
  "credential.update": ["更新凭据", "Update credential"], "credential.delete": ["删除凭据", "Delete credential"],
}

export function ManagementTargetsEditor({ rows, onChange, zh, disabled = false, readOnly = false }: {
  rows: ManagementTargetRow[]; onChange: (rows: ManagementTargetRow[]) => void; zh: boolean; disabled?: boolean; readOnly?: boolean
}) {
  return <section aria-label={zh ? "管理目标" : "Management targets"}>
    <p>{zh ? "填写精确的服务或凭据 ID，并分别选择允许的操作。查看凭据仅返回掩码。调用还需已同意的对应工具与权限范围；移除全部目标会拒绝所有目标操作。" : "Enter exact service or credential IDs and select their allowed actions. Credential reads return masks only. Calls also require the consented tool and scope; removing every target denies all target operations."}</p>
    <Table rowKey={(_, index) => index!} size="small" dataSource={rows.map((row, index) => ({ ...row, index }))} pagination={{ pageSize: 10, showSizeChanger: false }} scroll={{ x: 680 }}
      locale={{ emptyText: zh ? "未授权任何管理目标。" : "No management targets authorized." }} columns={[
        { title: zh ? "目标 ID" : "Target ID", render: (_, row) => readOnly ? row.id : <Input aria-label={zh ? `目标 ID ${row.index + 1}` : `Target ID ${row.index + 1}`} maxLength={128} disabled={disabled} placeholder="service-example" value={row.id} onChange={event => onChange(rows.map((item, index) => index === row.index ? { ...item, id: event.target.value } : item))} /> },
        { title: zh ? "允许操作" : "Allowed actions", width: 540, render: (_, row) => readOnly ? row.actions.map(action => actionLabels[action]?.[zh ? 0 : 1] || action).join(" · ") : <Checkbox.Group aria-label={zh ? `允许操作 ${row.index + 1}` : `Allowed actions ${row.index + 1}`} style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", gap: "var(--space-2, 8px)", whiteSpace: "nowrap" }} disabled={disabled} value={row.actions} options={managementActions.map(action => ({ value: action, label: actionLabels[action][zh ? 0 : 1] }))} onChange={actions => onChange(rows.map((item, index) => index === row.index ? { ...item, actions: actions.map(String) } : item))} /> },
        ...(!readOnly ? [{ title: zh ? "操作" : "Actions", width: 85, render: (_: unknown, row: ManagementTargetRow & { index: number }) => <Button size="small" disabled={disabled} onClick={() => onChange(rows.filter((_, index) => index !== row.index))}>{zh ? "移除" : "Remove"}</Button> }] : []),
      ]} />
    {!readOnly && <Button disabled={disabled || rows.length >= 1000} onClick={() => onChange([...rows, newManagementTarget()])}>{zh ? "添加精确目标" : "Add exact target"}</Button>}
  </section>
}

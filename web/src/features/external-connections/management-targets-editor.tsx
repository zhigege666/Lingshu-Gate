import { Button, Checkbox, Input, Table } from "antd"
import { newManagementTarget, type ManagementTargetRow } from "./management-targets-model"

export function ManagementTargetsEditor({ rows, onChange, zh, disabled = false, readOnly = false }: {
  rows: ManagementTargetRow[]; onChange: (rows: ManagementTargetRow[]) => void; zh: boolean; disabled?: boolean; readOnly?: boolean
}) {
  return <section aria-label={zh ? "管理目标" : "Management targets"}>
    <p>{zh ? "逐项指定精确服务 ID 和创建/更新权限。没有通配符；移除全部目标将拒绝所有目标操作。此处不生成凭据、不修改 HTTP 信任，也不发布工具分类。" : "Specify exact server IDs and create/update rights. Wildcards are unsupported; removing every target denies all target operations. This does not generate credentials, change HTTP trust or publish tool classifications."}</p>
    <Table rowKey={(_, index) => index!} size="small" dataSource={rows.map((row, index) => ({ ...row, index }))} pagination={{ pageSize: 10, showSizeChanger: false }} scroll={{ x: 510 }}
      locale={{ emptyText: zh ? "未授权任何管理目标。" : "No management targets authorized." }} columns={[
        { title: zh ? "服务 ID" : "Server ID", render: (_, row) => readOnly ? row.id : <Input aria-label={zh ? `服务 ID ${row.index + 1}` : `Server ID ${row.index + 1}`} maxLength={128} disabled={disabled} placeholder="service-example" value={row.id} onChange={event => onChange(rows.map((item, index) => index === row.index ? { ...item, id: event.target.value } : item))} /> },
        { title: zh ? "允许操作" : "Allowed actions", width: 210, render: (_, row) => readOnly ? row.actions.map(action => zh ? action === "create" ? "创建" : "更新" : action).join(" · ") : <Checkbox.Group aria-label={zh ? `允许操作 ${row.index + 1}` : `Allowed actions ${row.index + 1}`} disabled={disabled} value={row.actions} options={[{ value: "create", label: zh ? "创建" : "Create" }, { value: "update", label: zh ? "更新" : "Update" }]} onChange={actions => onChange(rows.map((item, index) => index === row.index ? { ...item, actions: actions.map(String) } : item))} /> },
        ...(!readOnly ? [{ title: zh ? "操作" : "Actions", width: 85, render: (_: unknown, row: ManagementTargetRow & { index: number }) => <Button size="small" disabled={disabled} onClick={() => onChange(rows.filter((_, index) => index !== row.index))}>{zh ? "移除" : "Remove"}</Button> }] : []),
      ]} />
    {!readOnly && <Button disabled={disabled || rows.length >= 1000} onClick={() => onChange([...rows, newManagementTarget()])}>{zh ? "添加精确目标" : "Add exact target"}</Button>}
  </section>
}

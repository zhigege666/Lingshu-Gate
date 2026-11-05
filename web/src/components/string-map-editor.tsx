import { useEffect, useRef, useState } from "react"
import { Radio, Select } from "antd"
import { Trash2 } from "lucide-react"
import type { Credential } from "@/api/client"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { credentialRef, envKeyFromCredential } from "@/features/mcp-config/model"
import { resolveStringMapRows, type StringMapRow } from "@/features/mcp-config/string-map-draft"

export function StringMapEditor({ value, label, disabled, onChange, zh, id, credentials = [], credentialKeyMode = "environment", onDraftDirtyChange }: {
  value: Record<string, string>; label: string; disabled: boolean; onChange: (value: Record<string, string>) => void
  zh: boolean; id: string; credentials?: Credential[]; credentialKeyMode?: "environment" | "header"; onDraftDirtyChange: (dirty: boolean) => void
}) {
  const sequence = useRef(0)
  const blank = (): StringMapRow => ({ id: ++sequence.current, key: "", value: "" })
  const fromValue = () => [...Object.entries(value).map(([key, item]) => ({ id: ++sequence.current, key, value: item, originalKey: key, originalValue: item })), blank()]
  const [rows, setRows] = useState<StringMapRow[]>(fromValue)
  const serialized = JSON.stringify(value)
  const lastPublished = useRef(serialized)
  const [referenceId, setReferenceId] = useState<string | undefined>()
  const [referencePrefix, setReferencePrefix] = useState("Bearer ")
  const referenceRow = useRef<number | null>(null)
  const reportDirty = useRef(onDraftDirtyChange)
  reportDirty.current = onDraftDirtyChange
  const resolved = resolveStringMapRows(rows, credentialKeyMode === "header")
  const invalid = resolved.issues.length > 0
  useEffect(() => {
    if (serialized === lastPublished.current) return
    lastPublished.current = serialized
    setRows(fromValue()); setReferenceId(undefined); referenceRow.current = null
  }, [serialized])
  useEffect(() => { reportDirty.current(invalid) }, [invalid])
  useEffect(() => () => reportDirty.current(false), [])

  function update(next: StringMapRow[]) {
    if (!next.some(row => row.originalKey === undefined && !row.key && !row.value)) next = [...next, blank()]
    setRows(next)
    const result = resolveStringMapRows(next, credentialKeyMode === "header")
    reportDirty.current(result.issues.length > 0)
    if (result.value) { lastPublished.current = JSON.stringify(result.value); onChange(result.value) }
  }
  function edit(rowId: number, patch: Partial<Pick<StringMapRow, "key" | "value">>) {
    update(rows.map(row => row.id === rowId ? { ...row, ...patch } : row))
  }
  function chooseCredential(credentialId: string, prefix = referencePrefix) {
    const target = rows.find(row => row.id === referenceRow.current)
      || rows.find(row => row.originalKey === undefined && !row.key && !row.value)!
    referenceRow.current = target.id; setReferenceId(credentialId)
    edit(target.id, { key: target.key || (credentialKeyMode === "environment" ? envKeyFromCredential(credentialId) : "Authorization"),
      value: (credentialKeyMode === "header" ? prefix : "") + credentialRef(credentialId) })
  }
  const messages = {
    missing_key: zh ? "请填写键名，或移除此行。" : "Enter a key or remove this row.",
    duplicate_key: zh ? "键名重复，请修改后保存。" : "This key is duplicated. Rename it before saving.",
    masked_rename: zh ? "改键名后请重新填写值或凭据引用；*** 只能保留原键的秘密。" : "Supply a value or credential reference after renaming. *** can only retain the original key's secret.",
  }
  return <fieldset className="manifest-map" disabled={disabled}>
    <legend className="sr-only">{label}</legend>
    {rows.map((row, index) => {
      const issue = resolved.issues.find(issue => issue.id === row.id)
      const errorId = `${id}-${row.id}-error`
      return <div key={row.id}>
        <div className="manifest-map-row">
          <Input id={index === 0 ? id : `${id}-${row.id}-key`} aria-label={`${label} ${zh ? "键名" : "key"} ${index + 1}`} placeholder={zh ? "键名" : "Key"} value={row.key}
            aria-invalid={Boolean(issue)} aria-describedby={issue ? errorId : undefined} onChange={event => edit(row.id, { key: event.target.value })} />
          <Input aria-label={`${label} ${zh ? "值" : "value"} ${index + 1}`} placeholder={zh ? "值（可为空）" : "Value (may be empty)"} value={row.value}
            aria-invalid={Boolean(issue)} aria-describedby={issue ? errorId : undefined} onChange={event => edit(row.id, { value: event.target.value })} />
          <Button type="button" variant="ghost" size="sm" className="size-9 shrink-0 px-0" disabled={rows.length === 1 && !row.key && !row.value}
            aria-label={`${zh ? "移除" : "Remove"} ${row.key || `${label} ${index + 1}`}`} onClick={() => {
              if (referenceRow.current === row.id) { referenceRow.current = null; setReferenceId(undefined) }
              update(rows.filter(item => item.id !== row.id))
            }}><Trash2 className="size-4" /></Button>
        </div>
        {issue && <p id={errorId} role="alert" className="text-xs text-destructive">{messages[issue.code]}</p>}
      </div>
    })}
    {credentials.length > 0 && <section className="space-y-2">
      <Label htmlFor={`${id}-credential`} className="text-xs">{zh ? "插入凭据引用" : "Insert credential reference"}</Label>
      <Select id={`${id}-credential`} className="w-full" showSearch optionFilterProp="label" aria-label={zh ? "插入凭据引用" : "Insert credential reference"}
        getPopupContainer={(trigger: HTMLElement) => trigger.closest<HTMLElement>('[role="dialog"]') || trigger.parentElement!}
        disabled={disabled} value={referenceId} placeholder={zh ? "搜索凭据 ID 或名称" : "Search credential ID or name"}
        options={credentials.map(item => ({ value: item.id, label: `${item.name} · ${item.id}` }))} onChange={credentialId => chooseCredential(credentialId)} />
      {credentialKeyMode === "header" && <Radio.Group size="small" aria-label={zh ? "引用格式" : "Reference format"} disabled={disabled} value={referencePrefix}
        options={[{ value: "Bearer ", label: "Bearer token" }, { value: "", label: zh ? "原始值" : "Raw value" }]} onChange={event => {
          const prefix = event.target.value as string; setReferencePrefix(prefix)
          if (referenceId) chooseCredential(referenceId, prefix)
        }} />}
    </section>}
  </fieldset>
}

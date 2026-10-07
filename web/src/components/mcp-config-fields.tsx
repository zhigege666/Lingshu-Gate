import { Children, cloneElement, isValidElement, useId, useState, type ReactElement, type ReactNode } from "react"
import { Popover } from "antd"
import { AlertCircle, Plus, Trash2, X } from "lucide-react"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Switch } from "@/components/ui/switch"

export function ConfigHelp({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  return <Popover trigger="click" open={open} onOpenChange={setOpen} content={
    <div className="max-w-xs text-sm" onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); setOpen(false) } }}>
      <div className="mb-2 flex items-center justify-between gap-3 font-medium">{label}<button type="button" aria-label={`${label} ×`} onClick={() => setOpen(false)}><X className="size-4" /></button></div>
      {children}
    </div>
  }><button type="button" aria-label={`${label} ?`} aria-expanded={open} className="inline-flex size-7 shrink-0 items-center justify-center rounded text-muted-foreground hover:bg-muted focus-visible:outline focus-visible:outline-2 focus-visible:outline-primary" onKeyDown={event => { if (event.key === "Escape") { event.stopPropagation(); setOpen(false) } }}><AlertCircle className="size-4" /></button></Popover>
}

export function ConfigField({ label, help, children, className = "", search = "" }: { label: string; help?: string; children: ReactNode; className?: string; search?: string }) {
  const id = useId()
  const child = Children.only(children)
  return <div className={`min-w-0 space-y-1.5 ${className}`} data-config-field={`${label} ${search}`}>
    <div className="flex min-h-7 items-center gap-1"><label htmlFor={id} className="text-sm font-medium">{label}</label>{help && <ConfigHelp label={label}>{help}</ConfigHelp>}</div>
    {isValidElement(child) ? cloneElement(child as ReactElement<Record<string, unknown>>, { id, "aria-label": label }) : child}
  </div>
}

// 任意元数据保留值类型；复杂字段通过结构化控件编辑，不偷偷转成字符串。
export function ConfigValue({ value, onChange, label, zh, depth = 0 }: { value: unknown; onChange: (value: unknown) => void; label: string; zh: boolean; depth?: number }) {
  const [newKey, setNewKey] = useState("")
  const [newType, setNewType] = useState("string")
  const [error, setError] = useState("")
  const defaults: Record<string, unknown> = { string: "", number: 0, boolean: false, object: {}, array: [], null: null }
  if (depth > 12) return <span className="text-sm text-muted-foreground">{zh ? "嵌套过深，请使用右上角 JSON 编辑" : "Use JSON for deeply nested values"}</span>
  if (Array.isArray(value)) return <div className="space-y-2">
    {value.map((item, index) => <div key={index} className="flex items-start gap-2"><div className="min-w-0 flex-1"><ConfigValue value={item} onChange={next => onChange(value.map((old, i) => i === index ? next : old))} label={`${label} ${index + 1}`} zh={zh} depth={depth + 1} /></div><Button type="button" variant="ghost" size="sm" aria-label={`${zh ? "删除" : "Remove"} ${label} ${index + 1}`} onClick={() => onChange(value.filter((_, i) => i !== index))}><Trash2 className="size-4" /></Button></div>)}
    <div className="flex gap-2"><ValueType value={newType} onChange={setNewType} zh={zh} label={label} /><Button type="button" variant="outline" size="sm" onClick={() => onChange([...value, defaults[newType]])}><Plus className="mr-1 size-4" />{zh ? "添加项" : "Add item"}</Button></div>
  </div>
  if (value !== null && typeof value === "object") {
    const object = value as Record<string, unknown>
    return <div className="space-y-3">
      {Object.entries(object).map(([key, item]) => <div key={key} className="grid grid-cols-[minmax(100px,1fr)_minmax(0,3fr)_32px] items-start gap-2">
        <span className="break-all py-2 text-sm font-mono">{key}</span><ConfigValue value={item} label={`${label}.${key}`} zh={zh} depth={depth + 1} onChange={next => onChange({ ...object, [key]: next })} /><Button type="button" variant="ghost" size="sm" aria-label={`${zh ? "删除" : "Remove"} ${key}`} onClick={() => { const next = { ...object }; delete next[key]; onChange(next) }}><Trash2 className="size-4" /></Button>
      </div>)}
      <div className="flex flex-wrap gap-2"><Input className="max-w-56" value={newKey} aria-label={`${label} ${zh ? "新字段" : "new key"}`} placeholder={zh ? "字段名称" : "Field name"} onChange={event => { setNewKey(event.target.value); setError("") }} /><ValueType value={newType} onChange={setNewType} zh={zh} label={label} /><Button type="button" variant="outline" size="sm" onClick={() => {
        if (!newKey.trim() || Object.prototype.hasOwnProperty.call(object, newKey.trim())) { setError(zh ? "请输入不重复的字段名称" : "Enter a unique field name"); return }
        onChange({ ...object, [newKey.trim()]: defaults[newType] }); setNewKey(""); setError("")
      }}><Plus className="mr-1 size-4" />{zh ? "添加字段" : "Add field"}</Button></div>{error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </div>
  }
  if (typeof value === "boolean") return <Switch aria-label={label} checked={value} onCheckedChange={onChange} />
  if (value === null) return <div className="flex gap-2"><span className="text-sm text-muted-foreground">null</span><Button type="button" size="sm" variant="outline" onClick={() => onChange("")}>{zh ? "设为文本" : "Use text"}</Button></div>
  return <Input aria-label={label} type={typeof value === "number" ? "number" : "text"} value={String(value ?? "")} onChange={event => onChange(typeof value === "number" ? Number(event.target.value) : event.target.value)} />
}

function ValueType({ value, onChange, zh, label }: { value: string; onChange: (value: string) => void; zh: boolean; label: string }) {
  return <select aria-label={`${label} ${zh ? "值类型" : "value type"}`} value={value} onChange={event => onChange(event.target.value)} className="h-9 rounded-md border border-input bg-background px-2 text-sm">
    {[['string', '文本'], ['number', '数字'], ['boolean', '开关'], ['object', '对象'], ['array', '列表'], ['null', '空值']].map(([type, name]) => <option key={type} value={type}>{zh ? name : type}</option>)}
  </select>
}

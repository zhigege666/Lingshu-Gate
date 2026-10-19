import { useId } from "react"
import type { PackageManagerOverride } from "@/api/builds"
import { FieldLabel } from "@/components/field-help"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

const pins = { npm: "11.6.0", pnpm: "9.15.4", yarn: "1.22.22" }
const locks = { npm: ["npm-shrinkwrap.json", "package-lock.json"], pnpm: ["pnpm-lock.yaml"], yarn: ["yarn.lock"] } as const

export function PackageManagerFields({ value, onChange, choices = [], disabled, zh }: {
  value: PackageManagerOverride | null
  onChange: (value: PackageManagerOverride | null) => void
  choices?: PackageManagerOverride[]
  disabled?: boolean
  zh: boolean
}) {
  const fieldId = useId()
  return <fieldset disabled={disabled} className="gate-form-fields min-w-0 border-0 p-0">
    <legend className="mb-4 text-sm font-medium">{zh ? "项目依赖工具覆盖" : "Project package manager override"}</legend>
    <div className="gate-form-row"><label className="gate-form-label" htmlFor={`${fieldId}-manager`}><FieldLabel label={zh ? "工具选择" : "Manager"} zh={zh} helpId={`${fieldId}-manager-help`} help={zh ? "覆盖保存至当前操作者的项目草稿。缺失工具会列入待确认计划，在隔离执行器按固定版本准备；不改变宿主配置。pnpm 11 要求 Node ≥22.13。pnpm 12 与 Yarn Berry 暂不支持。" : "Overrides are saved in your project draft. Missing tools are prepared at the confirmed exact version by the isolated executor. pnpm 11 requires Node ≥22.13. pnpm 12 and Yarn Berry are unsupported."} /></label><div className="gate-form-control"><select id={`${fieldId}-manager`} aria-label={zh ? "工具选择" : "Manager selection"} aria-describedby={`${fieldId}-manager-help`} className="gate-input h-[var(--control-height)] min-w-0 rounded-[var(--radius-control)] border border-input bg-card px-[var(--control-padding-inline)] text-sm" value={value?.name || "auto"} onChange={event => {
      const name = event.target.value as PackageManagerOverride["name"] | "auto"
      onChange(name === "auto" ? null : { name, version: pins[name], lockfile: null })
    }}><option value="auto">{zh ? "依据声明与锁文件" : "Use declaration and lockfile"}</option><option value="npm">npm 9–11</option><option value="pnpm">pnpm 8–11</option><option value="yarn">Yarn Classic 1.22</option></select></div></div>
    {value && <div className="gate-form-fields">
      <div className="gate-form-row"><label className="gate-form-label" htmlFor={`${fieldId}-version`}>{zh ? "精确版本" : "Exact version"}</label><div className="gate-form-control"><Input id={`${fieldId}-version`} value={value.version} onChange={event => onChange({ ...value, version: event.target.value })} placeholder="9.15.4" /></div></div>
      <div className="gate-form-row"><label className="gate-form-label" htmlFor={`${fieldId}-lockfile`}>{zh ? "锁文件" : "Lockfile"}</label><div className="gate-form-control"><select id={`${fieldId}-lockfile`} className="gate-input h-[var(--control-height)] min-w-0 rounded-[var(--radius-control)] border border-input bg-card px-[var(--control-padding-inline)] text-sm" value={value.lockfile || "auto"} onChange={event => onChange({ ...value, lockfile: event.target.value === "auto" ? null : event.target.value as PackageManagerOverride["lockfile"] })}><option value="auto">{zh ? "自动匹配" : "Match automatically"}</option>{locks[value.name].map(lock => <option key={lock} value={lock}>{lock}</option>)}</select></div></div>
    </div>}
    {choices.length > 0 && <div className="flex flex-wrap gap-2" role="group" aria-label={zh ? "推荐选择" : "Recommended choices"}>{choices.map(choice => <Button key={`${choice.name}:${choice.lockfile}`} size="sm" variant="outline" type="button" onClick={() => onChange(choice)}>{choice.name}@{choice.version} · {choice.lockfile}</Button>)}</div>}
  </fieldset>
}

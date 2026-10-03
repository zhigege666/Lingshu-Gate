import type { PackageManagerOverride } from "@/api/builds"
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
  return <fieldset disabled={disabled} className="flex min-w-0 flex-col gap-2 rounded-md border p-3">
    <legend className="px-1 text-sm font-medium">{zh ? "项目依赖工具覆盖" : "Project package manager override"}</legend>
    <label className="flex flex-col gap-1 text-sm"><span>{zh ? "工具选择" : "Manager selection"}</span><select className="h-9 rounded-md border border-input bg-transparent px-3" value={value?.name || "auto"} onChange={event => {
      const name = event.target.value as PackageManagerOverride["name"] | "auto"
      onChange(name === "auto" ? null : { name, version: pins[name], lockfile: null })
    }}><option value="auto">{zh ? "依据声明与锁文件" : "Use declaration and lockfile"}</option><option value="npm">npm 9–11</option><option value="pnpm">pnpm 8–11</option><option value="yarn">Yarn Classic 1.22</option></select></label>
    {value && <div className="grid min-w-0 gap-2 md:grid-cols-2">
      <label className="flex flex-col gap-1 text-sm"><span>{zh ? "精确版本" : "Exact version"}</span><Input value={value.version} onChange={event => onChange({ ...value, version: event.target.value })} placeholder="9.15.4" /></label>
      <label className="flex flex-col gap-1 text-sm"><span>{zh ? "锁文件" : "Lockfile"}</span><select className="h-9 min-w-0 rounded-md border border-input bg-transparent px-3" value={value.lockfile || "auto"} onChange={event => onChange({ ...value, lockfile: event.target.value === "auto" ? null : event.target.value as PackageManagerOverride["lockfile"] })}><option value="auto">{zh ? "自动匹配" : "Match automatically"}</option>{locks[value.name].map(lock => <option key={lock} value={lock}>{lock}</option>)}</select></label>
    </div>}
    <p className="text-xs text-muted-foreground">{zh ? "覆盖保存至当前操作者的项目草稿。缺失工具会列入待确认计划，在隔离执行器按固定版本准备；不改变宿主配置。pnpm 11 要求 Node ≥22.13。pnpm 12 与 Yarn Berry 暂不支持。" : "Overrides are saved in your project draft. Missing tools are prepared at the confirmed exact version by the isolated executor. pnpm 11 requires Node ≥22.13. pnpm 12 and Yarn Berry are unsupported."}</p>
    {choices.length > 0 && <div className="flex flex-wrap gap-2" role="group" aria-label={zh ? "推荐选择" : "Recommended choices"}>{choices.map(choice => <Button key={`${choice.name}:${choice.lockfile}`} size="sm" variant="outline" type="button" onClick={() => onChange(choice)}>{choice.name}@{choice.version} · {choice.lockfile}</Button>)}</div>}
  </fieldset>
}

// 本地浏览器验收夹具：所有接口均为内存桩，不连接后端或写入真实配置。
import { useEffect, useState } from "react"
import { createRoot } from "react-dom/client"
import { api } from "@/api/client"
import { ConsoleDesignProvider, useConsoleDesign } from "@/components/console-design-provider"
import { ConfigsPage } from "@/pages/configs-page"
import { translate, type TFunction } from "@/i18n"
import "@/index.css"
import "@/console-workspace.css"

if (!import.meta.env.DEV) throw new Error("Preview fixture is development-only")
api.credentials = async () => [{ id: "gitNexus_token", name: "GitNexus", description: "测试引用", value_masked: "***", created_at: "", updated_at: "" }]
api.validateConfig = async () => ({ ok: true, can_apply: true, summary: { errors: 0, warnings: 0, info: 0, ok: 1 }, checks: [] })
const example = { id: "gitnexus", name: "GitNexus Code Graph", enabled: true, launch: { type: "external" }, transport: { type: "streamable_http", endpoint: "https://graph.example.com/mcp", headers: { Authorization: "Bearer ${credential:gitNexus_token}", "X-Client": "lingshu-gate" } }, timeout_seconds: 30, roots: ["/workspace/projects"], analysis: { nested: { enabled: false, count: 0 } } }
function Fixture() {
  const [value, setValue] = useState(JSON.stringify(example, null, 2))
  const [open, setOpen] = useState(true)
  const [saved, setSaved] = useState("")
  const t: TFunction = key => translate("zh-CN", key)
  return <ConsoleDesignProvider><PreviewTheme /><ConfigsPage locale="zh-CN" t={t} configs={[{ id: "gitnexus", path: "/example/gitnexus.yaml", format: "yaml", manifest: example }]} configErrors={[]} selectedConfigId="gitnexus" configText={value} busy={false} editorOpen={open} onCloseEditor={() => setOpen(false)} onNewConfig={() => setOpen(true)} onReloadConfigs={() => {}} onEditConfig={() => setOpen(true)} onApplyConfig={() => {}} onDeleteConfig={() => {}} onConfigTextChange={setValue} onSaveConfig={async next => { setSaved(next || value); setOpen(false) }} /><output aria-label="测试保存结果">{saved}</output></ConsoleDesignProvider>
}
function PreviewTheme() {
  const { setTheme } = useConsoleDesign()
  useEffect(() => { setTheme("light") }, [])
  return null
}
createRoot(document.getElementById("root")!).render(<Fixture />)

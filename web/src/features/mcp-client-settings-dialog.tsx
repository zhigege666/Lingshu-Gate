import { useRef, useState } from "react"
import { Form, Input, Radio } from "antd"
import { FormDialog } from "@/components/form-dialog"
import { Button } from "@/components/ui/button"
import { useConfirm } from "@/components/confirm-dialog"
import { useDraftCloseGuard } from "@/components/use-draft-close-guard"
import type { Locale, TFunction } from "@/i18n"
import { clientConfiguration, clientEndpoint, type McpClientSettings } from "./mcp-client-settings"
import "./mcp-client-settings.css"

const storageKey = "lingshu-gate-mcp-client-settings"

export function McpClientSettingsDialog({ locale, t }: { locale: Locale; t: TFunction }) {
  const zh = locale === "zh-CN"
  const [open, setOpen] = useState(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const [draft, setDraft] = useState<McpClientSettings>({ name: "gate", endpoint: "", mode: "direct" })
  const [baseline, setBaseline] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState("")
  const { confirm, confirmDialog } = useConfirm(t)
  const dirty = JSON.stringify(draft) !== baseline
  const close = useDraftCloseGuard({ dirty, pending: false, locale, confirm, onClose: () => setOpen(false) })
  let configuration = ""
  try { configuration = clientConfiguration(draft) } catch { /* Incomplete drafts retain editable inputs. */ }

  function begin() {
    let initial: McpClientSettings = { name: "gate", endpoint: `${window.location.origin}/mcp`, mode: "direct" }
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || "null") as McpClientSettings | null
      if (saved && ["direct", "on_demand"].includes(saved.mode)) { clientEndpoint(saved); initial = saved }
    } catch { /* Optional browser preference may be absent or invalid. */ }
    setDraft(initial); setBaseline(JSON.stringify(initial)); setError(null); setNotice(""); setOpen(true)
  }

  function save() {
    try {
      clientEndpoint(draft)
      localStorage.setItem(storageKey, JSON.stringify(draft))
      setBaseline(JSON.stringify(draft)); setError(null)
      setNotice(zh ? "客户端设置已保存在此浏览器。复制配置并重新连接客户端后生效。" : "Client settings saved in this browser. Copy the configuration and reconnect your client to apply them.")
    } catch {
      setError(zh ? "检查客户端名称和 /mcp 地址；地址不能包含凭据或其他查询参数。浏览器还需允许保存设置。" : "Check the client name and /mcp URL; credentials and other query parameters are excluded. Browser storage must be available.")
    }
  }

  async function copy() {
    try { await navigator.clipboard.writeText(configuration); setNotice(zh ? "配置已复制，请在客户端中替换令牌占位符。" : "Configuration copied. Replace the token placeholder in your client."); setError(null) }
    catch { setError(zh ? "复制失败，请手动选择并复制配置。" : "Copy failed. Select and copy the configuration manually.") }
  }

  return <>
    <Button ref={trigger} onClick={begin}>{zh ? "客户端设置" : "Client settings"}</Button>
    <FormDialog open={open} title={zh ? "MCP 客户端设置" : "MCP client settings"} closeLabel={t("close")} onClose={() => void close()} dirty={dirty} error={error}
      onCloseAutoFocus={event => { event.preventDefault(); trigger.current?.focus() }}
      description={zh ? "为此客户端选择工具发现方式。按需模式先搜索，再读取选中工具的参数；每次调用仍检查现有授权。" : "Choose how this client discovers tools. On-demand mode searches first, then loads the selected tool schema; each call still checks existing permissions."}
      footer={<><Button variant="outline" onClick={() => void close()}>{t("close")}</Button><Button variant="outline" disabled={!configuration} onClick={() => void copy()}>{zh ? "复制配置" : "Copy configuration"}</Button><Button onClick={save}>{zh ? "保存设置" : "Save settings"}</Button></>}>
      {notice && <p role="status" className="mb-4 text-sm">{notice}</p>}
      <Form layout="horizontal" className="mcp-client-inline-form" colon={false}>
        <Form.Item label={zh ? "客户端名称" : "Client name"} htmlFor="mcp-client-name"><Input id="mcp-client-name" value={draft.name} maxLength={64} onChange={event => setDraft({ ...draft, name: event.target.value })} /></Form.Item>
        <Form.Item label={zh ? "MCP 地址" : "MCP URL"} htmlFor="mcp-client-url"><Input id="mcp-client-url" value={draft.endpoint} maxLength={2048} onChange={event => setDraft({ ...draft, endpoint: event.target.value })} /></Form.Item>
        <Form.Item label={zh ? "工具发现" : "Tool discovery"}>
          <Radio.Group aria-label={zh ? "工具发现" : "Tool discovery"} value={draft.mode} onChange={event => setDraft({ ...draft, mode: event.target.value })}>
            <Radio value="direct">{zh ? "完整工具列表" : "Full tool list"}</Radio><Radio value="on_demand">{zh ? "按需发现" : "On demand"}</Radio>
          </Radio.Group>
          <p className="text-xs text-muted-foreground">{zh ? "完整列表保留旧客户端行为；按需模式提供四个固定入口，适合大型工具目录。新工具仍需按现有流程审核与授权。" : "Full list preserves existing client behavior. On demand exposes four fixed entries for large catalogs. New tools still follow existing review and authorization."}</p>
        </Form.Item>
        <Form.Item label={zh ? "客户端配置" : "Client configuration"} htmlFor="mcp-client-configuration"><Input.TextArea id="mcp-client-configuration" readOnly value={configuration} autoSize={{ minRows: 6, maxRows: 10 }} /></Form.Item>
      </Form>
    </FormDialog>{confirmDialog}
  </>
}

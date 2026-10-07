import { useRef, useState } from "react"
import { Button, Input, Tag, Tooltip } from "antd"
import { FormDialog } from "@/components/form-dialog"
import type { OAuthTool } from "./oauth-api"

/** Read-only identity disclosure; the caller still owns scope selection. */
export function OAuthToolIdentity({ tool, zh }: { tool: OAuthTool; zh: boolean }) {
  const [open, setOpen] = useState(false)
  const [message, setMessage] = useState("")
  const generation = useRef(0)
  const trigger = useRef<HTMLButtonElement>(null)
  function close() { generation.current++; setOpen(false); setMessage("") }
  async function copy() {
    const current = generation.current
    try {
      await navigator.clipboard.writeText(tool.id)
      if (current === generation.current) setMessage(zh ? "工具 ID 已复制。" : "Tool ID copied.")
    } catch { if (current === generation.current) setMessage(zh ? "复制失败；请从字段中手动复制。" : "Copy failed; copy from the field manually.") }
  }
  return <>
    <Tooltip trigger={["hover", "focus"]} title={tool.id}>
      <Button ref={trigger} type="text" size="small" className="oauth-tool-name" aria-label={`${tool.name} · ${tool.id}`} onClick={() => { setMessage(""); setOpen(true) }}>{tool.name}</Button>
    </Tooltip>
    <FormDialog open={open} title={zh ? "工具详情" : "Tool details"} closeLabel={zh ? "关闭" : "Close"} onClose={close} className="oauth-tool-identity-dialog" onCloseAutoFocus={event => { if (trigger.current?.isConnected) { event.preventDefault(); trigger.current.focus({ preventScroll: true }) } }} footer={<Button onClick={close}>{zh ? "关闭" : "Close"}</Button>}>
      <dl className="oauth-identity-fields">
        <div><dt>{zh ? "工具名称" : "Tool name"}</dt><dd>{tool.name}</dd></div>
        <div><dt>Tool ID</dt><dd><Input aria-label="Tool ID" readOnly value={tool.id} /><Button onClick={() => void copy()}>{zh ? "复制工具 ID" : "Copy tool ID"}</Button></dd></div>
        <div><dt>{zh ? "服务名称" : "MCP name"}</dt><dd>{tool.server_name || "—"}</dd></div>
        <div><dt>MCP ID</dt><dd>{tool.server_id}</dd></div>
        <div><dt>{zh ? "权限" : "Access"}</dt><dd><Tag color={tool.access === "write" ? "orange" : "blue"}>{tool.access === "write" ? zh ? "写入" : "Write" : zh ? "只读" : "Read"}</Tag>{tool.currently_authorized === false && <span>{zh ? "当前不可授权" : "Currently unavailable"}</span>}</dd></div>
      </dl>
      {message && <p role="status">{message}</p>}
    </FormDialog>
  </>
}

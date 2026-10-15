import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"
import { McpAuthorizationEditor, McpPolicyDifference, QuotaFields, policyGroups, validQuotas, type McpServerPolicy } from "./mcp-authorization-editor"

describe("持续 MCP 授权与配额", () => {
  it("配额只接受边界内正整数，空白不能静默变成默认值", () => {
    expect(validQuotas(6000, 100)).toBe(true)
    expect(validQuotas(300, 1)).toBe(true)
    for (const value of [null, 0, -1, 1.5, 10001]) expect(validQuotas(value, 1)).toBe(false)
    for (const value of [null, 0, -1, 1.5, 101]) expect(validQuotas(6000, value)).toBe(false)
    const html = renderToStaticMarkup(<QuotaFields rate={null} concurrency={100} onRate={vi.fn()} onConcurrency={vi.fn()} zh />)
    expect(html).toContain("请输入 1–10000 的整数")
    expect(html).toContain('role="alert"')
  })
  it("当前没有工具的已保存持续策略仍显示并可撤除", () => {
    const policies: McpServerPolicy[] = [{ server_id: "offline", server_binding: "saved-binding", mode: "continuous", access: "read" }]
    const groups = policyGroups([], policies)
    expect(groups).toEqual([{ server_id: "offline", server_name: null, tool_count: 0, read_count: 0, write_count: 0 }])
    const html = renderToStaticMarkup(<McpAuthorizationEditor groups={groups} policies={policies} onMode={vi.fn()} onAccess={vi.fn()} canWrite={false} zh />)
    expect(html).toContain("offline")
    expect(html).toContain("不授权")
    expect(html).toContain("持续授权")
    expect(html).toContain("指定工具")
    expect(html).toContain('type="radio"')
    expect(html).toMatch(/disabled=""[^>]*type="radio"[^>]*value="write"|type="radio"[^>]*disabled=""[^>]*value="write"/)
  })
  it("即使工具差异为零也确认持续策略变更及未来写权限", () => {
    const html = renderToStaticMarkup(<McpPolicyDifference before={[]} after={[{ server_id: "demo", mode: "continuous", access: "write" }]} beforeSelected={["demo"]} zh />)
    expect(html).toContain("指定工具")
    expect(html).toContain("含未来写工具")
    expect(html).toContain("→")
    const removal = renderToStaticMarkup(<McpPolicyDifference before={[{ server_id: "offline", mode: "continuous", access: "read" }]} after={[]} zh />)
    expect(removal).toContain("不授权")
  })
  it("保存中即使具备写权限也禁用读写单选", () => {
    const policies: McpServerPolicy[] = [{ server_id: "demo", mode: "continuous", access: "write" }]
    const html = renderToStaticMarkup(<McpAuthorizationEditor groups={policyGroups([], policies)} policies={policies} onMode={vi.fn()} onAccess={vi.fn()} canWrite disabled zh />)
    const radios = [...html.matchAll(/<input\b[^>]*type="radio"[^>]*>/g)].map(match => match[0])
    expect(radios).toHaveLength(5)
    expect(radios.every(radio => radio.includes('disabled=""'))).toBe(true)
  })
  it("工具分类计数取实际读写结果，显示名称不是身份", () => {
    const groups = policyGroups([
      { id: "a", name: "same", server_id: "one", access: "read", snapshot: "a" },
      { id: "b", name: "same", server_id: "one", access: "write", snapshot: "b" },
      { id: "c", name: "same", server_id: "two", access: "read", snapshot: "c" },
    ])
    expect(groups.map(group => [group.server_id, group.tool_count, group.read_count, group.write_count])).toEqual([["one", 2, 1, 1], ["two", 1, 1, 0]])
  })
})

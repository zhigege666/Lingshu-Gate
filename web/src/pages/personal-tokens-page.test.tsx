import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"
import { getDefaultTokenScopes, getTokenScopeOptions } from "@/features/personal-token-scopes"
import { TokenScopeSelector, TokenScopeSummary } from "@/pages/personal-tokens-page"

const options = ["tools.read", "tools.invoke", "audit.read", "audit.payload.read", "system_settings.manage", "network.use"]

describe("API Token 权限展示", () => {
  it("创建时按用途分组，管理员全选，其他账号只选择只读", () => {
    for (const role of ["admin", "operator"]) {
      const selected = getDefaultTokenScopes(options, { role, roles: [role] })
      const html = renderToStaticMarkup(<TokenScopeSelector options={options} selected={selected} locale="zh-CN" disabled={false} onChange={vi.fn()} />)
      expect(html.match(/<fieldset\b/g)).toHaveLength(3)
      expect(html).toContain("工具调用与运行态")
      expect(html).toContain("凭据与审计")
      expect(html).toContain("系统与外部接入")
      expect(html).toContain('aria-label="其他用户调用内容"')
      expect(html).toContain("读取经过脱敏和限长的其他用户调用内容")
      expect(html).toContain("aria-describedby=")
      expect(html.match(/role="switch"/g)).toHaveLength(options.length)
      expect(html.match(/aria-checked="true"/g)).toHaveLength(role === "admin" ? options.length : 1)
    }
  })

  it("编辑现有 Token 展示新增选项时保留已保存的选择", () => {
    const selected = ["tools.read", "legacy.review"]
    const html = renderToStaticMarkup(<TokenScopeSelector options={getTokenScopeOptions(options, selected)} selected={selected} locale="zh-CN" disabled={false} onChange={vi.fn()} />)
    expect(html.match(/aria-checked="true"/g)).toHaveLength(2)
    expect(html).toContain("其他权限")
    expect(html).toContain("legacy.review")
    expect(selected).toEqual(["tools.read", "legacy.review"])
  })

  it("提交期间禁用全部权限开关", () => {
    const html = renderToStaticMarkup(<TokenScopeSelector options={options} selected={options} locale="en-US" disabled onChange={vi.fn()} />)
    const switches = [...html.matchAll(/<button\b[^>]*role="switch"[^>]*>/g)].map(match => match[0])
    expect(switches).toHaveLength(options.length)
    expect(switches.every(button => button.includes('disabled=""'))).toBe(true)
    expect(html).toContain("System &amp; external connections")
    expect(html).toContain("Use reviewed Git and dependency networks")
  })

  it("列表使用分组和中文名称，并保留权限代码与说明供核对", () => {
    const html = renderToStaticMarkup(<TokenScopeSummary scopes={["tools.read", "credentials.manage.system", "audit.payload.read"]} locale="zh-CN" />)
    expect(html).toContain("只读工具")
    expect(html).toContain("共享服务凭据")
    expect(html).toContain("其他用户调用内容")
    expect(html).toContain("凭据与审计")
    expect(html).toContain('title="credentials.manage.system · 维护共享 MCP 服务凭据')
  })
})

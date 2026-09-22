import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { PageHeader, PageToolbar } from "@/components/page-shell"

describe("统一页面头部", () => {
  it("列表首屏保留标题、搜索、操作与帮助入口，长说明按需展示", () => {
    const html = renderToStaticMarkup(<PageHeader title="工具读写分类" description="分类发布前必须经过人工确认" helpLabel="使用说明"
      toolbar={<PageToolbar query="" onQueryChange={() => {}} placeholder="搜索工具" resultCount={76} resultLabel="工具" clearLabel="清除搜索" />}
      actions={<button>运行规则分析</button>} />)
    expect(html).toContain("<h1>工具读写分类</h1>")
    expect(html).toContain('aria-label="搜索工具"')
    expect(html).toContain("运行规则分析")
    expect(html).toContain('aria-label="使用说明"')
    expect(html).not.toContain("分类发布前必须经过人工确认")
  })

  it("服务详情保留资源名称、状态和对象说明", () => {
    const html = renderToStaticMarkup(<PageHeader variant="detail" title="Example MCP" description="example-server"
      titleExtra={<span>运行中</span>} actions={<button>停止服务</button>} />)
    expect(html).not.toContain("page-header-compact")
    expect(html).toContain('title="Example MCP">Example MCP</h1>')
    expect(html).toContain("运行中")
    expect(html).toContain("example-server")
    expect(html).toContain("停止服务")
  })
})

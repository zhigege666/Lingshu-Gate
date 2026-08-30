import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { RouteLoadingFallback, routeBoundaryCopy } from "@/components/route-boundary"

describe("route loading boundary", () => {
  it("renders an accessible localized loading state", () => {
    const html = renderToStaticMarkup(<RouteLoadingFallback locale="zh-CN" />)

    expect(html).toContain('role="status"')
    expect(html).toContain("页面加载中")
  })

  it("provides localized recovery copy", () => {
    expect(routeBoundaryCopy("en-US").retry).toBe("Refresh and retry")
    expect(routeBoundaryCopy("zh-CN").errorTitle).toBe("页面加载失败")
  })
})

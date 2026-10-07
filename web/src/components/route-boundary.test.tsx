import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { RouteErrorBoundary, RouteLoadingFallback, routeBoundaryCopy } from "@/components/route-boundary"

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


it("keeps lazy-surface failures inside the provided recoverable surface", () => {
  const boundary = new RouteErrorBoundary({ locale: "en-US", children: <span>loaded</span>, fallback: <div role="alert">Close search and retry after saving edits</div> })
  boundary.state = RouteErrorBoundary.getDerivedStateFromError(new Error("chunk failed"))
  const html = renderToStaticMarkup(boundary.render())
  expect(html).toContain("Close search")
  expect(html).not.toContain("loaded")
})

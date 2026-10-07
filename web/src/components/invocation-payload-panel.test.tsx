import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { InvocationPayloadPanel, payloadText } from "./invocation-payload-panel"

describe("recorded invocation payload presentation", () => {
  it.each([null, false, 0, "", [], {}])("preserves recorded JSON value %j", value => {
    expect(payloadText({ status: "recorded", value })).toBe(JSON.stringify(value, null, 2))
  })
  it("does not invent content or offer copying for unrecorded history", () => {
    const html = renderToStaticMarkup(<InvocationPayloadPanel title="Input" payload={{ status: "not_recorded" }} locale="en-US" onCopy={async () => {}} />)
    expect(html).toContain("cannot be recovered")
    expect(html).not.toContain("Copy JSON")
  })
  it("marks truncated contents and provides searchable, collapsible retained JSON", () => {
    const html = renderToStaticMarkup(<InvocationPayloadPanel title="输出" payload={{ status: "truncated", value: { partial: false } }} locale="zh-CN" onCopy={async () => {}} />)
    expect(html).toContain("仅展示和复制保留部分")
    expect(html).toContain("搜索 JSON 行")
    expect(html).toContain("<details open")
    expect(html).toContain("false")
  })
})

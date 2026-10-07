import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { ExternalUserSelector } from "./external-user-selector"

describe("binding user selection markup", () => {
  it("uses an accessible searchable selector and retains selected label plus stable ID", () => {
    const markup = renderToStaticMarkup(<ExternalUserSelector value={{ id: "stable-synthetic-id", username: "reader", display_name: "Read Team", status: "active" }} onChange={() => {}} disabled={false} zh={false} />)
    expect(markup).toContain('aria-label="Gate user"')
    expect(markup).toContain('role="combobox"')
    expect(markup).toContain("Read Team (@reader) · stable-synthetic-id")
  })
  it("labels the unselected and pending states without substituting free-text IDs", () => {
    const markup = renderToStaticMarkup(<ExternalUserSelector value={null} onChange={() => {}} disabled zh />)
    expect(markup).toContain("搜索名称、用户名或 ID")
    expect(markup).toContain('aria-label="Gate 用户"')
    expect(markup).toContain("disabled")
  })
})

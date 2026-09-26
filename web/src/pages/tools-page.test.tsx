import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { ToolsPage } from "@/pages/tools-page"
import { translate } from "@/i18n"
import type { ToolDefinition } from "@/api/client"

const tool: ToolDefinition = { id: "mcp.docs-test.read_document", name: "Read document", description: "Full document description", source: "mcp", permission: "default:read", input_schema: {}, metadata: { server_id: "docs-test", gate_access: { required_access: "write" } } }
const props = { tools: [tool], servers: [], loading: false, error: null, t: (key: Parameters<typeof translate>[1]) => translate("en-US", key), onInvoke: () => {}, onRefresh: () => {} }

describe("tools page states", () => {
  it("renders a card with explicit actions and the exact service identity", () => {
    const html = renderToStaticMarkup(<ToolsPage {...props} />)
    expect(html).toContain('<article')
    expect(html).not.toContain('<table')
    expect(html).toContain('aria-label="MCP Servers"')
    expect(html).toContain('aria-label="Detail · Read document"')
    expect(html).toContain("mcp.docs-test.read_document")
    expect(html).toContain('tool-access-write')
    expect(html).toContain('title="docs-test"')
  })

  it("hides stale cards while loading or when discovery fails", () => {
    const loading = renderToStaticMarkup(<ToolsPage {...props} loading />)
    expect(loading).toContain('aria-busy="true"')
    expect(loading).not.toContain('<article')
    const failed = renderToStaticMarkup(<ToolsPage {...props} error="Network unavailable" />)
    expect(failed).toContain("Unable to load tools")
    expect(failed).toContain("Retry")
    expect(failed).not.toContain('<article')
  })

  it("explains visibility in an empty catalog", () => {
    const html = renderToStaticMarkup(<ToolsPage {...props} tools={[]} />)
    expect(html).toContain("Only tools visible to your account are shown")
    expect(html).not.toContain('<article')
  })
})

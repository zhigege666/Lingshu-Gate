import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { initialToolCatalogView, ToolsPage } from "@/pages/tools-page"
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
  it("renders only the selected page of a 5000 tool catalog", () => {
    const tools = Array.from({ length: 5000 }, (_, index) => ({ ...tool, id: `mcp.synthetic.tool_${index}`, name: `Synthetic ${index}` }))
    const html = renderToStaticMarkup(<ToolsPage {...props} tools={tools} />)
    expect(html.match(/<article/g)).toHaveLength(48)
    expect(html).toContain('tool-catalog-scroll')
    expect(html).toContain('5000')
    expect(html).not.toContain('Synthetic 4999')
    expect(html).toContain('1 / 105')
    const restored = renderToStaticMarkup(<ToolsPage {...props} tools={tools} viewState={{ ...initialToolCatalogView, page: 2, pageSize: 96 }} />)
    expect(restored.match(/<article/g)).toHaveLength(96)
    expect(restored).toContain('Synthetic 96')
    expect(restored).not.toContain('aria-label="Synthetic 0"')
  })

})

import { describe, expect, it, vi } from "vitest"
import { renderToStaticMarkup } from "react-dom/server"
import { McpHttpAuthEditor } from "./mcp-http-auth-editor"
import { McpConnectionTestResult } from "./mcp-connection-test-result"
import type { HttpConnectionResult } from "@/api/http-connection-test"

const props = { serverId: "synthetic", endpoint: "https://mcp.example.test/mcp", zh: false, disabled: false,
  credentials: [], loading: false, loadError: false, canCreate: true, onChange: vi.fn(), onCreated: vi.fn(), onReload: vi.fn(),
  onPendingChange: vi.fn(), onDraftChange: vi.fn(), onAdvanced: vi.fn(), onHomeTemplate: vi.fn() }

describe("HTTP authentication initial rendering", () => {
  it.each([undefined, {}])("renders a new empty-header draft without dereferencing a missing local selection", value => {
    const html = renderToStaticMarkup(<McpHttpAuthEditor {...props} value={value} />)
    expect(html).toContain("No authentication header is added")
    expect(html).toContain("Bearer Token")
    expect(props.onChange).not.toHaveBeenCalled()
  })
  it("never decodes or prints legacy secret values while representing them as custom", () => {
    const html = renderToStaticMarkup(<McpHttpAuthEditor {...props} value={{ Authorization: "Bearer synthetic-private-literal" }} />)
    expect(html).toContain("Existing headers are retained")
    expect(html).not.toContain("synthetic-private-literal")
  })
  it("renders failed credential reads separately from an empty list", () => {
    const html = renderToStaticMarkup(<McpHttpAuthEditor {...props} loadError value={{ Authorization: "Bearer ${credential:synthetic}" }} />)
    expect(html).toContain("credential list could not be loaded")
    expect(html).not.toContain("No credential matches")
  })
})

const success: HttpConnectionResult = { ok: true, status: "success", elapsed_ms: 42, network_attempted: true,
  config_saved: false, trust_changed: false, registry_changed: false, business_permissions_verified: false,
  tool_count: 2, protocol_version: "synthetic-version", stages: [{ id: "configuration", status: "passed" }, { id: "http", status: "passed" },
    { id: "authentication", status: "passed" }, { id: "handshake", status: "passed" }, { id: "tools", status: "passed" }] }

describe("connection result hierarchy", () => {
  it("shows explicit stage text and a short success summary with technical details separate", () => {
    const html = renderToStaticMarkup(<McpConnectionTestResult result={success} stale={false} zh={false} />)
    expect(html).toContain("Connection successful")
    expect(html.match(/role="listitem"/g)).toHaveLength(5)
    expect(html).toContain("Technical details")
    expect(html).toContain("Business permissions remain unverified")
  })
  it("never presents an expired result as success", () => {
    const html = renderToStaticMarkup(<McpConnectionTestResult result={success} stale zh />)
    expect(html).toContain("已过期")
    expect(html).not.toContain("连接成功")
  })
})

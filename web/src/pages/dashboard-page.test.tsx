import type { ComponentProps } from "react"
import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it, vi } from "vitest"
import type { McpServer, ToolDefinition } from "@/api/client"
import { DashboardPage, DashboardResourceOverview } from "@/pages/dashboard-page"
import { translate, type Locale, type TFunction } from "@/i18n"

// Locale context only: the actual page, resource components and their markup render unchanged.
vi.mock("@/components/console-design-provider", () => ({
  useConsoleDesign: () => ({ locale: "en-US" }),
}))

type OverviewProps = ComponentProps<typeof DashboardResourceOverview>
type PageProps = ComponentProps<typeof DashboardPage>
const t: TFunction = key => translate("en-US", key)

function server(id: string, changes: Partial<McpServer> = {}): McpServer {
  return {
    id, name: `Service ${id}`, enabled: true, launch_type: "external", transport_type: "streamable_http",
    status: "external", tool_count: 0, restart_policy: {}, restart_count: 0, restart_attempts: 0,
    consecutive_health_failures: 0, health_status: "unknown", ...changes,
  }
}

function tool(id: string, source: string): ToolDefinition {
  return { id, name: id, description: "", permission: "read", input_schema: {}, source, metadata: {} }
}

const loaded: OverviewProps = {
  health: { status: "ok", service: "gate", version: "0.2.0" }, healthError: null,
  servers: [server("first")], serversLoaded: true, serversError: null,
  tools: [tool("builtin-tool", "builtin")], toolsLoaded: true, toolsError: null,
  operationsAllowed: true, canReadTools: true, locale: "en-US", t,
}

function overview(changes: Partial<OverviewProps> = {}) {
  return renderToStaticMarkup(<DashboardResourceOverview {...loaded} {...changes} />)
}

function page(changes: Partial<PageProps> = {}) {
  return renderToStaticMarkup(<DashboardPage {...loaded} principalId="viewer" globalRefreshId={1} canReadAudit={false} {...changes} />)
}

function text(html: string) {
  return html.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim()
}

// Isolate the rendered resource boundaries without asserting visual classes or CSS values.
function resources(html: string): Record<string, string> {
  const starts = [...html.matchAll(/<(?:a|div)\b[^>]*data-resource="([^"]+)"[^>]*>/g)]
  return Object.fromEntries(starts.map((match, index) => [
    match[1], html.slice(match.index, starts[index + 1]?.index ?? html.length),
  ]))
}

function primaryValue(html: string) {
  const value = html.match(/<strong\b[^>]*>([\s\S]*?)<\/strong>/)?.[1]
  return value === undefined ? undefined : text(value)
}

describe("dashboard resource permissions and independent loading", () => {
  it.each([
    { operationsAllowed: false, canReadTools: false, expected: ["gate"] },
    { operationsAllowed: true, canReadTools: false, expected: ["gate", "servers"] },
    { operationsAllowed: false, canReadTools: true, expected: ["gate", "tools"] },
    { operationsAllowed: true, canReadTools: true, expected: ["gate", "servers", "tools"] },
  ])("only renders authorized resources and loading states: $expected", ({ expected, ...permissions }) => {
    const html = overview({ ...permissions, health: null, serversLoaded: false, toolsLoaded: false })
    const parts = resources(html)
    expect(Object.keys(parts)).toEqual(expected)
    expect(html.match(/aria-busy="true"/g)).toHaveLength(expected.length)
    expect(html.match(/role="status"/g)).toHaveLength(expected.length)
    for (const part of Object.values(parts)) {
      expect(part).toContain(t("loadingData"))
      expect(primaryValue(part)).toBeUndefined()
    }
  })

  it("console-view-only accounts do not receive server, tool or audit content", () => {
    const html = page({ operationsAllowed: false, canReadTools: false, canReadAudit: false })
    expect(Object.keys(resources(html))).toEqual(["gate"])
    expect(html).not.toContain('href="#/servers"')
    expect(html).not.toContain('href="#/tools"')
    expect(html).not.toContain(t("serverOverview"))
    expect(html).not.toContain("Service first")
    expect(html).not.toContain(t("dashboardUsage"))
    expect(html).toMatch(/<h1\b[^>]*>Dashboard<\/h1>/)
  })

  it("pending Gate health does not hide independently loaded servers or tools", () => {
    const parts = resources(overview({ health: null }))
    expect(parts.gate).toContain('aria-busy="true"')
    expect(parts.servers).toContain('aria-busy="false"')
    expect(parts.tools).toContain('aria-busy="false"')
    expect(primaryValue(parts.servers)).toBe("1 registered")
    expect(primaryValue(parts.tools)).toBe("1 visible to you")
    expect(page({ health: null })).toContain("Service first")
  })

  it.each([false, true])("tool errors replace stale values even when toolsLoaded=%s", toolsLoaded => {
    const part = resources(overview({ toolsLoaded, toolsError: "Request failed" })).tools
    expect(primaryValue(part)).toBe("—")
    expect(part).toContain(t("dashboardToolsUnavailable"))
    expect(part).toContain('aria-busy="false"')
    expect(part).not.toContain(t("dashboardVisibleToYou"))
    expect(part).not.toContain(t("dashboardBuiltinSource"))
  })

  it("distinguishes a real empty tool catalog from a request still loading", () => {
    const empty = resources(overview({ tools: [] })).tools
    const pending = resources(overview({ tools: [], toolsLoaded: false })).tools
    expect(primaryValue(empty)).toBe("0 visible to you")
    expect(empty).not.toContain(t("loadingData"))
    expect(primaryValue(pending)).toBeUndefined()
    expect(pending).toContain(t("loadingData"))
    expect(pending).not.toContain(t("dashboardVisibleToYou"))
  })

  it("a failed health refresh does not present stale healthy data as current", () => {
    const parts = resources(overview({ healthError: "Timeout" }))
    expect(parts.gate).toContain(t("dashboardGateUnavailable"))
    expect(parts.gate).toContain(t("dashboardRefreshHint"))
    expect(parts.gate).not.toContain(t("dashboardGateResponding"))
    expect(parts.gate).toContain('aria-busy="false"')
    expect(primaryValue(parts.servers)).toBe("1 registered")
    expect(primaryValue(parts.tools)).toBe("1 visible to you")
  })
})

describe("dashboard data scope and server states", () => {
  it.each(["en-US", "zh-CN"] as Locale[])("counts real tool sources without treating unknown sources as built-in (%s)", locale => {
    const localT: TFunction = key => translate(locale, key)
    const tools = [tool("builtin-a", "builtin"), tool("builtin-b", "builtin"), tool("mcp-a", "mcp"), tool("custom", "extension"), tool("unknown", "")]
    tools[3].metadata = { source: "builtin" }
    const part = resources(overview({ tools, locale, t: localT })).tools
    expect(primaryValue(part)).toBe(`5 ${localT("dashboardVisibleToYou")}`)
    expect(text(part)).toContain("1 MCP")
    expect(text(part)).toContain(`2 ${localT("dashboardBuiltinSource")}`)
    expect(text(part)).toContain(`2 ${localT("dashboardOtherSource")}`)
  })

  it("Gate reachability is shown separately from downstream failures", () => {
    const parts = resources(overview({ servers: [server("broken", { status: "failed" })] }))
    expect(parts.gate).toContain(t("dashboardGateResponding"))
    expect(parts.gate).toContain(t("dashboardGateHealthScope"))
    expect(text(parts.servers)).toContain("0 running")
    expect(text(parts.servers)).toContain("1 need attention")
  })

  it("separates running, failed/unsupported and neutral server states", () => {
    const servers = [
      server("running", { status: "running" }), server("failed", { status: "failed" }),
      server("unsupported", { status: "unsupported" }), server("external"),
      server("disabled", { enabled: false, last_error: "Server is disabled", restore_blocked_reason: "Server is disabled" }),
      server("stopped", { status: "stopped" }),
    ]
    const part = resources(overview({ servers })).servers
    expect(primaryValue(part)).toBe("6 registered")
    expect(text(part)).toContain("1 running")
    expect(text(part)).toContain("2 need attention")
    expect(text(part)).toContain("3 other states")
  })

  it("external and intentionally disabled services alone do not imply failures", () => {
    const servers = [server("external"), server("disabled", { enabled: false, last_error: "Server is disabled" })]
    const part = resources(overview({ servers })).servers
    expect(text(part)).toContain("2 other states")
    expect(part).not.toContain(t("dashboardServerAttention"))
    expect(page({ servers })).not.toContain(t("warning"))
  })

  it.each([false, true])("server failure feedback supersedes stale summary and list (loaded=%s)", serversLoaded => {
    const changes = { serversLoaded, serversError: "Request failed", servers: [server("stale-failure", { status: "failed" })] }
    const part = resources(overview(changes)).servers
    expect(primaryValue(part)).toBe("—")
    expect(part).toContain(t("dashboardServersUnavailable"))
    expect(part).toContain('aria-busy="false"')
    expect(part).not.toContain(t("dashboardRegistered"))
    const fullPage = page(changes)
    expect(fullPage.split(t("dashboardServersUnavailable"))).toHaveLength(3)
    expect(fullPage).not.toContain("Service stale-failure")
    expect(fullPage).not.toContain(t("warning"))
    expect(fullPage).not.toContain(t("noData"))
  })

  it("an unloaded service list does not render old rows or an empty-list claim", () => {
    const html = page({ serversLoaded: false, servers: [server("stale-failure", { status: "failed" })] })
    expect(html).not.toContain("Service stale-failure")
    expect(html).not.toContain(t("noData"))
    expect(html).not.toContain(t("warning"))
    expect(html).toContain(t("loadingData"))
  })

  it("a successfully loaded empty service list can display zero and its empty state", () => {
    expect(primaryValue(resources(overview({ servers: [] })).servers)).toBe("0 registered")
    expect(page({ servers: [] })).toContain(t("noData"))
  })
})

describe("dashboard navigation and audit controls", () => {
  it("resource navigation uses named native links without nested controls", () => {
    const parts = resources(overview())
    for (const [resource, label] of [["servers", t("mcpServers")], ["tools", t("toolRegistry")]]) {
      expect(parts[resource]).toMatch(/^<a\b/)
      expect(parts[resource]).toContain(`href="#/${resource}"`)
      expect(text(parts[resource])).toContain(label)
      expect(parts[resource]).not.toMatch(/<(?:button|input|select)\b/)
    }
    expect(parts.gate).not.toContain("href=")
  })

  it("retains audit period controls only when the account can read audits", () => {
    const allowed = page({ canReadAudit: true })
    expect(allowed).toContain(`aria-label="${t("dashboardUsage")}"`)
    expect(allowed).toMatch(/<button\b[^>]*aria-pressed="true"[^>]*>Last 24 hours<\/button>/)
    expect(allowed).toMatch(/<button\b[^>]*aria-pressed="false"[^>]*>Last 7 days<\/button>/)
    const restricted = page({ canReadAudit: false })
    expect(restricted).not.toContain(t("dashboard24Hours"))
    expect(restricted).not.toContain(t("dashboard7Days"))
  })
})

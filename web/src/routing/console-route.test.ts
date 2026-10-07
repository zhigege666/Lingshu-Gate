import { afterEach, describe, expect, it, vi } from "vitest"
import { CONSOLE_ROUTE_REPLACED, consoleViewHash, parseConsoleHash, replaceConsoleRouteHash } from "@/routing/use-console-route"

describe("console routing", () => {
  afterEach(() => vi.unstubAllGlobals())

  it("preserves back/forward metadata when replacing an in-page build selection", () => {
    const metadata = { gateConsoleIndex: 7, unrelatedState: "preserved" }
    const replaceState = vi.fn()
    const dispatchEvent = vi.fn()
    vi.stubGlobal("window", { history: { state: metadata, replaceState }, dispatchEvent })
    replaceConsoleRouteHash("#/builds/build-b")
    expect(replaceState).toHaveBeenCalledWith(metadata, "", "#/builds/build-b")
    expect(dispatchEvent.mock.calls[0][0].type).toBe(CONSOLE_ROUTE_REPLACED)
    replaceConsoleRouteHash("#/builds")
    expect(replaceState).toHaveBeenLastCalledWith(metadata, "", "#/builds")
    expect(dispatchEvent).toHaveBeenCalledTimes(2)
  })

  it("parses deep build links", () => {
    expect(parseConsoleHash("#/builds/build%2F42")).toEqual({ view: "builds", buildId: "build/42" })
  })

  it("preserves service deep link IDs", () => {
    expect(parseConsoleHash("#/servers/service%2F42")).toEqual({ view: "servers", serverId: "service/42" })
  })

  it("falls back to the dashboard for unknown routes", () => {
    expect(parseConsoleHash("#/unknown")).toEqual({ view: "dashboard" })
    expect(parseConsoleHash("#/builds/%broken")).toEqual({ view: "dashboard" })
  })

  it("serializes typed views", () => {
    expect(consoleViewHash("runtimeCache")).toBe("#/runtimeCache")
  })
})

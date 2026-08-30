import { describe, expect, it } from "vitest"
import { consoleViewHash, parseConsoleHash } from "@/routing/use-console-route"

describe("console routing", () => {
  it("parses deep build links", () => {
    expect(parseConsoleHash("#/builds/build%2F42")).toEqual({ view: "builds", buildId: "build/42" })
  })

  it("falls back to the dashboard for unknown routes", () => {
    expect(parseConsoleHash("#/unknown")).toEqual({ view: "dashboard" })
  })

  it("serializes typed views", () => {
    expect(consoleViewHash("runtimeCache")).toBe("#/runtimeCache")
  })
})

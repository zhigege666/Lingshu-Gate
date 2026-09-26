import { describe, expect, it } from "vitest"
import {
  parseEnv,
  parseManifest,
  precheckManifest,
  patchManifestField,
  canKeepMaskedEndpoint,
  changeRuntimeMode,
  REDACTED_ENDPOINT,
  manifestValidationIssues,
  sensitiveEnvKeys,
  withoutUserCredentialValues,
  type ManifestPrecheckMessageKey,
} from "@/features/mcp-config/model"

const copy = (key: ManifestPrecheckMessageKey) => key

describe("MCP config model", () => {
  it("accepts only a JSON object as the manifest root", () => {
    expect(parseManifest('{"id":"demo"}')).toMatchObject({ id: "demo" })
    expect(() => parseManifest("[]")).toThrow("Manifest root must be a JSON object")
  })

  it("parses environment values without losing equals signs", () => {
    expect(parseEnv("# ignored\nAPI_TOKEN=a=b=c\n MODE = safe ")).toEqual({
      API_TOKEN: "a=b=c",
      MODE: "safe",
    })
    expect(sensitiveEnvKeys("API_TOKEN=secret\nMODE=safe")).toEqual(["API_TOKEN"])
  })

  it("removes one-shot user credential values without mutating the source", () => {
    const source = { id: "demo", user_credential_values: { token: "secret" } }
    expect(withoutUserCredentialValues(source)).toEqual({ id: "demo" })
    expect(source.user_credential_values).toEqual({ token: "secret" })
  })

  it("validates HTTP endpoints", () => {
    const result = precheckManifest({
      id: "demo",
      launch: { type: "external" },
      transport: { type: "streamable_http", endpoint: "not-a-url" },
      timeout_seconds: 30,
    }, copy)

    expect(result.errors).toContain("endpointInvalid")
  })

  it("accepts a masked endpoint only as a keep instruction bound to the original config", () => {
    const manifest = { id: "original", launch: { type: "external" }, transport: { type: "streamable_http", endpoint: REDACTED_ENDPOINT }, timeout_seconds: 30 }
    const context = { existingConfigId: "original", originalEndpointMasked: true }
    expect(canKeepMaskedEndpoint(manifest, context)).toBe(true)
    expect(precheckManifest(manifest, copy, context).errors).not.toContain("endpointInvalid")
    expect(precheckManifest(manifest, copy).errors).toContain("endpointInvalid")
    expect(precheckManifest({ ...manifest, id: "another" }, copy, context).errors).toContain("endpointInvalid")
    expect(precheckManifest(manifest, copy, { ...context, originalEndpointMasked: false }).errors).toContain("endpointInvalid")
    expect(precheckManifest({ ...manifest, transport: { ...manifest.transport, endpoint: "invalid replacement" } }, copy, context).errors).toContain("endpointInvalid")
    expect(precheckManifest({ ...manifest, transport: { ...manifest.transport, endpoint: "https://example.test/mcp" } }, copy, context).errors).toEqual([])
  })

  it("does not warn that a supported external HTTP runtime is unsupported", () => {
    const result = precheckManifest({ id: "external", launch: { type: "external" }, transport: { type: "streamable_http", endpoint: "https://example.test/mcp" }, timeout_seconds: 30 }, copy)
    expect(result.warnings).not.toContain("launchTypeWarning")
  })

  it("never changes runtime configuration when choosing advanced editing", () => {
    const original = { id: "external", launch: { type: "external", future: false }, transport: { type: "streamable_http", endpoint: REDACTED_ENDPOINT }, timeout_seconds: 0 }
    expect(changeRuntimeMode(original, "advanced")).toBe(original)
    expect(changeRuntimeMode(original, "managed_http")).toEqual({ ...original, launch: { ...original.launch, type: "managed_process" } })
  })

  it("changes only the edited path, preserving missing fields, falsy values, unknown siblings and argument order", () => {
    const original = { id: "demo", name: "", launch: { type: "managed_process", command: "server", args: ["", " space ", "--flag"], env: { PADDED: " value ", EMPTY: "", EQUALS: "a=b" }, custom: null }, transport: { type: "stdio", future: { enabled: false, count: 0 } }, restart_policy: { delay_seconds: 0 }, unknown: [false, 0, null, ""] }
    const result = patchManifestField(original, ["launch", "command"], { kind: "set", value: "next" })
    expect(result).toEqual({ ...original, launch: { ...original.launch, command: "next" } })
    expect(result).not.toHaveProperty("timeout_seconds")
    expect(result).not.toHaveProperty("auto_start")
    expect(original.launch.command).toBe("server")
  })

  it("distinguishes setting empty or null from removal", () => {
    const original = { id: "demo", launch: { type: "managed_process", cwd: "/old" } }
    expect(patchManifestField(original, ["launch", "cwd"], { kind: "set", value: "" }).launch?.cwd).toBe("")
    expect(patchManifestField(original, ["launch", "cwd"], { kind: "set", value: null }).launch?.cwd).toBeNull()
    expect(patchManifestField(original, ["launch", "cwd"], { kind: "remove" }).launch).not.toHaveProperty("cwd")
    expect(() => patchManifestField(original, ["__proto__", "bad"], { kind: "set", value: true })).toThrow()
  })

  it("keeps malformed JSON invalid instead of restoring a previous valid document", () => {
    expect(() => parseManifest('{"id":"draft",')).toThrow()
    expect(() => parseManifest("")).toThrow()
  })

  it("retains all backend field paths and the checked revision for actionable diagnostics", () => {
    const issues = manifestValidationIssues([
      { name: "manifest.schema", severity: "error", message: "Invalid", metadata: { errors: [
        { type: "missing", msg: "Field required", loc: ["launch", "command"] },
        { type: "string_type", msg: "Expected string", loc: ["transport", "headers", "X/Trace~ID"] },
      ] } },
      { name: "launch.cwd", severity: "warning", message: "Path unavailable", metadata: {} },
      { name: "transport.stdio", severity: "ok", message: "Supported", metadata: {} },
    ], 7)
    expect(issues.map((issue) => issue.path)).toEqual(["/launch/command", "/transport/headers/X~1Trace~0ID", "/launch/cwd"])
    expect(issues.every((issue) => issue.revision === 7 && issue.source === "server")).toBe(true)
  })

  it("enforces the managed container schema before save", () => {
    const result = precheckManifest({
      id: "container",
      launch: {
        type: "managed_container",
        image: "registry.example/server:mutable",
        volumes: ["/host:/workspace:ro"],
        mounts: [{ source: "/host", target: "/workspace", read_only: false }],
        environment: { LINGSHU_GATE_PORT: "9000" },
      },
      transport: { type: "stdio" },
      timeout_seconds: 30,
    }, copy)

    expect(result.errors).toEqual(expect.arrayContaining([
      "containerImageDigestError",
      "containerVolumesUnsupported",
      "containerMountsError",
      "containerEnvironmentProtected",
    ]))
  })
})

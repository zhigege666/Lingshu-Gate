import { describe, expect, it } from "vitest"
import {
  parseEnv,
  parseManifest,
  precheckManifest,
  patchManifestField,
  canKeepMaskedEndpoint,
  changeRuntimeMode,
  changeStartupPolicy,
  createMcpConfigTemplate,
  REDACTED_ENDPOINT,
  manifestValidationIssues,
  manifestValidationStatus,
  sensitiveEnvKeys,
  withoutUserCredentialValues,
  type ManifestPrecheckMessageKey,
} from "@/features/mcp-config/model"

const copy = (key: ManifestPrecheckMessageKey) => key

describe("MCP config model", () => {
  it("enables new drafts independently of startup and preserves explicit disable across every form mode", () => {
    const draft = createMcpConfigTemplate()
    expect(draft).toMatchObject({ enabled: true, auto_start: false, startup_policy: "gate_start_v1" })
    for (const mode of ["external_http", "managed_stdio", "managed_http"] as const) {
      expect(changeRuntimeMode(draft, mode)).toMatchObject({ enabled: true, auto_start: false, startup_policy: "gate_start_v1" })
      const disabled = parseManifest(JSON.stringify({ ...draft, enabled: false }))
      expect(changeRuntimeMode(disabled, mode).enabled).toBe(false)
    }
    const next = createMcpConfigTemplate()
    draft.enabled = false
    draft.launch!.type = "managed_process"
    expect(next).toMatchObject({ enabled: true, launch: { type: "external" }, auto_start: false })
  })
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

  it("round-trips HTTP to stdio without losing endpoints, headers, falsy or unsupported draft fields", () => {
    const original = { id: "round-trip", enabled: false, launch: { type: "managed_process", command: "node", args: ["server"], future: { count: 0, value: "" } }, transport: { type: "streamable_http", endpoint: "https://example.test/mcp", headers: { "X-Trace": "${credential:demo}" } }, timeout_seconds: 30 }
    const stdio = changeRuntimeMode(original, "managed_stdio")
    expect(stdio.transport).toEqual({ ...original.transport, type: "stdio" })
    expect(changeRuntimeMode(stdio, "managed_http")).toEqual(original)
    expect(stdio.enabled).toBe(false)
    expect(stdio.launch).toEqual(original.launch)
  })

  it("retains a pinned toolchain during a mode change and reports its incompatible runtime", () => {
    const original = { id: "pinned", launch: { type: "managed_process", command: "node", toolchain: { manager: "node", version: "22" } }, transport: { type: "streamable_http", endpoint: "https://example.test/mcp" }, timeout_seconds: 30 }
    const external = changeRuntimeMode(original, "external_http")
    expect(external.launch?.toolchain).toEqual(original.launch.toolchain)
    expect(precheckManifest(external, copy).errors).toContain("toolchainModeUnsupported")
  })

  it("migrates startup policy only after an explicit switch edit", () => {
    const original = { id: "legacy", auto_start: false, launch: { type: "external" }, transport: { type: "streamable_http", endpoint: "https://example.test/mcp" }, timeout_seconds: 30 }
    expect(patchManifestField(original, ["name"], { kind: "set", value: "Renamed" })).not.toHaveProperty("startup_policy")
    const changed = changeStartupPolicy(original, true)
    expect(changed).toEqual({ ...original, auto_start: true, startup_policy: "gate_start_v1" })
    expect(precheckManifest(changed, copy).errors).toEqual([])
    expect(changeStartupPolicy(changed, false)).toEqual({ ...original, auto_start: false, startup_policy: "gate_start_v1" })
    expect(original.auto_start).toBe(false)
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

describe("manifest validation status", () => {
  const passed = { ok: true, can_apply: true, manifest_id: "demo", summary: { errors: 0, warnings: 0, info: 0, ok: 1 }, checks: [] }
  it("lets failure flags and checks dominate success counters", () => {
    expect(manifestValidationStatus({ ...passed, ok: false })).toBe("error")
    expect(manifestValidationStatus({ ...passed, can_apply: false })).toBe("error")
    expect(manifestValidationStatus({ ...passed, checks: [{ name: "transport.endpoint", severity: "error", message: "Invalid endpoint", metadata: {} }] })).toBe("error")
    expect(manifestValidationStatus({ ...passed, summary: { ...passed.summary, errors: 1, warnings: 2 } })).toBe("error")
  })
  it("distinguishes warning and pass, including an empty informational list", () => {
    expect(manifestValidationStatus(passed)).toBe("success")
    expect(manifestValidationStatus({ ...passed, summary: { ...passed.summary, warnings: 1 } })).toBe("warning")
    expect(manifestValidationStatus({ ...passed, checks: [{ name: "launch.cwd", severity: "warning", message: "Path unavailable", metadata: {} }] })).toBe("warning")
  })
})


describe("masked container source identity", () => {
  const manifest = { id: "container-a", launch: { type: "managed_container", image: `example.test/synthetic@sha256:${"a".repeat(64)}`,
    mounts: [{ source: "***", target: "/workspace", read_only: true }] }, transport: { type: "stdio" } }
  const context = { existingConfigId: "container-a", originalEndpointMasked: false, originalMaskedMountTargets: ["/workspace"] }
  it("retains a masked source only for its original config and target", () => {
    expect(precheckManifest(manifest, copy, context).errors).not.toContain("containerMountsError")
    expect(precheckManifest(manifest, copy).errors).toContain("containerMountsError")
    expect(precheckManifest({ ...manifest, id: "container-b" }, copy, context).errors).toContain("containerMountsError")
    expect(precheckManifest(manifest, copy, { ...context, originalMaskedMountTargets: [] }).errors).toContain("containerMountsError")
    expect(precheckManifest({ ...manifest, launch: { ...manifest.launch, mounts: [{ source: "***", target: "/different", read_only: true }] } }, copy, context).errors).toContain("containerMountsError")
  })
})

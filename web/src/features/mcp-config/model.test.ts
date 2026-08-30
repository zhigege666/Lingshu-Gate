import { describe, expect, it } from "vitest"
import {
  parseEnv,
  parseManifest,
  precheckManifest,
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

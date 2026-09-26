import { describe, expect, it } from "vitest"
import { changeRuntimeMode, manifestFingerprint, updateManifestPath } from "./draft"
import { parseManifest, precheckManifest } from "./model"

const source = {
  id: "graph", enabled: true, timeout_seconds: 30,
  launch: { type: "external" },
  transport: { type: "streamable_http", endpoint: "https://graph.example.com/mcp", headers: { Authorization: "Bearer ${credential:graph}" } },
  analysis: { nested: { flags: [false, 0, ""] } },
  user_credentials: [{ id: "token", required: false }],
  roots: ["/workspace"],
}

describe("配置草稿契约", () => {
  it("修改字段保留凭据引用、嵌套元数据和其他配置，且不修改来源", () => {
    const changed = updateManifestPath(source, ["transport", "endpoint"], "https://new.example.com/mcp")
    expect(changed.transport).toEqual({ ...source.transport, endpoint: "https://new.example.com/mcp" })
    expect(changed.analysis).toEqual(source.analysis)
    expect(changed.user_credentials).toEqual(source.user_credentials)
    expect(source.transport.endpoint).toBe("https://graph.example.com/mcp")
  })
  it("表单到 JSON 再返回不会覆盖源码修改或丢失 false、0 和空值", () => {
    const text = JSON.stringify(updateManifestPath(source, ["enabled"], false))
    const fromJson = parseManifest(text.replace('"timeout_seconds":30', '"timeout_seconds":90'))
    const changed = updateManifestPath(fromJson, ["name"], "Graph")
    expect(changed.enabled).toBe(false)
    expect(changed.timeout_seconds).toBe(90)
    expect(changed.analysis).toEqual(source.analysis)
  })
  it("修正无效地址后按新草稿校验，不被旧值阻塞", () => {
    const invalid = updateManifestPath(source, ["transport", "endpoint"], "[REDACTED]")
    expect(precheckManifest(invalid, key => key).errors).toContain("endpointInvalid")
    const fixed = updateManifestPath(invalid, ["transport", "endpoint"], source.transport.endpoint)
    expect(precheckManifest(fixed, key => key)).toEqual({ errors: [], warnings: [] })
  })
  it("普通编辑不启用重启策略；显式切换外部模式才清除不兼容启动配置", () => {
    const managed = { ...source, launch: { type: "managed_process", command: "node", args: ["server"], env: { KEY: "${credential:graph}" } }, restart_policy: { enabled: true, health_check: { enabled: true, interval_seconds: 60 } } }
    const changed = changeRuntimeMode(managed, "external_http")
    expect(changed.launch).toEqual({ type: "external" })
    expect(changed.restart_policy).toEqual({ enabled: false, health_check: { enabled: false, interval_seconds: 60 } })
    expect(changed.transport).toEqual(source.transport)
    expect(managed.restart_policy.enabled).toBe(true)
  })
  it("仅格式化不会变脏；删除可选值不影响其他字段", () => {
    expect(manifestFingerprint(JSON.stringify(source))).toBe(manifestFingerprint(JSON.stringify(source, null, 2)))
    expect(updateManifestPath(source, ["transport", "headers"], undefined).transport).toEqual({ type: "streamable_http", endpoint: source.transport.endpoint })
    expect(() => parseManifest('{"id":')).toThrow()
  })
})

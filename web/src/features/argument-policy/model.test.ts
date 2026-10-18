import { describe, expect, it } from "vitest"
import { parsePolicyJson } from "./json"
import { newRule, policyDraft, validatePolicyDraft } from "./model"

describe("policy JSON preservation", () => {
  it.each(['{"x":1,"x":2}', '{"x":1,"\\u0078":2}', '{"value":{"a":false,"a":true}}', '[{"id":1,"id":2}]'])("rejects duplicate members: %s", text => {
    expect(() => parsePolicyJson(text)).toThrow("json_duplicate")
  })
  it.each(["9007199254740993", "0.10000000000000001", "1e400", "1e-400", "1e20"])("rejects numbers it cannot preserve: %s", text => {
    expect(() => parsePolicyJson(text)).toThrow("json_number")
  })
  it("keeps false, null, zero, nested arrays and own prototype keys", () => {
    const value = parsePolicyJson('{"__proto__":{"marker":true},"a":[false,null,0,-0,0.100,1.2e-7],"键":"😊"}') as Record<string, unknown>
    expect(Object.getPrototypeOf(value)).toBe(Object.prototype)
    expect(Object.hasOwn(value, "__proto__")).toBe(true)
    expect(value.a).toEqual([false, null, 0, -0, 0.1, 0.00000012])
    expect(value["键"]).toBe("😊")
  })
  it.each(["", '{"a":}', "[1,]", "true false", '"bad\nvalue"', '"\\ud800"', '"\\udfff"', '{"x":01}', '"\\q"'])("rejects malformed or unsupported text: %s", text => {
    expect(() => parsePolicyJson(text)).toThrow()
  })
  it("enforces bytes, nodes and depth before recursive overflow", () => {
    expect(() => parsePolicyJson('"中"', 4)).toThrow("json_limit")
    expect(() => parsePolicyJson("[".repeat(26) + "0" + "]".repeat(26))).toThrow("json_depth")
    expect(() => parsePolicyJson("[" + "0,".repeat(8200) + "0]")).toThrow("json_limit")
  })
})

describe("policy draft authority", () => {
  it("never submits a prior parsed value when the active text is invalid, even when off", () => {
    const draft = { ...newRule("rule_1"), value: '{"approved":true' }
    const result = validatePolicyDraft(false, [draft], 7, 42)
    expect(result.issues).toEqual([expect.objectContaining({ code: "json_syntax", path: "/rules/0/value", revision: 42, immediate: true })])
    expect(draft.value).toBe('{"approved":true')
  })
  it("preserves an omitted range bound and root pointer", () => {
    const rows = policyDraft({ tool_id: "synthetic", revision: 2, enabled: true, rules: [
      { id: "r1", pointer: "", operator: "equals", value: null },
      { id: "r2", pointer: "/limit", operator: "number_range", minimum: null, maximum: 3 },
    ] })
    const result = validatePolicyDraft(true, rows, 2, 0)
    expect(result.issues).toEqual([])
    expect(result.body.rules[0]).toEqual({ id: "r1", pointer: "", operator: "equals", value: null })
    expect(result.body.rules[1]).toEqual({ id: "r2", pointer: "/limit", operator: "number_range", maximum: 3 })
  })
  it("rejects unsupported stored fields before allowing a rewrite", () => {
    expect(() => policyDraft({ tool_id: "x", enabled: false, revision: 1, rules: [
      { id: "r", pointer: "", operator: "equals", value: null, future_flag: true } as never,
    ] })).toThrow("policy_editor_unsupported")
  })
  it("keeps a valid compact policy editable when indentation alone would exceed the text budget", () => {
    let value: unknown = Array.from({ length: 2000 }, () => null)
    for (let i = 0; i < 20; i++) value = [value]
    expect(JSON.stringify(value, null, 2).length).toBeGreaterThan(65_536)
    const rows = policyDraft({ tool_id: "x", enabled: true, revision: 1, rules: [{ id: "r", pointer: "/a", operator: "equals", value }] })
    expect(rows[0].value.length).toBeLessThan(65_536)
    const result = validatePolicyDraft(false, rows, 1, 2)
    expect(result.issues).toEqual([])
    expect(result.body.rules[0]).toEqual({ id: "r", pointer: "/a", operator: "equals", value })
  })
  it.each(["depth", "nodes"])("keeps the response envelope outside the rules %s budget", kind => {
    let value: unknown = kind === "nodes" ? Array.from({ length: 8182 }, () => null) : null
    if (kind === "depth") for (let i = 0; i < 22; i++) value = [value]
    const saved = { tool_id: "x", enabled: true, revision: 1, rules: [{ id: "r", pointer: "/a", operator: "equals" as const, value }] }
    expect(() => parsePolicyJson(JSON.stringify(saved))).toThrow(kind === "nodes" ? "json_limit" : "json_depth")
    const envelope = parsePolicyJson(JSON.stringify(saved), 131_072, { maxDepth: 32, maxNodes: 16_384 }) as typeof saved
    const result = validatePolicyDraft(false, policyDraft(envelope), 1, 3)
    expect(result.issues).toEqual([])
    expect(result.body.rules).toEqual(saved.rules)
  })
  it("keeps duplicate ids, invalid pointers, empty values and reversed ranges actionable", () => {
    const first = { ...newRule("r"), operator: "allowed_values" as const, pointer: "/a~2b" }
    const second = { ...newRule("r"), operator: "number_range" as const, minimum: "3", maximum: "1" }
    expect(validatePolicyDraft(true, [first, second], 0, 4).issues.map(issue => issue.code)).toEqual(["pointer", "allowed_values", "rule_id", "range_order"])
  })
})

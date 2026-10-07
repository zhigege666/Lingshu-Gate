import { describe, expect, it } from "vitest"
import { classificationChangeReason } from "./classification-change"

const row = (invalidation: Record<string, unknown>) => ({ evidence: { invalidation: { reason: "tool_definition_changed", ...invalidation } } })

describe("classification change explanation", () => {
  it("names input/output changes and keeps review and publication separate", () => {
    expect(classificationChangeReason(row({ changed_fields: ["output_schema"] }), false)).toBe("output contract changed; review and publish again.")
    expect(classificationChangeReason(row({ changed_fields: ["input_schema", "output_schema"] }), true)).toBe("输入契约、输出契约已变更，需重新审核并发布。")
  })
  it.each([false, true])("does not invent historical field differences: output recorded %s", output => {
    const legacy = row({ previous_definition_unrecorded: true, output_schema_recorded: output, changed_fields: ["output_schema"] })
    expect(classificationChangeReason(legacy, false)).toContain("field differences are unavailable")
    expect(classificationChangeReason(legacy, true)).toContain("无法还原逐字段差异")
    expect(classificationChangeReason(legacy, false).includes("output contract is now recorded")).toBe(output)
    expect(classificationChangeReason(legacy, true).includes("现已记录输出契约")).toBe(output)
  })
  it("uses literal boolean evidence rather than truthy strings", () => {
    expect(classificationChangeReason(row({ previous_definition_unrecorded: "true", changed_fields: ["annotations"] }), false)).toBe("safety annotations changed; review and publish again.")
  })
  it.each([
    ["missing_from_latest_tools_list", "Removed from latest catalog", "最新目录中已移除"],
    ["reappeared_in_tools_list", "Tool reappeared; review required", "工具重新出现，需复核"],
  ])("keeps the current lifecycle reason: %s", (reason, en, zh) => {
    const item = { evidence: { ...row({ changed_fields: ["output_schema"] }).evidence, lifecycle: { reason } } }
    expect(classificationChangeReason(item, false)).toBe(en)
    expect(classificationChangeReason(item, true)).toBe(zh)
  })
  it.each([null, [], "synthetic-private-value", 42])("handles malformed evidence without displaying it: %s", invalidation => {
    expect(classificationChangeReason({ evidence: { invalidation } }, false)).toBe("Review required; inspect evidence")
    expect(classificationChangeReason({ evidence: { invalidation } }, true)).toBe("需重新审核，详见证据")
  })
  it("deduplicates known field names and never displays unknown names or definition values", () => {
    const item = row({ changed_fields: ["input_schema", null, 3, "input_schema", "__proto__", "synthetic-private-value"], previous_definition_snapshot: { secret: "synthetic-private-value" }, current_definition_snapshot: { secret: "synthetic-private-value" } })
    expect(classificationChangeReason(item, false)).toBe("input contract changed; review and publish again.")
  })
  it.each([undefined, "output_schema", ["unknown-field"]])("uses a bounded definition fallback for unknown differences: %s", changed_fields => {
    expect(classificationChangeReason(row({ changed_fields }), false)).toBe("Definition changed; review and publish again.")
    expect(classificationChangeReason(row({ changed_fields }), true)).toBe("定义已变更，需重新审核并发布。")
  })
})

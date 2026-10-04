import { describe, expect, it } from "vitest"
import { classificationChangeReason } from "./classification-change"

const row = (invalidation: Record<string, unknown>) => ({ evidence: { invalidation: { reason: "tool_definition_changed", ...invalidation } } })
describe("classification change explanation", () => {
  it("names input/output changes and requires separate review/publication", () => {
    expect(classificationChangeReason(row({ changed_fields: ["output_schema"] }), false)).toContain("output contract changed; review and publish again")
    expect(classificationChangeReason(row({ changed_fields: ["input_schema", "output_schema"] }), true)).toContain("输入契约、输出契约已变更")
  })
  it("does not invent historical differences on upgrade", () => {
    const legacy = row({ previous_definition_unrecorded: true, output_schema_recorded: true })
    expect(classificationChangeReason(legacy, false)).toContain("field differences are unavailable")
    expect(classificationChangeReason(legacy, true)).toContain("现已记录输出契约")
  })
})

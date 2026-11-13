import { describe, expect, it } from "vitest"
import { resolveStringMapRows, type StringMapRow } from "./string-map-draft"

const row = (id: number, key: string, value: string, saved = false): StringMapRow => ({ id, key, value, ...(saved ? { originalKey: key, originalValue: value } : {}) })

describe("inline key/value draft", () => {
  it("includes a new key with an empty value without a separate Add action", () => {
    expect(resolveStringMapRows([row(1, " TOKEN ", ""), row(2, "", "")]).value).toEqual({ " TOKEN ": "" })
  })
  it("renames a key without retaining its old name or changing its value", () => {
    expect(resolveStringMapRows([{ ...row(1, "OLD", "${credential:token}", true), key: "NEW" }]).value)
      .toEqual({ NEW: "${credential:token}" })
  })
  it("retains duplicate and incomplete input as invalid instead of losing a row", () => {
    expect(resolveStringMapRows([row(1, "A", "one"), row(2, "A", "two")]).value).toBeNull()
    expect(resolveStringMapRows([row(1, "", "unfinished")]).issues).toEqual([{ id: 1, code: "missing_key" }])
    expect(resolveStringMapRows([row(1, " ", "")]).value).toBeNull()
  })
  it("checks HTTP header names without case while preserving environment key case", () => {
    const rows = [row(1, "Authorization", "first"), row(2, "authorization", "second")]
    expect(resolveStringMapRows(rows, true).value).toBeNull()
    expect(resolveStringMapRows(rows).value).toEqual({ Authorization: "first", authorization: "second" })
  })
  it("preserves existing empty keys, whitespace and values losslessly", () => {
    expect(resolveStringMapRows([row(1, "", "value", true), row(2, " ", "", true)]).value).toEqual({ "": "value", " ": "" })
  })
  it("allows a saved mask only at its original key and never transfers it", () => {
    const saved = row(1, "TOKEN", "***", true)
    expect(resolveStringMapRows([saved]).value).toEqual({ TOKEN: "***" })
    expect(resolveStringMapRows([{ ...saved, key: "OTHER" }]).issues[0]?.code).toBe("masked_rename")
    expect(resolveStringMapRows([row(1, "TOKEN", "***")]).value).toBeNull()
    expect(resolveStringMapRows([{ ...saved, key: "OTHER", value: "${credential:token}" }]).value).toEqual({ OTHER: "${credential:token}" })
  })
  it("retains special property names as data rather than object mutations", () => {
    expect(Object.hasOwn(resolveStringMapRows([row(1, "__proto__", "data")]).value!, "__proto__")).toBe(true)
  })
})

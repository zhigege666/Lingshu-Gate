import { readFile } from "node:fs/promises"
import { describe, expect, it } from "vitest"
import { validateI18nMessages } from "./i18n-contract.mjs"

describe("i18n source contract", () => {
  it("accepts reordered locales and keys, quoted names, comments, assertions and formatting changes", () => {
    const source = `
      type Locale = "zh-CN" | "en-US"
      export const messages = (({
        'en-US' : ({ 'second.key': 'Second', first: 'First' } as const),
        // Language object order and whitespace are not part of the contract.
        "zh-CN" : ({ first: '第一', "second.key": '第二' } satisfies Record<string, string>),
      } as const) satisfies Record<Locale, Record<string, string>>)
      const unrelated = (() => { throw new Error('must never execute') })()
    `
    const keys = validateI18nMessages(source)
    expect([...keys.get("zh-CN")]).toEqual(["first", "second.key"])
    expect([...keys.get("en-US")]).toEqual(["second.key", "first"])
  })

  it("checks the actual catalog with nonempty matching language keys", async () => {
    const source = await readFile(new URL("../src/i18n.ts", import.meta.url), "utf8")
    const keys = validateI18nMessages(source)
    expect(keys.get("zh-CN").size).toBeGreaterThan(0)
    expect(keys.get("en-US")).toEqual(keys.get("zh-CN"))
  })

  it.each([
    ["empty file", ""],
    ["different object", 'const other = { "zh-CN": { one: "一" }, "en-US": { one: "One" } }'],
    ["nested decoy", 'function example() { const messages = { "zh-CN": { one: "一" }, "en-US": { one: "One" } } }'],
    ["duplicate declarations", "const messages = {}; const messages = {}"],
  ])("rejects %s instead of accepting an empty extraction", (_label, source) => {
    expect(() => validateI18nMessages(source)).toThrow(/exactly one top-level messages object/)
  })

  it.each([
    ['const messages = { "en-US": { one: "One" } }', "zh-CN"],
    ['const messages = { "zh-CN": { one: "一" } }', "en-US"],
  ])("rejects a missing locale in %s", (source, locale) => {
    expect(() => validateI18nMessages(source)).toThrow(`missing locale ${locale}`)
  })

  it.each([
    'const messages = { "zh-CN": {}, "en-US": {} }',
    'const messages = { "zh-CN": { one: "一" }, "en-US": {} }',
  ])("rejects empty language objects: %s", source => {
    expect(() => validateI18nMessages(source)).toThrow(/at least one message key/)
  })

  it("reports missing keys in both directions even when counts match", () => {
    const source = 'const messages = { "zh-CN": { one: "一" }, "en-US": { two: "Two" } }'
    expect(() => validateI18nMessages(source)).toThrow(/en-US is missing keys: one; zh-CN is missing keys: two/)
  })

  it.each([
    ['const messages = { "zh-CN": { one: "一", "one": "二" }, "en-US": { one: "One" } }', 'messages.zh-CN contains duplicate key "one"'],
    ['const messages = { "zh-CN": { one: "一" }, "en-US": { one: "One", one: "Two" } }', 'messages.en-US contains duplicate key "one"'],
    ['const messages = { "zh-CN": { one: "一" }, "zh-CN": { one: "二" }, "en-US": { one: "One" } }', 'messages contains duplicate key "zh-CN"'],
  ])("rejects duplicate properties in %s", (source, error) => {
    expect(() => validateI18nMessages(source)).toThrow(error)
  })

  it.each([
    'const messages = loadMessages()',
    'const messages = { "zh-CN": chinese, "en-US": { one: "One" } }',
  ])("rejects locale data it cannot statically inspect: %s", source => {
    expect(() => validateI18nMessages(source)).toThrow(/must be a static object literal/)
  })

  it.each([
    'const messages = { ...catalog }',
    'const messages = { "zh-CN": { ...shared }, "en-US": { one: "One" } }',
    'const messages = { "zh-CN": { [key]: "一" }, "en-US": { one: "One" } }',
    'const messages = { "zh-CN": { get one() { return "一" } }, "en-US": { one: "One" } }',
    'const messages = { "zh-CN": { one }, "en-US": { one: "One" } }',
  ])("rejects dynamic members rather than counting an incomplete subset: %s", source => {
    expect(() => validateI18nMessages(source)).toThrow(/explicit, non-computed properties/)
  })

  it("reports malformed TypeScript with a source location", () => {
    expect(() => validateI18nMessages('const messages = { "zh-CN": {', "catalog.ts")).toThrow(/catalog.ts:1:\d+:/)
  })
})

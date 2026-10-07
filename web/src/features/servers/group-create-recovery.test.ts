import { afterEach, describe, expect, it, vi } from "vitest"
import { forgetGroupCreation, readGroupCreation, rememberGroupCreation } from "./group-create-recovery"

afterEach(() => vi.unstubAllGlobals())

describe("unconfirmed group creation recovery", () => {
  const first = { userId: "opaque-synthetic-user-a", origin: "https://gate.example.test" }
  const second = { ...first, userId: "opaque-synthetic-user-b" }
  const otherGate = { ...first, origin: "https://other-gate.example.test" }

  function storage() {
    const values = new Map<string, string>()
    vi.stubGlobal("window", { sessionStorage: {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
      removeItem: (key: string) => values.delete(key),
    } })
    return values
  }

  it("keeps only request keys, isolated by exact authenticated ID and Gate origin", () => {
    const values = storage(), key = "a".repeat(32)
    expect(rememberGroupCreation(first, key)).toBe(true)
    expect(readGroupCreation(first)).toBe(key)
    expect(readGroupCreation(second)).toBeNull()
    expect(readGroupCreation(otherGate)).toBeNull()
    expect(Array.from(values.values())).toEqual([key])
    expect(rememberGroupCreation(second, "b".repeat(32))).toBe(true)
    expect(forgetGroupCreation(second, "b".repeat(32))).toBe(true)
    expect(readGroupCreation(first)).toBe(key)
  })

  it("cannot persist a draft or let a late reconciliation clear a newer key", () => {
    const values = storage(), original = "c".repeat(32), newer = "d".repeat(32)
    expect(rememberGroupCreation(first, '{"name":"Synthetic draft"}')).toBe(false)
    expect(values.size).toBe(0)
    rememberGroupCreation(first, original); rememberGroupCreation(first, newer)
    expect(forgetGroupCreation(first, original)).toBe(true)
    expect(readGroupCreation(first)).toBe(newer)
    expect(forgetGroupCreation(first, newer)).toBe(true)
    expect(readGroupCreation(first)).toBeNull()
  })

  it("reports unavailable browser storage without persisting elsewhere", () => {
    vi.stubGlobal("window", { get sessionStorage() { throw new Error("Synthetic storage unavailable") } })
    expect(readGroupCreation(first)).toBeNull()
    expect(rememberGroupCreation(first, "e".repeat(32))).toBe(false)
    expect(forgetGroupCreation(first, "e".repeat(32))).toBe(false)
  })
})

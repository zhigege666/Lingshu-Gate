import { describe, expect, it } from "vitest"
import type { RuntimeCacheItem } from "@/api/client"
import { cacheAccess, cacheClearBlock, cacheCleanupConfirmed, cacheCopy } from "./runtime-cache-state"
const populated: RuntimeCacheItem = { name: "npm", path: "/synthetic/runtime-cache/npm-cache", exists: true, is_dir: true, readable: true, writable: true, parent_writable: true, size_bytes: 40, file_count: 2, last_modified_at: null }
const empty = { ...populated, size_bytes: 0, file_count: 0 }
describe("runtime cache operation semantics", () => {
  it("distinguishes existing writable, missing creatable and existing readonly directories", () => {
    expect(cacheAccess(populated)).toBe("writable")
    expect(cacheAccess({ ...populated, exists: false, is_dir: false, writable: false })).toBe("creatable")
    // A writable parent does not make an existing cache directory writable.
    expect(cacheAccess({ ...populated, writable: false })).toBe("blocked")
    expect(cacheAccess({ ...populated, is_dir: false })).toBe("invalid")
  })
  it("explains no-op cleanup without offering an enabled clear action", () => {
    expect(cacheClearBlock(empty)).toBe("emptyHint")
    expect(cacheClearBlock({ ...populated, exists: false })).toBe("emptyHint")
    expect(cacheClearBlock(populated)).toBeNull()
    expect(cacheClearBlock({ ...empty, readable: false })).toBe("unreadable")
    expect(cacheClearBlock({ ...populated, parent_writable: false })).toBe("permissions")
    expect(cacheClearBlock({ ...populated, writable: false })).toBe("permissions")
  })
  it("does not report clear success from HTTP success or removed alone", () => {
    expect(cacheCleanupConfirmed({ cache: "npm", removed: true, before: populated, after: populated }, "npm")).toBe(false)
    expect(cacheCleanupConfirmed({ cache: "other", removed: true, before: populated, after: empty }, "npm")).toBe(false)
    expect(cacheCleanupConfirmed({ cache: "npm", removed: false, before: empty, after: empty }, "npm")).toBe(true)
  })
  it("provides semantic access and empty-state labels in both languages", () => {
    expect(cacheCopy["zh-CN"].writable).toBe("可写")
    expect(cacheCopy["en-US"].writable).toBe("Writable")
    expect(cacheCopy["zh-CN"].empty).toBe("无需清理")
    expect(cacheCopy["en-US"].empty).toBe("Nothing to clear")
  })
})

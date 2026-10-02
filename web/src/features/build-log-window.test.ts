import { describe, expect, it } from "vitest"
import type { BuildLog } from "@/api/builds"
import { BUILD_LOG_WINDOW, mergeBuildLogWindow } from "./build-log-window"
const log = (sequence: number) => ({ id: String(sequence), sequence, build_id: "build", message: `log ${sequence}` } as BuildLog)
describe("bounded build log display", () => {
  it("keeps the latest 200 of a 50000-record stream", () => {
    let window: BuildLog[] = []
    for (let start = 0; start < 50000; start += 200) {
      window = mergeBuildLogWindow(window, Array.from({ length: 200 }, (_, offset) => log(start + offset)))
      expect(window.length).toBeLessThanOrEqual(BUILD_LOG_WINDOW)
    }
    expect(window[0].sequence).toBe(49800)
    expect(window.at(-1)?.sequence).toBe(49999)
  })
  it("deduplicates replayed IDs, sorts out-of-order delivery and never mutates inputs", () => {
    const original = [log(3), log(1)]
    const result = mergeBuildLogWindow(original, [log(2), log(3)])
    expect(result.map(item => item.sequence)).toEqual([1, 2, 3])
    expect(original.map(item => item.sequence)).toEqual([3, 1])
  })
  it("does not replace a newer stream tail with an older REST snapshot", () => {
    const result = mergeBuildLogWindow([log(203)], Array.from({ length: 200 }, (_, index) => log(index)))
    expect(result.at(-1)?.sequence).toBe(203)
    expect(result).toHaveLength(200)
  })
})

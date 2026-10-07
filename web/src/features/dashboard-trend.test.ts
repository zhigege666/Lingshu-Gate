import { describe, expect, it } from "vitest"
import { trendGeometry, trendPointerIndex } from "./dashboard-trend"

describe("zero-based trend geometry", () => {
  it("supports empty, zero and single-point windows without invalid paths", () => {
    expect(trendGeometry([]).line).toBe("")
    expect(trendGeometry([0, 0]).points.every(point => point.y === 100)).toBe(true)
    expect(trendGeometry([3]).points[0].x).toBe(50)
    expect(trendGeometry([NaN, Infinity, -1]).line).not.toMatch(/NaN|Infinity/)
  })
  it("keeps a zero baseline and a ceiling above the greatest value", () => {
    for (const values of [[1, 3, 0], [890, 920], [1000000, 9200000]]) {
      const result = trendGeometry(values)
      expect(result.ticks.at(-1)).toBe(0)
      expect(result.ticks[0]).toBeGreaterThanOrEqual(Math.max(...values))
      expect(result.points.every(point => point.y >= 0 && point.y <= 100)).toBe(true)
      expect(result.line).not.toMatch(/[CQ]/) // No spline-generated peaks.
    }
  })
  it("clamps pointer hit testing and tolerates missing width", () => {
    expect(trendPointerIndex(-10, 600, 12)).toBe(0)
    expect(trendPointerIndex(900, 600, 12)).toBe(11)
    expect(trendPointerIndex(300, 600, 12)).toBe(6)
    expect(trendPointerIndex(10, 0, 0)).toBe(0)
  })
})

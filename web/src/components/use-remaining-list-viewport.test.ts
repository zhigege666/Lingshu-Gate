import { describe, expect, it } from "vitest"
import { remainingListHeight } from "./use-remaining-list-viewport"

describe("section-relative list ceiling", () => {
  it("grows a below-fold section to available space when it scrolls into view", () => {
    expect(remainingListHeight(1100, 844, 32, 130)).toBe(130)
    expect(remainingListHeight(180, 844, 32, 130)).toBe(632)
    expect(remainingListHeight(-200, 844, 32, 130)).toBe(812)
  })
  it("preserves actual wrapped controls and one row on short screens", () => {
    expect(remainingListHeight(700, 844, 32, 238)).toBe(238)
    expect(remainingListHeight(250, 844, 32, 238)).toBe(562)
  })
  it("uses remaining tall-screen space instead of a fixed fraction", () => {
    expect(remainingListHeight(260, 1222, 32, 130)).toBe(930)
  })
})

import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import { listPage, ListPagination } from "@/components/list-pagination"
import { translate } from "@/i18n"
const t = (key: Parameters<typeof translate>[1]) => translate("en-US", key)
const items = Array.from({ length: 5000 }, (_, id) => ({ id }))

describe("loaded list pagination", () => {
  it("bounds 5000 records to a stable page without mutating the authorized input", () => {
    const first = listPage(items, 1)
    const next = listPage(items, 2)
    expect(first.items).toHaveLength(50)
    expect(next.items).toHaveLength(50)
    expect(next.items[0].id).toBe(50)
    expect(first.items.some(item => next.items.includes(item))).toBe(false)
    expect(items).toHaveLength(5000)
  })
  it("clamps the page after deletion or refresh and reports an exact loaded range", () => {
    expect(listPage(items.slice(0, 51), 100)).toMatchObject({ page: 2, pageCount: 2, start: 51, end: 51 })
    expect(listPage([], 100)).toMatchObject({ page: 1, pageCount: 1, start: 0, end: 0 })
    const html = renderToStaticMarkup(<ListPagination paging={{ ...listPage(items, 100), setPage: () => {} }} t={t} />)
    expect(html).toContain("4951")
    expect(html).toContain("5000")
    expect(html).toContain("disabled")
  })
  it("retains range statistics without redundant single-page controls", () => {
    for (const count of [0, 1, 50]) {
      const html = renderToStaticMarkup(<ListPagination paging={{ ...listPage(items.slice(0, count), 1), setPage: () => {} }} t={t} />)
      expect(html).toContain(` / ${count}`)
      expect(html).not.toContain("<button")
    }
  })

})

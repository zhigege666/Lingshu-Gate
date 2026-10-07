import { useEffect, useRef } from "react"

// Unlike a page-root ceiling, a lower-page list must grow as its section enters
// the viewport. The minimum comes from its actual controls and first row.
export function remainingListHeight(top: number, viewportHeight: number, bottomGap: number, minimum: number) {
  return Math.ceil(Math.max(minimum, viewportHeight - Math.max(0, top) - bottomGap))
}

export function useRemainingListViewport(bottomGap: number, standaloneSection = false) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const node = ref.current
    if (!node) return
    let frame = 0
    const measure = () => {
      const rows = node.querySelector<HTMLElement>(":scope > .bounded-list-scroll, :scope > .delivery-records-table")
      if (!rows) return
      const style = getComputedStyle(node)
      const number = (value: string) => Number.parseFloat(value) || 0
      const siblings = Array.from(node.children).filter(child => child !== rows) as HTMLElement[]
      const controls = siblings.reduce((height, child) => {
        const childStyle = getComputedStyle(child)
        return height + child.getBoundingClientRect().height + number(childStyle.marginTop) + number(childStyle.marginBottom)
      }, 0)
      const firstRow = rows.querySelector<HTMLElement>("tbody > tr") ?? rows.firstElementChild
      const rowHeight = firstRow?.getBoundingClientRect().height ?? 0
      const headerHeight = rows.querySelector("thead")?.getBoundingClientRect().height ?? 0
      const minimum = controls + rowHeight + headerHeight + number(style.rowGap) * siblings.length
        + number(style.paddingTop) + number(style.paddingBottom) + number(style.borderTopWidth) + number(style.borderBottomWidth)
      // A lower-page section needs enough document extent to scroll its heading
      // above the rows. Budget that section from the measured shell/header,
      // rather than shrinking it to one row and trapping it at maxScroll.
      const section = standaloneSection ? node.closest("section") : null
      const shellHeight = document.querySelector(".console-header")?.getBoundingClientRect().height ?? 0
      const top = section
        ? shellHeight + node.getBoundingClientRect().top - section.getBoundingClientRect().top
        : node.getBoundingClientRect().top
      let ancestorBottom = 0
      for (let ancestor = node.parentElement; ancestor; ancestor = ancestor.parentElement) {
        const ancestorStyle = getComputedStyle(ancestor)
        ancestorBottom += number(ancestorStyle.paddingBottom) + number(ancestorStyle.borderBottomWidth)
        if (ancestor.classList.contains("console-content")) break
      }
      const height = `${remainingListHeight(top, window.innerHeight, Math.max(bottomGap, ancestorBottom), minimum)}px`
      if (node.style.getPropertyValue("--remaining-list-height") !== height) node.style.setProperty("--remaining-list-height", height)
    }
    const schedule = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(measure) }
    const onScroll = (event: Event) => {
      // Row scrolling never changes the section's viewport position.
      if (event.target instanceof Node && node.contains(event.target)) return
      schedule()
    }
    measure()
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(schedule)
    for (let ancestor: HTMLElement | null = node; ancestor; ancestor = ancestor.parentElement) observer?.observe(ancestor)
    Array.from(node.children).forEach(child => observer?.observe(child))
    const mutation = new MutationObserver(schedule)
    mutation.observe(node, { childList: true, subtree: true, characterData: true })
    window.addEventListener("scroll", onScroll, true)
    window.addEventListener("resize", schedule)
    window.visualViewport?.addEventListener("resize", schedule)
    return () => {
      cancelAnimationFrame(frame)
      observer?.disconnect()
      mutation.disconnect()
      window.removeEventListener("scroll", onScroll, true)
      window.removeEventListener("resize", schedule)
      window.visualViewport?.removeEventListener("resize", schedule)
    }
  }, [bottomGap, standaloneSection])
  return ref
}

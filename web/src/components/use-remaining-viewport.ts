import { useEffect, useRef } from "react"

/** A ceiling, not a forced height: consumers keep small lists content-sized.
 * Attach to the page root and use var(--remaining-viewport-height) as its
 * max-height. Flex descendants own toolbar, scrolling content and pagination.
 */
export function useRemainingViewport<T extends HTMLElement = HTMLDivElement>(bottomGap = 16) {
  const ref = useRef<T>(null)
  useEffect(() => {
    const node = ref.current
    if (!node) return
    let frame = 0
    const measure = () => {
      const top = Math.max(0, node.getBoundingClientRect().top + window.scrollY)
      const pixels = (value: string) => Number.parseFloat(value) || 0
      // The page ceiling excludes the real space after it. Shell padding varies
      // across desktop/mobile; a fixed 16px allowance left a second scrollbar.
      let trailingSpace = pixels(getComputedStyle(node).marginBottom)
      for (let ancestor = node.parentElement; ancestor; ancestor = ancestor.parentElement) {
        const style = getComputedStyle(ancestor)
        trailingSpace += pixels(style.paddingBottom) + pixels(style.borderBottomWidth) + pixels(style.marginBottom)
      }
      const ceiling = `${Math.max(0, window.innerHeight - top - Math.max(bottomGap, trailingSpace))}px`
      if (node.style.getPropertyValue("--remaining-viewport-height") !== ceiling) {
        node.style.setProperty("--remaining-viewport-height", ceiling)
      }
    }
    const schedule = () => { cancelAnimationFrame(frame); frame = requestAnimationFrame(measure) }
    measure()
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(schedule)
    // Ancestor/header geometry may move the page without changing its own size.
    for (let ancestor: HTMLElement | null = node; ancestor; ancestor = ancestor.parentElement) observer?.observe(ancestor)
    const header = document.querySelector(".console-header")
    if (header) observer?.observe(header)
    window.addEventListener("resize", schedule)
    window.visualViewport?.addEventListener("resize", schedule)
    return () => {
      cancelAnimationFrame(frame)
      observer?.disconnect()
      window.removeEventListener("resize", schedule)
      window.visualViewport?.removeEventListener("resize", schedule)
    }
  }, [bottomGap])
  return ref
}

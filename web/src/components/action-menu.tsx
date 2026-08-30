import { createContext, useContext, useEffect, useId, useLayoutEffect, useRef, useState, type ButtonHTMLAttributes, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent, type ReactNode } from "react"
import { createPortal } from "react-dom"
import { MoreHorizontal } from "lucide-react"
import { cn } from "@/lib/utils"

const CloseActionMenuContext = createContext<() => void>(() => undefined)
const MENU_WIDTH = 176

export function ActionMenu({ label, children }: { label: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const [position, setPosition] = useState({ left: 0, top: 0 })
  const triggerRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)
  const menuId = useId()

  function updatePosition() {
    const trigger = triggerRef.current
    if (!trigger) return
    const rect = trigger.getBoundingClientRect()
    const menuHeight = menuRef.current?.getBoundingClientRect().height || 0
    const left = Math.max(8, Math.min(rect.right - MENU_WIDTH, window.innerWidth - MENU_WIDTH - 8))
    const fitsBelow = rect.bottom + menuHeight + 8 <= window.innerHeight
    setPosition({ left, top: fitsBelow || !menuHeight ? rect.bottom + 4 : Math.max(8, rect.top - menuHeight - 4) })
  }

  useLayoutEffect(() => {
    if (open) updatePosition()
  }, [open])

  useEffect(() => {
    if (!open) return undefined
    const focusTimer = window.setTimeout(() => menuRef.current?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus(), 0)
    function handlePointerDown(event: PointerEvent) {
      const target = event.target as Node
      if (!triggerRef.current?.contains(target) && !menuRef.current?.contains(target)) setOpen(false)
    }
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setOpen(false)
        triggerRef.current?.focus()
      }
    }
    window.addEventListener("resize", updatePosition)
    window.addEventListener("scroll", updatePosition, true)
    document.addEventListener("pointerdown", handlePointerDown)
    document.addEventListener("keydown", handleKeyDown)
    return () => {
      window.clearTimeout(focusTimer)
      window.removeEventListener("resize", updatePosition)
      window.removeEventListener("scroll", updatePosition, true)
      document.removeEventListener("pointerdown", handlePointerDown)
      document.removeEventListener("keydown", handleKeyDown)
    }
  }, [open])

  function handleMenuKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>('button:not(:disabled)'))
    if (!items.length) return
    event.preventDefault()
    const currentIndex = items.indexOf(document.activeElement as HTMLButtonElement)
    const nextIndex = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1 : event.key === "ArrowDown" ? (currentIndex + 1) % items.length : (currentIndex <= 0 ? items.length : currentIndex) - 1
    items[nextIndex]?.focus()
  }

  return <div className="inline-block text-left">
    <button
      ref={triggerRef}
      type="button"
      aria-haspopup="menu"
      aria-expanded={open}
      aria-controls={open ? menuId : undefined}
      className="inline-flex h-8 items-center justify-center gap-2 rounded-md border border-input bg-background px-3 text-xs font-medium shadow-sm transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      onClick={(event) => { event.stopPropagation(); setOpen((value) => !value) }}
    >
      <MoreHorizontal className="size-4" /><span className="sr-only sm:not-sr-only">{label}</span>
    </button>
    {open ? createPortal(
      <CloseActionMenuContext.Provider value={() => setOpen(false)}>
        <div id={menuId} ref={menuRef} role="menu" className="fixed z-[80] min-w-44 overflow-hidden rounded-md border bg-popover p-1 text-popover-foreground shadow-lg" style={{ left: position.left, top: position.top, width: MENU_WIDTH }} onKeyDown={handleMenuKeyDown}>
          {children}
        </div>
      </CloseActionMenuContext.Provider>,
      document.body,
    ) : null}
  </div>
}

export function ActionMenuItem({ destructive = false, className, onClick, ...props }: ButtonHTMLAttributes<HTMLButtonElement> & { destructive?: boolean }) {
  const close = useContext(CloseActionMenuContext)

  function handleClick(event: MouseEvent<HTMLButtonElement>) {
    event.stopPropagation()
    close()
    onClick?.(event)
  }

  return <button {...props} type="button" role="menuitem" className={cn("flex w-full items-center rounded-sm px-2 py-2 text-left text-xs transition-colors hover:bg-accent disabled:pointer-events-none disabled:opacity-50", destructive && "text-destructive hover:bg-destructive/10", className)} onClick={handleClick} />
}

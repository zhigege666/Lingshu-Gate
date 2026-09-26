import { useCallback, useEffect, useRef, useState } from "react"
import { isConsoleView, type ConsoleView } from "@/routing/console-routes"

export type ConsoleRouteState = { view: ConsoleView; buildId?: string }

const RECENT_VIEWS_KEY = "lingshu-gate-console-recent"

export function parseConsoleHash(hash: string): ConsoleRouteState {
  let parts: string[]
  try { parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean).map((part) => decodeURIComponent(part)) }
  catch { return { view: "dashboard" } }
  const route = parts[0]
  if (route === "builds") return { view: "builds", buildId: parts[1] || "" }
  if (route && isConsoleView(route)) return { view: route }
  return { view: "dashboard" }
}

export function consoleViewHash(view: ConsoleView): string {
  return `#/${view}`
}

function readRecentViews(): ConsoleView[] {
  try {
    const raw = window.localStorage.getItem(RECENT_VIEWS_KEY)
    const parsed = raw ? (JSON.parse(raw) as unknown) : []
    return Array.isArray(parsed)
      ? parsed.filter((item): item is ConsoleView => typeof item === "string" && isConsoleView(item))
      : []
  } catch {
    return []
  }
}

export function useConsoleRoute(beforeLeave?: () => Promise<boolean>) {
  const initialRoute = parseConsoleHash(window.location.hash)
  const [view, setView] = useState<ConsoleView>(initialRoute.view)
  const [routeBuildId, setRouteBuildId] = useState(initialRoute.buildId || "")
  const [recentViews, setRecentViews] = useState<ConsoleView[]>(readRecentViews)

  const accepted = useRef(initialRoute)
  const guard = useRef(beforeLeave)
  guard.current = beforeLeave
  const deciding = useRef(false)
  const position = useRef(Number(window.history.state?.gateConsoleIndex) || 0)
  const acceptedPosition = useRef(position.current)
  const target = useRef<{ route: ConsoleRouteState; position: number | null } | null>(null)

  const decide = useCallback(async () => {
    if (deciding.current) return false
    deciding.current = true
    try {
      const allowed = !guard.current || await guard.current()
      const destination = target.current
      if (!destination) return false
      if (!allowed) {
        if (destination.position !== null && position.current !== acceptedPosition.current) {
          window.history.go(acceptedPosition.current - position.current)
        }
        return false
      }
      if (destination.position === null) {
        const hash = consoleViewHash(destination.route.view) + (destination.route.buildId ? `/${encodeURIComponent(destination.route.buildId)}` : "")
        position.current += 1
        window.history.pushState({ ...window.history.state, gateConsoleIndex: position.current }, "", hash)
      }
      acceptedPosition.current = position.current
      accepted.current = destination.route
      setView(destination.route.view)
      setRouteBuildId(destination.route.buildId || "")
      return true
    } finally { target.current = null; deciding.current = false }
  }, [])

  useEffect(() => {
    // Index entries without replacing their URLs. Accepted native back/forward
    // navigation must never push a new entry or discard the forward stack.
    window.history.replaceState({ ...window.history.state, gateConsoleIndex: position.current }, "")
    const handleHashChange = () => {
      const next = parseConsoleHash(window.location.hash)
      const storedIndex: unknown = window.history.state?.gateConsoleIndex
      position.current = typeof storedIndex === "number" ? storedIndex : position.current + 1
      if (typeof storedIndex !== "number") window.history.replaceState({ ...window.history.state, gateConsoleIndex: position.current }, "")
      if (next.view === accepted.current.view && (next.buildId || "") === (accepted.current.buildId || "")) {
        if (deciding.current) target.current = { route: next, position: position.current }
        else acceptedPosition.current = position.current
        return
      }
      // Keep the mounted draft while deciding. Further browser navigation only
      // updates the destination, sharing the same leave confirmation.
      target.current = { route: next, position: position.current }
      void decide()
    }
    window.addEventListener("hashchange", handleHashChange)
    return () => window.removeEventListener("hashchange", handleHashChange)
  }, [decide])

  useEffect(() => {
    setRecentViews((previous) => {
      const next = [view, ...previous.filter((item) => item !== view)].slice(0, 5)
      try { window.localStorage.setItem(RECENT_VIEWS_KEY, JSON.stringify(next)) } catch { /* Storage can be disabled. */ }
      return next
    })
  }, [view])

  const navigate = useCallback(async (next: ConsoleView) => {
    if (deciding.current) return false
    if (next === accepted.current.view && !accepted.current.buildId) return true
    target.current = { route: { view: next }, position: null }
    return decide()
  }, [decide])

  return { view, routeBuildId, recentViews, navigate }
}

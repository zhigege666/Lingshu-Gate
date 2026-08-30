import { useCallback, useEffect, useState } from "react"
import { isConsoleView, type ConsoleView } from "@/routing/console-routes"

export type ConsoleRouteState = { view: ConsoleView; buildId?: string }

const RECENT_VIEWS_KEY = "lingshu-gate-console-recent"

export function parseConsoleHash(hash: string): ConsoleRouteState {
  const parts = hash.replace(/^#\/?/, "").split("/").filter(Boolean).map((part) => decodeURIComponent(part))
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

export function useConsoleRoute() {
  const initialRoute = parseConsoleHash(window.location.hash)
  const [view, setView] = useState<ConsoleView>(initialRoute.view)
  const [routeBuildId, setRouteBuildId] = useState(initialRoute.buildId || "")
  const [recentViews, setRecentViews] = useState<ConsoleView[]>(readRecentViews)

  useEffect(() => {
    const handleHashChange = () => {
      const next = parseConsoleHash(window.location.hash)
      setView(next.view)
      setRouteBuildId(next.buildId || "")
    }
    handleHashChange()
    window.addEventListener("hashchange", handleHashChange)
    return () => window.removeEventListener("hashchange", handleHashChange)
  }, [])

  useEffect(() => {
    setRecentViews((previous) => {
      const next = [view, ...previous.filter((item) => item !== view)].slice(0, 5)
      try { window.localStorage.setItem(RECENT_VIEWS_KEY, JSON.stringify(next)) } catch { /* Storage can be disabled. */ }
      return next
    })
  }, [view])

  const navigate = useCallback((next: ConsoleView) => {
    setView(next)
    setRouteBuildId("")
    const hash = consoleViewHash(next)
    if (window.location.hash !== hash) window.location.hash = hash
  }, [])

  return { view, routeBuildId, recentViews, navigate }
}

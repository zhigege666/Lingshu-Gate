import { createContext, useContext, useEffect, useRef } from "react"

export type PageRefreshHandler = () => void | Promise<void>
export type RegisterPageRefresh = (handler: PageRefreshHandler, busy: boolean) => () => void
export const PageRefreshContext = createContext<RegisterPageRefresh | null>(null)

/** Registers the mounted page's read action. Never remounts editors or polls. */
export function usePageRefresh(handler: PageRefreshHandler, busy = false) {
  const register = useContext(PageRefreshContext)
  const latest = useRef(handler)
  latest.current = handler
  useEffect(() => register?.(() => latest.current(), busy), [register, busy])
}

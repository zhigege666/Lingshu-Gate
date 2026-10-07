import type { ReactNode } from "react"
import { useRemainingViewport } from "@/components/use-remaining-viewport"
import "./build-log-workbench.css"

export function BuildLogWorkbench({ children }: { children: ReactNode }) {
  const viewport = useRemainingViewport(32)
  return <div ref={viewport} className="build-log-workbench">{children}</div>
}

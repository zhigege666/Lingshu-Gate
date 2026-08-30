import { Component, type ErrorInfo, type ReactNode } from "react"
import type { Locale } from "@/i18n"

const ROUTE_BOUNDARY_COPY = {
  "zh-CN": {
    loading: "页面加载中…",
    errorTitle: "页面加载失败",
    errorDescription: "页面资源可能已更新或网络暂时不可用，请刷新后重试。",
    retry: "刷新重试",
  },
  "en-US": {
    loading: "Loading page…",
    errorTitle: "Failed to load page",
    errorDescription: "The page assets may have changed or the network may be temporarily unavailable. Refresh to retry.",
    retry: "Refresh and retry",
  },
} as const

export function routeBoundaryCopy(locale: Locale) {
  return ROUTE_BOUNDARY_COPY[locale]
}

export function RouteLoadingFallback({ locale }: { locale: Locale }) {
  const copy = routeBoundaryCopy(locale)
  return (
    <div role="status" aria-live="polite" className="rounded-xl border bg-card p-6 shadow-sm">
      <div className="mb-4 h-5 w-40 animate-pulse rounded bg-muted" />
      <div className="space-y-3">
        <div className="h-16 animate-pulse rounded-lg bg-muted/70" />
        <div className="h-16 animate-pulse rounded-lg bg-muted/50" />
      </div>
      <span className="sr-only">{copy.loading}</span>
    </div>
  )
}

type RouteErrorBoundaryProps = { locale: Locale; children: ReactNode }
type RouteErrorBoundaryState = { error: Error | null }

export class RouteErrorBoundary extends Component<RouteErrorBoundaryProps, RouteErrorBoundaryState> {
  state: RouteErrorBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): RouteErrorBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Console route failed to render", error, info)
  }

  render() {
    if (!this.state.error) return this.props.children
    const copy = routeBoundaryCopy(this.props.locale)
    return (
      <div role="alert" className="rounded-xl border border-destructive/30 bg-card p-6 shadow-sm">
        <h2 className="font-semibold text-destructive">{copy.errorTitle}</h2>
        <p className="mt-2 text-sm text-muted-foreground">{copy.errorDescription}</p>
        <button
          type="button"
          className="mt-4 rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground"
          onClick={() => window.location.reload()}
        >
          {copy.retry}
        </button>
      </div>
    )
  }
}

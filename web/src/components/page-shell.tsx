import type { ReactNode } from "react"
import { Search, X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { cn } from "@/lib/utils"

type Tone = "default" | "success" | "warning" | "danger"

export function PageHeader({
  title,
  description,
  eyebrow,
  actions,
  stats = [],
}: {
  title: string
  description: string
  eyebrow?: string
  actions?: ReactNode
  stats?: Array<{ label: string; value: ReactNode; tone?: Tone }>
}) {
  return (
    <section className="overflow-hidden rounded-xl border bg-card shadow-sm">
      <div className="h-1 bg-gradient-to-r from-primary via-primary/65 to-transparent" />
      <div className="flex flex-col gap-4 p-4 md:p-5">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            {eyebrow ? <div className="mb-1 text-xs font-semibold uppercase tracking-[0.16em] text-primary">{eyebrow}</div> : null}
            <h2 className="text-lg font-semibold tracking-tight md:text-xl">{title}</h2>
            <p className="mt-1 max-w-3xl text-sm leading-6 text-muted-foreground">{description}</p>
          </div>
          {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
        </div>
        {stats.length ? <div className="flex flex-wrap gap-2 border-t pt-3">{stats.map((stat) => <PageStat key={stat.label} {...stat} />)}</div> : null}
      </div>
    </section>
  )
}

export function PageStat({ label, value, tone = "default" }: { label: string; value: ReactNode; tone?: Tone }) {
  const variant = tone === "success" ? "success" : tone === "warning" ? "warning" : tone === "danger" ? "danger" : "secondary"
  return <div className="flex min-w-0 max-w-full items-center gap-2 rounded-full border bg-background/70 px-3 py-1.5 text-xs"><span className="shrink-0 text-muted-foreground">{label}</span><Badge variant={variant} className="min-w-0 max-w-64"><span className="truncate">{value}</span></Badge></div>
}

export function PageToolbar({
  query,
  onQueryChange,
  placeholder,
  resultCount,
  resultLabel,
  clearLabel,
  children,
  className,
}: {
  query?: string
  onQueryChange?: (value: string) => void
  placeholder?: string
  resultCount?: number
  resultLabel?: string
  clearLabel: string
  children?: ReactNode
  className?: string
}) {
  return (
    <div className={cn("flex flex-col gap-3 rounded-lg border bg-muted/30 p-3 sm:flex-row sm:items-center sm:justify-between", className)}>
      <div className="flex min-w-0 flex-1 items-center gap-3">
        {onQueryChange ? <div className="relative w-full max-w-md">
          <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input value={query || ""} onChange={(event) => onQueryChange(event.target.value)} placeholder={placeholder} className="pl-9 pr-9" />
          {query ? <Button type="button" variant="ghost" size="sm" className="absolute right-1 top-1/2 size-7 -translate-y-1/2 px-0" onClick={() => onQueryChange("")} aria-label={clearLabel}><X /></Button> : null}
        </div> : null}
        {resultCount !== undefined ? <div className="shrink-0 text-xs text-muted-foreground"><span className="font-semibold text-foreground">{resultCount}</span> {resultLabel || ""}</div> : null}
      </div>
      {children ? <div className="flex flex-wrap items-center gap-2">{children}</div> : null}
    </div>
  )
}

export function WorkflowSteps({ steps, ariaLabel }: { steps: Array<{ label: string; state?: "done" | "current" | "next" }>; ariaLabel: string }) {
  return <div className="flex flex-wrap items-center gap-2" aria-label={ariaLabel}>{steps.map((step, index) => <div key={`${step.label}-${index}`} className="flex items-center gap-2">
    {index > 0 ? <span className="hidden text-muted-foreground/50 sm:inline">→</span> : null}
    <div className={cn("flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs", step.state === "current" && "border-primary bg-primary/10 font-medium text-primary", step.state === "done" && "border-success/40 bg-success/10 text-success", (!step.state || step.state === "next") && "bg-muted/40 text-muted-foreground") }>
      <span className="flex size-5 items-center justify-center rounded-full border bg-background font-mono text-[10px]">{index + 1}</span>{step.label}
    </div>
  </div>)}</div>
}

export function InlineEmpty({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return <div className="flex flex-col items-center justify-center rounded-lg border border-dashed px-4 py-10 text-center"><div className="font-medium">{title}</div>{description ? <div className="mt-1 max-w-lg text-sm text-muted-foreground">{description}</div> : null}{action ? <div className="mt-4">{action}</div> : null}</div>
}

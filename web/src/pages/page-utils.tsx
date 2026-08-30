import type { JSX, ReactNode } from "react"
import { Inbox } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty"
import { TableCell, TableRow } from "@/components/ui/table"
import { localizeStatus, type TFunction } from "@/i18n"
import { cn } from "@/lib/utils"

export function codePanelClass(extra = "") {
  return cn("overflow-auto rounded-lg border bg-muted p-3 text-xs text-foreground", extra)
}

/** Empty state rendered as a full-width table row (use inside TableBody). */
export function TableEmptyRow({ colSpan, title, description, icon }: { colSpan: number; title: string; description?: string; icon?: ReactNode }) {
  return (
    <TableRow className="hover:bg-transparent">
      <TableCell colSpan={colSpan} className="h-40">
        <Empty className="border-none p-0">
          <EmptyHeader>
            <EmptyMedia variant="icon">{icon ?? <Inbox />}</EmptyMedia>
            <EmptyTitle>{title}</EmptyTitle>
            {description ? <EmptyDescription>{description}</EmptyDescription> : null}
          </EmptyHeader>
        </Empty>
      </TableCell>
    </TableRow>
  )
}

export function statusBadge(status?: string | boolean, t?: TFunction) {
  const value = String(status ?? "unknown")
  let variant: "success" | "warning" | "danger" | "outline" | "secondary" = "secondary"
  if (["ok", "true", "running"].includes(value)) variant = "success"
  else if (["starting", "external", "warning"].includes(value)) variant = "warning"
  else if (["failed", "false", "error"].includes(value)) variant = "danger"
  else variant = "outline"
  const label = t ? localizeStatus(t, value) : value
  return <Badge variant={variant}>{label}</Badge>
}

export function Metric({ title, value, hint, badge, icon }: { title: string; value: string; hint?: string; badge?: JSX.Element; icon?: ReactNode }) {
  return (
    <Card className="transition-shadow hover:shadow-md">
      <CardContent className="flex items-start justify-between gap-3 p-5">
        <div className="min-w-0">
          <div className="text-sm font-medium text-muted-foreground">{title}</div>
          <div className="mt-1.5 truncate text-2xl font-semibold tracking-tight">{value}</div>
          {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
        </div>
        <div className="flex shrink-0 flex-col items-end gap-2">
          {icon && <div className="flex size-9 items-center justify-center rounded-lg bg-primary/10 text-primary">{icon}</div>}
          {badge}
        </div>
      </CardContent>
    </Card>
  )
}

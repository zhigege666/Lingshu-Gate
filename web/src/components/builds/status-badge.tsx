import { Badge, type BadgeProps } from "@/components/ui/badge"
import { localizeStatus, type TFunction } from "@/i18n"

export function StatusBadge({ value, t }: { value: string; t?: TFunction }) {
  const variant: BadgeProps["variant"] =
    value === "success" || value === "info"
      ? "success"
      : value === "failed" || value === "error"
        ? "danger"
        : value === "unsupported" || value === "warning" || value === "queued" || value === "running" || value === "cancel_requested" || value === "cancelled"
          ? "warning"
          : "outline"
  return <Badge variant={variant}>{t ? localizeStatus(t, value) : value}</Badge>
}

import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function prettyJson(value: unknown) {
  return JSON.stringify(value, null, 2)
}

/**
 * Render an ISO/UTC timestamp as China Standard Time (UTC+8), formatted as
 * "YYYY-MM-DD HH:mm:ss" ("sv-SE" locale yields the ISO-like layout).
 * Non-date strings are returned unchanged; empty values become "-".
 */
export function formatDateTime(value: string | number | null | undefined) {
  if (value === null || value === undefined || value === "") return "-"
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return date.toLocaleString("sv-SE", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" })
}

/** Human-readable byte size, e.g. 1536 -> "1.5 KB". */
export function formatBytes(value: number) {
  if (!Number.isFinite(value) || value <= 0) return "0 B"
  const units = ["B", "KB", "MB", "GB", "TB"]
  let next = value
  let index = 0
  while (next >= 1024 && index < units.length - 1) {
    next /= 1024
    index += 1
  }
  return `${next.toFixed(index === 0 ? 0 : 1)} ${units[index]}`
}

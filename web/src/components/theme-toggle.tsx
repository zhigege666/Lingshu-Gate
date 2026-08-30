import { Moon, Sun } from "lucide-react"
import { Switch } from "@/components/ui/switch"
import type { ThemeMode } from "@/theme"

export function ThemeToggle({ theme, onChange }: { theme: ThemeMode; onChange: (theme: ThemeMode) => void }) {
  const checked = theme === "dark"
  return (
    <div className="flex items-center gap-2 rounded-md border bg-card px-3 py-2 text-sm text-foreground">
      <Sun className="size-4" />
      <Switch checked={checked} onCheckedChange={(next) => onChange(next ? "dark" : "light")} aria-label="Toggle theme" />
      <Moon className="size-4" />
    </div>
  )
}

import { Languages } from "lucide-react"
import { locales, translate, type Locale } from "@/i18n"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

export function LanguageSwitcher({ locale, onChange }: { locale: Locale; onChange: (locale: Locale) => void }) {
  return (
    <div className="flex min-w-[150px] items-center gap-2">
      <Languages className="size-4 text-muted-foreground" />
      <Select value={locale} onValueChange={(value) => onChange(value as Locale)}>
        <SelectTrigger aria-label={translate(locale, "language")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {locales.map((item) => (
            <SelectItem key={item.value} value={item.value}>{item.label}</SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

import { useId } from "react"
import { Badge } from "@/components/ui/badge"
import { Switch } from "@/components/ui/switch"
import { getTokenScopeGroups } from "@/features/personal-token-scopes"
import type { Locale } from "@/i18n"
import "@/features/personal-token-scopes.css"

export function TokenScopeSelector({ options, selected, locale, disabled, onChange }: { options: string[]; selected: string[]; locale: Locale; disabled: boolean; onChange: (scopes: string[]) => void }) {
  const descriptionId = useId()
  return <div className="token-scope-selector">
    {getTokenScopeGroups(options, locale).map(group => <fieldset key={group.name} disabled={disabled} className="min-w-0 rounded-lg border p-3 pt-2">
      <legend className="px-1 text-sm font-medium">{group.name}</legend>
      <div className="token-scope-options">
        {group.scopes.map(scope => <label key={scope.code} className="token-scope-option">
          <span className="min-w-0"><span className="block break-words text-sm font-medium">{scope.name}</span><code className="block break-all text-xs text-muted-foreground">{scope.code}</code><span id={`${descriptionId}-${scope.code}`} className="mt-1 block break-words text-xs text-muted-foreground">{scope.description}</span></span>
          <Switch disabled={disabled} aria-label={scope.name} aria-describedby={`${descriptionId}-${scope.code}`} checked={selected.includes(scope.code)} onCheckedChange={checked => onChange(checked ? [...new Set([...selected, scope.code])] : selected.filter(code => code !== scope.code))} />
        </label>)}
      </div>
    </fieldset>)}
  </div>
}

export function TokenScopeSummary({ scopes, locale }: { scopes: string[]; locale: Locale }) {
  return <div className="flex max-w-lg flex-col gap-2">
    {getTokenScopeGroups(scopes, locale).map(group => <div key={group.name} className="flex flex-col gap-1">
      <span className="text-xs text-muted-foreground">{group.name}</span>
      <div className="flex flex-wrap gap-1">{group.scopes.map(scope => <Badge key={scope.code} variant="outline" title={`${scope.code} · ${scope.description}`}>{scope.name}</Badge>)}</div>
    </div>)}
  </div>
}

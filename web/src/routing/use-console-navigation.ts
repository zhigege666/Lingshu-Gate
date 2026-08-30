import { useMemo } from "react"
import type { Locale, TFunction } from "@/i18n"
import { navigationCopy } from "@/i18n/namespaces/navigation"
import {
  CONSOLE_ROUTES,
  CONSOLE_SECTION_ORDER,
  type ConsoleRouteDefinition,
  type ConsoleView,
} from "@/routing/console-routes"

export type ConsoleNavItem = Omit<ConsoleRouteDefinition, "label"> & { label: string }

export function useConsoleNavigation(options: {
  locale: Locale
  t: TFunction
  can: (permission: string) => boolean
  authenticated: boolean
}) {
  const { locale, t, can, authenticated } = options

  return useMemo(() => {
    const copy = navigationCopy(locale)
    const nav = CONSOLE_ROUTES.map<ConsoleNavItem>((route) => ({
      ...route,
      label: route.label.source === "messages" ? t(route.label.key) : copy.labels[route.label.key],
    }))
    const navById = Object.fromEntries(nav.map((item) => [item.id, item])) as Record<ConsoleView, ConsoleNavItem>
    const canAccessView = (item: ConsoleNavItem | undefined) => Boolean(
      item && can(item.permission) && (!item.requiresAuthentication || authenticated),
    )
    const navGroups = CONSOLE_SECTION_ORDER.map((section) => ({
      title: copy.sections[section],
      items: nav.filter((item) => item.section === section && canAccessView(item)).map((item) => item.id),
    })).filter((group) => group.items.length > 0)

    return { nav, navById, navGroups, canAccessView }
  }, [authenticated, can, locale, t])
}

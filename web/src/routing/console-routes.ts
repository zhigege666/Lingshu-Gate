import {
  Activity,
  Braces,
  FileKey2,
  Fingerprint,
  Gauge,
  HardDrive,
  KeyRound,
  Play,
  Rocket,
  ScrollText,
  Server,
  Shield,
  ShieldCheck,
  UploadCloud,
  UserRoundCog,
  Wrench,
  type LucideIcon,
} from "lucide-react"
import type { MessageKey } from "@/i18n"
import type { NavigationLabelKey, NavigationSectionKey } from "@/i18n/namespaces/navigation"

export const CONSOLE_VIEW_IDS = [
  "dashboard",
  "configs",
  "servers",
  "builds",
  "credentials",
  "logs",
  "runtimeCache",
  "uploads",
  "accessUsers",
  "accessRoles",
  "accessGrants",
  "toolClassifications",
  "personalTokens",
  "downstreamCredentials",
  "invocationAudit",
  "diagnostics",
  "tools",
  "invoke",
] as const

export type ConsoleView = (typeof CONSOLE_VIEW_IDS)[number]
export type ConsoleRouteLabel =
  | { source: "messages"; key: MessageKey }
  | { source: "navigation"; key: NavigationLabelKey }

export type ConsoleRouteDefinition = {
  id: ConsoleView
  label: ConsoleRouteLabel
  icon: LucideIcon
  permission: string
  section: NavigationSectionKey
  requiresAuthentication?: boolean
}

const VIEW_SET = new Set<string>(CONSOLE_VIEW_IDS)

export function isConsoleView(value: string): value is ConsoleView {
  return VIEW_SET.has(value)
}

export const CONSOLE_ROUTES = [
  { id: "dashboard", label: { source: "messages", key: "dashboard" }, icon: Gauge, permission: "console.view", section: "overview" },
  { id: "configs", label: { source: "messages", key: "configs" }, icon: Braces, permission: "operations.manage", section: "manage" },
  { id: "servers", label: { source: "messages", key: "servers" }, icon: Server, permission: "operations.manage", section: "manage" },
  { id: "builds", label: { source: "messages", key: "builds" }, icon: Rocket, permission: "operations.manage", section: "manage" },
  { id: "credentials", label: { source: "messages", key: "credentials" }, icon: KeyRound, permission: "operations.manage", section: "manage" },
  { id: "tools", label: { source: "messages", key: "tools" }, icon: Wrench, permission: "tools.read", section: "tools" },
  { id: "invoke", label: { source: "messages", key: "invoke" }, icon: Play, permission: "tools.read", section: "tools" },
  { id: "logs", label: { source: "messages", key: "logs" }, icon: ScrollText, permission: "operations.manage", section: "ops" },
  { id: "runtimeCache", label: { source: "messages", key: "runtimeCache" }, icon: HardDrive, permission: "operations.manage", section: "ops" },
  { id: "uploads", label: { source: "messages", key: "uploads" }, icon: UploadCloud, permission: "operations.manage", section: "ops" },
  { id: "diagnostics", label: { source: "messages", key: "diagnostics" }, icon: Activity, permission: "operations.manage", section: "ops" },
  { id: "accessUsers", label: { source: "navigation", key: "users" }, icon: UserRoundCog, permission: "users.manage", section: "access" },
  { id: "accessRoles", label: { source: "navigation", key: "roles" }, icon: Shield, permission: "roles.manage", section: "access" },
  { id: "toolClassifications", label: { source: "navigation", key: "classifications" }, icon: FileKey2, permission: "classifications.manage", section: "access" },
  { id: "accessGrants", label: { source: "navigation", key: "grants" }, icon: ShieldCheck, permission: "grants.manage", section: "access" },
  { id: "invocationAudit", label: { source: "navigation", key: "audit" }, icon: ScrollText, permission: "audit.read", section: "access" },
  { id: "personalTokens", label: { source: "navigation", key: "tokens" }, icon: KeyRound, permission: "credentials.manage.self", section: "access", requiresAuthentication: true },
  { id: "downstreamCredentials", label: { source: "navigation", key: "downstream" }, icon: Fingerprint, permission: "credentials.manage.self", section: "access", requiresAuthentication: true },
] as const satisfies readonly ConsoleRouteDefinition[]

export const CONSOLE_SECTION_ORDER: readonly NavigationSectionKey[] = ["overview", "manage", "tools", "ops", "access"]

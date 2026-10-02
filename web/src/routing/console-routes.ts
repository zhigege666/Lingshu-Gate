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
  "myServers",
  "myConnections",
  "connectionInfrastructure",
  "myInvocations",
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
  hidden?: boolean
  requiresAuthentication?: boolean
}

const VIEW_SET = new Set<string>(CONSOLE_VIEW_IDS)

export function isConsoleView(value: string): value is ConsoleView {
  return VIEW_SET.has(value)
}

export const CONSOLE_ROUTES = [
  { id: "dashboard", label: { source: "navigation", key: "overview" }, icon: Gauge, permission: "console.view", section: "overview" },
  { id: "servers", label: { source: "navigation", key: "serviceOperations" }, icon: Server, permission: "operations.manage", section: "overview" },
  { id: "myServers", label: { source: "navigation", key: "myServers" }, icon: Server, permission: "tools.read", section: "overview" },
  { id: "configs", label: { source: "navigation", key: "serviceConfigurations" }, icon: Braces, permission: "operations.manage", section: "overview" },
  { id: "builds", label: { source: "navigation", key: "projectDelivery" }, icon: Rocket, permission: "operations.manage", section: "overview" },
  { id: "uploads", hidden: true, label: { source: "messages", key: "uploads" }, icon: UploadCloud, permission: "operations.manage", section: "overview" },
  { id: "tools", label: { source: "navigation", key: "toolCatalog" }, icon: Wrench, permission: "tools.read", section: "tools" },
  { id: "invoke", label: { source: "navigation", key: "toolTesting" }, icon: Play, permission: "tools.read", section: "tools" },
  { id: "toolClassifications", label: { source: "navigation", key: "classifications" }, icon: FileKey2, permission: "classifications.manage", section: "tools" },
  { id: "logs", label: { source: "messages", key: "logs" }, icon: ScrollText, permission: "operations.manage", section: "ops" },
  { id: "invocationAudit", label: { source: "navigation", key: "audit" }, icon: ScrollText, permission: "audit.read", section: "ops" },
  { id: "diagnostics", label: { source: "navigation", key: "healthChecks" }, icon: Activity, permission: "operations.manage", section: "ops" },
  { id: "accessUsers", label: { source: "navigation", key: "users" }, icon: UserRoundCog, permission: "users.manage", section: "access" },
  { id: "accessRoles", label: { source: "navigation", key: "roles" }, icon: Shield, permission: "roles.manage", section: "access" },
  { id: "accessGrants", label: { source: "navigation", key: "grants" }, icon: ShieldCheck, permission: "grants.manage", section: "access" },
  { id: "credentials", label: { source: "navigation", key: "sharedCredentials" }, icon: KeyRound, permission: "credentials.manage.system", section: "access" },
  { id: "runtimeCache", label: { source: "navigation", key: "maintenance" }, icon: HardDrive, permission: "operations.manage", section: "access" },
  { id: "connectionInfrastructure", label: { source: "navigation", key: "connectionInfrastructure" }, icon: Server, permission: "external_connections.manage", section: "access" },
  { id: "myConnections", label: { source: "navigation", key: "myConnections" }, icon: Fingerprint, permission: "credentials.manage.self", section: "personal", requiresAuthentication: true },
  { id: "myInvocations", label: { source: "navigation", key: "myInvocations" }, icon: ScrollText, permission: "console.view", section: "personal", requiresAuthentication: true },
  { id: "personalTokens", label: { source: "navigation", key: "tokens" }, icon: KeyRound, permission: "credentials.manage.self", section: "personal", requiresAuthentication: true },
  { id: "downstreamCredentials", label: { source: "navigation", key: "downstream" }, icon: Fingerprint, permission: "credentials.manage.self", section: "personal", requiresAuthentication: true },
] as const satisfies readonly ConsoleRouteDefinition[]

export const CONSOLE_SECTION_ORDER: readonly NavigationSectionKey[] = ["overview", "tools", "ops", "access", "personal"]

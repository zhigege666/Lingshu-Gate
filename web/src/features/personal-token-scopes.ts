import type { AuthUser } from "@/components/auth-gate"
import { presentControlPermission } from "@/features/access-roles/presentation"
import type { Locale } from "@/i18n"

type TokenScopeIdentity = Pick<AuthUser, "permissions" | "auth_type" | "scopes">

// 仅控制展示顺序，不作为权限白名单；可授予范围由当前身份提供。
const SCOPE_ORDER = [
  "tools.read", "tools.invoke", "audit.read", "console.view",
  "operations.manage", "classifications.manage", "credentials.manage.self",
  "credentials.manage.all", "users.manage", "roles.manage", "grants.manage",
]

function compareScopes(a: string, b: string): number {
  const left = SCOPE_ORDER.indexOf(a)
  const right = SCOPE_ORDER.indexOf(b)
  if (left === -1 || right === -1) return left === right ? a.localeCompare(b) : left === -1 ? 1 : -1
  return left - right
}

export function getAvailableTokenScopes(user: TokenScopeIdentity): string[] {
  // 与后端保持一致：Token 或 OAuth 登录均不能超出当前令牌的 scope。
  const tokenLimited = ["token", "oauth"].includes(user.auth_type) && !user.scopes.includes("*")
  return [...new Set(user.permissions)]
    .filter((scope) => scope !== "*" && (!tokenLimited || user.scopes.includes(scope)))
    .sort(compareScopes)
}

export function getTokenScopeOptions(availableScopes: string[], existingScopes: string[] = []): string[] {
  // 编辑时保留已有范围，避免尚未识别或已失去授予权限的 scope 被静默移除。
  return [...new Set([...availableScopes, ...existingScopes])].sort(compareScopes)
}

export function isTokenScopeAdministrator(user: Pick<AuthUser, "role" | "roles">): boolean {
  return user.role === "admin" || user.roles.includes("admin")
}

export function getDefaultTokenScopes(availableScopes: string[], user: Pick<AuthUser, "role" | "roles">): string[] {
  // 管理员新建时选择全部当前可授予权限，含新增权限；不使用 * 扩大已有 Token。
  if (isTokenScopeAdministrator(user)) return [...availableScopes]
  // 其他账号没有只读权限时等待用户选择，不默认授予写入或管理权限。
  return availableScopes.includes("tools.read") ? ["tools.read"] : []
}

export function getTokenScopeGroups(scopes: string[], locale: Locale) {
  const groups = new Map<string, { code: string; name: string; description: string }[]>()
  for (const code of new Set(scopes)) {
    const { group, name, description } = presentControlPermission({ code }, locale)
    const items = groups.get(group) || []
    items.push({ code, name, description })
    groups.set(group, items)
  }
  // 未识别的新增或历史权限仍可见，不因展示分组而改变可选或已保存范围。
  return [...groups].map(([name, items]) => ({ name, scopes: items }))
}

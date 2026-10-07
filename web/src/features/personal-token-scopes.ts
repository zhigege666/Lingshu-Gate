import type { AuthUser } from "@/components/auth-gate"

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
  // 与后端保持一致：Token 登录不能超出父 Token 的 scope，即使所属账号是管理员。
  const tokenLimited = user.auth_type === "token" && !user.scopes.includes("*")
  return [...new Set(user.permissions)]
    .filter((scope) => scope !== "*" && (!tokenLimited || user.scopes.includes(scope)))
    .sort(compareScopes)
}

export function getTokenScopeOptions(availableScopes: string[], existingScopes: string[] = []): string[] {
  // 编辑时保留已有范围，避免尚未识别或已失去授予权限的 scope 被静默移除。
  return [...new Set([...availableScopes, ...existingScopes])].sort(compareScopes)
}

export function getDefaultTokenScopes(availableScopes: string[]): string[] {
  // 没有只读权限时等待用户选择，不自动勾选写入或管理权限。
  return availableScopes.includes("tools.read") ? ["tools.read"] : []
}

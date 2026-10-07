/** One unresolved create key per authenticated user and Gate origin; never a draft. */
export type GroupCreationScope = { userId: string; origin: string }

const storageKey = (scope: GroupCreationScope) => `gate-mcp-group-create-pending:${JSON.stringify([scope.origin, scope.userId])}`
const validKey = (key: string) => /^[a-f0-9]{32}$/.test(key)

export function readGroupCreation(scope: GroupCreationScope): string | null {
  try {
    const key = window.sessionStorage.getItem(storageKey(scope))
    return key && validKey(key) ? key : null
  } catch { return null }
}

export function rememberGroupCreation(scope: GroupCreationScope, key: string): boolean {
  if (!validKey(key)) return false
  try { window.sessionStorage.setItem(storageKey(scope), key); return true }
  catch { return false }
}

export function forgetGroupCreation(scope: GroupCreationScope, key: string): boolean {
  try {
    // A late result cannot clear a newer attempt's recovery key.
    if (window.sessionStorage.getItem(storageKey(scope)) === key) window.sessionStorage.removeItem(storageKey(scope))
    return true
  } catch { return false }
}

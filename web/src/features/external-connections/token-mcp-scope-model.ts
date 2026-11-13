import type { McpServerPolicy, OAuthTool } from "./oauth-api"
import type { McpAuthorizationMode } from "./mcp-authorization-editor"

export type TokenMcpChoice = "none" | "read" | "write" | "selected"
export type TokenMcpDraft = { selected: string[]; policies: McpServerPolicy[]; modes: Record<string, McpAuthorizationMode> }
export type TokenMcpSnapshot = Pick<TokenMcpDraft, "selected" | "policies">

export function tokenMcpChoice(server: string, draft: TokenMcpDraft): TokenMcpChoice {
  const policy = draft.policies.find(item => item.server_id === server)
  return policy ? policy.access : draft.modes[server] === "selected" ? "selected" : "none"
}

export function tokenMcpTools(server: string, selected: readonly string[], tools: readonly OAuthTool[]): string[] {
  const ids = new Set(tools.filter(tool => tool.server_id === server).map(tool => tool.id))
  return selected.filter(id => ids.has(id))
}

/** Presentation-only modes with zero tools do not invent a persisted grant. */
export function tokenMcpSignature(server: string, snapshot: TokenMcpSnapshot, tools: readonly OAuthTool[]): string {
  const policy = snapshot.policies.find(item => item.server_id === server)
  return JSON.stringify({ policy: policy ? [policy.mode, policy.access, policy.server_binding ?? null] : null, tools: tokenMcpTools(server, snapshot.selected, tools).sort() })
}

/** A row owns only its MCP's IDs, including retained unavailable selections. */
export function mergeTokenMcpTools(server: string, selected: readonly string[], next: readonly string[], tools: readonly OAuthTool[]): string[] {
  const ids = new Set(tools.filter(tool => tool.server_id === server).map(tool => tool.id))
  return [...selected.filter(id => !ids.has(id)), ...new Set(next.filter(id => ids.has(id)))]
}

/** Access edits preserve a saved lifecycle binding. Reconfirmation is separate. */
export function changeTokenMcpChoice(server: string, choice: TokenMcpChoice, draft: TokenMcpDraft, tools: readonly OAuthTool[], binding?: string): TokenMcpDraft {
  const existing = draft.policies.find(item => item.server_id === server)
  const continuous = choice === "read" || choice === "write"
  const policy: McpServerPolicy | undefined = continuous
    ? existing ? { ...existing, access: choice } : { server_id: server, server_binding: binding, mode: "continuous", access: choice }
    : undefined
  return {
    selected: choice === "selected" ? [...draft.selected] : mergeTokenMcpTools(server, draft.selected, [], tools),
    policies: [...draft.policies.filter(item => item.server_id !== server), ...(policy ? [policy] : [])],
    modes: { ...draft.modes, [server]: continuous ? "continuous" : choice },
  }
}

/** Refresh cannot erase an unavailable saved or unsaved selection's identity. */
export function retainTokenTools(previous: readonly OAuthTool[], current: readonly OAuthTool[], saved: readonly OAuthTool[], keepIds: readonly string[]): OAuthTool[] {
  const keep = new Set(keepIds)
  const result = new Map<string, OAuthTool>()
  for (const tool of [...previous, ...saved]) if (keep.has(tool.id)) result.set(tool.id, { ...tool, currently_authorized: false })
  for (const tool of current) result.set(tool.id, tool)
  return [...result.values()]
}

/** Match the token API's functional-scope checks without silently narrowing a draft. */
export function tokenMcpPermissionConflicts(snapshot: TokenMcpSnapshot, tools: readonly OAuthTool[], scopes: readonly string[]) {
  if (scopes.includes("*")) return []
  const selected = new Set(snapshot.selected), conflicts = new Map<string, Set<string>>()
  for (const item of [...snapshot.policies, ...tools.filter(tool => selected.has(tool.id))]) {
    const required = item.access === "write" ? "tools.invoke" : "tools.read"
    if (!scopes.includes(required)) {
      const missing = conflicts.get(item.server_id) || new Set<string>()
      missing.add(required); conflicts.set(item.server_id, missing)
    }
  }
  return [...conflicts].map(([server_id, required]) => ({ server_id, required: [...required] }))
}

/** Completes an explicit MCP choice or permission action; never invents owner access. */
export function completeTokenMcpPermissions(snapshot: TokenMcpSnapshot, tools: readonly OAuthTool[], scopes: readonly string[], available: readonly string[]): string[] | null {
  const missing = [...new Set(tokenMcpPermissionConflicts(snapshot, tools, scopes).flatMap(item => item.required))]
  if (missing.some(scope => !available.includes(scope))) return null
  return [...new Set([...scopes, ...missing])]
}

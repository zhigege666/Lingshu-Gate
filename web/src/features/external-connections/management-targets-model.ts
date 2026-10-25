import { OAuthRequestError } from "./oauth-api"

export type ManagementTargetRow = { id: string; actions: string[] }
export const managementActions = ["test", "create", "update", "delete", "revoke_trust", "restore_trust", "credential.read", "credential.create", "credential.update", "credential.delete"] as const
export const newManagementTarget = (): ManagementTargetRow => ({ id: "", actions: ["create"] })
export function managementTargetRows(targets: Record<string, string[]>): ManagementTargetRow[] {
  return Object.entries(targets).sort(([a], [b]) => a.localeCompare(b)).map(([id, actions]) => ({ id, actions: [...actions] }))
}
export function managementTargets(rows: ManagementTargetRow[], allowEmpty = false): Record<string, string[]> {
  if (rows.length > 1000 || (!allowEmpty && !rows.length)) throw new OAuthRequestError("invalid_management_targets")
  const targets: Record<string, string[]> = Object.create(null)
  for (const row of rows) {
    if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(row.id) || Object.prototype.hasOwnProperty.call(targets, row.id)
      || !row.actions.length || row.actions.some(action => !(managementActions as readonly string[]).includes(action))
      || new Set(row.actions).size !== row.actions.length) throw new OAuthRequestError("invalid_management_targets")
    targets[row.id] = [...row.actions].sort()
  }
  return targets
}

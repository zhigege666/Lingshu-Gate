import type { AccessRole, AccessRoleSaveRequest, PermissionType, PermissionTypeSaveRequest } from "@/api/client"

export type AccessItem = AccessRole | PermissionType
export type AccessFilters = {
  query: string
  source: "all" | "system" | "custom"
  status: "all" | "enabled" | "disabled"
  level: "all" | PermissionType["base_level"]
}

export const emptyAccessFilters: AccessFilters = { query: "", source: "all", status: "all", level: "all" }

export function filterAccessItems<T extends AccessItem>(items: T[], filters: AccessFilters): T[] {
  const query = filters.query.trim().toLocaleLowerCase()
  return items.filter(item =>
    (!query || `${item.name} ${item.code}`.toLocaleLowerCase().includes(query)) &&
    (filters.source === "all" || item.is_system === (filters.source === "system")) &&
    (filters.status === "all" || item.enabled === (filters.status === "enabled")) &&
    (!("base_level" in item) || filters.level === "all" || item.base_level === filters.level),
  )
}

export function rolePayload(role: AccessRole): AccessRoleSaveRequest {
  return { code: role.code, name: role.name, description: role.description, permissions: [...role.permissions], enabled: role.enabled }
}

export function permissionTypePayload(item: PermissionType): PermissionTypeSaveRequest {
  return { code: item.code, name: item.name, description: item.description, base_level: item.base_level, enabled: item.enabled }
}

export function copyRolePayload(role: AccessRole, suffix: string): AccessRoleSaveRequest {
  return { ...rolePayload(role), code: "", name: `${role.name}${suffix}` }
}

export function copyPermissionTypePayload(item: PermissionType, suffix: string): PermissionTypeSaveRequest {
  return { ...permissionTypePayload(item), code: "", name: `${item.name}${suffix}` }
}

export function canDeleteAccessItem(item: AccessItem): boolean {
  return !item.is_system && ("member_count" in item ? item.member_count === 0 : item.reference_count === 0)
}

// Match the backend's normalization so duplicate checks use the stored code.
export function normalizeAccessCode(code: string): string {
  return code.trim().toLowerCase().replace(/[^a-z0-9_.-]+/g, "-").replace(/^[-.]+|[-.]+$/g, "")
}

type AccessDraft = AccessRoleSaveRequest | PermissionTypeSaveRequest

/** Compare editable values; toggling a permission off and on is not a new draft. */
export function accessDraftChanged(current: AccessDraft, original: AccessDraft): boolean {
  const fingerprint = (draft: AccessDraft) => JSON.stringify("permissions" in draft ? { ...draft, permissions: [...draft.permissions].sort() } : draft)
  return fingerprint(current) !== fingerprint(original)
}

/** Own the submitted permissions array so later state updates cannot change it. */
export function roleSaveSnapshot(draft: AccessRoleSaveRequest): AccessRoleSaveRequest {
  return { ...draft, code: normalizeAccessCode(draft.code), name: draft.name.trim(), permissions: [...draft.permissions] }
}

export function accessIdentityErrors(draft: AccessDraft, items: AccessItem[], editingId?: string): { code?: "required" | "duplicate"; name?: "required" } {
  const code = normalizeAccessCode(draft.code)
  return {
    code: !code ? "required" : items.some(item => item.code === code && item.id !== editingId) ? "duplicate" : undefined,
    name: draft.name.trim() ? undefined : "required",
  }
}

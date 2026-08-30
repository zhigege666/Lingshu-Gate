import { queryString, request } from "@/api/http"

export type Credential = {
  id: string
  name: string
  description: string
  value_masked: string
  created_at: string
  updated_at: string
}

export type CredentialSaveRequest = { name: string; value?: string | null; description?: string }

export type AccessUser = {
  id: string
  username: string
  display_name: string
  role: string
  roles: string[]
  status: "pending" | "active" | "disabled"
  must_change_password: boolean
  created_at: string
  updated_at: string
}

export type AccessUserCreateRequest = {
  username: string
  display_name: string
  password: string
  status: AccessUser["status"]
  roles: string[]
  must_change_password: boolean
}

export type ControlPermission = { id: string; code: string; name: string; description: string; is_system: boolean }

export type AccessRole = {
  id: string
  code: string
  name: string
  description: string
  is_system: boolean
  enabled: boolean
  member_count: number
  permissions: string[]
  created_at: string
  updated_at: string
}

export type AccessRoleSaveRequest = { code: string; name: string; description: string; permissions: string[]; enabled: boolean }

export type PermissionType = {
  id: string
  code: string
  name: string
  base_level: "none" | "read" | "write"
  description: string
  is_system: boolean
  enabled: boolean
  reference_count: number
  created_at: string
  updated_at: string
}

export type PermissionTypeSaveRequest = {
  code: string
  name: string
  base_level: "none" | "read" | "write"
  description: string
  enabled: boolean
}

export type ResourceGrant = {
  id: string
  subject_type: "user" | "role"
  subject_id: string
  server_id: string
  tool_id?: string | null
  permission_type_id: string
  permission_type_code: string
  permission_type_name: string
  base_level: "none" | "read" | "write"
  expires_at?: string | null
  created_by: string
  created_at: string
  updated_at: string
}

export type ResourceGrantSaveRequest = {
  subject_type: "user" | "role"
  subject_id: string
  server_id: string
  tool_id?: string | null
  permission_type_code: string
  expires_at?: string | null
}

export type AccessResource = {
  server_id: string
  tool_id: string
  tool_name: string
  classification: "read" | "write" | "unknown"
  classification_status: "pending" | "published" | "stale" | "missing"
}

export type ToolClassification = {
  id: string
  server_id: string
  tool_id: string
  tool_name: string
  fingerprint: string
  suggested_access: "read" | "write" | "unknown"
  effective_access: "read" | "write" | "unknown"
  status: "pending" | "published" | "stale"
  confidence: number
  source: string
  destructive: boolean
  idempotent: boolean
  open_world: boolean
  evidence: Record<string, unknown>
  reviewed_by?: string | null
  reviewed_at?: string | null
  created_at: string
  updated_at: string
}

export type ToolClassificationConfirmResponse = {
  confirmed: ToolClassification[]
  skipped: Array<{ server_id: string; tool_id: string; reason: "unknown" | "published" | string }>
  confirmed_count: number
  skipped_count: number
  total_count: number
}

export type InvocationAudit = {
  id: string
  correlation_id: string
  user_id: string
  username: string
  auth_type: string
  api_token_id?: string | null
  server_id: string
  tool_id: string
  tool_access: string
  required_access: string
  granted_access: string
  decision: "allow" | "deny"
  reason: string
  outcome: "success" | "error" | "not_invoked"
  duration_ms?: number | null
  payload: Record<string, unknown>
  created_at: string
}

export type InvocationAuditFilterOptions = {
  users: Array<{ id: string; username: string }>
  servers: string[]
  tools: Array<{ server_id: string; tool_id: string }>
}

export type PersonalToken = {
  id: string
  name: string
  username?: string | null
  token_prefix: string
  scopes: string[]
  expires_at?: string | null
  revoked_at?: string | null
  last_used_at?: string | null
  created_at: string
}

export type PersonalTokenCreateResponse = PersonalToken & { token: string }

export type UserDownstreamCredential = {
  server_id: string
  server_name: string
  transport_type: string
  id: string
  name: string
  description: string
  required: boolean
  injection: { type: "http_header"; name: string; template: string }
  configured: boolean
  created_at?: string | null
  updated_at?: string | null
  last_used_at?: string | null
}

export const identityAccessApi = {
  credentials: () => request<Credential[]>("/v1/credentials"),
  createCredential: (credential: CredentialSaveRequest) => request<Credential>("/v1/credentials", { method: "POST", body: JSON.stringify(credential) }),
  updateCredential: (credentialId: string, credential: CredentialSaveRequest) => request<Credential>(`/v1/credentials/${encodeURIComponent(credentialId)}`, { method: "PUT", body: JSON.stringify(credential) }),
  deleteCredential: (credentialId: string) => request<Credential>(`/v1/credentials/${encodeURIComponent(credentialId)}`, { method: "DELETE" }),
  accessUsers: () => request<{ users: AccessUser[] }>("/v1/access/users"),
  createAccessUser: (payload: AccessUserCreateRequest) => request<AccessUser>("/v1/access/users", { method: "POST", body: JSON.stringify(payload) }),
  updateAccessUser: (userId: string, payload: { display_name?: string; status?: AccessUser["status"]; roles?: string[] }) => request<AccessUser>(`/v1/access/users/${encodeURIComponent(userId)}`, { method: "PATCH", body: JSON.stringify(payload) }),
  controlPermissions: () => request<{ permissions: ControlPermission[] }>("/v1/access/control-permissions"),
  accessRoles: () => request<{ roles: AccessRole[] }>("/v1/access/roles"),
  createAccessRole: (payload: AccessRoleSaveRequest) => request<AccessRole>("/v1/access/roles", { method: "POST", body: JSON.stringify(payload) }),
  updateAccessRole: (roleId: string, payload: AccessRoleSaveRequest) => request<AccessRole>(`/v1/access/roles/${encodeURIComponent(roleId)}`, { method: "PUT", body: JSON.stringify(payload) }),
  deleteAccessRole: (roleId: string) => request<{ message: string }>(`/v1/access/roles/${encodeURIComponent(roleId)}`, { method: "DELETE" }),
  permissionTypes: () => request<{ permission_types: PermissionType[] }>("/v1/access/permission-types"),
  createPermissionType: (payload: PermissionTypeSaveRequest) => request<PermissionType>("/v1/access/permission-types", { method: "POST", body: JSON.stringify(payload) }),
  updatePermissionType: (permissionTypeId: string, payload: PermissionTypeSaveRequest) => request<PermissionType>(`/v1/access/permission-types/${encodeURIComponent(permissionTypeId)}`, { method: "PUT", body: JSON.stringify(payload) }),
  deletePermissionType: (permissionTypeId: string) => request<{ message: string }>(`/v1/access/permission-types/${encodeURIComponent(permissionTypeId)}`, { method: "DELETE" }),
  resourceGrants: (filters: { server_id?: string; subject_type?: string; subject_id?: string } = {}) => request<{ grants: ResourceGrant[] }>(`/v1/access/grants${queryString(filters)}`),
  accessSubjects: () => request<{ users: AccessUser[]; roles: AccessRole[] }>("/v1/access/subjects"),
  accessResources: () => request<{ resources: AccessResource[] }>("/v1/access/resources"),
  saveResourceGrant: (payload: ResourceGrantSaveRequest) => request<ResourceGrant>("/v1/access/grants", { method: "PUT", body: JSON.stringify(payload) }),
  deleteResourceGrant: (grantId: string) => request<{ message: string }>(`/v1/access/grants/${encodeURIComponent(grantId)}`, { method: "DELETE" }),
  toolClassifications: (filters: { server_id?: string; status?: string } = {}) => request<{ classifications: ToolClassification[] }>(`/v1/access/tool-classifications${queryString(filters)}`),
  analyzeToolClassifications: (payload: { server_id?: string | null }) => request<{ classifications: ToolClassification[] }>("/v1/access/tool-classifications/analyze", { method: "POST", body: JSON.stringify(payload) }),
  updateToolClassification: (serverId: string, toolId: string, payload: { access: "read" | "write" | "unknown"; destructive: boolean; idempotent: boolean; note?: string }) => request<ToolClassification>(`/v1/access/tool-classifications/${encodeURIComponent(serverId)}/${encodeURIComponent(toolId)}`, { method: "PUT", body: JSON.stringify(payload) }),
  confirmToolClassifications: (payload: { items: Array<{ server_id: string; tool_id: string; expected_fingerprint: string }>; note?: string }) => request<ToolClassificationConfirmResponse>("/v1/access/tool-classifications/confirm", { method: "POST", body: JSON.stringify(payload) }),
  publishToolClassifications: (payload: { server_id?: string | null; tool_ids?: string[] }) => request<{ classifications: ToolClassification[] }>("/v1/access/tool-classifications/publish", { method: "POST", body: JSON.stringify(payload) }),
  invocationAudits: (filters: { user_id?: string; server_id?: string; tool_id?: string; decision?: string; outcome?: string; limit?: number } = {}) => request<{ audits: InvocationAudit[]; filter_options: InvocationAuditFilterOptions }>(`/v1/access/invocation-audits${queryString(filters)}`),
  personalTokens: () => request<{ tokens: PersonalToken[] }>("/v1/auth/tokens"),
  createPersonalToken: (payload: { name: string; scopes: string[]; expires_at?: string | null }) => request<PersonalTokenCreateResponse>("/v1/auth/tokens", { method: "POST", body: JSON.stringify(payload) }),
  updatePersonalTokenScopes: (tokenId: string, scopes: string[]) => request<PersonalToken>(`/v1/auth/tokens/${encodeURIComponent(tokenId)}`, { method: "PATCH", body: JSON.stringify({ scopes }) }),
  revokePersonalToken: (tokenId: string) => request<PersonalToken>(`/v1/auth/tokens/${encodeURIComponent(tokenId)}`, { method: "DELETE" }),
  downstreamCredentials: () => request<{ credentials: UserDownstreamCredential[] }>("/v1/auth/downstream-credentials"),
  saveDownstreamCredential: (serverId: string, slotId: string, value: string) => request<UserDownstreamCredential>(`/v1/auth/downstream-credentials/${encodeURIComponent(serverId)}/${encodeURIComponent(slotId)}`, { method: "PUT", body: JSON.stringify({ value }) }),
  deleteDownstreamCredential: (serverId: string, slotId: string) => request<UserDownstreamCredential>(`/v1/auth/downstream-credentials/${encodeURIComponent(serverId)}/${encodeURIComponent(slotId)}`, { method: "DELETE" }),
}

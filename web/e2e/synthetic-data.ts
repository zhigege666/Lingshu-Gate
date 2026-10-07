/** Deterministic presentation fixtures; never evidence of API authorization. */
const timestamp = '2026-01-01T00:00:00Z'
export const servers = Array.from({ length: 100 }, (_, i) => ({
  id: `synthetic-service-${String(i).padStart(3, '0')}`, name: `Synthetic service ${i}`,
  enabled: false, launch_type: 'remote', transport_type: 'streamable_http', status: 'stopped',
  tool_count: 50, restart_policy: {}, restart_count: 0, restart_attempts: 0,
  consecutive_health_failures: 0, health_status: 'unknown', allowed_actions: ['start'],
}))
export const tools = Array.from({ length: 5000 }, (_, i) => ({
  id: `synthetic-tool-${String(i).padStart(4, '0')}`, name: `Synthetic tool ${String(i).padStart(4, '0')}`,
  description: `Synthetic description ${i}`, permission: 'read', input_schema: { type: 'object', properties: {} },
  source: 'mcp', metadata: { server_id: servers[i % 100].id, effective_access: 'read', classification_status: 'published' },
}))
export const classifications = tools.map((tool, i) => ({
  id: `classification-${i}`, server_id: tool.metadata.server_id, tool_id: tool.id, tool_name: tool.name,
  fingerprint: `synthetic-fingerprint-${i}`, suggested_access: 'read', effective_access: 'read', status: 'published',
  confidence: 1, source: 'manual', destructive: false, idempotent: true, open_world: false,
  evidence: {}, created_at: timestamp, updated_at: timestamp,
}))
export const credentials = Array.from({ length: 200 }, (_, i) => ({
  id: `synthetic-credential-${i}`, name: `Synthetic credential ${i}`, description: 'No actual secret',
  value_masked: '********', created_at: timestamp, updated_at: timestamp,
}))
const many = <T>(make: (i: number) => T, count = 200) => Array.from({ length: count }, (_, i) => make(i))
export const users = many(i => ({ id: `user-${i}`, username: `synthetic-user-${i}`, display_name: `Synthetic user ${i}`, role: 'viewer', roles: ['viewer'], status: 'active', must_change_password: false, created_at: timestamp, updated_at: timestamp }))
export const roles = many(i => ({ id: `role-${i}`, code: `synthetic-role-${i}`, name: `Synthetic role ${i}`, description: 'Synthetic role', is_system: false, enabled: true, member_count: 0, permissions: ['console.view'], created_at: timestamp, updated_at: timestamp }), 60)
export const grants = many(i => ({ id: `grant-${i}`, subject_type: 'user', subject_id: users[i % users.length].id, server_id: servers[i % 100].id, tool_id: tools[i].id, permission_type_id: 'read', permission_type_code: 'read', permission_type_name: 'Read', base_level: 'read', created_by: 'synthetic-admin', created_at: timestamp, updated_at: timestamp }), 2000)
export const audits = many(i => ({ id: `audit-${i}`, correlation_id: `synthetic-correlation-${i}`, user_id: users[i].id, username: users[i].username, auth_type: 'session', server_id: servers[i % 100].id, tool_id: tools[i].id, tool_access: 'read', required_access: 'read', granted_access: 'read', decision: 'allow', reason: 'synthetic', outcome: 'success', duration_ms: 1, payload: {}, created_at: timestamp }))
export const tokens = many(i => ({ id: `token-${i}`, name: `Synthetic token ${i}`, token_prefix: 'synthetic', scopes: ['tools.read'], created_at: timestamp }), 100)
export const bindings = many(i => ({ server_id: servers[i % 100].id, server_name: servers[i % 100].name, transport_type: 'streamable_http', id: `binding-${i}`, name: `Synthetic binding ${i}`, description: 'Synthetic personal binding', required: false, injection: { type: 'http_header', name: 'X-Synthetic', template: '{value}' }, configured: false }))
export const logs = many(i => ({ id: `log-${i}`, level: 'info', source: 'synthetic', server_id: servers[i % 100].id, event_type: 'synthetic.event', message: `Synthetic log ${i}`, payload: {}, created_at: timestamp }))
export const events = many(i => ({ id: `event-${i}`, type: `synthetic.event.${i}`, source: 'synthetic', subject_id: servers[i % 100].id, payload: {}, created_at: timestamp }))
const cachePath = { path: '/synthetic/cache', exists: true, is_dir: true, readable: true, writable: true, parent_writable: true }
export const cache = { root: cachePath, total_size_bytes: 1000, caches: many(i => ({ ...cachePath, name: `synthetic-cache-${i}`, size_bytes: 10, file_count: 1 }), 100) }
export const uploads = many(i => ({ id: `upload-${i}`, filename: `synthetic-project-${i}.zip`, status: 'uploaded', detected_runtime: 'python', root_dir: `/synthetic/project-${i}`, analysis: {}, created_at: timestamp, updated_at: timestamp }), 500)
export const builds = many(i => ({ id: `build-${i}`, upload_id: uploads[i % uploads.length].id, status: 'success', runtime: 'python', source_dir: uploads[i % uploads.length].root_dir, artifact_dir: `/synthetic/artifact-${i}`, commands: [], logs: [], manifest: { id: servers[i % 100].id }, created_at: timestamp, updated_at: timestamp }), 1000)
export const deployments = many(i => ({ id: `deployment-${i}`, build_id: builds[i].id, server_id: servers[i % 100].id, status: 'deployed', manifest: {}, rollback_available: false, started: false, created_at: timestamp, updated_at: timestamp }), 500)
export const listFixtures: Record<string, unknown> = {
  '/v1/auth/external-grants': { grants: many(i => ({ id: `synthetic-grant-${i}`, client_id: `synthetic-client-${i}`, server_allowlist: [servers[i % 100].id], tool_allowlist: [tools[i].id], access: ['read'], expires_at: '2099-01-01T00:00:00Z', enabled: false, state: 'disabled', revision: 1, scope_currently_authorized: true, rate_per_minute: 30, concurrency: 1 })) },
  '/v1/access/permission-types': { permission_types: many(i => ({ id: `synthetic-type-${i}`, code: `synthetic-type-${i}`, name: `Synthetic type ${i}`, base_level: 'read', description: '', enabled: true, is_system: false, reference_count: 0, created_at: timestamp, updated_at: timestamp }), 30) },
  '/v1/access/users': { users }, '/v1/access/subjects': { users, roles }, '/v1/access/roles': { roles }, '/v1/access/grants': { grants },
  '/v1/access/invocation-audits': { audits, filter_options: { users, servers: servers.map(s => s.id), tools: [] } },
  '/v1/auth/tokens': { tokens }, '/v1/auth/downstream-credentials': { credentials: bindings },
  '/v1/logs': { logs }, '/v1/events': { events }, '/v1/runtime/cache': cache,
  '/v1/projects/uploads': { uploads }, '/v1/builds': { builds }, '/v1/deployments': { deployments },
}

import { describe, expect, it } from "vitest"
import type { ResourceGrant } from "@/api/client"
import { resourceGrantEditorDraft, resourceGrantSavePayload } from "./access-grants-page"

const grant: ResourceGrant = { id: "grant-existing", subject_type: "role", subject_id: "role-reader", server_id: "mcp-a", tool_id: "mcp-a.read", permission_type_id: "read", permission_type_code: "read", permission_type_name: "Read", base_level: "read", expires_at: "2030-06-15T08:09:10.123Z", created_by: "admin", created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z" }

describe("资源授权编辑", () => {
  it("预填已有主体、资源、权限及本地有效期，未修改的到期精度保持原值", () => {
    const draft = resourceGrantEditorDraft(grant)
    expect(draft.scope).toBe("tool")
    expect(draft.form).toMatchObject({ subject_type: "role", subject_id: "role-reader", server_id: "mcp-a", tool_id: "mcp-a.read", permission_type_code: "read" })
    expect(new Date(draft.form.expires_at!).getTime()).toBe(Math.floor(Date.parse(grant.expires_at!) / 1000) * 1000)
    expect(resourceGrantSavePayload({ ...draft.form, permission_type_code: "write" }, draft.scope, grant)).toEqual({ subject_type: "role", subject_id: "role-reader", server_id: "mcp-a", tool_id: "mcp-a.read", permission_type_code: "write", expires_at: grant.expires_at })
  })
  it("编辑 payload 固定原记录自然键，不能因改身份而意外新增授权", () => {
    const draft = resourceGrantEditorDraft(grant)
    const payload = resourceGrantSavePayload({ ...draft.form, subject_type: "user", subject_id: "other", server_id: "other", tool_id: null, expires_at: null }, "server", grant)
    expect(payload).toMatchObject({ subject_type: "role", subject_id: "role-reader", server_id: "mcp-a", tool_id: "mcp-a.read", expires_at: null })
  })
  it("新建整服务和指定工具仍遵守原 API，编辑永久授权可设置本地到期", () => {
    const forever = { ...grant, tool_id: null, expires_at: null }
    const draft = resourceGrantEditorDraft(forever)
    expect(draft).toMatchObject({ scope: "server", form: { tool_id: null, expires_at: null } })
    const changed = { ...draft.form, expires_at: "2031-04-02T10:11:12", tool_id: "mcp-a.write" }
    expect(resourceGrantSavePayload(changed, "server", null)).toMatchObject({ tool_id: null, expires_at: new Date(changed.expires_at).toISOString() })
    expect(resourceGrantSavePayload(changed, "tool", null).tool_id).toBe("mcp-a.write")
    expect(resourceGrantSavePayload(changed, "server", forever).expires_at).toBe(new Date(changed.expires_at).toISOString())
  })
})

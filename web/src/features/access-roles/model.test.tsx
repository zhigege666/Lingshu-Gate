import { renderToStaticMarkup } from "react-dom/server"
import { describe, expect, it } from "vitest"
import type { AccessRole, PermissionType } from "@/api/client"
import { translate } from "@/i18n"
import { AccessInlineActions } from "./inline-actions"
import { accessDraftChanged, accessIdentityErrors, canDeleteAccessItem, copyPermissionTypePayload, copyRolePayload, emptyAccessFilters, filterAccessItems, normalizeAccessCode, permissionTypePayload, rolePayload, roleSaveSnapshot } from "./model"

const role: AccessRole = { id: "role-viewer", code: "viewer", name: "只读观察者", description: "Read access", is_system: true, enabled: true, member_count: 3, permissions: ["console.view", "tools.read"], created_at: "", updated_at: "" }
const type: PermissionType = { id: "type-read", code: "read", name: "只读", description: "Read tools", is_system: true, enabled: true, reference_count: 2, base_level: "read", created_at: "", updated_at: "" }

describe("Roles and permission types", () => {
  it("combines name/code, source, status, and level filters without changing server data", () => {
    const customRole = { ...role, id: "role-custom", code: "audit_copy", is_system: false, enabled: false }
    const items = [role, customRole]
    expect(filterAccessItems(items, { ...emptyAccessFilters, query: "  AUDIT_ ", source: "custom", status: "disabled" })).toEqual([customRole])
    expect(filterAccessItems(items, { ...emptyAccessFilters, query: "观察", status: "enabled" })).toEqual([role])
    expect(filterAccessItems(items, { ...emptyAccessFilters, query: "missing" })).toEqual([])
    expect(filterAccessItems([type], { ...emptyAccessFilters, level: "write" })).toEqual([])
    expect(filterAccessItems([type], { ...emptyAccessFilters, level: "read" })).toEqual([type])
    expect(items).toEqual([role, customRole])
  })

  it("copies permissions into an independent create payload without system identity or membership", () => {
    const copy = copyRolePayload(role, "副本")
    expect(copy).toEqual({ code: "", name: "只读观察者副本", description: "Read access", permissions: ["console.view", "tools.read"], enabled: true })
    copy.permissions.push("audit.read")
    expect(role.permissions).toEqual(["console.view", "tools.read"])
    expect(copy).not.toHaveProperty("id")
    expect(copy).not.toHaveProperty("is_system")
    expect(copy).not.toHaveProperty("member_count")
  })

  it("copies type semantics without copying identity or resource references", () => {
    expect(copyPermissionTypePayload(type, " copy")).toEqual({ code: "", name: "只读 copy", description: "Read tools", base_level: "read", enabled: true })
    expect(copyPermissionTypePayload({ ...type, enabled: false }, " copy").enabled).toBe(false)
  })

  it("preserves editable data when toggling status", () => {
    expect({ ...rolePayload(role), enabled: false }).toEqual({ code: "viewer", name: role.name, description: role.description, permissions: role.permissions, enabled: false })
    expect({ ...permissionTypePayload(type), enabled: false }).toEqual({ code: "read", name: type.name, description: type.description, base_level: "read", enabled: false })
  })

  it("does not offer deletion for built-in, assigned, or referenced entries", () => {
    expect(canDeleteAccessItem({ ...role, member_count: 0 })).toBe(false)
    expect(canDeleteAccessItem({ ...type, reference_count: 0 })).toBe(false)
    expect(canDeleteAccessItem({ ...role, is_system: false })).toBe(false)
    expect(canDeleteAccessItem({ ...type, is_system: false })).toBe(false)
    expect(canDeleteAccessItem({ ...role, is_system: false, member_count: 0 })).toBe(true)
    expect(canDeleteAccessItem({ ...type, is_system: false, reference_count: 0 })).toBe(true)
  })

  it.each([["  Viewer  ", "viewer"], [" Audit / Read ", "audit-read"], ["---", ""], ["_custom.read-1", "_custom.read-1"]])("normalizes %s like the API before checking duplicates", (input, output) => {
    expect(normalizeAccessCode(input)).toBe(output)
  })

  it("protects unsaved editable values but allows closing an unchanged or reverted draft", () => {
    const original = rolePayload(role)
    expect(accessDraftChanged(rolePayload(role), original)).toBe(false)
    expect(accessDraftChanged({ ...original, name: "Changed name" }, original)).toBe(true)
    expect(accessDraftChanged({ ...original, permissions: ["console.view"] }, original)).toBe(true)
    expect(accessDraftChanged({ ...original, permissions: [...original.permissions].reverse() }, original)).toBe(false)
    const originalType = permissionTypePayload(type)
    expect(accessDraftChanged({ ...originalType, base_level: "write" }, originalType)).toBe(true)
    expect(accessDraftChanged({ ...originalType, enabled: false }, originalType)).toBe(true)
    expect(accessDraftChanged(permissionTypePayload(type), originalType)).toBe(false)
  })

  it("owns a normalized submission snapshot independently of the current form", () => {
    const draft = { ...rolePayload(role), code: " Audit / Read ", name: "  Audit reader  " }
    const submitted = roleSaveSnapshot(draft)
    draft.name = "Edited after submission"
    draft.permissions.push("audit.read")
    expect(submitted.code).toBe("audit-read")
    expect(submitted.name).toBe("Audit reader")
    expect(submitted.permissions).toEqual(["console.view", "tools.read"])
  })

  it("locates identity errors without rejecting the currently edited entry's code", () => {
    expect(accessIdentityErrors(rolePayload(role), [role], role.id)).toEqual({ code: undefined, name: undefined })
    expect(accessIdentityErrors({ ...rolePayload(role), code: " VIEWER " }, [role])).toEqual({ code: "duplicate", name: undefined })
    expect(accessIdentityErrors({ ...permissionTypePayload(type), code: "---", name: "  " }, [type])).toEqual({ code: "required", name: "required" })
    expect(accessIdentityErrors({ ...permissionTypePayload(type), code: "custom" }, [type])).toEqual({ code: undefined, name: undefined })
  })
})

describe("Visible row actions", () => {
  const noOp = () => {}
  function render(item: AccessRole | PermissionType, busy = false) {
    return renderToStaticMarkup(<AccessInlineActions item={item} locale="zh-CN" t={key => translate("zh-CN", key)} busy={busy} onView={noOp} onEdit={noOp} onCopy={noOp} onToggle={noOp} onDelete={noOp} />)
  }

  it("keeps built-in editing available without enable/disable or delete controls", () => {
    const html = render(role)
    expect(html).toContain('aria-label="查看 只读观察者"')
    expect(html).toContain('aria-label="编辑 只读观察者"')
    expect(html).toContain('aria-label="复制 只读观察者"')
    expect(html).not.toContain("停用")
    expect(html).not.toContain("删除")
    expect(html).not.toContain("aria-haspopup")
  })

  it("shows all five custom actions and explains why a referenced type cannot be deleted", () => {
    const html = render({ ...type, is_system: false })
    expect((html.match(/<button /g) || [])).toHaveLength(5)
    expect(html).toContain('aria-label="停用 只读"')
    expect(html).toContain('aria-label="删除 只读"')
    expect(html).toContain("请先移除相关资源授权")
    expect((html.match(/disabled=""/g) || [])).toHaveLength(1)
  })

  it("offers enable for a disabled custom role and blocks writes while a request is in flight", () => {
    const html = render({ ...role, is_system: false, member_count: 0, enabled: false }, true)
    expect(html).toContain('aria-label="启用 只读观察者"')
    expect((html.match(/disabled=""/g) || [])).toHaveLength(4)
  })
})

import { describe, expect, it } from "vitest"
import {
  getAvailableTokenScopes,
  getDefaultTokenScopes,
  getTokenScopeOptions,
} from "@/features/personal-token-scopes"

const adminPermissions = [
  "console.view", "users.manage", "roles.manage", "grants.manage",
  "classifications.manage", "credentials.manage.self", "credentials.manage.all",
  "audit.read", "tools.read", "tools.invoke", "operations.manage",
]

describe("个人 Token 范围", () => {
  it("管理员会话可以选择上传构建和分类发布权限", () => {
    const scopes = getAvailableTokenScopes({ permissions: adminPermissions, auth_type: "session", scopes: [] })

    expect(scopes).toEqual(expect.arrayContaining(["tools.invoke", "operations.manage", "classifications.manage"]))
    expect(new Set(scopes)).toEqual(new Set(adminPermissions))
    expect(getDefaultTokenScopes(scopes)).toEqual(["tools.read"])
  })

  it.each([
    ["运维", ["console.view", "credentials.manage.self", "audit.read", "tools.read", "tools.invoke", "operations.manage"]],
    ["只读", ["console.view", "credentials.manage.self", "tools.read"]],
  ])("%s 会话只展示账号实际拥有的权限", (_role, permissions) => {
    const scopes = getAvailableTokenScopes({ permissions, auth_type: "session", scopes: [] })

    expect(new Set(scopes)).toEqual(new Set(permissions))
    expect(scopes).not.toContain("classifications.manage")
  })

  it("新权限不受前端展示顺序表过滤", () => {
    const scopes = getAvailableTokenScopes({
      permissions: ["custom.review", "tools.read", "custom.review"],
      auth_type: "session",
      scopes: [],
    })

    expect(scopes).toEqual(["tools.read", "custom.review"])
  })

  it("管理员的受限 Token 不能授予父 Token 范围外的权限", () => {
    const scopes = getAvailableTokenScopes({
      permissions: adminPermissions,
      auth_type: "token",
      scopes: ["credentials.manage.self", "tools.read"],
    })

    expect(scopes).toEqual(["tools.read", "credentials.manage.self"])
  })

  it("父 Token 的通配范围仍受账号当前权限约束", () => {
    const scopes = getAvailableTokenScopes({
      permissions: ["tools.read", "credentials.manage.self"],
      auth_type: "token",
      scopes: ["*"],
    })

    expect(scopes).toEqual(["tools.read", "credentials.manage.self"])
    expect(scopes).not.toContain("*")
  })

  it("父 Token 的范围为空或账号权限已收回时不提供对应选项", () => {
    expect(getAvailableTokenScopes({ permissions: adminPermissions, auth_type: "token", scopes: [] })).toEqual([])
    expect(getAvailableTokenScopes({ permissions: ["tools.read"], auth_type: "token", scopes: ["operations.manage"] })).toEqual([])
  })

  it("没有只读权限时不默认选择管理或写入权限", () => {
    expect(getDefaultTokenScopes(["operations.manage", "tools.invoke"])).toEqual([])
    expect(getDefaultTokenScopes([])).toEqual([])
  })

  it("编辑现有 Token 时展示新增可选权限并保留已有范围", () => {
    const available = ["tools.read", "operations.manage", "classifications.manage"]
    const existing = ["tools.read", "legacy.review"]
    const options = getTokenScopeOptions(available, existing)

    expect(options).toEqual(["tools.read", "operations.manage", "classifications.manage", "legacy.review"])
    expect(existing).toEqual(["tools.read", "legacy.review"])
  })
})

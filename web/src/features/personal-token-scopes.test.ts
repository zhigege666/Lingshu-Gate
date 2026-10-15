import { readFileSync } from "node:fs"
import { describe, expect, it } from "vitest"
import type { AuthUser } from "@/components/auth-gate"
import {
  getAvailableTokenScopes,
  getDefaultTokenScopes,
  getTokenScopeGroups,
  getTokenScopeOptions,
} from "@/features/personal-token-scopes"

// 从真实后端目录核对展示覆盖，避免新增权限后测试仍只检查旧的固定列表。
const permissionSource = readFileSync(new URL("../../../src/lingshu_gate/access_control.py", import.meta.url), "utf8")
const permissionBlock = permissionSource.match(/CONTROL_PERMISSIONS = \(([\s\S]*?)\r?\n\)/)?.[1]
if (!permissionBlock) throw new Error("无法读取后端控制面权限目录")
const adminPermissions = [...permissionBlock.matchAll(/^\s+\("([^"]+)",/gm)].map(match => match[1])
const admin: Pick<AuthUser, "role" | "roles"> = { role: "admin", roles: ["admin"] }
const operator: Pick<AuthUser, "role" | "roles"> = { role: "operator", roles: ["operator"] }

describe("个人 Token 范围", () => {
  it("管理员新建 Token 默认选择全部当前可授予权限", () => {
    const scopes = getAvailableTokenScopes({ permissions: adminPermissions, auth_type: "session", scopes: [] })

    expect(scopes).toEqual(expect.arrayContaining(["tools.invoke", "operations.manage", "classifications.manage"]))
    expect(new Set(scopes)).toEqual(new Set(adminPermissions))
    expect(getDefaultTokenScopes(scopes, admin)).toEqual(scopes)
  })

  it.each([
    ["运维", ["console.view", "credentials.manage.self", "audit.read", "tools.read", "tools.invoke", "operations.manage"]],
    ["只读", ["console.view", "credentials.manage.self", "tools.read"]],
  ])("%s 会话只展示账号实际拥有的权限", (_role, permissions) => {
    const scopes = getAvailableTokenScopes({ permissions, auth_type: "session", scopes: [] })

    expect(new Set(scopes)).toEqual(new Set(permissions))
    expect(scopes).not.toContain("classifications.manage")
    expect(getDefaultTokenScopes(scopes, operator)).toEqual(["tools.read"])
  })

  it("新权限不受前端展示顺序表过滤", () => {
    const scopes = getAvailableTokenScopes({
      permissions: ["custom.review", "tools.read", "custom.review"],
      auth_type: "session",
      scopes: [],
    })

    expect(scopes).toEqual(["tools.read", "custom.review"])
    expect(getDefaultTokenScopes(scopes, admin)).toEqual(["tools.read", "custom.review"])
    expect(getTokenScopeGroups(scopes, "zh-CN").flatMap(group => group.scopes.map(scope => scope.code))).toContain("custom.review")
  })

  it.each(["token", "oauth"])("管理员的受限 %s 默认全选仍不能突破当前令牌范围", auth_type => {
    const scopes = getAvailableTokenScopes({
      permissions: adminPermissions,
      auth_type,
      scopes: ["credentials.manage.self", "tools.read"],
    })

    expect(scopes).toEqual(["tools.read", "credentials.manage.self"])
    expect(getDefaultTokenScopes(scopes, admin)).toEqual(["tools.read", "credentials.manage.self"])
  })

  it("父 Token 的通配范围仍受账号当前权限约束", () => {
    const scopes = getAvailableTokenScopes({
      permissions: ["tools.read", "credentials.manage.self"],
      auth_type: "token",
      scopes: ["*"],
    })

    expect(scopes).toEqual(["tools.read", "credentials.manage.self"])
    expect(scopes).not.toContain("*")
    expect(getDefaultTokenScopes(scopes, admin)).toEqual(scopes)
  })

  it("父 Token 的范围为空或账号权限已收回时不提供对应选项", () => {
    expect(getAvailableTokenScopes({ permissions: adminPermissions, auth_type: "token", scopes: [] })).toEqual([])
    expect(getAvailableTokenScopes({ permissions: ["tools.read"], auth_type: "token", scopes: ["operations.manage"] })).toEqual([])
  })

  it("其他账号没有只读权限时不默认选择管理或写入权限", () => {
    expect(getDefaultTokenScopes(["operations.manage", "tools.invoke"], operator)).toEqual([])
    expect(getDefaultTokenScopes([], operator)).toEqual([])
    expect(getDefaultTokenScopes([], admin)).toEqual([])
  })

  it("从实际角色识别管理员，不根据权限多少推断管理员", () => {
    expect(getDefaultTokenScopes(adminPermissions, { role: "operator", roles: ["operator", "admin"] })).toEqual(adminPermissions)
    expect(getDefaultTokenScopes(adminPermissions, { role: "custom-manager", roles: ["custom-manager"] })).toEqual(["tools.read"])
  })

  it("编辑现有 Token 时展示新增可选权限并保留已有范围", () => {
    const available = ["tools.read", "operations.manage", "classifications.manage"]
    const existing = ["tools.read", "legacy.review"]
    const options = getTokenScopeOptions(available, existing)

    expect(options).toEqual(["tools.read", "operations.manage", "classifications.manage", "legacy.review"])
    expect(existing).toEqual(["tools.read", "legacy.review"])
  })

  it.each(["zh-CN", "en-US"] as const)("%s 为后端全部权限提供名称、用途和分组", locale => {
    const groups = getTokenScopeGroups(adminPermissions, locale)
    const scopes = groups.flatMap(group => group.scopes)
    expect(adminPermissions.length).toBeGreaterThan(0)
    expect(new Set(scopes.map(scope => scope.code))).toEqual(new Set(adminPermissions))
    expect(groups).toHaveLength(5)
    for (const scope of scopes) {
      expect(scope.name).not.toBe(scope.code)
      expect(scope.description).not.toBe(scope.code)
      expect(scope.description.length).toBeGreaterThan(10)
      if (locale === "zh-CN") expect(scope.description).toMatch(/[\u4e00-\u9fff]/)
    }
    expect(groups.map(group => group.name)).not.toContain(locale === "zh-CN" ? "其他权限" : "Other permissions")
  })

  it("权限用途说明保留凭据、内容读取和网络调用的独立边界", () => {
    const scopes = getTokenScopeGroups(adminPermissions, "zh-CN").flatMap(group => group.scopes)
    const description = (code: string) => scopes.find(scope => scope.code === code)?.description
    expect(description("credentials.manage.all")).toContain("不读取用户下游秘密")
    expect(description("audit.payload.read")).toContain("脱敏和限长")
    expect(description("system_settings.manage")).toContain("另需 network.use")
    expect(description("network.use")).toContain("不包含网络配置管理")
    expect(description("external_connections.manage")).toContain("不代替用户同意授权")
    expect(description("tools.invoke")).toContain("只读调用还需 tools.read")
  })

  it("分组保留历史或新增未知权限并且不重复展示", () => {
    const scopes = ["tools.read", "legacy.review", "tools.read"]
    const groups = getTokenScopeGroups(scopes, "zh-CN")
    expect(groups.flatMap(group => group.scopes.map(scope => scope.code))).toEqual(["tools.read", "legacy.review"])
    expect(groups.find(group => group.name === "其他权限")?.scopes[0].name).toBe("legacy.review")
    expect(scopes).toEqual(["tools.read", "legacy.review", "tools.read"])
  })
})

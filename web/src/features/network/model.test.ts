import { describe, expect, it } from "vitest"
import { networkPermission, selectionFromKey, selectionKey, selectionOptions } from "./model"
import type { AuthUser } from "@/components/auth-gate"

const manager: AuthUser = { id: "manager", username: "manager", display_name: "Manager", role: "operator", roles: ["operator"], permissions: ["system_settings.manage"], status: "active", auth_type: "session", must_change_password: false, scopes: [] }

describe("delivery network selection and permissions", () => {
  it("keeps configuration permission separate from invocation and token scope", () => {
    expect(networkPermission(manager, "system_settings.manage")).toBe(true)
    expect(networkPermission(manager, "network.use")).toBe(false)
    expect(networkPermission({ ...manager, auth_type: "token", scopes: ["network.use"] }, "system_settings.manage")).toBe(false)
  })
  it("preserves explicit direct, inherit and pinned profile versions", () => {
    expect(selectionFromKey("inherit")).toEqual({ mode: "inherit" })
    expect(selectionFromKey("direct")).toEqual({ mode: "direct" })
    expect(selectionFromKey("named@3")).toEqual({ mode: "profile", profile_id: "named", version: 3 })
    expect(selectionKey({ mode: "profile", profile_id: "named", version: 3 })).toBe("named@3")
  })
  it("disables unusable profiles and never inserts a fallback profile", () => {
    const options = selectionOptions([{ id: "named", version: 2, name: "Example", scheme: "socks5", enabled: false, credential_configured: true, credential_ref: null, endpoint_masked: "***" }], false)
    expect(options.find(option => option.value === "named@2")).toMatchObject({ disabled: true })
    expect(selectionOptions([], false, false).map(option => option.value)).toEqual(["direct"])
    expect(JSON.stringify(options)).not.toContain("endpoint")
  })
})

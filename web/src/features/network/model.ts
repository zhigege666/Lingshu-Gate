import type { AuthUser } from "@/components/auth-gate"
import type { NetworkProfile, NetworkSelection } from "@/api/network"

export function networkPermission(user: AuthUser, permission: string) {
  return (user.permissions.includes("*") || user.permissions.includes(permission)) && (!["token", "oauth"].includes(user.auth_type) || user.scopes.includes("*") || user.scopes.includes(permission))
}

export function selectionKey(selection: NetworkSelection) {
  return selection.mode === "profile" ? `${selection.profile_id}@${selection.version ?? "current"}` : selection.mode
}

export function selectionFromKey(key: string): NetworkSelection {
  if (key === "inherit" || key === "direct") return { mode: key }
  const [profile_id, raw] = key.split("@")
  return { mode: "profile", profile_id, ...(raw && raw !== "current" ? { version: Number(raw) } : {}) }
}

export function selectionOptions(profiles: NetworkProfile[], zh: boolean, inherit = true) {
  return [
    ...(inherit ? [{ value: "inherit", label: zh ? "继承系统默认（计划时固定）" : "Inherit system default (pin at planning)" }] : []),
    { value: "direct", label: zh ? "直连（不使用代理）" : "Direct (no proxy)" },
    ...profiles.map(profile => ({ value: `${profile.id}@${profile.version}`, label: `${profile.name} · v${profile.version} · ${profile.scheme}${profile.enabled ? "" : zh ? " · 已停用" : " · Disabled"}`, disabled: !profile.enabled || !profile.credential_configured })),
  ]
}

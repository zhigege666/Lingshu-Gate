import type { ArgumentPolicy, ArgumentPolicyWrite, ArgumentRule } from "@/api/argument-policy"
import { parsePolicyJson, PolicyJsonError } from "./json"

export type RuleDraft = { key: string; id: string; pointer: string; operator: ArgumentRule["operator"]; value: string; values: string; minimum: string; maximum: string; prefix: string }
export type PolicyIssue = { code: string; path: string; field: string; index: number; severity: "error"; source: "policy"; revision: number; immediate: boolean }
export const newRule = (key: string): RuleDraft => ({ key, id: key, pointer: "", operator: "equals", value: "null", values: "[]", minimum: "", maximum: "", prefix: "" })

function editableJson(value: unknown): string {
  const pretty = JSON.stringify(value, null, 2)
  return new TextEncoder().encode(pretty).length <= 65_536 ? pretty : JSON.stringify(value)
}

export function policyDraft(policy: ArgumentPolicy): RuleDraft[] {
  if (typeof policy.enabled !== "boolean" || !Number.isSafeInteger(policy.revision) || policy.revision < 0 || !Array.isArray(policy.rules) || policy.rules.length > 64) throw new Error("policy_editor_unsupported")
  parsePolicyJson(JSON.stringify(policy.rules))
  return policy.rules.map((rule, index) => {
    if (!rule || typeof rule.id !== "string" || typeof rule.pointer !== "string") throw new Error("policy_editor_unsupported")
    const keys = ["id", "pointer", "operator", ...(rule.operator === "equals" ? ["value"] : rule.operator === "allowed_values" ? ["values"]
      : rule.operator === "number_range" ? ["minimum", "maximum"] : rule.operator === "string_prefix" ? ["prefix"] : [])]
    if (Object.keys(rule).some(key => !keys.includes(key))) throw new Error("policy_editor_unsupported")
    const draft = { ...newRule("stored_" + index), id: rule.id, pointer: rule.pointer, operator: rule.operator }
    if (rule.operator === "equals" && Object.hasOwn(rule, "value")) return { ...draft, value: editableJson(rule.value) }
    if (rule.operator === "allowed_values" && Array.isArray(rule.values)) return { ...draft, values: editableJson(rule.values) }
    if (rule.operator === "number_range") return { ...draft, minimum: rule.minimum == null ? "" : String(rule.minimum), maximum: rule.maximum == null ? "" : String(rule.maximum) }
    if (rule.operator === "string_prefix" && typeof rule.prefix === "string") return { ...draft, prefix: rule.prefix }
    throw new Error("policy_editor_unsupported")
  })
}

export function validatePolicyDraft(enabled: boolean, rows: RuleDraft[], expectedRevision: number, revision: number): { body: ArgumentPolicyWrite; issues: PolicyIssue[] } {
  const rules: ArgumentRule[] = [], issues: PolicyIssue[] = [], ids = new Set<string>()
  const issue = (index: number, field: string, code: string, immediate = false) => issues.push({ index, field, code,
    path: index >= 0 ? "/rules/" + index + "/" + field : "/rules", severity: "error", source: "policy", revision, immediate })
  const json = (raw: string, index: number, field: string): unknown => {
    try { return parsePolicyJson(raw) } catch (cause) {
      issue(index, field, cause instanceof PolicyJsonError ? cause.code : "json_syntax", raw.length > 0)
      return undefined
    }
  }
  rows.forEach((row, index) => {
    if (!/^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$/.test(row.id) || ids.has(row.id)) issue(index, "id", "rule_id")
    ids.add(row.id)
    if (Array.from(row.pointer).length > 512 || row.pointer !== "" && !row.pointer.startsWith("/") || /~(?![01])|[\u0000-\u001f]/.test(row.pointer) || row.pointer.split("/").length > 33) issue(index, "pointer", "pointer")
    const common = { id: row.id, pointer: row.pointer }
    switch (row.operator) {
      case "equals": {
        const value = json(row.value, index, "value")
        if (value !== undefined) rules.push({ ...common, operator: "equals", value })
        break
      }
      case "allowed_values": {
        const values = json(row.values, index, "values")
        if (values !== undefined && (!Array.isArray(values) || values.length < 1 || values.length > 64)) issue(index, "values", "allowed_values")
        else if (Array.isArray(values)) rules.push({ ...common, operator: "allowed_values", values })
        break
      }
      case "number_range": {
        const minimum = row.minimum.trim() ? json(row.minimum, index, "minimum") : undefined
        const maximum = row.maximum.trim() ? json(row.maximum, index, "maximum") : undefined
        if (!row.minimum.trim() && !row.maximum.trim()) issue(index, "minimum", "range_required")
        if (minimum !== undefined && typeof minimum !== "number") issue(index, "minimum", "range_number")
        if (maximum !== undefined && typeof maximum !== "number") issue(index, "maximum", "range_number")
        if (typeof minimum === "number" && typeof maximum === "number" && minimum > maximum) issue(index, "maximum", "range_order")
        rules.push({ ...common, operator: "number_range", ...(typeof minimum === "number" ? { minimum } : {}), ...(typeof maximum === "number" ? { maximum } : {}) })
        break
      }
      case "string_prefix":
        if (Array.from(row.prefix).length < 1 || Array.from(row.prefix).length > 1024) issue(index, "prefix", "prefix")
        rules.push({ ...common, operator: "string_prefix", prefix: row.prefix })
        break
    }
  })
  if (rows.length > 64 || new TextEncoder().encode(JSON.stringify(rules)).length > 65_536) issue(-1, "", "policy_limit")
  else {
    try { parsePolicyJson(JSON.stringify(rules)) } catch (cause) { issue(-1, "", cause instanceof PolicyJsonError ? cause.code : "policy_limit") }
  }
  return { body: { enabled, expected_revision: expectedRevision, rules }, issues }
}

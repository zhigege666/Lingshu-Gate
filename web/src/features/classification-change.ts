import type { ToolClassification } from "@/api/identity-access"

export function classificationChangeReason(item: Pick<ToolClassification, "evidence">, zh: boolean): string {
  const lifecycle = item.evidence?.lifecycle as { reason?: string } | undefined
  const invalidation = item.evidence?.invalidation as { reason?: string; changed_fields?: unknown; previous_definition_unrecorded?: boolean; output_schema_recorded?: boolean } | undefined
  if (lifecycle?.reason === "missing_from_latest_tools_list") return zh ? "最新目录中已移除" : "Removed from latest catalog"
  if (lifecycle?.reason === "reappeared_in_tools_list") return zh ? "工具重新出现，需复核" : "Tool reappeared; review required"
  if (invalidation?.reason !== "tool_definition_changed") return zh ? "需重新审核，详见证据" : "Review required; inspect evidence"
  if (invalidation.previous_definition_unrecorded) {
    return zh
      ? `定义已变更${invalidation.output_schema_recorded ? "；现已记录输出契约" : ""}。旧版未记录字段摘要，无法还原逐字段差异；需重新审核并发布。`
      : `Definition changed${invalidation.output_schema_recorded ? "; the output contract is now recorded" : ""}. Previous field digests were not recorded; field differences are unavailable. Review and publish again.`
  }
  const names: Record<string, string> = zh
    ? { id: "工具 ID", name: "名称", description: "描述", permission: "权限", source: "来源", input_schema: "输入契约", output_schema: "输出契约", annotations: "安全标注", required_control_permission: "控制权限", sensitive_input_fields: "敏感输入字段", sensitive_output_fields: "敏感输出字段" }
    : { id: "tool ID", name: "name", description: "description", permission: "permission", source: "source", input_schema: "input contract", output_schema: "output contract", annotations: "safety annotations", required_control_permission: "control permission", sensitive_input_fields: "sensitive input fields", sensitive_output_fields: "sensitive output fields" }
  const fields = Array.isArray(invalidation.changed_fields) ? invalidation.changed_fields.filter((field): field is string => typeof field === "string").map(field => names[field] ?? field) : []
  return zh ? `${fields.length ? fields.join("、") : "定义"}已变更，需重新审核并发布。` : `${fields.length ? fields.join(", ") : "Definition"} changed; review and publish again.`
}

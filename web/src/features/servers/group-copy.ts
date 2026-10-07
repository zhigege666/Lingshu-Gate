import type { Locale } from "@/i18n"

const copy = {
  "en-US": {
    groups: "Groups", instances: "Instances", newGroup: "Create group", edit: "Edit group", delete: "Delete group",
    ungrouped: "Ungrouped", select: "Select a group or ungrouped instances", searchGroups: "Search groups by name or ID",
    searchInstances: "Search instances by name or ID", active: "Active", archived: "Archived", all: "All",
    name: "Name", description: "Description", state: "State", members: "Members", instanceId: "Instance ID",
    defaultInstance: "Default instance", noDefault: "None selected", clearDefault: "Clear default", contractVersion: "Contract version", runtimeStatus: "Status", unknownContract: "Not discovered",
    defaultHint: "A suggested default. Calls still require an explicit instance selection.",
    contractConflict: "Different contract versions are selected. Tools with incompatible contracts stay in separate partitions; arguments cannot be shared between them.",
    saved: "Group saved", deleted: "Group deleted", retry: "Retry", reload: "Reload saved group", save: "Save group",
    missing: "Missing / needs confirmation", noMatches: "No matches", empty: "No groups yet", selected: "selected",
    metadata: "Groups only organize existing instances. Membership copies no configuration and grants no access. Archiving or deleting a group only changes its metadata and relationships; services keep running.",
    missingHint: "Missing members can be retained or removed. To confirm a restored instance, uncheck it and explicitly select it again in the current catalog.",
    deleteTitle: "Delete this group?", reloadTitle: "Reload saved group?", reloadHint: "Discard this draft and read the current saved revision.",
    failed: "Request failed", conflict: "The group changed. Your draft is intact; reload the saved group before trying again.",
    unavailable: "A newly selected instance is unavailable. Refresh the catalog and check the selection.",
    forbidden: "A current administrator with operations.manage is required; writes also require tools.invoke.", csrf: "The request ticket is invalid or expired. Try again to obtain a fresh ticket.",
    checkCreate: "Check saved result", retryCreate: "Retry original creation", createChanged: "The creation result is unconfirmed and this draft changed. Check the saved result or retry the original creation first; your edits are preserved.",
    createRecovered: "The saved group was recovered. Your current edits are preserved; save to update this group.", createAbsent: "No saved result was found yet. Retry the original creation; absence does not prove that the earlier request failed.",
    createUnconfirmed: "The creation result is unconfirmed. Check its saved result or retry the original creation.",
    createDeleted: "This creation belongs to a group that was deleted. It will not be recreated; start a new draft if needed.",
    createClose: "The creation result is unconfirmed. Discarding also forgets its recovery key and does not delete a group that may already be saved. Check its result first; a new draft creates a separate group.",
    requestCapacity: "The creation receipt limit is full. This request did not create a new group; your draft is preserved. Existing requests can still be checked or replayed.",
    recoveryTitle: "A creation result still needs checking", recoveryHint: "Only its request key was kept for this user and Gate. Unsaved edits cannot be restored. Check the saved result by read only, or explicitly abandon this recovery record before creating another group.",
    recoveryAbsent: "No saved result was found yet; this does not prove the earlier request failed. The key is kept. No group will be created automatically.",
    abandonRecovery: "Abandon recovery record", abandonRecoveryHint: "Forget this request key? A group may already have been saved and will not be deleted. Its original draft cannot be restored; creating another group may duplicate it.",
    recoveredAfterReload: "The saved group was found. Unsaved edits were not restored.", recoveryUnavailable: "Browser recovery storage is unavailable. Do not rely on reload to restore this request key.",
    timeout: "The request timed out. Its result is unconfirmed; refresh the saved group/list before retrying.",
    notFound: "The group no longer exists. Refresh the list.", refresh: "Refresh", paging: "Instance pages", memberLimit: "Select up to 1,000 instances.", notLoaded: "Not loaded",
  },
  "zh-CN": {
    groups: "组", instances: "实例", newGroup: "创建组", edit: "编辑组", delete: "删除组",
    ungrouped: "未分组", select: "选择组或未分组实例", searchGroups: "按名称或 ID 搜索组",
    searchInstances: "按名称或 ID 搜索实例", active: "有效", archived: "已归档", all: "全部",
    name: "名称", description: "说明", state: "状态", members: "成员", instanceId: "实例 ID",
    defaultInstance: "默认实例", noDefault: "未选择", clearDefault: "清除默认", contractVersion: "合同版本", runtimeStatus: "状态", unknownContract: "尚未发现",
    defaultHint: "默认实例仅作建议，调用仍须显式选择实例。",
    contractConflict: "已选择不同合同版本。合同不兼容的工具保持独立分区，不能混用参数。",
    saved: "组已保存", deleted: "组已删除", retry: "重试", reload: "重新读取已保存组", save: "保存组",
    missing: "缺失 / 待确认", noMatches: "无匹配结果", empty: "尚未创建组", selected: "已选择",
    metadata: "组只整理已有实例。归组不复制配置，也不授予访问权限。归档或删除组只改变元数据和关系，服务继续运行。",
    missingHint: "缺失成员可以保留或移除。恢复的实例须在当前目录中取消选择后再显式选中，才能重新确认。",
    deleteTitle: "删除此组？", reloadTitle: "重新读取已保存组？", reloadHint: "放弃当前草稿，读取最新保存版本。",
    failed: "请求失败", conflict: "组已被修改。草稿仍保留；请重新读取已保存组后再尝试。",
    unavailable: "新选实例已不可用，请刷新目录并核对选择。",
    forbidden: "需要当前有效管理员及 operations.manage 权限；写入还需 tools.invoke。", csrf: "请求票据无效或已过期，请重试以获取新票据。",
    checkCreate: "核对保存结果", retryCreate: "重试原创建", createChanged: "创建结果未确认且草稿已修改。请先核对保存结果或重试原创建；当前编辑仍保留。",
    createRecovered: "已找回保存的组。当前编辑仍保留，保存即可更新此组。", createAbsent: "暂未找到保存结果。请重试原创建；未找到不代表上次请求失败。",
    createUnconfirmed: "创建结果尚未确认，请核对保存结果或重试原创建。",
    createDeleted: "此创建请求对应的组已删除，不会重新创建；需要时请另开新草稿。",
    createClose: "创建结果尚未确认。放弃草稿也会忘记其恢复键，不会删除可能已保存的组。请先核对结果；另开新草稿会创建另一个组。",
    requestCapacity: "创建回执容量已满，本次请求未新建组；草稿仍保留。已有请求仍可核对或重放。",
    recoveryTitle: "有一个创建结果待核对", recoveryHint: "仅为当前用户和 Gate 保留了请求键，无法恢复未保存的编辑内容。请只读核对保存结果，或明确放弃此恢复记录后再创建其他组。",
    recoveryAbsent: "暂未找到保存结果，不代表上次请求失败。请求键仍保留，不会自动创建组。",
    abandonRecovery: "放弃恢复记录", abandonRecoveryHint: "要忘记此请求键吗？组可能已保存，不会被删除。原草稿无法恢复，再创建可能产生重复组。",
    recoveredAfterReload: "已找到保存的组，未保存的编辑内容未恢复。", recoveryUnavailable: "浏览器恢复存储不可用，请勿依赖刷新来找回此请求键。",
    timeout: "请求超时，结果尚未确认；请刷新已保存组或列表后再重试。",
    notFound: "组已不存在，请刷新列表。", refresh: "刷新", paging: "实例分页", memberLimit: "最多选择 1,000 个实例。", notLoaded: "未载入",
  },
} satisfies Record<Locale, Record<string, string>>

export const groupCopy = (locale: Locale) => copy[locale]
export function groupError(cause: unknown, locale: Locale): string {
  const c = groupCopy(locale), message = cause instanceof Error ? cause.message : String(cause)
  if (message.includes("group_revision_conflict")) return c.conflict
  if (message.includes("group_instance_unavailable") || message.includes("group_default_unavailable")) return c.unavailable
  if (message.includes("group_admin_required") || message.includes("group_connection_invalid")) return c.forbidden
  if (message.includes("csrf")) return c.csrf
  if (message.includes("group_request_timeout")) return c.timeout
  if (message.includes("group_request_conflict")) return c.createChanged
  if (message.includes("group_request_not_found")) return c.createAbsent
  if (message.includes("group_request_deleted")) return c.createDeleted
  if (message.includes("group_request_capacity")) return c.requestCapacity
  if (message.includes("group_not_found")) return c.notFound
  return `${c.failed}: ${message}`
}

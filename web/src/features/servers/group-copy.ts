import type { Locale } from "@/i18n"

const copy = {
  "en-US": {
    groups: "Groups", instances: "Instances", newGroup: "Create group", edit: "Edit group", delete: "Delete group",
    ungrouped: "Ungrouped", select: "Select a group or ungrouped instances", searchGroups: "Search groups by name or ID",
    searchInstances: "Search instances by name or ID", active: "Active", archived: "Archived", all: "All",
    name: "Name", description: "Description", state: "State", members: "Members", instanceId: "Instance ID",
    saved: "Group saved", deleted: "Group deleted", retry: "Retry", reload: "Reload saved group", save: "Save group",
    missing: "Missing / needs confirmation", noMatches: "No matches", empty: "No groups yet", selected: "selected",
    metadata: "Groups only organize existing instances. Membership copies no configuration and grants no access. Archiving or deleting a group only changes its metadata and relationships; services keep running.",
    missingHint: "Missing members can be retained or removed. To confirm a restored instance, uncheck it and explicitly select it again in the current catalog.",
    deleteTitle: "Delete this group?", reloadTitle: "Reload saved group?", reloadHint: "Discard this draft and read the current saved revision.",
    failed: "Request failed", conflict: "The group changed. Your draft is intact; reload the saved group before trying again.",
    unavailable: "A newly selected instance is unavailable. Refresh the catalog and check the selection.",
    forbidden: "A current administrator with operations.manage is required.", csrf: "The request ticket is invalid or expired. Try again to obtain a fresh ticket.",
    timeout: "The request timed out. Its result is unconfirmed; refresh the saved group/list before retrying.",
    notFound: "The group no longer exists. Refresh the list.", refresh: "Refresh", paging: "Instance pages", memberLimit: "Select up to 1,000 instances.", notLoaded: "Not loaded",
  },
  "zh-CN": {
    groups: "组", instances: "实例", newGroup: "创建组", edit: "编辑组", delete: "删除组",
    ungrouped: "未分组", select: "选择组或未分组实例", searchGroups: "按名称或 ID 搜索组",
    searchInstances: "按名称或 ID 搜索实例", active: "有效", archived: "已归档", all: "全部",
    name: "名称", description: "说明", state: "状态", members: "成员", instanceId: "实例 ID",
    saved: "组已保存", deleted: "组已删除", retry: "重试", reload: "重新读取已保存组", save: "保存组",
    missing: "缺失 / 待确认", noMatches: "无匹配结果", empty: "尚未创建组", selected: "已选择",
    metadata: "组只整理已有实例。归组不复制配置，也不授予访问权限。归档或删除组只改变元数据和关系，服务继续运行。",
    missingHint: "缺失成员可以保留或移除。恢复的实例须在当前目录中取消选择后再显式选中，才能重新确认。",
    deleteTitle: "删除此组？", reloadTitle: "重新读取已保存组？", reloadHint: "放弃当前草稿，读取最新保存版本。",
    failed: "请求失败", conflict: "组已被修改。草稿仍保留；请重新读取已保存组后再尝试。",
    unavailable: "新选实例已不可用，请刷新目录并核对选择。",
    forbidden: "需要当前有效管理员及 operations.manage 权限。", csrf: "请求票据无效或已过期，请重试以获取新票据。",
    timeout: "请求超时，结果尚未确认；请刷新已保存组或列表后再重试。",
    notFound: "组已不存在，请刷新列表。", refresh: "刷新", paging: "实例分页", memberLimit: "最多选择 1,000 个实例。", notLoaded: "未载入",
  },
} satisfies Record<Locale, Record<string, string>>

export const groupCopy = (locale: Locale) => copy[locale]
export function groupError(cause: unknown, locale: Locale): string {
  const c = groupCopy(locale), message = cause instanceof Error ? cause.message : String(cause)
  if (message.includes("group_revision_conflict")) return c.conflict
  if (message.includes("group_instance_unavailable")) return c.unavailable
  if (message.includes("group_admin_required") || message.includes("group_connection_invalid")) return c.forbidden
  if (message.includes("csrf")) return c.csrf
  if (message.includes("group_request_timeout")) return c.timeout
  if (message.includes("group_not_found")) return c.notFound
  return `${c.failed}: ${message}`
}

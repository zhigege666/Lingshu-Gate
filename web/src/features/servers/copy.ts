import type { Locale } from "@/i18n"

const zh = {
  directory: "MCP 服务", search: "搜索服务名称或 ID", all: "全部", running: "运行中", issues: "异常",
  add: "接入服务", refresh: "刷新", overview: "概览", tools: "工具", logs: "日志", configuration: "配置",
  viewTools: "查看工具", more: "更多操作", connection: "连接信息", readiness: "工具访问状态",
  transport: "传输方式", process: "运行状态", launch: "运行类型", pid: "进程 ID", discovered: "已发现工具",
  health: "健康检查", healthOff: "未启用", healthOffHint: "当前未配置健康检查，运行状态不代表业务调用已验证。",
  published: "已发布分类", visible: "当前登录身份可见", client: "客户端加载", clientUnknown: "未验证",
  clientHint: "此处无法确认客户端是否已加载工具，请在对应客户端验证。",
  noClassificationAccess: "无分类查看权限", unread: "未读取", loading: "加载中", visibleError: "工具目录读取失败",
  visibleHint: "按当前登录身份的工具目录统计，与客户端 API Token 的权限范围可能不同。",
  noToolsAccess: "当前账号无权读取工具目录", preview: "工具预览", allTools: "查看全部工具", name: "工具名称",
  description: "描述", classification: "生效分类", read: "只读", write: "读写", review: "待确认", annotatedRead: "只读标注",
  unknownAccess: "未读取分类", searchTools: "搜索工具名称或描述", noTools: "暂无匹配工具", inputSchema: "输入参数",
  toolDetails: "工具详情", viewSchema: "查看参数", metadata: "其他元数据", emptyServices: "还没有 MCP 服务",
  emptyHint: "接入一个外部 HTTP 服务，或配置本机受管服务。", noMatches: "没有匹配的服务", selectService: "选择一个 MCP 服务",
  back: "返回服务列表", loadFailed: "读取失败", retry: "重试", serviceLogs: "服务日志", events: "事件", recovery: "恢复记录",
  time: "时间", level: "级别", eventType: "事件类型", message: "摘要", recordDetails: "记录详情", noRecords: "暂无记录",
  logLimit: "显示最近 40 条记录", openLogs: "打开完整日志页", manifest: "服务配置", configPath: "配置文件",
  runtimeCache: "运行缓存", cacheHint: "展开后才统计缓存目录，不影响详情首屏加载。", fullDiagnostics: "完整诊断",
  diagnosticHint: "按需读取日志、恢复历史与缓存信息，生成诊断提示。", desired: "期望状态", keepRunning: "保持运行",
  keepStopped: "保持停止", lastStarted: "最近启动", lastError: "最近错误", restartPolicy: "自动恢复", enabled: "启用", disabled: "停用",
  start: "启动", stop: "停止", restart: "重启", connect: "连接", disconnect: "断开", failure: "失败", openClassification: "查看分类",
} as const

const en: Record<keyof typeof zh, string> = {
  directory: "MCP services", search: "Search name or ID", all: "All", running: "Running", issues: "Issues",
  add: "Connect service", refresh: "Refresh", overview: "Overview", tools: "Tools", logs: "Logs", configuration: "Configuration",
  viewTools: "View tools", more: "More actions", connection: "Connection", readiness: "Tool access",
  transport: "Transport", process: "Runtime status", launch: "Launch type", pid: "Process ID", discovered: "Discovered tools",
  health: "Health checks", healthOff: "Not enabled", healthOffHint: "Health checks are not configured. Running status does not verify business calls.",
  published: "Published classifications", visible: "Visible to signed-in user", client: "Client loading", clientUnknown: "Not verified",
  clientHint: "Gate cannot confirm whether a client loaded the tools. Verify in that client.",
  noClassificationAccess: "Classification access required", unread: "Not loaded", loading: "Loading", visibleError: "Tool catalog could not be loaded",
  visibleHint: "Counted from the signed-in user's tool catalog. A client's API token may have different scopes.",
  noToolsAccess: "This account cannot read the tool catalog", preview: "Tool preview", allTools: "View all tools", name: "Tool name",
  description: "Description", classification: "Effective classification", read: "Read", write: "Read + write", review: "Review required", annotatedRead: "Read-only hint",
  unknownAccess: "Not loaded", searchTools: "Search tool name or description", noTools: "No matching tools", inputSchema: "Input schema",
  toolDetails: "Tool details", viewSchema: "View schema", metadata: "Other metadata", emptyServices: "No MCP services yet",
  emptyHint: "Connect an external HTTP service or configure a managed local service.", noMatches: "No matching services", selectService: "Select an MCP service",
  back: "Back to services", loadFailed: "Could not load", retry: "Retry", serviceLogs: "Service logs", events: "Events", recovery: "Recovery history",
  time: "Time", level: "Level", eventType: "Event type", message: "Summary", recordDetails: "Record details", noRecords: "No records",
  logLimit: "Latest 40 records", openLogs: "Open full log view", manifest: "Service configuration", configPath: "Configuration file",
  runtimeCache: "Runtime cache", cacheHint: "Directory size is calculated only when expanded, keeping initial details fast.", fullDiagnostics: "Full diagnostics",
  diagnosticHint: "Load logs, recovery history, and cache metadata on demand to derive diagnostic hints.", desired: "Desired state", keepRunning: "Keep running",
  keepStopped: "Keep stopped", lastStarted: "Last started", lastError: "Last error", restartPolicy: "Automatic recovery", enabled: "Enabled", disabled: "Disabled",
  start: "Start", stop: "Stop", restart: "Restart", connect: "Connect", disconnect: "Disconnect", failure: "Failed", openClassification: "View classifications",
}

export type ServerCopy = Record<keyof typeof zh, string>
export const serverCopy = (locale: Locale): ServerCopy => locale === "zh-CN" ? zh : en

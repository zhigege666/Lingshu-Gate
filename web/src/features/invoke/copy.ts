import type { Locale } from "@/i18n"

const zh = {
  title: "工具调用", description: "选择服务和工具，配置参数，查看返回结果。", selectTarget: "选择服务与工具", configure: "配置参数",
  service: "MCP 服务", builtin: "内置工具", otherSource: "工具来源", unknownService: "未提供服务 ID", serviceId: "服务实例 ID", tool: "工具", available: "个可用工具",
  searchServices: "搜索服务名称或 ID", searchTools: "搜索工具名称或 ID", noTools: "当前服务没有可调用工具", empty: "暂无可调用工具", emptyHint: "请确认工具已发布，并且当前账号具有访问权限。", loading: "正在加载工具…", loadFailed: "工具目录读取失败", retry: "重新加载",
  form: "表单", json: "JSON", editorMode: "参数编辑方式", example: "填入示例", defaults: "恢复默认", undo: "撤销", format: "格式化", docs: "参数说明", hideDocs: "收起说明",
  sampleHint: "已按工具定义预填，请检查后运行。", defaultsHint: "已恢复声明的默认值，缺失的必填项请补齐。", editedHint: "已保留当前服务与工具的编辑草稿。", noSampleHint: "工具未提供可用示例，请填写必需参数。", schemaChanged: "工具参数定义已更新，当前草稿已保留；运行前请重新核对。",
  required: "必填", optional: "可选", omit: "不传入", enter: "请填写", choose: "请选择", true: "是 (true)", false: "否 (false)", null: "空值 (null)", setValue: "填写值", setNull: "设为 null", addObject: "添加对象",
  defaultValue: "默认值", sampleValue: "示例", constraints: "约束", noDescription: "工具未提供字段说明。", docHint: "说明仅供阅读，不会加入请求。", complex: "此字段使用 JSON 编辑", editJson: "在 JSON 中编辑", unsupported: "此参数结构需要使用 JSON 编辑。", unknownFields: "未声明字段已保留，请在 JSON 中查看。", noParameters: "此工具无需参数，将提交空对象。",
  invalidJson: "JSON 格式有误，请检查引号、逗号和括号。当前输入已保留。", objectRequired: "参数必须是 JSON 对象。", schemaInvalid: "无法校验此工具的参数定义，请检查 Schema 的版本或引用。", requiredError: "为必填项", typeError: "类型不匹配", rangeError: "超出允许范围", enumError: "请选择工具允许的值", unknownError: "包含未声明字段", invalidValue: "不符合工具参数要求",
  noFixedFields: "工具未声明固定字段，可在 JSON 中配置参数。",
  run: "运行工具", running: "运行中…", target: "当前目标", result: "运行结果", idle: "未运行", success: "调用成功", failed: "调用失败", waiting: "等待首次调用", waitingHint: "运行工具后，在此查看返回结果。", runningHint: "正在等待服务返回结果。", lastResult: "上次调用", copy: "复制结果", copied: "已复制", copyFailed: "复制失败，请手动选择结果文本。", unavailable: "当前选择的工具已不可用，请重新选择。",
} as const
const en: Record<keyof typeof zh, string> = {
  title: "Invoke tool", description: "Select a service and tool, edit arguments, and inspect the response.", selectTarget: "Select service and tool", configure: "Configure arguments",
  service: "MCP service", builtin: "Built-in tools", otherSource: "Tool source", unknownService: "Service ID unavailable", serviceId: "Service instance ID", tool: "Tool", available: "available tools",
  searchServices: "Search service name or ID", searchTools: "Search tool name or ID", noTools: "No callable tools for this service", empty: "No callable tools", emptyHint: "Check that tools are published and your account has access.", loading: "Loading tools…", loadFailed: "Could not load the tool catalog", retry: "Reload",
  form: "Form", json: "JSON", editorMode: "Argument editor mode", example: "Fill example", defaults: "Restore defaults", undo: "Undo", format: "Format", docs: "Field reference", hideDocs: "Hide reference",
  sampleHint: "Prefilled from the tool definition. Review before running.", defaultsHint: "Declared defaults restored. Complete missing required fields.", editedHint: "Draft retained for this service and tool.", noSampleHint: "No usable example was supplied. Complete the required arguments.", schemaChanged: "The tool schema changed. Your draft is retained; review it before running.",
  required: "Required", optional: "Optional", omit: "Omit", enter: "Enter a value", choose: "Choose a value", true: "Yes (true)", false: "No (false)", null: "Null", setValue: "Enter value", setNull: "Set null", addObject: "Add object",
  defaultValue: "Default", sampleValue: "Example", constraints: "Constraints", noDescription: "No field description supplied.", docHint: "Reference text is not included in requests.", complex: "Edit this field in JSON", editJson: "Edit in JSON", unsupported: "Use JSON for this argument structure.", unknownFields: "Undeclared fields are retained. Inspect them in JSON.", noParameters: "This tool takes no arguments; an empty object will be sent.",
  invalidJson: "Invalid JSON. Check quotes, commas and brackets. Your input has been retained.", objectRequired: "Arguments must be a JSON object.", schemaInvalid: "Unable to validate this tool schema. Check its dialect or references.", requiredError: "is required", typeError: "incorrect type", rangeError: "outside the allowed range", enumError: "choose an allowed value", unknownError: "contains an undeclared field", invalidValue: "does not satisfy the tool schema",
  noFixedFields: "No fixed fields are declared. Configure arguments in JSON.",
  run: "Run tool", running: "Running…", target: "Current target", result: "Result", idle: "Not run", success: "Succeeded", failed: "Failed", waiting: "Waiting for the first call", waitingHint: "Run the tool to inspect its response here.", runningHint: "Waiting for the service response.", lastResult: "Last invocation", copy: "Copy result", copied: "Copied", copyFailed: "Could not copy. Select and copy the result manually.", unavailable: "The selected tool is no longer available. Select it again.",
}
export type InvokeCopy = Record<keyof typeof zh, string>
export const invokeCopy = (locale: Locale): InvokeCopy => locale === "zh-CN" ? zh : en

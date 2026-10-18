# 工具参数限制

[English](../argument-policies.md) · [文档索引](README.md)

参数策略为原本已有调用权限的工具增加限制，不授予权限。策略默认关闭，按工具 ID 持久保存，覆盖 REST、直接 MCP、目录、固定工具和分组调用。

## Console 编辑

具有真实认证与 `grants.manage` 权限时，从**工具 → 详情 → 参数限制**进入。启用策略、添加条件、按需校验示例，再保存。所有条件必须同时满足；字段缺失会拒绝，包括与 `null` 比较时。

| 运算 | 示例 | 含义 |
|---|---|---|
| `equals` | `{"id":"tenant","pointer":"/tenant","operator":"equals","value":"example"}` | 严格 JSON 相等，`true` 不等于数字 `1` |
| `allowed_values` | `{"id":"region","pointer":"/region","operator":"allowed_values","values":["eu","us"]}` | 等于最多 64 个显式候选之一 |
| `number_range` | `{"id":"size","pointer":"/limit","operator":"number_range","minimum":1,"maximum":50}` | 包含边界的数值范围，拒绝数字字符串和布尔值 |
| `string_prefix` | `{"id":"prefix","pointer":"/path","operator":"string_prefix","prefix":"/approved/"}` | 字符串必须以指定文本开头 |

使用 JSON Pointer：`/a~1b` 选择键 `a/b`，`/~0` 选择 `~`，`/items/0` 选择数组首项。数组索引必须是规范非负整数。空指针选择整个参数对象。

前缀规则只是字符串检查。文件系统安全依靠工具自身的目录约束；前缀本身不会解析符号链接或阻止路径穿越。

最多 **64 条规则、64 KiB 规则 JSON、24 层、8,192 节点**。编辑器拒绝重复键以及无法准确保留的数字，包括不安全的 JavaScript 整数，并保留原输入供修正。自动缩进超出预算时，大型合法值以紧凑 JSON 展示。

## 实际参数与纯预览

Gate 使用第一方工具明确的参数准备器，沿用已知默认值和类型归一化；不猜测未知 MCP 工具的默认值。真正派发时，策略与执行器使用同一份自有参数对象。在文件引用转换、等待运行锁和允许的只读重试后，重新检查身份、权限、定义和策略。

**校验示例**不调用工具、不保存草稿。`fileRef` 需要真实运行时按用户和目标转换为 `filePath`；预览返回 `argument_policy_preview_requires_runtime`，不会虚称已验证真实执行。示例通过不保证之后权限和参数仍未变化。

保存冲突或结果未知时，应先读取当前策略再保存。Console 刷新时保留草稿，持续提示需要刷新，并要求对照当前版本。清空或校验示例不能解除未知保存状态；带未保存规则或示例文本关闭时，会要求确认放弃。

## API 与审计

| 方法与路径 | 操作 |
|---|---|
| `GET /v1/tools/{tool_id}/argument-policy` | 读取启用状态、规则及版本 |
| `POST /v1/tools/{tool_id}/argument-policy/preview` | 校验草稿和示例，不执行 |
| `POST /v1/tools/{tool_id}/argument-policy/csrf?request_digest=<SHA-256>` | 获取绑定精确 PUT 正文的会话确认 |
| `PUT /v1/tools/{tool_id}/argument-policy` | 保存 `expected_revision`、`enabled`、`rules` |

Console 写入要求同源会话确认，摘要覆盖**实际发送的 UTF-8 字节**，不能对另行序列化的 JSON 计算。API 令牌写入同样受权限、scope 和委托上限约束。版本 CAS、策略写入与审计在同一事务中完成；审计失败回滚。

策略拒绝只记录稳定规则 ID、指针、策略版本和原因，不保留参数/结果值。执行前拒绝为 `not_invoked`；若首次读取已到达下游、重试才被拒绝，审计保留已派发事实并记为错误，不会声称从未执行。

策略在工具临时消失后保留；存储损坏时拒绝执行。升级新增 `0023_tool_argument_policy`；旧版本即使能打开数据库，也不会执行新参数策略。遵循[升级流程](deployment.md)，保留一致性备份。

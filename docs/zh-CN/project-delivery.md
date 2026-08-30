# 项目交付

[English](../project-delivery.md) · [文档索引](README.md)

项目交付把一个明确可信的 MCP 项目依次经过确定性打包、可续传上传、预检、构建计划、构建执行、部署、启动和工具分类对账。

这是代码执行流程，不是不可信代码沙箱。请在专用操作系统账户下使用原生 Gate 部署。Docker Core 会主动拒绝本机构建执行和受管 stdio 启动。

## 安全模型

- 管理员选择并信任准确的项目根目录。
- 上传前复核完整的 Included File 列表。
- 上传、构建、部署、覆盖、启动、取消和放弃都有明确确认边界。
- 每个写操作都使用幂等键。只有全部输入一致时，重试才能复用同一个键。
- SHA-256 摘要绑定归档、源码、构建计划、部署配置、凭据引用和发现到的工具快照。
- 构建命令来自经过复核的计划；Create 操作不接受任意替换命令。
- 只有脱敏绑定摘要匹配时，才能保留已有凭据引用。
- 工具刷新绝不会自动扩大有效权限。

## 自带 Delivery Skill

本仓库维护的 Skill 位于：

```text
.agents/skills/lingshu-gate-upload-build-start/
```

在能够加载仓库 Skill 的环境中配置目标 Gate 实例后，通过 `$lingshu-gate-upload-build-start` 调用。使用前应阅读：

- `SKILL.md`：强制边界与编排行为；
- `references/workflow.md`：阶段转换和轮询；
- `references/mcp-contract.md`：准确输入、输出和稳定错误码。

Skill 可以自动执行受限的机械步骤，但不能替代管理员的信任判断和确认。

## 确定性本地打包

在项目树保持稳定时，使用 PowerShell 7 或更高版本：

```powershell
pwsh -File .agents/skills/lingshu-gate-upload-build-start/scripts/New-LingshuGateProjectBundle.ps1 `
  -ProjectRoot /path/to/trusted-project `
  -OutputPath /path/outside/project-root/project.zip
```

输出路径必须位于项目根目录之外。脚本会拒绝 Link、敏感路径族、高置信度 Secret 内容、超过 3,000 个文件、超过 200 MiB 源码，或大于 50 MiB 的 ZIP。它排除常见版本控制、依赖和构建输出目录，并从临时快照创建归档。

内容扫描是启发式检查，不能证明项目中没有 Secret。必须复核每个 `included_files` 条目，以及报告的文件列表和 ZIP SHA-256。不要通过排除被标记的 Secret 后继续运行来绕过拒绝。

## 工作流

| 阶段 | 读取或计划 | 经确认的写操作 | 保留证据 |
|---|---|---|---|
| 打包 | 稳定源码树和本地扫描 | 创建本地 ZIP | 包含文件、大小、入口标记、文件列表摘要、ZIP 摘要 |
| 上传 | 目标、大小、ZIP 摘要 | Begin；受限 Chunk/Commit 续接 | `transfer_id`、`upload_id`、`source_sha256` |
| 预检 | 源码和运行时检查 | 无 | 检查结果和识别到的项目根目录 |
| 计划 | 准确的安装与构建步骤 | 无 | 命令、超时、网络影响、`plan_fingerprint` |
| 构建 | 轮询增量状态和日志 | Create 或 Cancel | `build_id`、终态、最终日志游标 |
| 部署 | 成功构建和目标状态 | 新部署或绑定摘要的覆盖 | `deployment_id`、`config_digest`、脱敏凭据状态 |
| 启动 | 已部署配置 | Start | 观测到的 Running 和健康状态 |
| 对账 | 发现到的工具定义 | Refresh Tools | `tool_snapshot_digest`、变化计数、复核状态 |

### 1. 上传

复核归档并确认上传后：

1. 调用 `gate_project_upload_begin`，提供文件名、总字节数、归档 SHA-256、新幂等键和 `confirmed=true`。
2. 从返回的 `next_offset` 开始调用 `gate_project_upload_chunk`；每块绑定自身 SHA-256 和独立幂等键。
3. 网络中断后，从服务端返回的 Offset 续传。
4. 所有字节都被接受后，调用 `gate_project_upload_commit`。

Begin 调用为其受限上传 Session 建立确认。Chunk 和 Commit 不接受 `confirmed`。禁止打印 `data_base64`，也不要把完整归档放入一个参数。

### 2. 预检和计划

调用 `gate_build_preflight`。如果 Status 不是 `ok`，立即停止。然后调用 `gate_build_plan`，向管理员展示：

- 解析后的运行时和项目根目录；
- 准确步骤和命令；
- 是否涉及依赖安装和网络访问；
- 源码 SHA-256、超时和计划指纹。

确认构建后，把计划输入原样返回给 `gate_build_create`，同时提供源码摘要、指纹、超时、新幂等键和 `confirmed=true`。输入漂移会产生冲突，不会静默构建另一份计划。

### 3. 构建

使用 `after_sequence` 和最多 200 条日志轮询 `gate_build_status`。保存每次返回的 `next_sequence`，只请求增量日志。一次 MCP 请求超时不能证明构建失败；应继续查询已有 `build_id`。

只有构建进入终态 `success` 才能继续。取消是单独的确认写操作；在状态进入终态前，取消仍未完成。

### 4. 部署和启动

部署前展示构建、源码与计划摘要、Artifact 和 Manifest 摘要、目标服务 ID、覆盖选项、当前配置摘要、脱敏凭据绑定摘要、缺失凭据、启动选项和工具刷新选项。

新目标使用 `overwrite=false` 部署。覆盖目标时：

1. 读取 `gate_server_status`；
2. 绑定 `expected_previous_config_digest`；
3. 存在凭据时使用 `credential_policy=preserve_existing`，并原样返回 `expected_credential_binding_digest`；
4. 任一摘要变化时停止，并要求重新复核。

部署默认 `start=false`。立即启动可以包含在确认后的部署操作中。如果单独启动，应再次确认，并以准确的已部署 `config_digest` 调用 `gate_server_start`。

### 5. 工具对账

进程报告 Running 后，校验健康和发现。只有确认后才能调用 `gate_server_refresh_tools`，并绑定当前配置摘要。

只有 `effective_permissions_expanded=false` 才能接受刷新。新增、变化、消失或重新出现的工具都保持未激活或 `needs_review`，直到人工复核并发布分类。

只有部署成功、观测状态为 Running、健康未失败、发现成功且分类对账没有扩大权限时，交付才完整完成；否则必须准确报告部分完成。

## 工具契约

| 工具 | 类型 | 确认和摘要边界 |
|---|---|---|
| `gate_project_upload_begin` | 写 | `confirmed=true`；归档大小与 SHA-256 |
| `gate_project_upload_chunk` | 写操作续接 | Transfer、Offset、Chunk SHA-256、幂等键 |
| `gate_project_upload_commit` | 写操作续接 | 完整确认会话和源码 SHA-256 |
| `gate_project_upload_abort` | 破坏性写 | 单独 `confirmed=true` |
| `gate_build_preflight` | 读 | Upload、运行时覆盖、项目根目录 |
| `gate_build_plan` | 读 | 预检输入以及安装和构建选项 |
| `gate_build_create` | 执行写 | `confirmed=true`；源码摘要和计划指纹 |
| `gate_build_status` | 读 | Build ID 和增量日志游标 |
| `gate_build_cancel` | 破坏性写 | 单独 `confirmed=true` |
| `gate_deploy_build` | 破坏性写 | `confirmed=true`；源码、计划、旧配置和凭据摘要 |
| `gate_deployment_status` | 读 | Deployment ID 和补偿状态 |
| `gate_server_start` | 执行写 | `confirmed=true`；预期配置摘要 |
| `gate_server_status` | 读 | 运行时、健康、配置摘要、脱敏凭据 |
| `gate_server_refresh_tools` | 执行写 | `confirmed=true`；配置摘要和工具快照结果 |

运行版本通过 `tools/list` 返回的准确 JSON Schema 是权威定义。未知字段会被拒绝。

## 失败恢复

- Chunk Offset 或摘要冲突：只从权威 Next Offset 续传；内容不同时创建新 Transfer。
- 预检或计划被阻止：不要创建构建。
- 构建失败：保留 Build ID 和增量日志；修改源码后创建新归档和计划。
- 幂等冲突：不能把不同输入绑定到已有键。
- 操作中断且完成状态未知：先检查返回资源的状态，再决定是否可以创建新写操作。
- 部署或启动失败：分别报告配置是否应用、运行时是否启动、补偿是否尝试或确认成功。
- 凭据摘要冲突：重新读取脱敏状态并再次复核；禁止要求把 Secret 放入工具参数。
- 工具刷新失败：保留已接受的快照，并将进程运行状态与刷新状态分开报告。

回滚、停止、删除、强制终止，以及状态未知后的重试，都需要管理员明确决定。

## 完成报告

记录源码与文件列表 SHA-256、计划指纹、脱敏凭据绑定摘要、工具快照摘要、Transfer/Upload/Build/Deployment/Server ID、分类变化计数、各阶段状态、最终日志游标、幂等重放情况，以及已验证和未验证的验收项。禁止包含 Secret、Base64 Chunk、完整进程输出或内部绝对路径。

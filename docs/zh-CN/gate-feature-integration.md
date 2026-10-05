# Gate 功能集成候选

[English](../gate-feature-integration.md) · [OAuth 分页](oauth-catalog-scaling.md) · [Native 执行器](native-executor.md)

`test/gate-feature-integration-20261005` 将已复审开发输入合入精确 main `d4786fd368e932bc758ea29da1a597c9d9551794`，版本保持 0.4.4。这是未发布 test 候选；main、tag、部署及宿主准备不在本次集成中。

| 输入 | 精确来源 | 集成处理 |
|---|---|---|
| OAuth UI、已存 grant 验证、候选分页、公共 catalog/group | `d8d4833bfdefbf7e679190565294f38f7a109145` | 普通三方合并的第一父提交，已包含复制的公共 `f51d1b18d7475034b61567be00ef999128918e83`／产品 `d99be556ff48e018792268abeb7c5a22c5517476` 改动 |
| Native 隔离获取／离线执行及安全修复 | `76bfe2c4eeae7f1a693e1d86b03c78e6098866d1` | 第二父提交，十九个 Native 提交全部保留真实祖先关系 |
| 公共 catalog 最终完整回归／包验证证据 | `6f3e87145a8ff581d8738ffbc3ee6f374ab56010` | 仅复制文档／数据，不重复产品 patch |

合并为 `31f5195`，纯文档证据复制为 `a089dc2`。未用伪祖先合并或单方源码覆盖。两输入分别修改 151、54 个路径，九个路径重叠。仅中英文 CHANGELOG 未发布标题存在文本冲突，双方条目保留到同一未发布区；README、安全指南、文档索引和 `main.py` 自动合并。

## 组合与安全复核

同一应用组合共享 catalog、显式 group router、OAuth 候选索引与 Native factory。GitImport 和 BuildDeploy 共用已配置隔离执行器及固定网络选择；group 定义保留独立存储和既有配置服务边界。即使提供启用的 Native 配置，Core 角色也不构造、启动 Native engine 边界。

Catalog/group 迁移保留 OAuth 输入的 0012–0016 顺序。Native 不增加冲突的 Gate migration，私有 job journal 使用独立 single-owner SQLite 文件。配置／runtime 锁、不可变 registry snapshot、选定实例 guard、当前权限检查、管理资源 allowlist 与直接 MCP 接口均保留已复审输入逻辑。

组合 lifespan 测试发现并修正一处相互作用：Native close 未知不能跳过独立 external-configuration/runtime 关闭。这些清理在 `finally` 中执行，Native 异常和保留的 journal lease 不变；仅关闭成功才发出 `gate.shutdown_complete`，不把未知执行报告为已终止。新增组合测试覆盖成功、未知关闭、Core 排除及 catalog/group migrations 共存。

## 包管理器支持

| 阶段 | 支持 | 明确限制 |
|---|---|---|
| 官方固定工具准备 | npm 9–11、pnpm 8–11、Yarn Classic 1.22，校验 integrity／engine | 禁 latest、全局安装、Corepack、自动下载 Node 和项目指定 image |
| 冻结离线依赖安装 | npm registry lock v2/v3、pnpm 8/9 受审 v3 store、Yarn Classic 1.22 registry mirror/cache | pnpm 10/11 package-ID store、Yarn Berry、workspace/link/patch/Git/custom-origin/弱完整性缓存仍拒绝 |
| 离线构建 | 选定、已校验 npm/pnpm/Yarn `run build`，包括支持的 build-only 项目 | 禁任意命令／路径／image、网络／秘密继承或 manager 替代 |
| Python | Native 之外既有 upload/direct legacy 路径 | Git/profile Python sandbox 缓存不支持 |
| Docker Core | 既有 gateway/catalog/OAuth/group control plane | 无 engine/socket、项目执行、远端 worker/deploy 或 stdio 桥接 |

## 验证合同

最终结果须标明精确集成候选 SHA。输入已有 benchmark、截图及完整回归计数是其记录 SHA 的历史证据，不是当前组合树的验收。执行 frozen Python/npm 准备、Ruff、mypy、完整 backend、前端 type/UX、Vitest、两个前端 build、身份／版本、Compose 语法及空白检查。构建静态资源时，不并行运行读取这些资源的 backend/browser 用例。

Backend 回归包含 OAuth A/B、普通／management 资源、直接 MCP/HTTP 兼容、catalog/group 权限与派发锁、配置／runtime／migrations，以及 Native acquisition/journal/cleanup 全套。包验证需从构建 wheel 执行 schema 验证子进程，移除 checkout import path，确认 deadline/取消子进程被回收，并从同一 artifact 导入 Native 模块。实际 Linux frozen worker、本地假数据浏览器验证如执行，单独报告证据。

真实 rootless Podman namespace/controller、受审 image/cache、凭据／provider／client 和 nx5 部署仍由操作员／根代理验收。缺少已配置宿主前提时，四项 opt-in Native host 测试保持 skip，不降级 host shell。合成集成成功不表示 Docker 用户交付／构建／部署／启动链完成。

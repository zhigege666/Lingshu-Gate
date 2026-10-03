# Git/网络整合记录

真实执行功能仍未完成，详见 [adapter 与基础设施范围决策](git-executor-decision.md)。当前补丁包含控制/UI/计划实现与拟议执行契约，不能作为 Git/install 交付功能已可用的声明。

审核修复增加协调器重启中断/容量释放持久化、准确九列导入 INSERT、活跃代理引用清理，以及现有 local stdio/受管 HTTP 客户端和 Manifest 预检消费的准确工具 pin。新增整合交叉点：`mcp_manifest.py`、`mcp_manifest_validation.py`、`mcp_stdio_client.py`、`mcp_managed_http_client.py` 及上传/构建删除事务。未改 auth/session，未新增 worker/远程运行时。构建 worker 待决策，不包含远程 MCP runtime/bridge/部署体系。

[English](../git-network-integration.md)

本轮执行边界修复从两条只读 Manifest 校验路由移除版本探测。`config.py` 增加服务端管理员维护的不可变工具注册表；固定版本启动仅使用登记 Node/JS CLI，不受项目 command/PATH 影响。校验只查元数据，版本保持未验证。整合时单独合并该 Settings 字段及环境解析；本修复不增加数据库或认证/session 迁移。

基线：main `362fffccfbc28a362f7f3431759319128cdbabd1`。分支：`feat/git-import-network-settings`。不提交、推送、开 PR、部署或配置真实凭据。

请与独立内置 OAuth 任务有意识合并以下公共文件：

- `database.py`：注册唯一命名的增量 Git/网络迁移；两项迁移均保留，不替换 schema。
- `access_control.py`：增加独立配置管理和网络调用权限，保留 OAuth 权限。
- `main.py`：组装设置/导入服务、路由和工具，不改外部认证模块。
- Console 路由、导航文案、`App.tsx`：增加系统设置，整合时保留 OAuth 标签/路由。
- `build_deploy.py`、`build_preflight.py`、`build_plan.py`、`project_delivery_mcp.py`：扩展已有交付来源/计划，保留确认、归属、摘要、幂等、令牌及分类检查。

生产安全执行器缺失是真实 Git/网络执行的发布阻塞，不应放宽 local/Core 边界来绕过。本静态任务提供测试代码但不运行，最终证据记录逐项列明静态检查和验收缺口。

新增共享修改：`application/delivery_drafts.py` 与 Console 交付草稿/组件增加版本化依赖工具覆盖；自带 Delivery Skill 契约描述相同的确认准备阶段和 Git 续接。合并 `SECURITY*`、README/文档导航及双语发行文档时需保留 OAuth 增量。生产组合仍不注入网络执行器。

独立 OAuth 审核正在修改 session purpose 校验和交互容量，并会继续修改 `auth.py` 及 session 迁移。本分支不修改 `auth.py`、`external_auth.py` 或 OAuth/session 表。整合时保留两项任务各自唯一命名的迁移，组装这些路由时保留新的 session/scope 校验。请对最终 OAuth 分支共同复核 `main.py`、`database.py`、`access_control.py` 与导航；本工作树没有合并 OAuth 分支，也没有针对其完成行为验证。

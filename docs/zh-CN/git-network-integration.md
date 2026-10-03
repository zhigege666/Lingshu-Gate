# Git/网络整合记录

[English](../git-network-integration.md) · [验证记录](release-validation.md)

0.4.0 候选将 Git/网络分支与 main `d500116548a90e4edaa0bfa0e0c1138afe45354a` 整合，包含内置 OAuth PR #42。Git 分支原始基线为 `362fffccfbc28a362f7f3431759319128cdbabd1`；PR #43 通过合并 main 保留原有历史，没有改写 OAuth 分支。

**生产 Git 拉取、代理测试、工具准备和指定网络安装仍不可用。** 生产组合没有提供 `SafeNetworkExecutor`。本次发行包含配置、策略、计划、API/UI 及整合契约；合成 adapter 测试不提供生产隔离边界。详见[执行缺口](git-executor-decision.md)。

整合树保留以下共享修改：

- `database.py` 注册 `0004_gate_git_network` 与 `0007_session_purpose`。独立 OAuth store 注册 `0006_builtin_oauth` 和 `0008_oauth_interaction_capacity`。两条注册路径和所有唯一命名迁移均须保留。
- `main.py`、`access_control.py`、Console 路由、导航与翻译组合两项功能。设置管理、网络调用和现有交付权限仍独立；内置与外部 OAuth 保留各自受控标签和会话用途。
- `build_deploy.py`、`build_preflight.py`、`build_plan.py`、`project_delivery_mcp.py`、`application/delivery_drafts.py` 与 Delivery Skill 扩展已有上传/构建/部署/启动链路。归属、确认、digest、幂等、令牌和分类检查仍必需。
- `config.py`、`mcp_manifest.py`、`mcp_manifest_validation.py`、`mcp_stdio_client.py` 和 `mcp_managed_http_client.py` 共用管理员复核工具注册表和准确 manager pin。只读校验仅查元数据，不执行程序；仅已授权的原生启动进行有界探测。Core 均不执行。
- 源码/构建删除事务、README/文档索引及 `SECURITY*` 保留两项功能边界。Docker Core 仍无特权，不挂引擎 socket。

Git 审核修复保留明确选择的项目根目录及其重分析，在不记录仓库 URL 或代理值的前提下审计成功计划创建，每轮最多清理 100 个过期未使用计划，并限制每用户 32 个、全局 256 个未使用计划。任何导入引用均保留计划来源，包括失败和取消的导入。重启中断和容量释放不宣称缺失执行器已终止。

整合测试覆盖真实 HTTP 审计路径、嵌套快照、工具/锁文件校验、脱敏、权限、取消/超时、引用/版本保留，以及失败不替换旧部署。OAuth 字符串秘密继续脱敏，JSON-RPC 保留范围中的负整数错误码保持可用。浏览器回归覆盖明确导航到外部模式，以及历史构建先加载所属项目再进入部署确认。已执行结果与真实网络验收缺口在[验证记录](release-validation.md)中分别记录。

本次发行准备不部署生产、不连接用户 Git/代理、不执行 SSH、不配置外部账户或真实凭据。隔离 worker 的实现与独立审查仍需另行基础设施决策；没有增加本地回退或远程 MCP bridge。

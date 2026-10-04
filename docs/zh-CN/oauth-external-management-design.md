# 外部配置的管理员 OAuth

[English](../oauth-external-management-design.md) · [当前外部配置流程](external-mcp-configuration.md)

这是已确定的增量实现方向，本候选尚未启用 OAuth 管理权限。现有 ChatGPT 业务连接目前不能配置外部 MCP。本轮没有生产授权、客户端修改或凭据配置。

## 权限与目标

沿用权限名 `operations.manage` 作为明确 OAuth 管理 scope。仅有 `tools.invoke` 绝不获得配置权限。只接受 Gate 内置 issuer 验证的 token，其他已信任 JWT issuer 不适用。必须是当前有效管理员并具有实时 `operations.manage` 角色权限。应用、取消和探测保留额外 `tools.invoke` 权限/scope 上限。所有所需 scope 均须位于 JWT、当前已启用 client、有效 grant、有效 refresh family 的交集中。

grant 精确授权 `gate_mcp_config_plan`、`gate_mcp_config_apply`、`gate_mcp_config_status`、`gate_mcp_config_cancel`，绑定定义/schema 指纹；其他 builtin 继续拒绝。配置目标使用独立 grant 字段，包含精确 `server_id` 和允许的 `create`/`update` 动作。新建必须预先授权准确且未占用的 ID，禁止通配符、前缀和任意新 ID。更新/状态/取消也验证实际目标。管理权限不授予下游业务工具、凭据创建/读取、HTTP 信任修改、分类发布、项目执行或 Git 执行器权限。

## 最小服务端增量

1. 内置 issuer/client 的 scope 校验和元数据增加 `operations.manage`，保留原两个业务 scope。grant/授权码增加明确管理工具快照与目标策略，不能把 builtin 假装为已发布下游工具，也不将它们加入普通 grant。
2. 已验证 principal/调用上下文携带内置 issuer 身份、client/resource、grant/family、token 到期及有效 scope 上限。每次副作用前及锁等待后重查实时行和权限。计划、日志及 worker 不保存原 bearer。
3. 在现有 manifest/配置/凭据/动作摘要之外，将计划和幂等请求绑定管理连接及目标策略。返回缓存结果前也检查精确工具和目标。撤销、到期、client 禁用、角色降级或移除目标后，排队工作停止，不能因恢复而扩大权限。
4. Console 独立确认用户/client/resource、四个工具、精确目标/动作及期限，复用严格 Origin、有效会话和一次性确认。OAuth consent 消费匹配的已核对意图并展示目标限制，不从不可信 authorize query 读取目标。保留业务 grant、旧 JWT、既有 family 上限；新管理权须由客户端重新发起授权码/PKCE，获得新的管理 grant/family。

## ChatGPT 请求 scope：已核验机制与缺失证据

官方客户端授权文档要求工具 `securitySchemes` 与 `_meta["mcp/www_authenticate"]` 错误共同触发工具级关联；仅有资源元数据不够。管理描述请求 `operations.manage`，写操作额外请求 `tools.invoke`，challenge 指向固定 `/mcp` 的资源元数据与所需 scope。支持静态 OAuth client。这些是文档已核验机制，**不是本 Gate 管理连接的实测结论**。来源：2026-10-04 核验的官方 Authentication 与 ChatGPT Developer mode 指南；直接来源链接附于独立复核回复。

建议 bootstrap 只向已明确登记、有效的管理员/client 和已核对目标意图展示静态管理描述，以便客户端接收 scope challenge。这个狭窄发现例外不授予调用权，不返回目标目录、凭据或操作状态。普通业务连接不自动获得管理描述或新 scope。传输必须保留 `securitySchemes` 与 challenge 元数据；当前通用拒绝工具结果不足以触发流程。bootstrap 可见性与 grant 授权后的目录/调用分别测试。

声称支持 ChatGPT 前，必须在另行授权的非生产 fixture 连接观察客户端实际生成的 authorize 请求：含 `operations.manage` 及所需写 scope、准确 client/redirect/resource、客户端自己的新 state/PKCE，且新 code/JWT/grant/family 携带批准交集。禁止伪造生产客户端 state/challenge、升级旧 family、把 `scopes_supported` 当作实际请求或绕过 scope。若客户端没有请求或不识别 challenge，保持阻断并提示重新连接/授权。本轮未获准实测此流程。

## 启用前验收

合成回归拒绝普通 OAuth、只读、非管理员、外部 issuer、其他 builtin、未列目标及 create/update 替换。覆盖精确工具/schema 漂移、其他 grant/family、过期/重放/跨会话确认、计划/幂等连接切换、排队时撤销/降级。证明旧业务 JWT/family 不变、管理 grant 不授予下游工具，以及被拒 bootstrap 不泄露目标。补完整元数据/challenge 协议测试，再进行独立获准的真实客户端 scope 观察。

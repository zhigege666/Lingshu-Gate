# 按需目录与分组集成溯源

[English](../on-demand-integration.md) · [使用指南](on-demand-tools.md) · [基础检查点](on-demand-validation.md)

独立 `test/on-demand-groups-integration-20261005` 分支经按需目录基础实现，源自 exact main `d4786fd368e932bc758ea29da1a597c9d9551794`（0.4.4）。分组变更依次通过普通 cherry-pick 复制。原六个分组提交并非本分支的字面祖先，其六个复制提交是祖先。未创建 merge、只为制造祖先关系的 merge、tag 或 release。

| 原分组提交 | 集成复制提交 | 稳定 patch ID |
|---|---|---|
| `554d25a12496ed22d23c5f7b3bd5af1d728b6354` | `a28faee47b71c6c5b080d172d19004bbf5eb9e33` | 不同；解决实现重叠 |
| `72a31a51cc9d5956028651154a9be27b5f8075bd` | `76fee1664d8187e671bef72a21355973612eebc2` | 不同；保留已有目录派发 guard |
| `9042797c37ab0d115daa27d48dd5217fd8e872ad` | `14c22b699a0e938929f164e950bf73d919017275` | 不同；保留双方文档入口 |
| `d913446dbd3bcf4cb4e89e16ff210d8207365409` | `b6194b3f3731810469cd762f0ba06bd285f5543f` | 相同 |
| `8a6bf03e554e5579cfbbfca08fa90ee4921f7d45` | `e73d2cfbfeabd4d31b7a518800fe3f65751d0963` | 相同 |
| `62c607b9d81965282ee0d1283c304c85e65b7d93` | `be59b01d50ddd3bca8eb1dcabaecb85ed6ea31b2` | 相同 |

第一处冲突同时保留目录迁移 0012、分组迁移 0013/0014、registry 持有的冻结快照以及目录增量通知。原子替换仅退役选定物理目标被移除的工具，其他实例的索引与审核状态保持有效。第二处同时保留分组定义版本/读重试控制、基础目录派发 guard 和选定分类同步。第三处保留按需、分组及 port 文档链接。分组 UI 与弹窗布局保持原实现，另加双语客户端模式设置。

在集成提交 `4887e94`，`application/tool_authority.py`、`auth.py`、`external_jwt.py`、`domain/mcp_group_routing.py`、`mcp_manifest.py`、`application/mcp_groups.py` 和 `persistence/mcp_groups.py` 的生产文件 blob 与分组源 `62c607b9d81965282ee0d1283c304c85e65b7d93` 相同。运行时代际 setter 与路由代际函数 AST 相同。已验证的 audience/client/JWKS/resource 证据、等待后当前权限收窄、连接代际 ABA 防护和旧 manifest ID 规则保留。缺少 output schema 时保留旧指纹；仅 output 契约变化仍会使审核失效。字节一致仅支持上述文件，不能宣称整个集成树等同原分支。

集成通过现有路由 port 提供公共限量分组搜索、描述、实例选择与显式会话开关。配置/运行时映射共享读租约加选定实例锁允许不同实例并发，变更仍排他执行。发现不授权，路由字段不进入业务参数，不自动选择默认实例，不重放分组读调用。

审计后续提交 `718ed985e9e834fce4fb904bd28e4f3519298c3b` 限制紧凑 schema DAG，在获取派发租约前终止超时或取消的验证子进程。已解析目标拒绝只记录一条物理 `not_invoked` 审计；未解析引用记录脱敏哈希/关联事件。公共 describe 拒绝并发目录/策略标记变化。`64c7f55` 将选定逻辑目标解析缩小为单条成员记录及该实例契约，每次检查仍复核物理与逻辑授权。`4887e94` 另将名为 `$defs` 的实际属性计入保守展开预算。全组搜索仍重新校验全部受限候选，与选定描述/调用成本不同。

已执行定向证据：70 项目录验证/审计/适配测试在 34.12 秒通过；三项物理/逻辑/发布 epoch 变化测试使用当前 operator 身份通过；选定目标优化后 76 项分组/外部权限测试在 54.72 秒通过；最终展开预算修正后 37 项验证/物理目录测试在 10.40 秒通过。Ruff、mypy 通过。这些是定向检查点；固定 SHA 全套测试、后续元数据刷新回归与独立物理/分组实测见[集成验收记录](on-demand-integration-validation.md)。1,438 项基础全套测试早于此次集成。根代理验收、独立视觉/安全复核与 nx5 部署仍独立进行。

`3b271f6` 另在 schema 准备前通过原当前物理 grant 映射和精确 OAuth 上限排除候选，保留工具授权覆盖服务默认的规则。每页只构建一次授权分组投影，并在昂贵投影前校验游标；授权结果不缓存。104 项目录/分组/外部权限测试在 68.06 秒通过。

同 exact main 的 OAuth 阶段 A `dfa18dde3169df173be72400054c4d567dc2cb1b` 复制为 `1b4592d2d30de39a5d728fc0707841d86d46cf4d`。access-control 冲突保留分组定义前置条件、原派发 guard、有界验证和只同步选定分类。新增 registry 原子 ID 查询返回其持有的冻结结构副本，保留修改隔离。`_verified_principal` 使用 `_grant_tools`，JWT 验证和分组新增的 `refresh_verified_principal` 均经过该方法，不再次构建 owner 全目录。合并后的 66 项扩展/registry/分组授权测试在 103.52 秒通过，涵盖 5,000 服务/50,000 工具、1/100/5,000 工具 grant、进程内刷新及零完整 registry 投影。其中三次采样的 OAuth 延迟仅为诊断，执行时存在并发 fixture，不能作为延迟保证。owner 候选分页/选择仍是 OAuth 作者的独立阶段。

复审后续 `d99be556ff48e018792268abeb7c5a22c5517476` 规范化无序授权集合，保留身份/证据及真实上限变化，并在私有初始化后的实际调用边界重复选定实例会话 guard；未改变复制的路由模块，未恢复完整分组派发投影。94 项安全回归在 63.70 秒通过。TTL 后续 `3947ae4171d27d2e693ea3f505e49cf6b12fa752` 保持未变元数据刷新稳定，保留显式/真实元数据变化失效；136 项配置/分组用例在 549.44 秒通过。最终检查点范围及原始测量见[集成验收记录](on-demand-integration-validation.md)。

最终 HEAD 验收后续在 `f51d1b18d7475034b61567be00ef999128918e83` 重新执行完整后端全套：1,734 passed / 3 skipped / 0 failures，1,289.04 秒。跳过项为可选固定 Playwright MCP discovery/列表 peer 未提供安装。该 HEAD 的 wheel 与 Linux 原生产物已重建，真实安装 CLI/frozen 父进程及验证子进程通过合成本地派发、非法类型拒绝、期限/回收及 chunk 检查。生产源码保持 `d99be55`，运行期间无变化。[完整测试/产物证据](on-demand-integration-validation.md) 保留精确边界与摘要。

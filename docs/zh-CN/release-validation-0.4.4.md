# 0.4.4 验证记录

[English](../release-validation-0.4.4.md) · [发行概述](../../packaging/release-notes.md)

此发行分支从 main `5fc3aaba94955e243598783166479136797733e4`（不可变的 0.4.3）开始，只纳入外部 HTTP 配置、独立管理 OAuth、精确目标授权、Console/同意控件及自带 Delivery Skill 契约。其他开发提交中的账户菜单整理、分组路由、目录缓存与海量目录检索均排除。登录页和 Console 继续以运行中的后端健康版本为单一来源。

## 已执行验证

Python/前端固定依赖安装成功。Ruff、mypy（116 个源码文件）、仓库身份、源版本/tag 对照、Compose 配置、前端类型/UX 源码检查、70 文件共 426 项前端测试及 Console/OAuth 构建通过。wheel 与 sdist 已按 0.4.4 构建；四个外部工具的 Skill 输入表与应用模型一致，包含禁止未知参数的边界。

完整后端运行记录为 1,359 通过、10 失败、3 跳过。9 项失败是公共静态资源尚未构建时返回 503，另 1 项是两个 Git 记录为 100755 的发行脚本在本地检出为 700。构建静态资源并恢复本地可执行权限后，原 10 项在不改断言的情况下全部通过；另一次完整内置 OAuth 运行 107 项通过。随后提供既有固定版本 Playwright MCP peer，原跳过的 3 项互操作测试全部通过。这是分别执行的记录，不宣称单次全绿运行。

受影响浏览器运行 142 项通过。模拟健康版本改从后端版本源读取后，管理资源套件再次 40 项通过，产出 48 张截图，覆盖 1600×900、1920×1080、2560×1080、2560×1440、中英文及明暗主题。模拟同意/管理测试不能证明真实 OAuth 客户端或 peer 联调；截图与作者检查也不代替 root 独立复核。

本地 wheel 包含 0.4.4 后端、管理模块及两个已构建 UI 入口。本地 Compose 包包含 BUILD-INFO/SPDX SBOM，校验和文件核验通过。[PR 发行制品运行](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37322815393) 对代码 head `1778826b1d8f88d94510e6bc50a1822e0270d688` 的质量门、五种 native 与 Compose 全部通过。PR 按既有流程跳过 Core/离线镜像发布任务，仍需正式 tag 工作流。

此检查点有两项验收阻塞。[容器扫描](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37322815456) 在继承的 `perl-base` 5.36.0-7+deb12u3 中报出 3 个 Critical（修复版本 5.36.0-7+deb12u4）：CVE-2026-13221、CVE-2026-42496、CVE-2026-8376。Dockerfile/base-image 输入与 main 相同，属于继承的打包问题，不是外部配置新增依赖。[CodeQL](https://github.com/zhigege666/Lingshu-Gate/runs/111806314351) 在 `application/external_mcp_configuration.py:50` 新报 1 个 High，将进入 SHA256 计划完整性摘要的数据认作密码。该 helper 不负责密码存储，但报告的数据流仍须独立复核/处理，未驳回或抑制告警。现有 integration 权限无法读取完整安全告警 API（403），未申请新权限。Source CI 仍在进行；未降低扫描阈值、修改工作流或保护。

## 真实 HTTP 服务验收

在操作者管理的部署中使用另行批准的非生产目标，不更改生产凭据，也不由成功业务连接推定管理权限。

1. 部署后确认运行后端为 0.4.4、已保存可信 HTTPS issuer/resource、有活动签名 key，且当前用户为持有 `operations.manage`、`tools.invoke` 的管理员。明确启用默认关闭的管理资源。Console 和 `/v1` 保持私有，仅公开所需 OAuth/发现/MCP 路径。
2. 登记或明确修改机密客户端的管理资源 allowlist 和 scope，保留一次性 secret 关闭确认，不把 secret 写入截图或笔记。客户端单独建立指向准确 `https://gate.example.test/mcp/manage` 的连接，核对实际请求所需管理 scope、同意页资源、所选工具及精确目标/创建更新操作。
3. 只同意可丢弃的精确 server ID，例如 `acceptance-http`。工具发现应只包含已选的四个 `gate_mcp_config_*` 子集；业务 `/mcp` bearer 在 `/mcp/manage` 必须失败，管理发现不得包含业务或无关内置工具。这属于真实客户端验收，不能用合成测试代替。
4. 使用已批准的外部 HTTPS 服务与已有托管凭据引用。如果服务使用内网 HTTP，其精确服务/IP/端口信任须已通过独立批准的管理员操作登记。用 `mode=create`、`connect=false`、`refresh_tools=false`、`probe=false` 建计划，核对没有 peer 请求或持久化；确认前展示调用者已知的真实 endpoint、返回的脱敏摘要与操作。
5. 已获授权时用 `probe=true,probe_confirmed=true` 和有界超时另建计划，确认临时探测关闭且不登记工具。需要连接时用 `connect=true,refresh_tools=true` 建计划，五分钟内携原 ID/摘要/操作、新幂等键与 `confirmed=true` 应用。轮询 `operation_id` 到终态，记录保存/连接/发现/清理状态、配置摘要及分类审核数量。已保存或排队不代表成功。
6. 独立核对当前连接和发现快照。新增/变化工具仍须分类审核，不暗示授权或分类已发布。响应中断只用相同业务输入/幂等键重试；写入终态不明须操作者核对。更新使用 `gate_mcp_config_status` 返回的原文件配置摘要，不用交付接口的规范化摘要。
7. 在可丢弃目标上明确测试本人目标修改、令牌/授权撤销和排队期间权限丢失。移除目标或撤销授权必须阻止后续保存/连接/发现，旧计划失效，较窄 JWT/令牌族 scope 不扩展。取消与清理/删除仍是需分别授权的写入。

记录脱敏 ID、摘要、状态变化、真实客户端 scope 请求和服务观察，不在公共发行证据中保留 bearer、客户端 secret、凭据值或私有 endpoint 详情。

## 仍需验收

root 独立复核、真实客户端管理 scope、真实 peer/socket/DNS 行为与部署验收仍待执行。文件持久化、运行状态与 SQLite 不是单一事务，期限为协作式。本版不实现安全 Git/代理执行器、分组调用/路由或海量目录检索。

此分支作者不打 tag、不合并 main、不发布。复核合并后，既有正式工作流须产出并核验五种原生目标、Compose、两个离线 Core 镜像、应用 SBOM、镜像摘要与 SHA256SUMS 共 11 项资产，包含来源证明及发布标题/正文回读。本地构建不能代表跨平台发行已验收。

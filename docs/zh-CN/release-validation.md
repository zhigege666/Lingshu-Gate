# 0.4.0 验证记录

[English](../release-validation.md) · [发行指南](releases.md) · [PR #43](https://github.com/zhigege666/Lingshu-Gate/pull/43)

本记录区分候选源码验证、正式发布和真实接入。产品代码与截图来源为 `8b3dc8a7cbc4877c157ef82d526000a5f478d924`，已整合 main `d500116548a90e4edaa0bfa0e0c1138afe45354a`（含内置 OAuth PR #42）。后续文档与浏览器夹具修改不改变该产品代码。最终 PR head 必须通过其自身检查，不能用此前绿色运行证明后续提交。

## 已执行检查

| 检查 | 实际结果 | 范围 |
|---|---|---|
| 冻结 uv 同步 / npm 干净安装 | 通过 | 锁定开发/运行依赖 |
| Ruff、mypy、Python 语法 | 通过；mypy 检查 106 个源码文件 | 源码检查，不是真实网络验收 |
| 完整 Python 测试 | 1,044 条通过 | 包含 Git 输入/协议、脱敏、继承、权限、超时/取消、锁文件、失败保留旧部署及整合 OAuth/API token/外部认证回归 |
| Git/网络专项 | 80 条通过 | 受控 fake adapter 和真实 HTTP adapter 审计；不连接用户 Git/代理 |
| Console 检查、Vitest、两套资源构建 | 通过；62 文件 / 325 测试 | Console 与独立 OAuth 资源；Vite 保留既有大 chunk 提示 |
| 浏览器失败项专项 | 72 条通过 | 双语与指定桌面尺寸、归属/确认、外部模式引导及真实 loopback MCP |
| 浏览器常规完整套件 | 100 通过 / 38 个 opt-in 跳过 | 真实隔离后端及明确模拟的展示场景；跳过不计通过 |
| 扩展浏览器首轮 | 55 通过 / 17 失败 | 所有可用 opt-in 文件、三尺寸列表矩阵及视觉测试；未重试或跳过失败 |
| 扩展定向复验 | 8 通过 / 9 失败 | 按实际控件和重置语义修正；剩余失败另列 |
| panel 夹具复验 | 2 通过 / 4 失败 | 身份诊断通过；构建日志剩余空间断言仍失败 |
| 固定 Chromium 视觉复验 | 1 通过 / 1 失败 | 既有 390×844 基线通过；1280×600 相差 18,241 像素（约 3%）；未改基线 |
| requirements 导出、身份、版本、Compose、diff | 通过 | 锁导出同步、仓库身份、`v0.4.0` 源码匹配、静态 Compose 契约和空白检查 |

修正夹具后仍有 8 个可选场景失败：总览排名高度/窄屏时间刻度密度（2）、窄屏个人工具抽屉（1）、构建日志剩余空间断言（4）、桌面登录视觉基线（1）。每场景最新结果来自上述各轮运行，不是新一轮全部变绿的扩展套件。与已通过的四尺寸 Git/OAuth 流程分开报告。不为使可选测试变绿而捆绑无关页面重设计或重生成视觉基线。外部 preview adapter 场景未提供 opt-in 源码路径，因此无法执行。

准确 `8b3dc8a` 的 [CI](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37121331535)、[CodeQL](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37121331529)、[容器契约](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37121331527)和[发行包](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37121331608)均成功。CI 包含 Python 3.11/3.12/3.13 和隔离浏览器 smoke。PR 发行矩阵实际构建并冒烟验证五个原生目标及 Compose 包；仅 Tag 的镜像提升、离线镜像和 GitHub 发布在 PR 中跳过，不能报告为通过或已发布。最终 head 与之后 Tag 的结果须通过 PR #43 和发行记录分别检查。

## 截图来源

两份 README 各链接九个页面：总览、工具目录、分类、个人工作区、可信 ZIP 交付、被阻断的 Git 来源、网络设置、关闭的 OAuth 和工具调用。18 张 PNG 均为相同候选产品代码的实际 1920×1080 明亮主题浏览器截图，没有修改像素或模拟 API 响应。[拍摄清单](../images/console/v0.4.0-capture.json)记录来源修订、产品源码摘要、语言、尺寸、实际状态及每张 PNG 的 SHA-256。

新建实例使用合成管理员/viewer、复核过的无依赖 ZIP、当地合成 HTTP MCP peer、指向保留无效主机的停用加密配置及保留 Git 主机。OAuth 未配置签名密钥或客户端秘密。Git 计划在 DNS/拉取前返回实际 `safe_executor_unavailable`。拍摄没有代理探测、用户仓库、依赖安装、SSH、外部账户或生产部署。合成名称是夹具数据；后端提供的工具名称/描述和原始诊断码保留原语言，周围 Console 控件使用所选语言。

截图复核检查控件已加载、双语导航一致、表单/表格可读、关闭/阻断状态，以及没有真实凭据或本地文件系统路径。截图证明实际展示，不代表生产授权提供方或网络接入验收。

## 剩余发行与执行边界

- 生产 `SafeNetworkExecutor` 缺失，真实 Git 解析/拉取、代理测试、工具准备和指定网络安装仍阻断；fake adapter 测试不提供生产隔离声明。
- 未连接或验收真实 GitHub/私有 Git、用户代理、Git SSH、pnpm/npm/Yarn 分发准备、私有依赖源、ChatGPT、公网 TLS/代理 Cookie 或外部 OAuth 账户。
- 未执行生产升级、部署或无中断会话迁移。受控测试覆盖构建失败保留旧部署及有界回滚；回滚可能中断正在运行的服务。
- 仓库 ruleset 可读取（返回空集合），当前 integration 无法读取旧 `main` protection（HTTP 403），因此未验证准确必需检查/审批策略。保留现有规则，使用准确已审查 head，不使用管理员绕过、force push 或跳过 CI。
- 版本/Tag/发行沿用既有 `main` 版本变化工作流：要求配置发行凭据并启用不可变发行，之后校验固定 Tag、产物、校验和、SBOM 和 provenance。不新建 token、不移动已有 Tag。CI 成功和版本号变化不证明已经发布。

合并前向整合审查提供准确 head 的 diff、文件清单、检查链接及分开的通过/失败/跳过/未运行证据。本记录不授权配置生产网络或凭据。

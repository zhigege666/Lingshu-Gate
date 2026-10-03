## Lingshu Gate v0.4.0

### English

0.4.0 combines opt-in built-in OAuth with initial Git/network delivery settings
and planning. Production Git/network execution remains blocked pending a safe
executor.

- Add opt-in Gate built-in OAuth authorization with confidential static clients,
  authorization codes and PKCE S256, per-user tool consent, encrypted RS256
  signing keys, refresh rotation and revocation. The public consent UI has its
  own asset bundle. OAuth remains disabled until an administrator explicitly
  configures and enables it; DCR and CIMD are not supported.
- Add **System settings → Network and dependencies**, named encrypted proxy
  profiles, immutable configuration revisions, separate Git/install defaults,
  project `inherit` / `direct` / `profile` choices, and separate administration
  and invocation permissions. Registry/index settings are separate from proxies;
  proxy values are not ordinary API responses or runtime MCP defaults.
- Integrate Git source forms and confirmed plans with the existing Project
  Delivery flow. Add fixed-commit provenance, controlled snapshot rules,
  credential references, cancellation/timeouts, reference checks, and
  deterministic supported npm/pnpm/Yarn lockfile planning. Pulling, installing,
  deploying and starting retain their independent permission/confirmation
  boundaries; failed builds preserve the previous deployment.
- **Git/network execution is only partially implemented. The production
  `SafeNetworkExecutor` is absent, so real Git resolution/fetch, proxy probes,
  package-tool preparation and configured network installs fail closed.**
  Saving configuration cannot enable them. HTTP proxies do not provide Git SSH
  support, and no host sandbox or container-socket boundary has been relaxed.
- Expand both READMEs with 18 actual screenshots (nine per language), provenance
  and paired guides. Keep blocked Git and disabled OAuth states visible. Fix
  the clipped English classification-review action and cover it in both
  languages at all four desktop acceptance sizes.

Validation: the release source passes 1,044 Python tests on each of Python
3.11/3.12/3.13 and 325 Console unit tests. The local default browser run passed
108 cases with 38 opt-in skips. **Eight optional layout/visual scenarios still
fail** (ranking/axis, narrow personal drawer, log-height budget and desktop
login baseline); they were neither waived nor reported passing. See the
[validation record](https://github.com/zhigege666/Lingshu-Gate/blob/v0.4.0/docs/release-validation.md).
Synthetic fixtures do not establish real user Git/proxy/SSH, ChatGPT/external
OAuth, public TLS or production-upgrade acceptance. Rollback may interrupt a
service; uninterrupted session migration is not claimed.

Assets cover five native targets (Linux x86_64/ARM64, Windows x86_64 and macOS
x86_64/ARM64), Compose, two offline Core images, an application SPDX inventory,
container digest metadata and `SHA256SUMS` (11 assets). Native packages include
`BUILD-INFO.json`, SPDX inventories and notices. Verify downloads with the
checksums and repository build-provenance attestations. Formal job results are
available in the
[tagged release workflow](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37127029127).

### 简体中文

0.4.0 整合需显式启用的内置 OAuth，以及 Git/网络交付的初步设置与计划能力。
生产 Git/网络执行仍因缺少安全执行器而阻断。

- 新增需显式启用的 Gate 内置 OAuth：静态机密客户端、授权码与 PKCE S256、
  按用户选择工具的授权、加密 RS256 签名密钥、刷新轮换和撤销，以及独立的公开授权
  页面资源包。管理员完成配置并启用前保持关闭；不支持 DCR/CIMD。
- 新增“系统设置 → 网络与依赖”：命名加密代理配置、不可变配置版本、Git 拉取与
  依赖安装独立默认值，以及项目 `inherit` / `direct` / `profile` 选择。
  配置管理权限与使用权限分离，registry/index 与代理分开；普通 API 不返回代理值，
  默认不会向运行时 MCP 传递代理。
- Git 来源表单和需确认的计划接入已有项目交付流程，补充固定提交来源记录、受控
  快照规则、凭据引用、取消/超时、引用检查及受支持 npm/pnpm/Yarn 锁文件的确定性
  计划。拉取、安装、部署、启动保留独立权限和确认；构建失败保留旧部署。
- **Git/网络执行仅部分实现：生产 `SafeNetworkExecutor` 尚未实现，真实 Git
  解析/拉取、代理测试、包管理器准备及使用网络配置的安装均 fail closed。**
  仅保存配置无法启用执行；HTTP 代理不等于支持 Git SSH，未放宽宿主沙箱或挂载
  容器引擎 socket。
- 中英文 README 增加 18 张真实截图（每种语言九张）、来源记录和成对指南，展示
  Git 阻断与 OAuth 关闭状态。修复英文工具分类审核操作被裁切，并增加中英文、
  四种桌面尺寸的回归覆盖。

验证：发行源码在 Python 3.11/3.12/3.13 上分别通过 1,044 项测试，Console 单元测试
通过 325 项；本地默认浏览器测试通过 108 项、跳过 38 项可选测试。**另有八项可选
布局/视觉测试仍失败**，涉及排行高度/时间轴、窄屏个人工具抽屉、日志高度预算和
桌面登录基线，未豁免或宣称通过。详见
[验证记录](https://github.com/zhigege666/Lingshu-Gate/blob/v0.4.0/docs/zh-CN/release-validation.md)。
合成测试不代表真实用户 Git/代理/SSH、ChatGPT/外部 OAuth、公开 TLS 或生产升级
已验收；回滚可能中断服务，不宣称无缝会话迁移。

资产包括五种原生目标（Linux x86_64/ARM64、Windows x86_64、macOS x86_64/ARM64）、
Compose、两个离线 Core 镜像、应用 SPDX 清单、镜像摘要和 `SHA256SUMS`，共 11 个。
原生包内含 `BUILD-INFO.json`、SPDX 清单及声明。使用前请核验校验和及仓库构建来源
证明；正式任务结果见
[tag 发行工作流](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37127029127)。

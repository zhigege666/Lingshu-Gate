## Lingshu Gate v0.2.1

### English

- Simplify the Console overview with Gate status, server and tool summaries,
  and invocation statistics. Remove redundant controls and clarify error recovery.
- Improve light and dark theme borders and display the full build version
  in the account menu.
- Restore Console sessions and streamline configuration actions.
- Start the verified release workflow automatically when the source version
  changes on `main`.

Cross-platform Lingshu Gate binaries, a Docker Compose deployment bundle, and
offline Core images are attached. Verify every download with `SHA256SUMS`
before use. Native archives include build metadata, an SPDX dependency
inventory, and the applicable notices. Build provenance is published through
the repository's artifact attestations.

### 简体中文

- 简化 Console 首页，集中展示 Gate 状态、服务与工具概况及调用统计，
  移除重复操作，并改进错误恢复提示。
- 增强浅色与深色主题的边框辨识度，在账户菜单中显示完整构建版本号。
- 支持 Console 会话恢复，并简化配置操作。
- `main` 分支的源码版本号变更后，自动启动包含校验步骤的发布流程。

附件包含跨平台 Lingshu Gate 可执行程序、Docker Compose 部署包和离线 Core
镜像。使用前请根据 `SHA256SUMS` 校验下载文件。原生压缩包包含构建元数据、SPDX
依赖清单和适用的声明；构建来源通过仓库的产物证明提供。

## Lingshu Gate v0.2.3

### English

- Show service start, stop, and restart actions directly in the detail header.
  External services retain their connect and disconnect labels.
- Expose build, deployment, upload, credential, user, resource-grant, and cache
  actions as inline buttons without opening an overflow menu.
- Keep OpenAPI and sign-out actions visible in the header, and show credential
  reference buttons directly in the configuration editor.
- Let action groups wrap on narrow screens, reserve space for build-record
  actions, and return focus to the credential edit button when its dialog closes.
- Preserve existing permissions, allowed actions, busy states, and confirmation
  flows. Add focused rendering tests for action visibility and state restrictions.

Cross-platform Lingshu Gate binaries, a Docker Compose deployment bundle, and
offline Core images are attached. Verify every download with `SHA256SUMS`
before use. Native archives include build metadata, an SPDX dependency
inventory, and the applicable notices. Build provenance is published through
the repository's artifact attestations.

### 简体中文

- 在服务详情顶部直接显示启动、停止和重启操作；外部服务保留连接、断开的文案。
- 将构建、部署、上传、凭据、用户、资源授权和缓存操作改为行内按钮，
  无需先打开“更多”菜单。
- 在顶部直接展示 OpenAPI 和退出登录，在配置编辑器中直接展示凭据引用按钮。
- 按钮组在窄屏下支持换行，为构建记录操作保留空间；关闭凭据编辑弹窗后，
  焦点回到对应的编辑按钮。
- 保留原有权限、允许操作、忙碌状态及确认流程，补充按钮可见性和状态限制的渲染测试。

附件包含跨平台 Lingshu Gate 可执行程序、Docker Compose 部署包和离线 Core
镜像。使用前请根据 `SHA256SUMS` 校验下载文件。原生压缩包包含构建元数据、SPDX
依赖清单和适用的声明；构建来源通过仓库的产物证明提供。

# 浏览器回归

[English](../browser-regression.md)

测试使用 Playwright 和真实 Gate 提供的已构建 Console，仅监听本机回环地址。每次运行创建独立临时目录和 SQLite 数据库，清除继承的 `LINGSHU_GATE_*` 配置，创建合成管理员和 viewer。夹具还在进程内注册、审核发布一个合成 MCP 工具并给 viewer 只读授权，用于真实草稿权限检查，不建立下游连接。不会连接已有服务，无需生产凭据、外部下游服务或隧道。交付场景仅启动已审查的合成 stdio 进程；恢复场景执行无依赖、确定性首次失败的 Node 构建；远程场景由夹具启动动态端口的合成 loopback HTTP peer。固定端口为 18763，冲突时失败，不复用未知服务。

## 运行

在仓库根目录安装常规冻结 Python 依赖后运行：

```bash
npm --prefix web ci
npm --prefix web run build
cd web
npx playwright install chromium
cd ..
timeout 180 npm --prefix web run e2e:smoke
timeout 1800 npm --prefix web run e2e:full
timeout 180 npm --prefix web run e2e:permissions
timeout 180 npm --prefix web run e2e:large-data
timeout 180 npm --prefix web run e2e:visual
timeout 120 .venv/bin/pytest -q tests/test_personal_access_contract.py tests/test_viewer_permissions.py tests/test_user_downstream_credentials.py tests/test_delegated_access_scope.py
```

可通过 `PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium` 使用兼容的已安装浏览器；CI 使用 Playwright 固定版本浏览器。仓库 Linux 视觉基线由系统 Chromium 151.0.7922.173 生成，比较时保持相同环境，或审核后生成平台基线。Python 来自 `.venv/bin/python`。前端变更后重新构建；测试不隐式构建或复用开发服务器。每项测试和服务启动分别限制 30 秒（真实交付场景 60 秒），夹具进程最长 30 分钟。每 30 秒检查进度；60 秒无输出时检查进程/日志并终止恢复，不取消超时掩盖阻塞。

## 场景与证据

| 编号 | 层级 | 合同 |
|---|---|---|
| E2E-001 | 真实浏览器/API | 短屏登录、关联输入标签、键盘提交、主按钮在视口内且无遮挡 |
| E2E-002 | 真实浏览器/API | viewer 不能读取服务/配置/凭据/构建/上传管理 API；可访问本人令牌元数据 |
| E2E-003 | 真实浏览器/API | 错误登录后可以重新提交正确信息恢复 |
| E2E-004 | 真实浏览器/API | 个人服务摘要和本人调用，不访问管理API |
| E2E-005 | 真实浏览器/API | 390×844窄屏登录、键盘提交、无横向溢出 |
| E2E-006 | 真实浏览器/API | 为已发布合成工具创建关闭态个人授权，验证未配置信任与身份时无法启用，跨用户拒绝，界面取消及撤销 |
| E2E-007 | 真实浏览器/API/stdio | 界面上传、无依赖构建、修改/保存交付配置、未保存离开取消且零写请求、确认部署启动；真实运行发现和调用验证标记及四个任务ID |
| E2E-008 | 真实浏览器/API/进程 | 合成构建首次故意失败，通过界面重试得到新成功记录；不声称修改了项目源代码 |
| E2E-009 | 真实浏览器/API/HTTP | 对本地合成 HTTP peer 创建远程配置、应用为停止、连接发现、保存重连及 UI 调用；不涉及 OAuth/ChatGPT |
| E2E-101 | mock 展示层 | 5,000 工具、有界分页、翻页内部滚动复位、首项操作可见 |
| E2E-102 | mock 展示层 | 5,000 分类、最多 50 行、审核按钮位于视口且无遮挡 |
| E2E-103 | mock 展示层 | 200 凭据、最多渲染 50 行 |
| E2E-104 | mock 展示层 | 100 服务、文档高度有界、主操作可见 |
| E2E-110–124 | mock 展示层 | 200成员、60角色/30权限类型、2000授权、1000构建/500部署/500上传、200凭据/绑定/审计/日志/事件、100令牌/缓存/配置、200关闭态范围草稿、100服务总览 |
| E2E-201–202 | mock 交互 | 取消保存无变更请求；迟到保存阻止重复；HTTP200但激活失败保留编辑器 |
| E2E-203 | mock 交互 | 迟到服务详情不能替换当前个人服务选择 |
| E2E-204 | mock 交互 | Back及Forward分别取消离开，保留未保存配置和当前URL |
| E2E-301 | 视觉 | 桌面短屏和窄屏登录截图基线 |

展示层测试在真实登录后只拦截指定 GET。不能证明真实授权、下游调用、部署成功或运行就绪。确定性数据位于 `web/e2e/synthetic-data.ts`。视口断言检查完整矩形和三个命中点，不先滚动；仅 `visible` 或自动滚动 `click` 不能证明操作本就在眼前。

失败截图和 trace 位于 `web/test-results/`，报告位于 `web/playwright-report/`，均被 Git 忽略。可能包含合成密码与 cookie，仅用于夹具；CI 失败产物保留三天。不得改为生产地址或上传生产 trace。

## 布局与操作上下文

可单独运行逐页与操作场景：

```bash
timeout 180 npm --prefix web run e2e:full -- --grep '@list-context|@operations'
GATE_LAYOUT_EVIDENCE_DIR=../qa/layout GATE_LAYOUT_ASSERT=1 timeout 180 npm --prefix web run e2e:full -- --grep @layout-evidence
```

E2E-401–411 分别检查配置、共享凭据、缓存、成员、角色、授权、分类、审计、令牌、构建和部署列表，包括中段/末段滚动、表头/搜索/分页可见、筛选及换页。E2E-412 检查缓存目录状态文案与取消清理零写请求；E2E-413–414 检查桌面及手机获准 MCP 选择器。这些是 **mock 界面/API 响应测试**，不能证明真实权限或文件清理成功。

可选布局采集器生成 2048×1222、1366×768、390×844、1280×600 的 PNG 和几何 JSON。不设置 `GATE_LAYOUT_ASSERT=1` 时，命令成功仅表示采集完成；设置后才检查有数据的趋势日期/排行榜、维护列表滚动及服务标题/页签上下文。常规运行未指定证据目录时跳过采集器。修复前后证据应分目录保存；截图交付包不能包含 trace、Cookie 或认证存储。

## 覆盖边界

OAuth 授权布局检查等待弹窗实际入场动画完成后再比较固定几何位置。编辑器回归截获前一个弹窗的外部事件并暂停退出动画，打开另一个授权的编辑器后再投递旧事件，验证它不能关闭新会话；随后返回前一次范围请求，检查外来工具和版本冲突错误都不会进入新会话。这些用例使用合成响应，不加入固定等待或测试重试。服务配置验收检查居中框架、主滚动区、末字段与底栏可达、放弃修改保护，以及真实 loopback 重新连接前的明确保存/应用选择。

按类别报告可选用例的跳过原因。输出目录开关控制布局、维护短标签、个人列表/载荷、日志工具范围、剩余空间面板、外部身份与保留策略的验收用例，数量随视口矩阵变化；有额外断言开关时也须开启。三条 `@layout-diagnostic` 仅采集几何信息，不能证明验收通过。E2E-507 另需外部合成交付适配器源码，适配器缺失属于测试依赖缺失，不代表交付旅程通过。真实交付和远程连接用例仍须独立报告。

full 命令表示当前已实现的非视觉浏览器场景，不代表全部验收要求。视觉检查单独执行，并保持浏览器/系统/字体与生成环境一致；更新需要人工审核，不能盲目执行 `--update-snapshots`。真实权限矩阵仍是 pytest 证据，须分别报告。恢复场景覆盖确定性构建失败重试、激活失败反馈和登录恢复，尚不覆盖每一种部署补偿失败。交付场景在 1672×941、1366×768 和 390×844 捕获中文界面，检查居中准备表单、桌面图标下方步骤名称及状态、手机紧凑进度、上传后操作及配置最后字段与底栏，390×844 场景还明确滚动到上传高级选项的最后复选框，检查末字段可达、无遮挡和固定底栏；这与首屏操作可见断言分开，不代表完整手机任务旅程整体验收。远程 MCP 浏览器创建/重新连接只覆盖合成 loopback HTTP peer，不证明外部网络互操作、每用户下游认证或 ChatGPT/OAuth 接入。视觉基线仍需独立审核。不得以上述场景替代缺失验收；随接口稳定追加确定性用例，分别报告单元、真实 API、mock 浏览器、真实浏览器与视觉审核结果。

### 构建请求归属与可选合成预览适配器

`build-ownership.spec.ts` 新增 E2E-501–506，视口 1280×720：延迟刷新保留已选上传、删除其他构建不改变上下文、目标修改支持取消切换并恢复目的项目草稿、预检查提交中保护浏览器历史，以及回滚启动选项绑定选中部署（包括同构建两条部署）。临时真实后端仅提供登录和 Console 静态资源，业务返回及写请求均为确定性 mock；这些断言证明界面归属、请求体和确认语义，不证明真实构建/回滚执行或权限校验。

```sh
cd web
timeout 120 env PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium npx playwright test e2e/build-ownership.spec.ts
```

E2E-507 为可选测试，适配器来自独立预览交接文件。测试加载实际 `delivery-preview.ts`，执行上传元数据、构建状态推进、配置草稿持久化、取消部署预览（零部署请求），再确认合成启动，并核对 upload/build/deployment/server ID 一致。所有业务 API 都拦截：未知端点返回 501，外域被阻止，不向临时 Gate 回退业务请求；仅静态资源使用本地服务。上传字节为合成元数据，不解压也不执行。这是合成交互证据，不是身份认证、进程启动、MCP 连接或生产部署验收。Playwright route 桥接同时承接原生 EventSource 请求；这不能独立证明交接文件的 fetch/EventSource 安装 shim 已正确挂载。

```sh
cd web
timeout 120 env GATE_PREVIEW_ADAPTER_PATH=/absolute/path/to/delivery-preview.ts PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium npx playwright test e2e/preview-adapter.spec.ts
```

未设置 `GATE_PREVIEW_ADAPTER_PATH` 时跳过 E2E-507。这个带状态的写操作适配器与前述只读展示夹具分别报告。

E2E-507 的 shell 夹具明确返回 health `status: synthetic`、诊断 `{ok:false, checks:[], summary:{synthetic:true, executed:false}}`，不声称检查过真实机器健康；启动成功仅为适配器的合成状态。

E2E-508–509 复用合成归属夹具：修改 target/start/overwrite/root 后直接创建构建，必须先 CAS 保存当前选项，再 POST 构建，最后用递增草稿 revision 关联新 build ID，不能恢复旧选项。初次保存返回409时必须零构建 POST，输入与路由保留。仅运行两项及受影响适配器旅程：`npx playwright test e2e/build-ownership.spec.ts e2e/preview-adapter.spec.ts --grep 'E2E-50[789]'`（设置上文 adapter 路径才能运行507）。这些场景不执行真实构建进程。

E2E-510 从另一上传项目的失败构建行重试，延迟最初的旧目的草稿响应，验证目标选项、不出现错误的提交中导航弹窗，以及后续保存使用最新revision。E2E-511 仅在构建创建后返回409：保留新构建及当前选项、显示明确关联保存错误，且构建POST只有一次。这两项仍使用mock业务接口。对ownership、adapter、delivery-recovery三个spec使用 `--grep 'E2E-(008|50[789]|51[01])'` 运行受影响六项；只有008执行真实隔离的合成构建/重试。

E2E-520–522 为可选中文维护列表排版检查（1188×768、1366×768、390×844；100配置、100缓存、200凭据）。设置 `GATE_MAINTENANCE_EVIDENCE_DIR=/tmp/maintenance` 采集初始/状态列/横滚末端截图及文本行数；增加 `GATE_MAINTENANCE_ASSERT=1` 才断言短表头/状态/操作单行、操作和横滚后目标列视口内无遮挡、外层无横向溢出且不增加既有纵向溢出（浏览器临时移除并恢复本次9条CSS进行对照）。命令 `npx playwright test e2e/maintenance-nowrap.spec.ts`。仅采集成功不等于布局验收；业务数据为合成，登录后端独立隔离。

E2E-530–533（`personal-layout.spec.ts`）通过 `GATE_PERSONAL_LAYOUT_DIR=/tmp/personal-layout` 启用，尺寸1188×761、2048×1119、1366×768、390×844。检查0/1/41获准服务摘要（单页自然高度、不显示单页分页、多页实际offset）、0/1工具个人抽屉自然高度与41工具抽屉剩余空间与测试入口、服务标题区创建按钮及实际路由/弹窗路径，以及5000工具目录/审核滚动区的空间利用、分页可见与换页滚动复位。业务响应为合成，只有登录/静态资源使用临时后端；这条只读旅程拒绝任何界面写请求。布局通过不代表API权限或远程MCP连接验收。

E2E-540–541（`log-tool-scope.spec.ts`，`GATE_LOG_TOOL_DIR=/tmp/log-tools`）在1188×761与390×844检查日志工具选择：全部MCP不查询工具、同MCP保留、切MCP清空、空工具/历史工具、精确ID回退、键盘清除、重复重置，以及明确应用前后请求语义。事件不提供工具筛选。这是合成响应交互证据，真实范围权限由API测试单独证明。

E2E-550–553（`remaining-panels.spec.ts`，`GATE_REMAINING_PANELS_DIR=/tmp/panels`）在个人列表同四尺寸及1600×900、1920×1080、2560×1080、2560×1440检查200下游凭据和个人授权、首屏下方200身份绑定、500上传历史和200构建日志。断言剩余空间、实际滚动、分页与操作可达。构建日志预算按实际分页、卡片和页面内边距计算，保留原2px几何容差，分页与末条日志仍须可达，不再使用遗漏占用空间的固定预算。第一条合成凭据为Authorization Header/必填/已配置，后续包含必填未配置与可选未配置，不含凭据秘密。

`layout-audit.spec.ts`也增加这四个桌面尺寸。桌面仪表盘检查现有有界剩余高度、排行有效空间、可见底部入口及末条排行可达，替代早期固定排行/图表高度。旧手机断言与这些桌面验收目标分别报告。E2E-591（`filter-reset.spec.ts`）覆盖四个桌面尺寸的中英文和明暗主题，另保留原三个宽度：输入与清除动作同高，键盘清除可用，动作显示/清除/重置不移动列表，保留原2px容差。采集空查询、有查询及重置截图，不更新黄金图。

运行`list-context.spec.ts`时设置`GATE_LIST_LAYOUT_MATRIX=1`，将11个逐页场景扩为2048×1119、1366×768、390×844的33例中文截图矩阵，保留首屏/中段/末段/筛选/换页语义，并检查存在的首末行操作。输出目录环境变量只启用对应可选场景；仅诊断捕获用`--grep-invert diagnostic`排除。这些套件使用合成业务夹具验证布局与界面请求，不能替代真实权限或构建进程验收。

E2E-560–565（`external-identity-layout.spec.ts`，`GATE_IDENTITY_EVIDENCE_DIR=/tmp/identity-ui`）独立检查2048×1119/1366×768/390×844配置弹窗、长用户名称与可复制ID、同用户多身份绑定、服务端姓名/ID检索及分页、dirty取消零写，以及缺少`external_connections.manage`时不显示/不请求用户目录。专用端点合同允许具备此能力但没有`users.manage`的自定义身份绑定用户，测试保留这个区别。列表/picker业务数据与能力展示为合成，不证明后端授权；与真实API权限测试分别执行和报告。

E2E-570–574（`personal-payload.spec.ts`，`GATE_PAYLOAD_EVIDENCE_DIR=/tmp/payload-ui`）检查已保留调用内容展示：`null`、`false`、`0`、五种录制状态、JSON行检索/展开、复制前重新GET详情且复制完整保留内容、关闭/切记录后的迟到响应、模拟403清除旧内容，以及剪贴板失败可见。手机使用390×844和长合成JSON。这些测试不证明脱敏完整性、后端权限、保留到期清理或未记录原文恢复；真实API/清理测试仍须单列。

E2E-576–577补复制请求归属：较新的输出复制拒绝必须使较早仍在等待的输入复制成功响应失效，不能恢复内容或写剪贴板；管理员复制须保留可见成功提示。二者使用合成详情响应。个人工具抽屉截图现在先等待外壳动画完成及连续三个动画帧矩形稳定，再捕获0/1/多工具状态并检查右侧操作列可见且无遮挡。

E2E-580–583（`retention-ui.spec.ts`，`GATE_RETENTION_EVIDENCE_DIR=/tmp/retention-ui`）覆盖390×844策略底栏、默认7天/仅元数据、工作进程关闭时不可清理、缩短策略预览/取消/仅保存、独立即时清理确认、仅手动刷新任务及取消、409草稿保留、迟到过期预览拒绝，以及无能力时零策略请求。E2E-582另覆盖四个桌面验收尺寸，分别检查两个策略警告和FormDialog持续提交错误区域、草稿保留、busy关闭锁定、错误/恢复入口可达及无额外写入。所有保留策略请求均由合成状态拦截，包括模拟启用worker的任务；不启用真实清理进程、不删除真实记录，也不替代后端策略/CAS/清理权限验收。

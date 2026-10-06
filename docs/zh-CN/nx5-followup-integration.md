# 统一后续修复候选

[English](../nx5-followup-integration.md)

`test/gate-nx5-followup-integration-20261006` 实测源码为
`be30faf1c293c64dc90a160150ad182f7a4177a9`。已通过普通 `--no-ff` merge 将最终 UI
来源 `95bfa7d97d936275781d11ec5c4939574390a27f` 合入现有候选
`76391f5f8abec6649cfc9a119af31f27fb832fee`，保留此前 CLI、目录性能历史及验收记录。
无冲突，UI blob 与已审核来源一致，后端代码、后端测试、构建脚本及依赖锁未因
本次 merge 改变。

保存的 cloud 工作区中实际执行：

| 检查 | 结果 |
|---|---|
| 冻结前端依赖安装、类型及静态 UI 契约 | 通过 |
| 前端单元 | 74 个文件，441 passed |
| Console 与公开 OAuth 构建 | 均通过，保留既有大 chunk 提示 |
| CLI / schema worker / 四个 OAuth 后端文件 | CPython 3.14.4，208 passed |
| 构建后 consent locale 重放 | 9 passed、98 deselected，与 208 项重叠 |
| 八个选定 browser spec | 206 passed、0 failed、0 skipped、0 flaky |
| Ruff、Mypy、标识、版本及 diff | 通过，Mypy 检查 158 个源码文件 |

浏览器使用 Node 22.23.2、系统 Chromium 151.0.7922.173 及 CPython 3.13.15
loopback fixture。用例包含 mock 展示状态和真实本人可见的 5,000 MCP、50,000
工具目录分页。双语键盘加载更多/重试/焦点返回、草稿保持及保存成功但响应丢失
后的回读均通过。browser 临时根已由 teardown 删除，监听已关闭。临时数据均在
本次专属磁盘目录中，系统设置未改。

主线程已认可两张最终 1600×900 中文截图（基础设施五行完整客户端、授权弹窗
九行完整及底部动作可见）。独立审查关闭原键盘 P2，代码层无阻断；三个父控制器
请求/状态/确认逻辑逐字未变。主线程报告与本次 cloud 自动化分开记录。

fresh Git/codeload 源码不带生成的静态资源。应在候选根目录、所选 Python 环境中
先构建，再运行包含页面的后端用例：

```bash
npm --prefix web ci
npm --prefix web run build
python -m pytest -q tests/test_builtin_oauth.py -k authorization_ui_locales_reaches_consent_without_entering_the_security_envelope
```

既有 `build` 类型检查并生成包内两个 static 目录；没有单独的 `build:oauth`
package script。consent 路由查找模块相对的
`src/lingshu_gate/static/oauth/oauth.html`，不是 `web/dist`，fixture 不构建或
替代 HTML。缺失时明确返回 `authorization_ui_unavailable` 503，与主线程报告
九项断言的未构建前置吻合，未放宽断言或增加 skip。本次 208 项命令与前端流水线
在已有静态构建的工作区并行运行；额外九项明确在新双构建完成后重放。

主线程的 `7bc834` tmpfs 全量在约 81% 之后 D01 用例被 OOM 终止，报告临时文件
shmem 1.53GB 与 Python anonymous 1.55GB 叠加。旧 `7bc834` 磁盘运行最终有
11 项缺静态构建前置失败，上述九项 consent 页面失败是中途已知子集。旧两轮
均不能标为全量通过。主线程随后补齐构建前置，在磁盘上完成最终源码
`be30faf1c293c64dc90a160150ad182f7a4177a9` 的验证。
[此前检查点及主机观测](cli-catalog-integration.md) 保留原源码与来源。磁盘复验
不能据此证明产品内存泄漏已修复，本 cloud 工作区未重复完整后端。

主线程最终 nx5 报告对应已部署源码
`be30faf1c293c64dc90a160150ad182f7a4177a9`，运行代码与文档检查点
`9154d15cfe0a24875b0808418d5a8ea0b03fcd1e` 一致。全量 pytest 使用 CPython
3.14.4、单进程、`MemoryMax=3GiB`、`CPU=200%`；`TMPDIR` 和 pytest
`--basetemp` 均指向 `/srv` 上该轮专属磁盘目录，省略具体主机路径。

| 主线程报告的 nx5 检查 | 结果 |
|---|---|
| 全量后端 pytest | 2201 passed、4 skipped、0 failed、5 warnings；2632.83 s |
| 前端 check 与单元 | 通过，441 项单元通过 |
| 正式 Console 与公开 OAuth 构建 | 均通过 |
| 构建后 builtin OAuth / release packaging / startup smoke | 184 passed，与全量后端重叠 |
| 真实 nx5 登录、导航及横向溢出检查 | 22 页 × 4 尺寸 = 88 项通过 |
| 基础设施 config / clients / management config | 均为 HTTP 200 |
| 连接指南 | 打开、Escape 关闭、焦点返回触发器均通过 |

四项后端 skip 全部属于 `test_native_executor_host_acceptance`，需要 rootless
Podman、镜像和 tmpfs。主机安全配置未获授权，因此仍未执行。88 项浏览器检查
覆盖登录、导航及横向溢出，不覆盖全部业务流。该测试环境 OAuth disabled、没有
客户端，因此没有完成真实 ChatGPT 授权验收。

主线程已保存验收 receipt，并报告清理该轮磁盘临时数据库和依赖缓存约 3.15GB。
全部源码、部署、必要日志、截图及 JUnit 证据均保留；测试 Chrome 进程为零，
Gate 测试服务仍 active。本 cloud 工作区未执行该清理，也未取回或独立核验
nx5 原始日志。以下 SHA-256 由主线程提供：

| 主线程保留的证据 | 主线程提供的 SHA-256 |
|---|---|
| 最终 `run.log` | `634bfe4d16d67c8a79e75a43f7fa511f45b3f1cc965fe5f3914f6875debafd2a` |
| 最终 `results.xml` | `06a02b46eb1479ca80ebcfe5af512b25d4892d3c928ea461eac13c71a5c7f94d` |
| 构建日志 | `608e90e9009dee4e3c74c6a690e692fa4e56ffe1750f5cbc907383e2ad4435a7` |
| 导航日志 | `36ee451b075cb890021db58f547d604443de020f7a820ddd3b0310f1c7353c6f` |

新 web 清单为 Console 97 文件、公开 OAuth 三文件，规范化 SHA-256 为
`5a7fad02c10fd6d3dc98911ebc90683f336ae41ac37c5fe7600818057e1c0013`。未重建或改标
wheel、sdist、native 二进制。本次 cloud 未跑 Podman、正式发布矩阵、其他平台、
全站浏览器或真实 Gate/Plane/ChatGPT 验收，未执行 SSH、main、tag 或 release。

[结构化证据及完整 web 清单](../benchmarks/gate-ui-final-integration-be30faf.json)
包含精确来源、命令、hash 与范围，[日志](../benchmarks/gate-ui-final-integration-be30faf.log)
包含实际检查输出。
[最终 nx5 receipt](../benchmarks/gate-nx5-final-acceptance-be30faf.json) 单独记录
主线程报告的结果与证据 hash。本次验收更新只改文档，未重跑测试或重建成品。

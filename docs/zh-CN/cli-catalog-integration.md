# CLI 与目录性能集成检查点

[English](../cli-catalog-integration.md)

`test/gate-nx5-followup-integration-20261006` 从精确 base
`7d145c28a94a00a6c5d6f4f7d4fc38c0e6153436` 整合已审核的 CLI 程序名修复和目录分类窄投影。
实测的统一源码提交为 `d8b1ee076ff39f60a9b633e414932adbd6478129`。

本报告覆盖此前 CLI/目录性能检查点，当时 UI head
`4fc96c8b45635f2ba886eb6cc8f14691c1810319` 暂缓合入。精修 UI 来源
`95bfa7d97d936275781d11ec5c4939574390a27f` 后续已普通 merge 到
`be30faf1c293c64dc90a160150ad182f7a4177a9`；合并后的验证与这 382 项另行记录。

两次普通 `--no-ff` merge 保留完整来源历史：CLI `a4f9be911852a9d354fe29804e1eafb8f301f9ba`，目录性能
`2b6a2c5173595787cb57fed394515c4fc0dd73bc`。无冲突，两个来源的改动文件没有交集，所有合并文件都与来源
blob 一致。production 改动仅为 `cli.py` 与 `access_control.py`：CLI 显式使用
`lingshu-gate` 程序名；目录读取省去大型分析/证据列，并保留原有实时策略检查。
完整分类 loader 与 schema worker 实现未改。

合并后实测使用保存的 cloud Linux x86_64 环境、CPython 3.14.4
及 pytest 8.4.2。冻结依赖同步检查 51 个包。两组回归各自使用独立
临时目录和缓存：

| 运行范围 | Passed | Pytest 时间 |
|---|---:|---:|
| CLI / schema worker / projection / ACL / group cache / adapter | 120 | 49.23 s |
| Group catalog / routing / authority / classification / OAuth consumers | 259 | 287.87 s |

原有三项 5,000 实例、50,000 工具 HTTP scale 用例也各自在独立进程中执行，全部
保留原采样、断言及阈值：

| Scale 用例 | Passed | Pytest 时间 |
|---|---:|---:|
| five_groups | 1 | 41.38 s |
| maximum_single_group | 1 | 101.55 s |
| over_cache_bytes | 1 | 150.57 s |

合计 **382 passed、0 failed、0 skipped**。CPython 3.13.15 项目环境中的全仓
Ruff、Mypy（158 个源码文件）、仓库标识、版本及 diff 检查均通过。测试结束后
没有携带精确 worker 参数的 schema worker 进程残留。

本次 scale 是修改后的测量，先前受控分配量对比仍沿用其原检查点证据。cloud
cgroup 上限为 16 GiB，与 nx5 不同。scale RSS 是包含 fixture 与全部请求的进程
累计 `ru_maxrss`，不能据此确认单请求峰值、泄漏或 nx5 全量 OOM 已解决。

主线程报告 nx5 合入前 baseline 已完成 2,175 个结果。最初三项失败中，当时 CLI 一项待新源
重测；Delivery 两项在激活 PATH 后通过。主线程还报告 peer 三项通过，安装
`uv` 后 wheel 40 项通过，四项 Podman 明确未跑。这些状态来自主线程，与本次
cloud 实测分开，不构成新源码的 nx5 验收。

2026-10-06，主线程报告候选 `7bc834e38f7b737bca1c660b92de2d3b6f60acd3` 的 nx5
全量后端运行已到约 75%，当时暂未失败。该运行仍未结束，不是最终结果。主线程
同时报告以下主机观测：

| 观测项 | 报告值 |
|---|---|
| 临时目录挂载 | `/tmp`，tmpfs，容量 3.9G |
| pytest 临时数据残留 | `pytest-of-root`，2.7G |
| Cgroup 内存上限 | 3GiB |
| `memory.stat` anonymous / shmem | 1.55GB / 1.53GB |
| 总计入内存 | 约 3.13GB |
| 当时 OOM 事件 | 0 |

这些是主线程提供的近似值及单位标签，并非 cloud 独立测量或精确字节换算。
总量按报告保留，不由取整后的分项重算。临时存储与 shmem 是重要环境证据；
此前单进程 OOM 本身不能直接证明产品泄漏，原因仍未确定。

在上述观测时，主线程计划把 `TMPDIR` 与 pytest `--basetemp` 都指向主机 `/srv`
挂载上该轮专属磁盘目录。随后主线程报告 tmpfs 运行在约 81% 之后、执行
`tests/test_real_delivery_journey.py::test_d01_real_upload_build_deploy_and_configuration_reapply`
时被 OOM 终止，观测到临时文件 shmem 1.53GB 与 Python anonymous 1.55GB 叠加。
该全量未完成，不能标为通过。

主线程已用相同 `7bc834` 源码及 3GiB 上限，在 unit `gate-full-backend-7bc-disk`
中启动磁盘 `TMPDIR` 与 `--basetemp` 复验，最终结果待定。该运行出现九项 consent
页面断言失败，实际 503、应为 200；主线程已确认 fresh 源码归档缺少生成的公开
OAuth HTML。只读核对表明静态查找不依赖临时目录：路由使用模块相对的
`src/lingshu_gate/static/oauth/oauth.html`，fixture 不构建或替代它。缺失时会明确
返回 `authorization_ui_unavailable` 503，与未构建前置吻合，不能放宽断言或跳过。

fresh Git/codeload 源码应先安装前端依赖并执行现有正式双构建，再运行包含页面的
后端用例：

```bash
npm --prefix web ci
npm --prefix web run build
```

`build` 会类型检查并把 Console 与公开 OAuth 构建到包内两个 static 目录。
仓库没有单独的 `build:oauth` package script，`web/dist` 也不是 consent 路由的
查找目标。保持主线程运行中的源码不变，主线程构建后九项重测仍待执行。测试
断言与系统安全设置保持不变，本 cloud 环境未启动重复全量。

本次 cloud 工作未跑完整后端、前端/浏览器、其他平台、nx5/Podman 或正式发布矩阵，也不
构成 Python 3.14 的完整支持。未重建 web、wheel、sdist 或 native 候选，旧包
证据仍绑定原源码 SHA。OAuth UI 等待其后续提交与审查，未混入；版本、依赖与权限行为
未改，未执行 SSH、main、tag 或 release 操作。

[结构化证据](../benchmarks/gate-nx5-followup-integration-d8b1ee0.json) 包含 merge parents、源码/测试 hash、
精确命令、验证范围及三项 scale 原始指标。
[测试日志](../benchmarks/gate-nx5-followup-integration-d8b1ee0.log) 包含两组回归摘要及三轮独立 scale。
来源报告：[CLI 程序名](cli-validation.md)、
[目录分类窄投影](catalog-classification-projection.md)。

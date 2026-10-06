# CLI 与目录性能集成检查点

[English](../cli-catalog-integration.md)

`test/gate-nx5-followup-integration-20261006` 从精确 base
`7d145c28a94a00a6c5d6f4f7d4fc38c0e6153436` 整合已审核的 CLI 程序名修复和目录分类窄投影。
实测的统一源码提交为 `d8b1ee076ff39f60a9b633e414932adbd6478129`。

本报告覆盖 CLI/目录性能检查点。OAuth UI 原作者正在处理主线程视觉审查的后续
修改，已只读核对的 UI head `4fc96c8b45635f2ba886eb6cc8f14691c1810319` 未合入。

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

本轮结束后，主线程计划另行验证：把 `TMPDIR` 与 pytest `--basetemp` 都指向
主机 `/srv` 挂载上该轮专属的磁盘目录。这一验证尚未执行，测试断言与系统安全
设置保持不变。本环境未启动重复全量或合入旧 UI，继续等待 UI 精修的新源码 SHA。

本次 cloud 工作未跑完整后端、前端/浏览器、其他平台、nx5/Podman 或正式发布矩阵，也不
构成 Python 3.14 的完整支持。未重建 web、wheel、sdist 或 native 候选，旧包
证据仍绑定原源码 SHA。OAuth UI 等待其后续提交与审查，未混入；版本、依赖与权限行为
未改，未执行 SSH、main、tag 或 release 操作。

[结构化证据](../benchmarks/gate-nx5-followup-integration-d8b1ee0.json) 包含 merge parents、源码/测试 hash、
精确命令、验证范围及三项 scale 原始指标。
[测试日志](../benchmarks/gate-nx5-followup-integration-d8b1ee0.log) 包含两组回归摘要及三轮独立 scale。
来源报告：[CLI 程序名](cli-validation.md)、
[目录分类窄投影](catalog-classification-projection.md)。

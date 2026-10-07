# CLI 程序名验证

[English](../cli-validation.md)

Gate 的已安装 console 脚本和 `python -m lingshu_gate.cli` 现在都使用
`lingshu-gate` 作为 CLI 程序名。解析器显式设置 `prog`，`--version` 继续使用
既有的唯一版本源 `__version__`。两个入口的帮助和参数错误 usage 输出也保持一致。

验证源码为 `test/gate-nx5-validation-fixes-20261006` 上的
`ae999912e3175bc6f79daf54da1d586836d4d06e`，精确 base 为
`7d145c28a94a00a6c5d6f4f7d4fc38c0e6153436`。执行环境是保存的 cloud Linux
x86_64 工作区。

未修改的 base 在 CPython 3.14.4 上复现 **1 failed、8 passed**。
`test_version_flag_uses_single_version_source` 期望 `lingshu-gate 0.4.4`，实际为
`python -m pytest 0.4.4`。该解释器的 `argparse` 在未指定程序名时会依据
`__main__.__spec__` 推导名称；因此通过模块运行 pytest 时，仅替换 `sys.argv[0]`
无法选定命令名。修复采用仓库声明的 console-script 标识，并保留原断言。

四个环境都在验证提交上执行以下命令，使用各自专属的临时目录和缓存：

```bash
python -m pytest -q tests/test_cli.py tests/test_schema_validation_budget.py
```

| CPython | CLI 用例 | Schema worker 用例 | 结果 | Pytest 时间 |
|---|---:|---:|---|---:|
| 3.11.16 | 12 | 13 | 25 passed、0 failed、0 skipped | 5.58 s |
| 3.12.14 | 12 | 13 | 25 passed、0 failed、0 skipped | 5.60 s |
| 3.13.15 | 12 | 13 | 25 passed、0 failed、0 skipped | 5.86 s |
| 3.14.4 | 12 | 13 | 25 passed、0 failed、0 skipped | 5.99 s |

新增三项回归用例从 checkout 之外的临时目录调用真实的已安装 console 脚本与模块
入口，对比 `--version`、`--help` 和无效端口的退出码、stdout 与 stderr。惰性的
无效服务配置用于验证这些路径会在加载服务配置前退出，每个子进程超时为 20 秒。

未修改的 schema worker 测试覆盖复杂度限制、截止时间、取消、子进程终止、槽位
复用、frozen 命令选择及绕过服务配置的真实模块 worker 入口。测试结束后，没有
携带精确 worker 参数的进程残留。3.13.15 项目环境中的 Ruff、Mypy（158 个源码
文件）、仓库标识、版本及 diff 检查均通过，依赖与版本文件未改。

这些结果限定于 CLI 与 worker，不构成 Python 3.14 的完整支持、全量测试或 nx5
验收结论。主线程报告 nx5 全量测试曾在 3 GB 上限下被 OOM 终止，正在另行逐文件
隔离验证；本次没有确认性能根因。OAuth UI、权限及 worker 实现未改。本次后续
修复未跑前端与浏览器测试、新 package/native 候选构建、其他平台、Podman 或正式
发布矩阵。此前包证据仍对应其原源码检查点。

[结构化证据](../benchmarks/gate-cli-identity-ae99991.json) 包含源码与测试 hash、
精确解释器版本、验证范围及未执行工作。[测试日志](../benchmarks/gate-cli-identity-ae99991.log)
包含失败复现及四次成功运行，临时路径和对象地址已脱敏。

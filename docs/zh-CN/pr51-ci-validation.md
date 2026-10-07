# PR51 CI 修复与 CodeQL 审查

[English](../pr51-ci-validation.md)

此记录覆盖 [PR51](https://github.com/zhigege666/Lingshu-Gate/pull/51)，起点为 `227db541871ef8753390760d323414efbbe94d7c`，分支为 `test/gate-nx5-followup-integration-20261006`。这是未发行的源码修改，不证明 Windows 二进制、真实 Podman 宿主、部署或发行已完成验收。

## 已复现失败

- [Source checks](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37563583943/job/112606142387) 在 frozen pip 导出比较处失败。使用工作流相同的 uv 0.11.33 正式重导出，仅为 `jsonschema` 的依赖来源注释增加 `lingshu-gate`。去除注释后，版本、环境标记和制品哈希逐字节一致；`uv.lock` 未变。
- [Windows native smoke](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37563583862/job/112606498820) 已生成归档并通过身份检查，随后因禁用的执行器配置按 Windows 绝对路径语义检查 `/usr/bin/podman` 而启动失败。回归以 `PureWindowsPath` 复现。默认禁用配置现在可加载；启用配置仍要求明确布尔值、管理员审定的绝对二进制/根目录路径及固定 image 摘要。Windows 和 Core 组合入口仍不能创建或探测 Linux 执行器。

## 原始八条 CodeQL 注释全部对齐

[Check 112606427064](https://github.com/zhigege666/Lingshu-Gate/runs/112606427064) 报告六条 high、两条 medium。原始检查注释可读，也直接读取了五条行内线程；五条线程只是八条注释的子集。安全告警 API 返回 HTTP 403（`Resource not accessible by integration`），因此用 CI 相同的 CodeQL CLI 2.27.1、`python-queries` 1.8.11 和 `python-all` 7.2.6 独立重建数据流。

| 原始位置 | 严重度 | 判定与证据 |
|---|---|---|
| [`benchmark_tool_catalog.py:185`](https://github.com/zhigege666/Lingshu-Gate/pull/51#discussion_r4202544285) | High | 误报：来源为 `oauth_ceiling` 统计字典，仅含已断言的固定错误码和耗时，详见下方数据流。 |
| [`native_executor/https.py:255`](https://github.com/zhigege666/Lingshu-Gate/pull/51#discussion_r4202544298) | High | 将本地 TLS context 的最低版本明确设为 TLS 1.2 后再赋给 transport；回归同时验证证书和主机名校验。 |
| `auth.py:87` | High | 误报：来源为随机会话/API token，不是人工密码。密码继续使用既有 200,000 轮 PBKDF2，详见下方。 |
| [`test_git_acquisition.py:36`](https://github.com/zhigege666/Lingshu-Gate/pull/51#discussion_r4202544305) | High | 误报：SHA-1 用于故意含合成反射秘密的拒绝夹具的 Git 对象身份；Git 身份语义及测试内容未改，详见下方。 |
| [`test_native_executor_integration.py:674`](https://github.com/zhigege666/Lingshu-Gate/pull/51#discussion_r4202544309) | High | 以解析后的 hostname 精确相等替换 registry 子串筛选，并要求 Git/install 两组调用都非空。 |
| [`test_native_executor_locks.py:36`](https://github.com/zhigege666/Lingshu-Gate/pull/51#discussion_r4202544324) | High | 断言原始 lock 的完整字节一致，替换 URL 子串断言。 |
| `interfaces/control_api/oauth_routes.py:589` | Medium | 仅服务端新生成的浏览器绑定值进入 `Set-Cookie`；既有绑定复用，不反射、不延长期限。回归验证并行票据及另一浏览器拒绝。 |
| `mcp_gateway.py:491` | Medium | 序列化协议错误明确的公开 `message` 字段；两个校验边界均不输出带内部诊断的异常格式化文本。 |

未修改的起点全量 Python 扫描有 12 条结果，修复提交 `63cab1c` 的全量扫描有七条：上述三条已审查误报，以及不属于该 PR check 八条注释的四条未变发现。五条已修复注释均已消失，没有新增 rule/file 组合。扫描覆盖全部 304 个 Python 文件。工作流、查询选择、告警状态及行内线程状态未改；未增加抑制或关闭告警。

## 误报的数据流证据

1. **基准日志。** SARIF 为 `scripts/benchmark_tool_catalog.py:132` → `scope_cases.oauth_catalog_ceiling` → 最终 JSON 输出。来源是 `{"code": error.code, "elapsed_ms": ...}`，紧接 `error.code == "tool_catalog_limit"` 断言。分类器密码命名启发式包含 `oauth`，将此统计变量标为密码。5,000 服务、50,000 工具、一次迭代的合成基准完整执行后，该字段只有 `code=tool_catalog_limit` 和数值耗时；未签发凭据，未联系下游。
2. **Token 哈希。** SARIF 从 `create_api_token` 返回值及夹具的 `oauth_sessions` 值流向 `hash_secret`。宽泛密码启发式包含 `api_token` 和 `oauth`。`AuthStore.login` 与 `AuthStore.create_api_token` 用 `secrets.token_urlsafe(32)` 生成实际哈希输入（256 位随机量）；OAuth 客户端秘密使用 48 个随机字节。这些值用于查找/绑定。人工密码经 `hash_password`/`verify_password`，使用随机 salt 和 200,000 轮 PBKDF2-HMAC-SHA256。修改查找哈希会改变已持久化 token 身份，不能改善密码安全性。
3. **Git 夹具哈希。** SARIF 起于 `test_reflected_bare_basic_or_proxy_secret_never_reaches_snapshot` 的固定合成值，编码进原始 blob 后进入 `ObjectFixture.add`。该函数对准确的 Git `<kind> <length>\0<data>` 表示计算 SHA-1。获取随后以 `git_snapshot_content_rejected` 拒绝反射内容，并关闭对象流。这不是密码存储或身份认证；替换 SHA-1 会破坏夹具声明的 SHA-1 Git 格式及对象校验覆盖。

## 补充回归证据

基准内部结果现在命名为 `catalog_limit_stats`，公开的 `scope_cases.oauth_catalog_ceiling` 键保持不变。输出由字面量 `tool_catalog_limit` 和数值耗时构造，不复制异常值或消息。[`test_catalog_benchmark_reporting.py`](../../tests/test_catalog_benchmark_reporting.py) 验证仅允许两个字段、固定结果和数值时间。相同完整 Python CodeQL 查询集扫描补充代码的全部 305 个文件，得到六条结果：Token 哈希和 Git 夹具哈希，以及原始 PR check 之外四条未变发现。基准告警已消失，没有新增 rule/file 组合。推送 SHA 的 GitHub 扫描仍须独立读取。

[`test_builtin_oauth.py`](../../tests/test_builtin_oauth.py) 以固定公开元数据向量验证既有 SHA-256 编码。测试观察真实随机生成器，不替换 token 值：Console/同意会话和 API token 请求 32 字节，OAuth 客户端秘密请求 48 字节。测试验证持久化查找身份、重新打开存储、伪造 token 拒绝及退出/撤销。独立测试观察创建用户、替换密码及成功/失败登录时的真实 PBKDF2 调用：五次操作均使用 SHA-256、32 字符 salt 和 200,000 轮；替换密码改变 salt，人工密码不进入 `hash_secret`。既有未知用户测试验证相同 PBKDF2 工作量及统一拒绝。Git 反射内容测试还断言所有已打开对象流关闭。哈希算法、持久化身份和 Git 对象格式未变，未加入 `usedforsecurity` 覆盖。

## GitHub 正式 triage 保持独立

在 `63cab1c` 上，[CodeQL check 112614151370](https://github.com/zhigege666/Lingshu-Gate/runs/112614151370) 因三条 high 失败。可读线程明确了[基准告警 #16](https://github.com/zhigege666/Lingshu-Gate/security/code-scanning/16) 和 [Git 夹具告警 #17](https://github.com/zhigege666/Lingshu-Gate/security/code-scanning/17)。Token 哈希注释定位 `src/lingshu_gate/auth.py` 和 `py/weak-sensitive-data-hashing`，但不提供告警编号。安全 API 的 list/get 均返回 HTTP 403；须经有权限的 [PR51 告警视图](https://github.com/zhigege666/Lingshu-Gate/security/code-scanning?query=pr%3A51+tool%3ACodeQL+is%3Aopen) 获取编号，不能猜测。

有权限的维护者须对最终准确 SHA 上每条剩余告警独立审查，包括受影响分支和完整 source-to-sink 路径。如果确认误报，应将理由、本证据、已审查 SHA 和回归结果记录在告警处置评论中，随后读回状态/理由/评论，并重跑或检查 PR checks。GitHub 会记录处置理由及评论，且 dismissal 影响所有分支，见 [GitHub 告警处置文档](https://docs.github.com/en/code-security/how-tos/manage-security-alerts/manage-code-scanning-alerts/resolve-alerts)。本次源码修改不执行 dismissal。文档、本地干净扫描或误报认定均不能将 GitHub 失败检查宣称为绿色。

## 验证边界

补充验证的 221 项认证/OAuth/Git/报告相关测试通过。5,000 服务、50,000 工具、一次迭代的完整合成基准保持报告全部顶层键及 scope-case 键不变，并满足结果字段的两字段允许列表。Frozen pip 导出、Ruff、mypy、仓库身份/历史及版本检查也通过；依赖锁与源码版本未变。

Frozen 依赖同步/导出、Ruff、mypy、仓库身份/历史、版本、Compose 配置、Console 检查、441 项前端测试、九项浏览器 smoke 及 150 项 native-executor 回归已通过。Linux x86_64 归档用 CPython 3.13.15/PyInstaller 6.22.2 构建，经过安全解包、校验和/身份检查及 native readiness smoke。这些是本地工作树结果；完整 Python 回归及新的 GitHub 结论随修复提交交接。deadline socket 夹具同时改为遵守已配置的 socket timeout，其断言不再依赖 supervisor 线程先于合成发送完成获得调度。

Windows 路径语义、禁用配置加载及非受支持平台组合入口已有合成回归。在 `63cab1c` 上，GitHub Source checks 和五个平台 native 构建均通过，包括实际 Windows readiness smoke。补充提交的准确检查结论仍须独立读取。真实 rootless Podman、namespace/cgroup 和上游实测验收保持独立宿主检查。

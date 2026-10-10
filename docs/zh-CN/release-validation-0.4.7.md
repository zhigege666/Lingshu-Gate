# 0.4.7 候选与正式发布验证

## 源码与 patch 范围

本 patch 包含 [PR64](https://github.com/zhigege666/Lingshu-Gate/pull/64) 审阅的
目录快照重试修复，精确 head 为
`2f59a904a8f90da6a242699a62b1ad8f556cee29`。代码内容提交为
`2534eb9032b8165d40d732bf1b033a55b96f3cbe`，后续证据提交未改变这些字节。
新发行候选必须从经核验的 main 合并开始，并在新包回执中保留准确源码身份。

PR64 已经正常合并为 `0fcfd27ba9f8e1474f6b7975a39512c1298ae279`，tree 为
`f02ab9c5f207d5b333a650f73efe3dc9fdf4059a`；远端全部 989 个 leaf 的 mode、type、
Git blob 与审阅 head 准确一致。精确 head 的普通 CI
[38014839844](https://github.com/zhigege666/Lingshu-Gate/actions/runs/38014839844)
已通过，包含 Source/Python 3.12 与托管浏览器 smoke、Python 3.11、Python 3.13
及 CI result。main 普通 CI
[38018193498](https://github.com/zhigege666/Lingshu-Gate/actions/runs/38018193498)
在本源码记录时仍在运行，作为版本合并前独立验收门槛。

唯一运行时版本源为 `src/lingshu_gate/_version.py`，本 patch 更新至 `0.4.7`，
同步双语 README、CHANGELOG、发行指南与 release notes。已整合的分组/会话、
根路径 Console、按需目录、OAuth 编辑与干净打包继续保留。权限规则、迁移、
依赖及可选执行器/OAuth 默认值不变。已占用的 v0.4.5/v0.4.6 标签保留原 SHA；
源码修复使用新 patch 身份。

## 已跑修复检查与限制

[重试证据](../benchmarks/gate-catalog-snapshot-retry-333862e.json) 记录四个修复前
预期失败的负对照、32 项通过的缓存/权限检查、三个真实 5,000 实例/50,000 工具
目录场景，以及 481 项通过的目录、OAuth、配置与 Registry 检查。全部规模场景
保留并发 writer、边界及原 20 秒 reader 预算。超缓存 writer 场景仅准备最初
7742 个 miss，取代修复前实际观察到的 15483 次准备；当前 token scope、grant、
分类及版本向量仍重新校验。

独立只读审查已检查 PR64 四个文件差异、715 行证据和 Registry/冻结数据/权限/
锁代码，未见 P1/P2；该审查未复跑作者测试。64 MiB 是共享缓存记账上限，请求
内有界引用不构成进程 RSS 上限。

新用户失败文本共 551 行且末尾截断，没有最终 pytest 汇总，仅展示原托管 reader
超时。本地原场景实际通过，因此不声明已复现准确的托管 20 秒失败或证明唯一
原因。耗时与 peak RSS 是具有各自进程历史的测量，不是生产 SLA。

先前 [0.4.6 验证](release-validation-0.4.6.md) 保留对应源码、浏览器与宿主边界。
真实 OAuth 客户端、多机器及可选 Native/Linux Podman 准备仍未完成。不放宽
浏览器 sandbox，也不在本地合成检查中创建真实宿主身份、grant 或 session。

## 新候选与正式发布必需门槛

新的 0.4.7 回执须覆盖当前 web 构建、两个静态清单、直接 PEP 517 wheel 和
sdist-to-wheel、准确 RECORD、Linux native 包内 manifest/SBOM、glibc 兼容及
schema worker/主入口 smoke 与所属进程回收。旧候选摘要不代表这些新包。

新的本地候选已在源码 `2d6b469f8c8d661b92f0da8d1fd2f55937342923`、tree
`9cd19c15e0d4d4833aef0f1fc216da33d0713b83` 完成；两条 wheel 链路字节一致。

| 候选 | SHA-256 |
|---|---|
| 直接 wheel 与 sdist-to-wheel | `e6138f23148b44e68c7bfd6c85ce90eebc152111296db910930b7ea1884db4e0` |
| sdist | `7bbda98aa873009ff323522c85de9bf4151b74e47dcc0afc4013d35e4263d680` |
| Linux x86_64 native | `6d432eb4977f5e94fc770b994794389a24fac59889392cc54823ca3d3bb37570` |

[包回执](../benchmarks/gate-release-0.4.7-packages-2d6b469.json) 验证 118 个静态
文件（Console 115、OAuth 3）、全部 283 项 wheel RECORD、467 项 native 清单、
200 个包的 SPDX SBOM 与最高 glibc 2.35。十二项入口及十二项父进程 worker
生命周期检查通过，含 deadline/cancel、slot 复用及回收。正式源码自带的冻结
主服务 readiness/HTTP/静态 smoke 也通过，使用临时所属 loopback 数据；该服务
fixture 与不创建身份的 worker 检查分别记录。

[实际检查回执](../benchmarks/gate-release-0.4.7-checks-2d6b469.json) 记录 455 项
前端与 207 项打包/schema/release 回归通过，包含两个静态目录连续 A→B 构建、
缺少/意外文件、路径边界及 native staging。使用 CPython 3.13.15、Node 22.23.2、
PyInstaller 6.22.3、setuptools 84.0.0。本地 uv 0.12.19 与正式固定 0.11.33 分别
记录；本地缓存缺少 registry 元数据时，以必需哈希和正常 TLS 安装同一冻结生产
依赖集，未改变版本或锁文件。候选回执绑定上述源码提交，后续文档/证据提交
另外记录；新正式资产及版本 main 合并仍需准确记录自身源码身份和校验和。

候选核验及版本 PR 必需检查通过后，版本合并触发既有 `publish-release`
selector；凭据与不可变发行预检在创建 tag、dispatch `release.yml` 前执行。
本验证不读出或创建任何凭据值。

正式发布继续执行独立完整 quality、五种 native 目标、Compose、双架构 Core/
离线镜像、应用 SPDX SBOM、镜像引用与 SHA256SUMS，共十一项准确资产。核对
全部必需任务、归档校验和、包内清单、SBOM、源码/工作流 attestation 和公开
标题/正文。tag、dispatch、本地候选或 PR artifact 都不代表正式发布完成；不以
复用旧失败标签、读取或改道下载旧拒绝 artifact 替代这些门槛。

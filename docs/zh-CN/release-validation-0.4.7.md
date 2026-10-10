# 0.4.7 候选与正式发布验证

不可变 [v0.4.7 正式发行](https://github.com/zhigege666/Lingshu-Gate/releases/tag/v0.4.7)
已于 2026-10-10 05:56:43 UTC 发布。下方最终回执绑定合并源码及实际下载的
全部十一项资产。

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
已在版本 PR 合并前成功完成。

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

## 正式发布完成与下载字节核验

PR65 合并为 `45cec40c1e57d7290ab249e620b5a50fa939e115`，tree 为
`5cf23e968371ca7623eaef75e7d774a38d022240`；远端全部 993 个 leaf 的 mode、type
及 blob 匹配审阅 head `c9261a2c95cc30edb7e46317a1c36778ac0227bf`。
现有 selector 在该合并上创建 v0.4.7；v0.4.5/v0.4.6 保留原 SHA。main CI、代码
扫描、容器验证、selector 与
[正式运行 38022781421](https://github.com/zhigege666/Lingshu-Gate/actions/runs/38022781421)
均已成功完成。

首次正式质量门槛达到未改动的 40 分钟 job 限制，pytest 未完成。新源码检查
及本地 66 项计时探针通过后，执行代理在已授权发布范围内使用原工具请求一次
有界重跑；此工程判断不证明 runner 瞬时故障。第二次在固定 CPython 3.13.15
上通过：2,336 passed、7 skipped、134 subtests，1,967.56 秒。原预算、断言和
job 限制均未改变。
[首次运行证据](../benchmarks/gate-release-0.4.7-formal-attempt-45cec40.json)
保留失败及重跑判断。

[最终完成证据](../benchmarks/gate-release-0.4.7-formal-completion-45cec40.json)
记录全部十一项实际下载、准确名称/大小/API 摘要与 SHA256SUMS、五平台 native
BUILD-INFO 清单及静态文件、SPDX SBOM、Compose 清单和双架构离线 Core blob
身份。每个平台包含 Console 115、OAuth 3 个文件。Linux/macOS 字节匹配新 Linux
构建；Windows 四个文本摘要受 CRLF 检出及 Vite HTML 空白影响。新 CRLF 检出及
Vite 构建准确匹配 Windows 全部 118 个路径和摘要；该参考运行在 Linux，不是
Windows 运行时测试。首次校验错误采用共同平台参考及修正均保留；每项资产只
下载一次。

实际下载的 Linux x86_64 SHA-256 为
`be4d4b52c4074da76f49bb2b8fe52d66a2853ad2fd6172c508ba454991adee80`。
该冻结字节通过六项入口与六项 worker 生命周期检查，含 deadline/cancel、slot
复用及所属子进程回收。父进程是已安装候选 wheel 的 Python，调用正式 native
worker，不宣称覆盖完整冻结应用父链路。托管 native readiness、Linux glibc、
Intel macOS OpenSSL 隔离、Compose、双架构 Core critical 扫描及离线 load smoke
均成功。

publisher 验证不可变发行及全部十一项带可信时间戳的强制源码/工作流 attestation
后更新 Docker Hub latest。可选环境密钥 OCI 签名未配置而跳过，与强制资产
attestation 分别记录。已发布标题/双语 notes 与源码匹配。真实 nx5/x16、Podman
准备及真实 OAuth 客户端验收仍不在这些云回执范围内。

## 已整合分支清理

2026-10-10 06:59:59 UTC，对精确远端 SHA 属于已发布 main 祖先的八个分支
执行了一次原子删除，每个分支分别使用预期 SHA 租约检查；提交仍可从 main
访问。十个有独有内容的分支（含发布证据和独立 UI 对齐修复）得到保留。
其他全部远端 ref、main 及 v0.4.5/v0.4.6/v0.4.7 标签与执行前快照完全一致，
未改发布资产。[清理回执](../benchmarks/gate-integrated-branch-cleanup-45cec40.json)
列出全部删除和保留的 head。UI 修复与不可变资产分开，仍待独立设计复核。

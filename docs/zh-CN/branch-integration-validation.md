# 独有分支整合验证

[English](../branch-integration-validation.md) · [发行产物](releases.md)

本次审查覆盖 2026-10-11 回读的全部 18 个公开分支头和 17 个标签。整合基线为 `2cbbe0673ce221a490af55d7d45abb5171552ec6`，已审查的模态候选为 `3d369665f4ab6fb54cc28d0b2b3bf69dba15800a`（PR #66）。独有内容按当前 main 与不可变 v0.4.7 的语义比较，不将提交独有性直接视为整支合并指令。

另行选取的内容为 PR #59 的三项通用发布防护，以及早期 WIP 分支的两项 ACL 回归测试。本次提取不改变应用运行时、源码版本、授权规则或发行权限。整合仍以前述 exact candidate 的普通完整 CI、打包工作流及独立复核通过为前提。合成发布测试不连接 GitHub 或容器 Registry；新的正式发行不在本次交付范围内。

## 分支取舍

SHA 列记录处置时使用的修复后公开来源，不表示所有分支都已合并。历史证据分支继续以其来源身份保留供后续复核，下方已批准的身份修复为唯一例外。

| 分支 | 来源 SHA | 取舍 |
|---|---|---|
| `fix/gate-service-modal-alignment-20261010` | [`39a85b8`](https://github.com/zhigege666/Lingshu-Gate/commit/39a85b8aebe389bca455fe7ffca3b2670fac93b7) | 已由 PR #66 的审查后模态候选覆盖；保留来源分支。 |
| `main` | [`2cbbe06`](https://github.com/zhigege666/Lingshu-Gate/commit/2cbbe0673ce221a490af55d7d45abb5171552ec6) | 精确整合基线；保留当前双语 README 修改。 |
| `test/gate-account-focus-diagnostic-20261008` | [`9f90dea`](https://github.com/zhigege666/Lingshu-Gate/commit/9f90dead000db20ed069ea3e720912a552b75fa3) | 账户入口、E2E 测试与诊断 JSON 已和 main 字节一致；保留来源分支，其继承的固定源码发行入口由 PR #59 的定向提取替代。 |
| `test/gate-account-focus-main-evidence-20261008` | [`5f01487`](https://github.com/zhigege666/Lingshu-Gate/commit/5f0148750ff9f66ab2b3feb14a97dd81332db76f) | 保留云端浏览器证据及明确未执行的 nx5 后续计划；不移植运行时实现。 |
| `test/gate-formal-environment-diagnostic-20261008` | [`31939e2`](https://github.com/zhigege666/Lingshu-Gate/commit/31939e2701c39181b31ef79ffb51a7d43666cc60) | 保留只读固定 v0.4.5 环境与 CLI 诊断；不将旧源码覆盖入口装入当前发布工作流。 |
| `test/gate-formal-environment-evidence-20261008` | [`da87705`](https://github.com/zhigege666/Lingshu-Gate/commit/da877054c8be79409f33967305d8b4b180158a2c) | 保留原超时、环境发现和批准边界作为历史证据。 |
| `test/gate-release-0.4.5-evidence-20261007` | [`e4f1921`](https://github.com/zhigege666/Lingshu-Gate/commit/e4f1921f7fb4f36045706b508665e76c5fe300be) | 保留精确 CI 与隔离验收收据及未完成验收结论；不补发 v0.4.5。 |
| `test/gate-release-0.4.6-package-evidence-20261009` | [`6cc6457`](https://github.com/zhigege666/Lingshu-Gate/commit/6cc6457905e7b03a11aabfa296a495ec819f6e42) | 保留 PR 包、质量失败和原控制器终态；不降级版本。 |
| `test/gate-release-0.4.7-formal-evidence-20261010` | [`f42d609`](https://github.com/zhigege666/Lingshu-Gate/commit/f42d609d47066ac8e6e43c13adc6436ab1379007) | 保留正式超时→完成及清理链；仅应用批准的两处执行代理标签修正，原三个提交可从验证后的 bundle 恢复。 |
| `test/gate-release-quality-d228-20261009` | [`0cd7432`](https://github.com/zhigege666/Lingshu-Gate/commit/0cd74320cecbb2b2c8aeb3f941590fef42a14ce4) | 保留绑定旧 v0.4.6 的诊断证据；当前工作流已有所需质量控制。 |
| `test/gate-release-resume-fixed-source-20261008` | [`b8150e8`](https://github.com/zhigege666/Lingshu-Gate/commit/b8150e878feffe1bd5b3784ae3050237e4db643d) | 提取精确标题正文校验、发布前资产证明和已有 Release 的写入防护；保留两个独有提交及恢复证据，以最小修复替代 PR #59，不引入固定 v0.4.5 入口或双源码资产命名。 |
| `test/gate-service-modal-delivery-20261010` | [`3d36966`](https://github.com/zhigege666/Lingshu-Gate/commit/3d369665f4ab6fb54cc28d0b2b3bf69dba15800a) | 在 exact head 的完整 CI 通过后，通过 PR #66 交付模态焦点修复；保留现有 UI 证据及验收范围。 |
| `test/mcp-groups-20261005` | [`62c607b`](https://github.com/zhigege666/Lingshu-Gate/commit/62c607b9d81965282ee0d1283c304c85e65b7d93) | 分组与运行时合同已在 main 整合或增强；保留独有来源历史。 |
| `test/oauth-catalog-scaling-20261005` | [`dfa18dd`](https://github.com/zhigege666/Lingshu-Gate/commit/dfa18dde3169df173be72400054c4d567dc2cb1b) | 目录规模、缓存行为与回归已在 main 保留；不重复移植产品实现。 |
| `test/oauth-scope-bulk-20261005` | [`acfccf0`](https://github.com/zhigege666/Lingshu-Gate/commit/acfccf0c4a5de9880056c465412d491d7e4a0ca8) | 批量 OAuth 编辑与授权边界已整合；保留旧分支。 |
| `test/on-demand-groups-integration-20261005` | [`6f3e871`](https://github.com/zhigege666/Lingshu-Gate/commit/6f3e87145a8ff581d8738ffbc3ee6f374ab56010) | 按需工具与分组整合已在 main，并保留更强的权限与缓存检查。 |
| `test/on-demand-tools-20261005` | [`8a04448`](https://github.com/zhigege666/Lingshu-Gate/commit/8a044488cb792b3eee96b7b69e1b4f1de2719ee8) | 按需工具控制及定向刷新保留其他实例索引已在 main 覆盖。 |
| `wip/stage1-after-v043-20261005` | [`c59ad25`](https://github.com/zhigege666/Lingshu-Gate/commit/c59ad25d6bfe0f26ce48a0f172bd787ad64b9375) | 仅恢复遗漏的 outputSchema 与旧分类合同两项 ACL 回归；当前运行时在凭据、Git、SRI 和诊断脱敏上已有相等或更强边界，保留历史阶段报告，不替换当前指南。 |

## 已批准的身份修复与恢复

唯一改写的公开 ref 是 `test/gate-release-0.4.7-formal-evidence-20261010`，通过精确旧 SHA lease 从 `e0766101fa344db399122884aadbb08ac4b8f439` 更新为 `f42d609d47066ac8e6e43c13adc6436ab1379007`。三个证据提交中，仅两份 JSON 的 `controlled_retry_request.requesting_execution_agent` 值改为 `Execution agent in the saved cloud workspace`。其他 JSON 值、文件字节及模式、作者与提交者头及正文全部保留，原对象、冻结工作树与记录继续保存。

恢复 bundle 的 SHA-256 为 `449565cc36f3476aaec0024e2cfa8a089b89a06452b78fc873d96da6a68a4f23`。实际恢复使用仅含不可变基线 `45cec40c1e57d7290ab249e620b5a50fa939e115` 的新仓库，导入前原三个证据提交都不存在，随后从 bundle 恢复并通过 `git fsck --full --no-dangling`。未修改的身份检查器随后对当前全部 18 个公开分支头和 17 个标签检查通过。原私有恢复材料继续保存，不公开本地路径或凭据。

v0.4.7 标签仍为 `45cec40c1e57d7290ab249e620b5a50fa939e115`，既有 v0.4.5/v0.4.6 标签继续保留。本次不发布 v0.4.8、不重跑旧 v0.4.5 恢复入口、不部署 nx5，也不将 UI 验收范围扩大至已审查模态范围之外。见[已记录的推送前验证快照](../benchmarks/gate-branch-integration-20261011.json)及 [PR #66 CI 第二轮](https://github.com/zhigege666/Lingshu-Gate/actions/runs/38067497722/attempts/2)；最终 PR 检查记录绑定精确合并候选。

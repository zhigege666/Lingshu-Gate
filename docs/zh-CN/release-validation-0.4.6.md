# 0.4.6 候选与正式发布验证

## 源码与 patch 范围

候选从已合 PR60、PR61 且普通 CI 通过的 main
`3e0f101ed858c94841a1f75b3ef23ee4d52e2e1b` 开始，唯一运行时版本源为
`src/lingshu_gate/_version.py`。本 patch 交付已整合的 0.4.5 功能与账户菜单
焦点修复，不改变权限或可选执行器/OAuth 默认值。已占用的 `v0.4.5` 标签保持
原 SHA；本候选使用新的 `v0.4.6` 身份。

[源码与包证据](../benchmarks/gate-main-package-3622c21.json) 记录先前准确 main
候选、静态清单、PEP517/sdist wheel 校验及 native schema worker 检查；这些是
历史证据，不是 0.4.6 包摘要。新 0.4.6 检查与摘要须分别记录。

## 已跑本地验收与限制

可供独立审查的 [PR62](https://github.com/zhigege666/Lingshu-Gate/pull/62) 记录
48 项所属 adapter 边界回归和产品源码 `3e0f101` 上十组实际 loopback HTTP/stdio
检查。已验证 115 个 Console SHA、111 对根路径/旧路径资源、根入口内容协商、
query 跳转、路径拒绝、管理权限拒绝，以及实际上传/copy-tree/部署/启动/发现
和 stdio 调用。管理器退出后八个已跟踪进程均不存在；所属数据根已删除，私有
回执已保留。

fixture 使用可再生本地合成账户与数据，不创建 nx5 身份、授予或持久 session。
构建计划不含依赖安装或编译命令；发现没有发布工具分类，也没有增加 viewer
权限，因此完整 Project Delivery Skill 验收分别记录。作者检查不计为独审。

Chromium 在 sandbox 开启时实际启动并报 **No usable sandbox**，没有放宽
browser policy。该环境中的四桌面布局/焦点与实际浏览器历史/片段/导航未执行。
先前浏览器和 main 普通 CI 回执保留各自精确源码范围。真实 OAuth 客户端、
跨机器验收及可选 Native/Linux Podman 宿主准备不在本轮本地证据内。

## 正式发布必需门槛

经核验的版本变更推入 main 后调用既有 `publish-release` selector；凭据与
不可变发行预检须成功，才能创建新 tag 并 dispatch `release.yml`。本验证工作
不读出或创建任何凭据值。

正式发布须通过既有 quality、五种 native 目标、Compose、双架构 Core/离线镜像、
应用 SPDX SBOM、镜像引用与 `SHA256SUMS`，共十一项准确资产。核验全部任务、
归档校验和、包内清单、SBOM 和源码/工作流 attestation，再回读公开标题、正文
及可下载资产。候选、tag 或 dispatch 回执均不代表发布完成；不以重跑旧失败
流程或读取旧拒绝 artifact 替代新门槛。

Core 架构和视觉方向属于后续规划，不扩大这次已整合 patch 的发布门槛。

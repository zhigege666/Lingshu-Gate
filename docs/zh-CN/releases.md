# 发行产物

[English](../releases.md) · [文档索引](README.md)

Lingshu Gate 发行自动化会生成可直接运行的原生包、Docker Compose 部署包，以及只在 Tag 发行提供的 Core 离线镜像。每个已发布资产都由 `SHA256SUMS` 和仓库 Build Provenance Attestation 覆盖。

## 产物矩阵

| 目标 | 资产 | 构建架构 |
|---|---|---|
| Linux x86-64 | `lingshu-gate-v<version>-linux-x86_64.tar.gz` | Ubuntu x86-64 |
| Linux ARM64 | `lingshu-gate-v<version>-linux-aarch64.tar.gz` | Ubuntu ARM64 |
| Windows x86-64 | `lingshu-gate-v<version>-windows-x86_64.zip` | Windows x86-64 |
| macOS x86-64 | `lingshu-gate-v<version>-macos-x86_64.tar.gz` | macOS Intel |
| macOS ARM64 | `lingshu-gate-v<version>-macos-arm64.tar.gz` | macOS Apple Silicon |
| Docker Compose | `lingshu-gate-v<version>-docker-compose.tar.gz` | 与平台无关的部署文件 |
| 离线 Core amd64 | `lingshu-gate-v<version>-docker-core-linux-amd64.tar.gz` | 仅 Tag 发行 |
| 离线 Core arm64 | `lingshu-gate-v<version>-docker-core-linux-arm64.tar.gz` | 仅 Tag 发行 |
| 应用 SBOM | `lingshu-gate-v<version>-application-sbom.spdx.json` | 仅 Tag 发行 |
| 容器镜像引用 | `lingshu-gate-v<version>-container-image.txt` | 仅 Tag 发行；记录发布镜像的精确 Digest |

不要在不同操作系统或 CPU 架构上运行不匹配的归档。

## 原生包内容

每个原生归档包含一个顶层目录，以及：

- `lingshu-gate` 可执行文件（Windows 为 `lingshu-gate.exe`）和捆绑运行文件；
- `start.sh` 或 `start.cmd`；
- `lingshu-gate.env.example`；
- 空的 `data`、`config/mcp.d` 和 `workspace` 目录；
- `README.md`、`LICENSE`、`NOTICE` 和 `THIRD_PARTY_NOTICES.md`；
- 使用 SPDX 2.3 的 `SBOM.spdx.json`，覆盖捆绑的 Python Runtime 和 Console 生产依赖闭包；
- `BUILD-INFO.json`，包括版本、Target、Source Revision、规范化构建时间、Builder 版本和文件摘要 Manifest。

启动器会选择包内可写目录，再启动 Gate。直接使用可执行文件时，遵循常规 `LINGSHU_GATE_*` 配置。

该包只包含 Gate 应用运行时，不包含所有下游项目工具链。受管项目所需的解释器、包管理器和容器引擎必须在宿主可用；确认执行前先运行预检。

SBOM 是清单，不是漏洞结论。应根据部署环境使用的安全策略和 Advisory 数据进行评估。

## 校验下载

解压前，把选定资产和 `SHA256SUMS` 下载到同一目录。

Linux：

```bash
asset='lingshu-gate-v<version>-linux-x86_64.tar.gz'
awk -v asset="$asset" '$2 == asset {print}' SHA256SUMS | sha256sum --check -
```

macOS：

```bash
asset='lingshu-gate-v<version>-macos-arm64.tar.gz'
awk -v asset="$asset" '$2 == asset {print}' SHA256SUMS | shasum --algorithm 256 --check
```

Windows PowerShell：

```powershell
$Asset = "lingshu-gate-v<version>-windows-x86_64.zip"
$Line = Get-Content SHA256SUMS | Where-Object { $_ -match "  $([Regex]::Escape($Asset))$" }
if (-not $Line) { throw "Checksum entry not found" }
$Expected = ($Line -split "\s+")[0].ToLowerInvariant()
$Actual = (Get-FileHash -Algorithm SHA256 $Asset).Hash.ToLowerInvariant()
if ($Actual -ne $Expected) { throw "Checksum mismatch" }
```

准确匹配文件名可以避免校验到另一个资产的摘要。条目缺失或不匹配都必须失败。

作为额外来源校验，使用当前 GitHub CLI：

```bash
gh attestation verify <asset> --repo zhigege666/Lingshu-Gate
gh attestation verify SHA256SUMS --repo zhigege666/Lingshu-Gate
```

Checksum 校验证明字节与发行 Manifest 一致；Attestation 校验把资产绑定到仓库工作流身份。生产部署应同时使用两者。

## 启动原生包

成功校验后：

```bash
tar -xzf lingshu-gate-v<version>-linux-x86_64.tar.gz
cd lingshu-gate-v<version>-linux-x86_64
./start.sh
```

Windows：

```powershell
$Destination = "release"
Expand-Archive -Path lingshu-gate-v<version>-windows-x86_64.zip -DestinationPath $Destination
Set-Location "$Destination\lingshu-gate-v<version>-windows-x86_64"
.\start.cmd
```

打开 <http://127.0.0.1:8000/console>，从包内 `data` 目录获取一次性凭据，并立即修改密码。

工作流不执行平台 Code Signing 或 macOS Notarization，因此操作系统可能显示信誉提示。请校验 Checksum 和 Attestation，检查发行记录，并遵循组织批准的执行策略；不要关闭系统级保护。

## Compose 包

校验并解压后：

1. 阅读包内 `DEPLOYMENT.md`；
2. 把 `.env.example` 复制为 `.env`；
3. 设置固定 Digest 的 `LINGSHU_GATE_IMAGE`；
4. 配置 `LINGSHU_GATE_BOOTSTRAP_ADMIN_USERNAME` 和受保护的 `LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE`；
5. 复核 Workspace 和 Proxy 值；
6. 运行 `docker compose config --quiet`；
7. 启动 Core 服务并校验 `/readyz`。

Compose 包包含该发行使用的 `SBOM.spdx.json`、`BUILD-INFO.json`、法律文件和文档。

## 离线 Core 镜像

Tag 发行会在 `lingshu-gate-v<version>-container-image.txt` 中记录已提升 Registry 镜像的精确引用与 Digest，也可以在不从 Registry 拉取镜像的情况下部署：

```bash
gunzip -c lingshu-gate-v<version>-docker-core-linux-amd64.tar.gz | docker load
```

加载后的 Tag 为：

```text
ghcr.io/zhigege666/lingshu-gate:<version>-amd64-offline
```

ARM64 使用 `arm64` 资产和 Tag。让 `LINGSHU_GATE_IMAGE` 指向加载后的 Tag，并把归档 Checksum 和 Attestation 结果保留在部署记录中。校验并保留 `lingshu-gate-v<version>-application-sbom.spdx.json`，作为 Gate 应用依赖清单。它覆盖 Python 应用运行依赖闭包和捆绑 Console 的生产依赖，不覆盖操作系统或容器层；已发布容器的镜像级 SBOM 由其 Container Attestation 提供。

## 自动化行为

发行工作流在影响打包的 Pull Request、手动触发和 `v*` Tag 上运行。独立的 **Publish release** 工作流是正式发行的仓库批准入口：从 `main` 触发并输入精确的 `v<version>` Tag。它会校验源码版本，在该次 `main` 修订上创建或验证不可移动的 Tag，再以已验证的 Tag 触发 `release.yml`。

- Pull Request 和分支级手动运行会构建并冒烟测试原生矩阵和 Compose 包，再上传短期 Workflow Artifact；
- Tag 必须与 `src/lingshu_gate/_version.py` 中的版本完全一致；
- Tag 运行还会从已验证的容器 Payload 导出 Core 离线镜像、构建应用 SPDX SBOM，汇总无文件名冲突的资产目录，重新生成聚合 `SHA256SUMS`，为每个资产生成 Attestation，并创建 GitHub Release；
- 如果该 Tag 的 Release 已存在，工作流要求其不可变、不是 Draft、资产名称集合完全一致且内容逐字节一致，随后保持其不变；Release 可变或资产缺失、陈旧、内容不同都会使运行失败；
- 新建 Release 后，工作流会立即重新读取并要求其不可变、资产完整且与已验证的本地资产逐字节一致；创建发行 Tag 前，请先启用 **Settings > Releases > Enable release immutability**；
- 原生包使用 PyInstaller `6.22.2` 在目标操作系统和架构上构建；
- 打包前基于 Lock File 构建 Console 资产和冻结的 Python 依赖；
- 发布前校验归档路径、时间戳、Mode、Symlink、必需声明、Checksum、SBOM 结构和启动行为。

Pull Request 构建成功不等于已经发布。只有匹配且通过验证的 Tag 才会产生 Release 记录。

## 版本与发行检查清单

创建 Tag 前：

1. 更新单一版本来源和面向用户的发行说明；
2. 运行后端、Console、身份、打包和容器检查；
3. 确认 `LICENSE`、`NOTICE` 和 `THIRD_PARTY_NOTICES.md` 为最新状态；
4. 确认英文与简体中文文档匹配产物行为；
5. 在首次创建 Release 前，为仓库启用 GitHub Release immutability；
6. 从 `main` 触发 **Publish release** 并输入精确的 `v<version>` Tag；工作流会在不移动已有 Ref 的前提下创建或验证 Tag，然后启动已验证的 Tag 发行；
7. 等待全部矩阵 Job 和发布步骤完成；
8. 独立下载并校验至少一个原生归档、Compose 包、`SHA256SUMS` 及其 Attestation；
9. 校验已发布容器摘要和 Release 链接。

工作流不会更新或删除任何已有 Release 或资产。如果首次创建中断并留下 Draft，或此前未启用 Release immutability，请先人工处置该失败 Release，再重试。

发行说明应使用中性语言描述当前行为和运维影响。

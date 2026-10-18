# Docker 生产部署

[English](DEPLOYMENT.md) · [发行包开始页](README.zh-CN.md)

本包运行非特权 Lingshu Gate Core 镜像，不挂载容器引擎 socket。默认 `compose.yaml` 用于 HTTPS 后的生产部署；本机 HTTP 试用请按发行包开始页显式选择 `compose.quickstart.yaml`。

1. 在线部署将 `.env.example` 复制为 `.env`。已载入离线镜像时，复制对应的 `.env.offline-amd64.example` 或 `.env.offline-arm64.example`，其中 `LINGSHU_GATE_PULL_POLICY=never`。
2. 生产使用前，将 `LINGSHU_GATE_IMAGE` 设置为正式发布的镜像 digest。
3. 为 `LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE` 填写一次性 bootstrap 密码文件的绝对路径。容器 UID `10001` 必须能够读取；root 所有的 `0600` 文件并不满足这个条件。
4. 如果浏览器经过反向代理访问 `/mcp`，将 `LINGSHU_GATE_MCP_ALLOWED_ORIGINS` 设置为逗号分隔的精确 Origin。空值只接受服务端口上的 loopback Origin。
5. 按下文准备权限，执行 `docker compose config --quiet`，然后 `docker compose up -d --no-build --wait --wait-timeout 120 core`。
6. 在 `http://127.0.0.1:8000/readyz` 检查就绪；管理员用户名以 `.env` 中的配置为准。

## Linux rootful Docker 的宿主准备

在本包解压目录中创建工作区和随机 bootstrap 密码，需要 OpenSSL 与 `sudo`：

```bash
install -d -m 0700 ./secrets
(umask 077; openssl rand -base64 48 > ./secrets/bootstrap-admin-password)
sudo chown 10001:10001 ./secrets/bootstrap-admin-password
sudo chmod 0400 ./secrets/bootstrap-admin-password
sudo install -d -o 10001 -g 10001 -m 0750 ./workspace
```

将 `.env` 中工作区和密码的占位路径改为上述两处的绝对路径，并填写 bootstrap 用户名、正式镜像 digest、精确代理地址和所需浏览器 Origin。启动前检查实际容器用户能读取秘密，检查命令不打印其值：

```bash
docker compose config --quiet
docker compose run --rm --no-deps --entrypoint sh core -c 'test -r /run/secrets/lingshu_gate_bootstrap_admin_password'
docker compose up -d --no-build --wait --wait-timeout 120 core
```

Rootless Docker 和 Docker Desktop 的宿主、虚拟机 UID 映射不同，需要采用相应的受保护权限映射，并执行同样的可读检查。不要通过允许所有人读取密码来解决权限错误。

从配置好的 HTTPS 入口打开 Console。在本机用 `sudo cat ./secrets/bootstrap-admin-password` 读取密码，以配置的用户名登录，修改密码后重新登录。旧密码和旧会话应失效。Compose 仍引用 bootstrap 文件时须保持它存在且受保护；外部准备的文件不会由 Gate 删除。读取自动生成的 `initial-admin-credentials.json` 属于本机 quickstart 流程。

## 代理与运行边界

未配置 TLS 反向代理和明确受信代理策略时保持 loopback 绑定。`LINGSHU_GATE_TRUSTED_PROXY_IPS` 只填写实际代理容器或地址，不信任不受控的整个网络。生产模板启用 Secure cookie，本机 HTTP 页面无法代替 HTTPS 登录验收。

`LINGSHU_GATE_MCP_ALLOWED_ORIGINS` 针对带 `Origin` 头的浏览器请求；普通非浏览器请求通常不带该头，不受浏览器 Origin 清单影响。

`SBOM.spdx.json` 列明 Python 应用运行依赖闭包和本版本 Console 生产依赖，不是操作系统或容器层清单。使用发行级 `SHA256SUMS` 与构建证明校验它和归档。

## 包内指南与可选服务

包内包含中英文 README、`docs/`、`examples/`、安全与发行说明及 Project Delivery Skill。参见[首次授权调用](../../docs/zh-CN/first-call.md)。启动可选 demo 前先完成本包的 Compose 配置，使用所选镜像，不进行源码构建。

`LINGSHU_GATE_TELEMETRY` 传给 Core，默认关闭。仅启用指标不需要导出凭据；链路 token/CA 文件需要明确只读挂载及正确所有者权限。参见[标准观测](../../docs/zh-CN/telemetry.md)。

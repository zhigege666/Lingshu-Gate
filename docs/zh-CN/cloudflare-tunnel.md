# Cloudflare Tunnel

Lingshu Gate 支持通过独立的 `cloudflared` Sidecar 使用 Cloudflare Tunnel。Gate Core 容器仍保持非特权运行，不挂载 Docker Socket，也不接触隧道 Token。

## Docker Compose

1. 在 Cloudflare Zero Trust 中创建远程管理隧道，并添加 Published application 路由。
2. 路由的 Service 设置为 `http://core:8000`。`cloudflared` 与 Gate 共用私有 Compose 网络，不要将 8000 端口直接暴露到公网。
3. 在部署目录的 `.env` 中设置 `LINGSHU_GATE_CLOUDFLARE_TOKEN_FILE`，使用宿主机上的绝对路径，例如 `/etc/lingshu-gate/secrets/cloudflare-tunnel-token`。源码部署若使用独立的生产配置，请同时设置 `COMPOSE_FILE=compose.prod.yaml`；正式 Compose 发行包已将生产配置命名为 `compose.yaml`。
4. 在宿主机以管理员身份将 Token 粘贴到该文件。默认 Docker 映射下，将其所有者设为 `65532:65532`、权限设为 `0400`，并限制宿主机目录访问。使用 user namespace 或 rootless Docker 时，请改用对应的宿主机映射 UID。文件必须预先存在。
5. 在同一部署目录执行：

   ```bash
   docker compose --profile cloudflare-tunnel up -d cloudflared
   docker compose ps --all cloudflared
   docker compose logs --tail=100 cloudflared
   ```

   通过 Cloudflare 控制台确认 Connector 显示 Healthy。从“系统设置 → Cloudflare Tunnel”可复制上述命令。运行 `docker compose stop cloudflared` 可单独停止隧道。

默认镜像为 `cloudflare/cloudflared:2026.10.7`，可通过 `LINGSHU_GATE_CLOUDFLARED_IMAGE` 指定已审核的镜像摘要。Token 仅以只读文件挂载到隧道容器。使用编辑器原子替换文件完成轮换后，执行 `docker compose up -d --force-recreate --no-deps cloudflared` 重新挂载新文件。

## 通过公网 HTTPS 域名访问

转发给 Core 时保留公网域名。将 `LINGSHU_GATE_TRUSTED_PROXY_IPS` 设为隧道容器的地址或最小专用网段，使 Gate 能识别外部 HTTPS 协议。如果浏览器客户端向 `/mcp` 发送 Origin，在 `LINGSHU_GATE_MCP_ALLOWED_ORIGINS` 中加入精确的外部来源，例如 `https://gate.example.com`。将配置应用到 Core 后，从公网域名验证登录和同源设置保存。参见[反向代理配置](configuration.md)。

## 安全与运维

- 远程管理隧道 Token 的持有者可以运行该隧道，必须按密码保护；怀疑泄露时应在 Cloudflare 中轮换。
- 应配置 Cloudflare Access 策略限制 Gate 域名的访问者。Tunnel 负责发布域名，不替代 Gate 自身的认证与授权。
- Cloudflare 路由必须指向内部服务 `http://core:8000`，不要指向宿主机公网 IP。
- Sidecar 不挂载 Docker Socket、不使用 host 网络、不申请 Linux capabilities，根文件系统只读。
- 隧道健康由 cloudflared 进程和 Cloudflare Connector 状态负责。Gate Core 不宣称可以控制或读取 Sidecar 状态。
- 此配置适用于 Docker Compose。Unraid 用户可在同一个自定义 Docker 网络中单独创建 `cloudflare/cloudflared` 容器，只读挂载 Token 文件，并使用相同的 cloudflared 命令。将源站设置为 Gate 实际容器名和内部端口，例如 `http://lingshu-gate:8000`。

## 官方参考

- [cloudflared 2026.10.7 发行版本](https://github.com/cloudflare/cloudflared/releases/tag/2026.10.7)
- [Tunnel 运行参数与 token-file 要求](https://developers.cloudflare.com/tunnel/reference/run-parameters/)
- [cloudflared 官方容器与非 root 用户](https://github.com/cloudflare/cloudflared/blob/master/Dockerfile)

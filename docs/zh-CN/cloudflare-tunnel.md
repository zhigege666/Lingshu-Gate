# Cloudflare Tunnel

Lingshu Gate 支持通过独立的 `cloudflared` Sidecar 使用 Cloudflare Tunnel。Gate Core 容器仍保持非特权运行，不挂载 Docker Socket，也不接触隧道 Token。

## Docker Compose

1. 在 Cloudflare Zero Trust 中创建远程管理隧道，并添加 Published application 路由。
2. 路由的 Service 设置为 `http://core:8000`。`cloudflared` 与 Gate 共用私有 Compose 网络，不要将 8000 端口直接暴露到公网。
3. 在宿主机创建 Token 文件。文件必须放在仓库之外，并限制部署管理员读取：

   ```bash
   install -d -m 700 ./secrets
   install -m 600 /dev/null ./secrets/cloudflare-tunnel-token
   chown 65532:65532 ./secrets/cloudflare-tunnel-token
   # 使用安全编辑器将隧道 Token 写入文件。
   ```

4. 启动可选服务：

   ```bash
   LINGSHU_GATE_CLOUDFLARE_TOKEN_FILE=./secrets/cloudflare-tunnel-token docker compose --profile cloudflare-tunnel up -d cloudflared
   ```

5. 使用 `docker compose logs --tail=100 cloudflared` 查看连接日志，并在 Cloudflare 控制台确认 Connector 状态为 Healthy。

只有显式启用 `cloudflare-tunnel` profile 才会启动隧道。Token 通过只读文件挂载，不放入 Compose 环境变量或命令行参数。默认镜像为 `cloudflare/cloudflared:latest`；生产环境应通过 `LINGSHU_GATE_CLOUDFLARED_IMAGE` 指定经过审核的版本或 digest。

## 安全与运维

- 远程管理隧道 Token 的持有者可以运行该隧道，必须按密码保护；怀疑泄露时应在 Cloudflare 中轮换。
- 应配置 Cloudflare Access 策略限制 Gate 域名的访问者。Tunnel 负责发布域名，不替代 Gate 自身的认证与授权。
- Cloudflare 路由必须指向内部服务 `http://core:8000`，不要指向宿主机公网 IP。
- Sidecar 不挂载 Docker Socket、不使用 host 网络、不申请 Linux capabilities，根文件系统只读。
- 隧道健康由 cloudflared 进程和 Cloudflare Connector 状态负责。Gate Core 不宣称可以控制或读取 Sidecar 状态。
- 此配置适用于 Docker Compose。Unraid 用户可在同一个自定义 Docker 网络中单独创建 `cloudflare/cloudflared` 容器，只读挂载 Token 文件，并使用相同命令和内部源站地址。
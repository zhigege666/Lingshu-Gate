# Cloudflare Tunnel

Lingshu Gate supports Cloudflare Tunnel as an optional, separately managed `cloudflared` sidecar. The Gate Core container remains unprivileged and does not receive a Docker socket or tunnel token.

## Docker Compose

1. Create a remotely managed tunnel in Cloudflare Zero Trust and add a published application route.
2. Set the route service to `http://core:8000`. The `cloudflared` sidecar shares the private Compose network with Gate; do not publish port 8000 publicly.
3. In the deployment directory’s `.env`, set `LINGSHU_GATE_CLOUDFLARE_TOKEN_FILE` to an absolute host path such as `/etc/lingshu-gate/secrets/cloudflare-tunnel-token`. For the standalone production manifest in the source tree, also set `COMPOSE_FILE=compose.prod.yaml`. The official Compose archive already names that manifest `compose.yaml`.
4. As the deployment administrator, paste the token into that file using a secret-safe editor. With the default Docker UID mapping, set its owner to `65532:65532` and mode to `0400`; restrict access to the host directory. For rootless Docker or user namespace remapping, use the corresponding mapped host UID. The file must exist before startup.
5. In the same deployment directory, run:

   ```bash
   docker compose --profile cloudflare-tunnel up -d cloudflared
   docker compose ps --all cloudflared
   docker compose logs --tail=100 cloudflared
   ```

   Confirm the connector is Healthy in the Cloudflare dashboard. The Console’s **System settings → Cloudflare Tunnel** tab provides copyable commands. To stop the tunnel alone, run `docker compose stop cloudflared`.

The default image is `cloudflare/cloudflared:2026.10.7`. Set `LINGSHU_GATE_CLOUDFLARED_IMAGE` to a reviewed digest to pin its identity. The tunnel token is mounted read-only in the tunnel container. After rotating it by replacing the host file, run `docker compose up -d --force-recreate --no-deps cloudflared` to remount the new file.

## Security and operation

- Anyone holding a remotely managed tunnel token can run that tunnel. Treat it as a password; rotate it in Cloudflare after suspected exposure.
- Use Cloudflare Access policies to restrict who can reach the Gate hostname. A Tunnel alone publishes the hostname; it does not replace Gate authentication or authorization.
- The Cloudflare route must point to the internal service `http://core:8000`, not the host's public IP.
- The sidecar has no Docker socket, host networking, Linux capabilities, or writeable root filesystem.
- Tunnel health is managed by the cloudflared process and Cloudflare connector status. Gate Core does not claim to control or introspect the sidecar.
- This setup supports Docker Compose deployments. Unraid users can create a separate `cloudflare/cloudflared` container on the same user-defined Docker network, mount the token file read-only, and use the same cloudflared command. Set the origin to the actual Gate container name and internal port, for example `http://lingshu-gate:8000`.

## Official references

- [cloudflared 2026.10.7 release](https://github.com/cloudflare/cloudflared/releases/tag/2026.10.7)
- [Tunnel run parameters and token-file requirement](https://developers.cloudflare.com/tunnel/reference/run-parameters/)
- [Official cloudflared container and non-root user](https://github.com/cloudflare/cloudflared/blob/master/Dockerfile)

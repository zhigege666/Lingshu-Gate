# Cloudflare Tunnel

Lingshu Gate supports Cloudflare Tunnel as an optional, separately managed `cloudflared` sidecar. The Gate Core container remains unprivileged and does not receive a Docker socket or tunnel token.

## Docker Compose

1. Create a remotely managed tunnel in Cloudflare Zero Trust and add a published application route.
2. Set the route service to `http://core:8000`. The `cloudflared` sidecar shares the private Compose network with Gate; do not publish port 8000 publicly.
3. Create the token file on the host. Keep it outside the repository and restrict it to the deployment administrator:

   ```bash
   install -d -m 700 ./secrets
   install -m 600 /dev/null ./secrets/cloudflare-tunnel-token
   chown 65532:65532 ./secrets/cloudflare-tunnel-token
   # Paste the tunnel token into this file using a secret-safe editor.
   ```

4. Start the optional service:

   ```bash
   LINGSHU_GATE_CLOUDFLARE_TOKEN_FILE=./secrets/cloudflare-tunnel-token docker compose --profile cloudflare-tunnel up -d cloudflared
   ```

5. Check `docker compose logs --tail=100 cloudflared` and the Cloudflare dashboard for a Healthy connector.

The Compose profile does not start the tunnel unless explicitly selected. The token-file option requires cloudflared 2025.4.0 or later; the pinned image version meets this requirement. The token is mounted as a read-only file and is not placed in Compose environment variables or command arguments. `cloudflare/cloudflared:2026.10.7` is the default image reference; operators can set `LINGSHU_GATE_CLOUDFLARED_IMAGE` to a reviewed digest when they require immutable image identity.

## Security and operation

- Anyone holding a remotely managed tunnel token can run that tunnel. Treat it as a password; rotate it in Cloudflare after suspected exposure.
- Use Cloudflare Access policies to restrict who can reach the Gate hostname. A Tunnel alone publishes the hostname; it does not replace Gate authentication or authorization.
- The Cloudflare route must point to the internal service `http://core:8000`, not the host's public IP.
- The sidecar has no Docker socket, host networking, Linux capabilities, or writeable root filesystem.
- Tunnel health is managed by the cloudflared process and Cloudflare connector status. Gate Core does not claim to control or introspect the sidecar.
- This setup supports Docker Compose deployments. Unraid users can create a separate `cloudflare/cloudflared` container on the same user-defined Docker network, mount the token file read-only, and use the same command and internal origin URL.

## Official references

- [cloudflared 2026.10.7 release](https://github.com/cloudflare/cloudflared/releases/tag/2026.10.7)
- [Tunnel run parameters and token-file requirement](https://developers.cloudflare.com/tunnel/reference/run-parameters/)
- [Official cloudflared container and non-root user](https://github.com/cloudflare/cloudflared/blob/master/Dockerfile)
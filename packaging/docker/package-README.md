# Lingshu Gate @VERSION@ — Docker Compose package

[简体中文](README.zh-CN.md) · [Getting started](../../docs/getting-started.md) · [Release verification](../../docs/releases.md)

Use Docker Engine and Docker Compose to run the released Core image. This package needs no source checkout, host Python or Node.js. Core provides the Console and external HTTP MCP gateway; trusted local stdio and project execution use the native package.

Download this Compose archive and `SHA256SUMS` from [v@VERSION@](https://github.com/zhigege666/Lingshu-Gate/releases/tag/v@VERSION@), verify the matching checksum, extract it and enter `lingshu-gate-v@VERSION@-docker-compose/`. [Release verification](../../docs/releases.md) covers archive and provenance checks.

## Try it on this computer

Run these commands from the extracted directory:

```bash
cp .env.quickstart.example .env.quickstart
docker compose --env-file .env.quickstart -f compose.quickstart.yaml config --quiet
docker compose --env-file .env.quickstart -f compose.quickstart.yaml up -d --no-build --wait --wait-timeout 120 core
```

PowerShell uses the same Docker commands; replace the first line with `Copy-Item .env.quickstart.example .env.quickstart`. The image is pinned to this release's version tag. No build, TLS domain or bootstrap-secret setup is needed for this local trial.

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/). Read the generated one-time credentials locally:

```bash
docker compose --env-file .env.quickstart -f compose.quickstart.yaml exec core cat /data/initial-admin-credentials.json
```

Sign in with that username and password, change the password, then sign in again. The old session is invalidated and the initial file is removed. Do not include its contents in shared logs or screenshots.

The trial binds only host `127.0.0.1`, keeps authentication on and uses cookies for local HTTP. Core runs as UID/GID `10001`, with a read-only root, empty read-only workspace and no container-engine socket. The `lingshu-gate-quickstart` project owns separate data and configuration volumes. Do not reuse production volumes. If port 8000 is occupied, change `LINGSHU_GATE_HTTP_PORT` and its matching loopback `LINGSHU_GATE_MCP_ALLOWED_ORIGINS` in `.env.quickstart`, then use the chosen URL.

## Start the optional demo

```bash
docker compose --env-file .env.quickstart -f compose.quickstart.yaml -f examples/compose.demo.yaml up -d --no-build --wait --wait-timeout 120 core demo
```

The demo shares Core's network namespace and listens on `127.0.0.1:18880`; it publishes no extra host port. The command waits for Core and the demo listener. Then follow [First successful and denied calls](../../docs/first-call.md) to connect, review, publish and grant access through Gate. A running demo does not automatically create users, grants or published tools.

Stop only the demo with the same `--env-file` and two `-f` options followed by `stop demo`. Start it again with the command above. To stop the whole trial while retaining data:

```bash
docker compose --env-file .env.quickstart -f compose.quickstart.yaml -f examples/compose.demo.yaml down
```

The next `up` reuses this trial's volumes and changed password. Do not add `--volumes` unless you intend to delete the trial's saved data.

## Production or offline use

For production follow [DEPLOYMENT.md](DEPLOYMENT.md), or [中文部署说明](DEPLOYMENT.zh-CN.md). The default `compose.yaml` requires an explicit bootstrap username/password file and uses Secure cookies behind HTTPS. Select the published image digest and configure the actual trusted proxy and browser origins. Local HTTP quickstart and production are explicit, separate configurations.

For offline evaluation, first verify and load the matching offline image as described in [deployment](../../docs/deployment.md#offline-docker-image). In `.env.quickstart` set `LINGSHU_GATE_IMAGE=ghcr.io/zhigege666/lingshu-gate:@VERSION@-amd64-offline` (use `arm64` for that host) and `LINGSHU_GATE_PULL_POLICY=never`. Use the same quickstart commands. The `.env.offline-*.example` files configure production Compose, including its bootstrap and HTTPS requirements.

Keep one Core per database. Back up data, configuration and credential keys together before upgrading. `BUILD-INFO.json`, `SBOM.spdx.json`, legal notices and [all guides](../../docs/README.md) are included in this package.

# Getting started

[简体中文](zh-CN/getting-started.md) · [Documentation index](README.md)

Start Gate, sign in, then use the included local demo to verify one allowed read and one denied write. Choose an installation before continuing to [First successful and denied calls](first-call.md). No separate desktop MCP client is needed for that walkthrough.

## Choose an entry

| Goal | Install | Host requirements |
|---|---|---|
| Try a released version; use trusted local stdio later | Native archive for your OS and CPU | No Python, Node.js or Git for Gate itself |
| Try the released HTTP gateway in a container | Compose archive, explicit `compose.quickstart.yaml` | Docker Engine and Docker Compose with `up --wait` |
| Run a production gateway | Compose archive, default `compose.yaml`, or a managed native service | TLS, explicit credentials, persistent storage and backup; see [deployment](deployment.md) |
| Develop Gate | Source checkout | Git, Python 3.11–3.13, uv; Node.js 22.12+ in 22.x, 24.x or 26+, and npm |

Each database has one Gate writer. Native can execute trusted local processes; Docker Core connects to external HTTP services and does not receive the container-engine socket.

## Download and verify

Download from [Lingshu Gate v0.5.0](https://github.com/zhigege666/Lingshu-Gate/releases/tag/v0.5.0), together with `SHA256SUMS`. Choose one archive:

| Platform | File |
|---|---|
| Linux x86-64 | `lingshu-gate-v0.5.0-linux-x86_64.tar.gz` |
| Linux ARM64 | `lingshu-gate-v0.5.0-linux-aarch64.tar.gz` |
| Windows x86-64 | `lingshu-gate-v0.5.0-windows-x86_64.zip` |
| macOS Intel | `lingshu-gate-v0.5.0-macos-x86_64.tar.gz` |
| macOS Apple silicon | `lingshu-gate-v0.5.0-macos-arm64.tar.gz` |
| Docker Compose | `lingshu-gate-v0.5.0-docker-compose.tar.gz` |

Verify that exact file against its single matching checksum line before extracting or running it. [Release verification](releases.md) provides Linux, macOS and Windows commands and build-provenance verification. Stop if the line is missing, duplicated or does not match. Each extracted package has its own English/Chinese README and local copies of these guides.

## Run a native package

Extract the verified archive, enter its directory and run `./start.sh` on Linux/macOS or `.\start.cmd` on Windows. The directory name matches the archive without its extension, for example `lingshu-gate-v0.5.0-linux-x86_64`. Keep this terminal open.

Visit [http://127.0.0.1:8000/](http://127.0.0.1:8000/). In a second terminal in the package directory, read `data/initial-admin-credentials.json` with `cat` or PowerShell `Get-Content`. Sign in, change the initial password and sign in again. Gate removes that file and invalidates the old session. Read credentials only on your computer; omit them from shared logs, screenshots and reports.

The launcher defaults to package-local `data/`, `config/mcp.d/` and `workspace/`. Existing `LINGSHU_GATE_*` environment settings take precedence; if you changed the data directory or port, read credentials in that actual directory and use that URL. It does not automatically load `lingshu-gate.env.example`; that file documents optional environment settings. Continue to [the demo](first-call.md#start-the-demo-beside-gate).

## Run the released Docker trial

After verifying and extracting the Compose archive, enter `lingshu-gate-v0.5.0-docker-compose` and run:

```bash
cp .env.quickstart.example .env.quickstart
docker compose --env-file .env.quickstart -f compose.quickstart.yaml config --quiet
docker compose --env-file .env.quickstart -f compose.quickstart.yaml up -d --no-build --wait --wait-timeout 120 core
docker compose --env-file .env.quickstart -f compose.quickstart.yaml exec core cat /data/initial-admin-credentials.json
```

In PowerShell, replace `cp` with `Copy-Item`; the Docker commands are identical. Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/), use the generated credentials, change the password and sign in again. The initial file is then removed. If any startup command fails, inspect its error before continuing.

This explicit quickstart uses the released image without a build, loopback-only HTTP with authentication, UID/GID `10001`, a read-only root and no engine socket. Its `lingshu-gate-quickstart` project and volumes are separate from production. If the host port is occupied, set another `LINGSHU_GATE_HTTP_PORT` and its exact loopback `LINGSHU_GATE_MCP_ALLOWED_ORIGINS` in `.env.quickstart`, then use that URL. The image's `/workspace` is empty and read-only for this trial.

For offline use, [load the matching offline image](deployment.md#offline-docker-image) and select its exact tag plus `LINGSHU_GATE_PULL_POLICY=never` in `.env.quickstart`. For production, use the bundle's paired `DEPLOYMENT.md` / `DEPLOYMENT.zh-CN.md`, which explain the default Compose file, digest, bootstrap file, TLS and Secure cookies. Continue to [the demo](first-call.md#start-the-demo-beside-gate).

## Develop from source

With the host requirements in the table installed:

```bash
git clone https://github.com/zhigege666/Lingshu-Gate.git
cd Lingshu-Gate
uv sync --frozen
npm --prefix web ci
npm --prefix web run build
uv run lingshu-gate
```

For a Docker source build, run this alternative from the same repository root:

```bash
mkdir -p runtime/workspace
docker compose up -d --build --wait --wait-timeout 120 core
docker compose exec core cat /data/initial-admin-credentials.json
```

Use separate development data, configuration and workspace paths, following [local development](local-development.md). After a fresh startup, read the one-time credentials from the selected data directory, sign in, change the password and sign in again. Do not share live production data with a development instance.

## Finish the first call

The [first-call guide](first-call.md) walks through an independent in-memory demo, explicit review/publication, a separate viewer's authorization, dynamic tool discovery, real invocation, audit, denied writes, invalid revisions, stopping/restarting the demo and revocation. A healthy Gate alone does not mean a downstream tool is published or authorized.

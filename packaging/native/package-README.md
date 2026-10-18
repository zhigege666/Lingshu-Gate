# Lingshu Gate @VERSION@ — native package

[简体中文](README.zh-CN.md) · [Getting started](../../docs/getting-started.md) · [Release verification](../../docs/releases.md)

This package includes Gate, its Web Console and an opt-in local demonstration MCP server. Gate itself needs no host Python, Node.js or Git installation. A downstream service or trusted project build can still require its own runtime.

## Verify, extract and start

Download the archive for your operating system and CPU plus `SHA256SUMS` from [this release](https://github.com/zhigege666/Lingshu-Gate/releases/tag/v@VERSION@). Compare the archive's SHA-256 with its matching line before extraction; [release verification](../../docs/releases.md) includes every platform and provenance verification.

For example, on Linux x86-64, from the download directory:

```bash
awk '$2 == "lingshu-gate-v@VERSION@-linux-x86_64.tar.gz" {print; n++} END {if (n != 1) exit 1}' SHA256SUMS > SHA256SUMS.native &&
sha256sum --check SHA256SUMS.native &&
tar -xzf lingshu-gate-v@VERSION@-linux-x86_64.tar.gz &&
cd lingshu-gate-v@VERSION@-linux-x86_64 &&
./start.sh
```

On macOS use the matching `macos-arm64` or `macos-x86_64` archive, verify with `shasum -a 256`, extract, enter that directory and run `./start.sh`. On Windows x86-64, verify with `Get-FileHash -Algorithm SHA256`, then in PowerShell:

```powershell
Expand-Archive .\lingshu-gate-v@VERSION@-windows-x86_64.zip -DestinationPath .
Set-Location .\lingshu-gate-v@VERSION@-windows-x86_64
.\start.cmd
```

If this directory is already extracted and verified, run its launcher directly. Keep the terminal open and visit [http://127.0.0.1:8000/](http://127.0.0.1:8000/). By default, the launcher stores `data/`, `config/mcp.d/` and `workspace/` inside this directory. Existing `LINGSHU_GATE_*` environment settings take precedence; if you changed the data directory or port, read credentials in that actual directory and use that URL. The example environment file is a reference; the launcher does not automatically load it.

## First sign-in

On an empty data directory, Gate generates private one-time credentials. In a second terminal in this package directory, read them locally:

```bash
cat data/initial-admin-credentials.json
```

On Windows: `Get-Content .\data\initial-admin-credentials.json`. Use the displayed username and password, change the password when prompted, then sign in again. The change invalidates the old session and removes that initial file. Keep the credentials out of shared terminal logs, screenshots and support reports. A missing file after the password change is expected.

## Make the first authorized call

Keep Gate running. In the second terminal start the independent demo:

```bash
./lingshu-gate demo-server --host 127.0.0.1 --port 18880
```

On Windows:

```powershell
.\lingshu-gate.exe demo-server --host 127.0.0.1 --port 18880
```

Follow [First successful and denied calls](../../docs/first-call.md): connect the included `examples/mcp.d/demo.yaml`, review and publish its three tools, create a separate read-only caller, then discover and invoke a read tool. Check the successful audit, deny a write without changing the counter, test an outdated revision, stop/restart the demo and revoke the token. The guide uses existing HTTP tools; it does not require a desktop MCP client.

The demo only changes its own in-memory note. Ctrl+C stops it and clears that note; Gate remains a separate process. Ctrl+C in Gate's terminal stops Gate while preserving its data and configuration.

## Keep a working installation

Use one Gate process per database. Back up data, configuration and credential keys consistently before upgrades; preserve the matching old backup for rollback. Avoid extracting a new version over a live data directory. A native installation can execute trusted local projects and stdio tools, so run it under a suitably restricted user.

[Deployment and upgrades](../../docs/deployment.md) · [Configuration](../../docs/configuration.md) · [Security](../../SECURITY.md) · [All guides](../../docs/README.md)

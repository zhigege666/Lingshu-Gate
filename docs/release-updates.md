# Check and install updates

Open **System settings → Updates** to check the latest stable release of `zhigege666/Lingshu-Gate`. The Console shows the running version, latest tag, release date, notes and link. You can repeat the check at any time.

## Use a proxy for release checks

Create an HTTP or HTTPS proxy profile under **System settings → Network and dependencies**. In **Updates**, choose the enabled profile and select **Save and check**. The check uses that profile revision. Select **Direct to GitHub** and save to return to direct access. Proxy credentials stay in Gate's encrypted credential store. Git imports, package registries and MCP requests keep their own network settings.

Agents with the `system_settings.manage` permission can read the current revision with `GET /v1/system-settings/updates`, save `expected_revision`, `proxy_profile_id` and `proxy_profile_version` with `PUT` on that path, and check with `POST /v1/system-settings/updates/check`. For direct access, send null for both proxy fields.

## Enable native updates on startup

Back up the database, configuration and credential keys together. Install GitHub CLI (`gh`) with `gh attestation verify` support and configure its GitHub access for the operating-system account that runs the launcher. The host's GitHub CLI uses its own proxy environment. The Console proxy only handles the version check made by Gate.

Stop the old Gate process and change the service's startup command to the following. Run it from the original installation directory or use the absolute executable path.

```sh
./lingshu-gate native-update update-start
```

On Windows use `.\lingshu-gate.exe native-update update-start`. Each startup checks the stable GitHub release, verifies the platform asset's size, SHA-256 and GitHub Actions provenance, then starts the selected binary. Keep using this launcher for later starts. The original installation's data, configuration and workspace paths continue to apply.

| Action after `native-update` | Effect |
|---|---|
| `update` | Check and stage the verified release for the next managed start. Suitable for a host scheduled task. |
| `start` | Start the selected local version without contacting GitHub, including after a failed network check. |
| `rollback` | Select the previous binary for the next managed start. Stop Gate first. If the database migrated, restore the matching backup before starting that binary. |

For an existing 0.5.10 installation, verify and extract 0.5.11 in a separate directory. Run the new binary with `native-update update-start --install-dir "/path/to/old-package"` after stopping the old process. Keep the new launcher's path in your service configuration. After starting Gate, check `/readyz` and the running version in the Console.

Docker and Unraid users can use the same Console release check. Upgrade the image with Compose or the Unraid container manager.

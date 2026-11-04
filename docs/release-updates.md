# Release update checks

The Console checks the latest stable GitHub Release for `zhigege666/Lingshu-Gate` when the Updates tab is opened. Administrators can also trigger a manual check. The result includes the running backend version, latest tag, release date, notes and release link.

## Optional GitHub proxy

The update checker can use one existing, enabled HTTP or HTTPS proxy profile:

1. Create or review a proxy profile under System settings → Network and dependencies.
2. Open System settings → Updates.
3. Select the proxy profile and save it. The checker pins the selected profile revision.
4. Select Direct to GitHub to disable the proxy for update checks.

The proxy setting is isolated to the GitHub Release API request. It does not change Git acquisition, npm/Python registries, MCP calls, or other Gate traffic. Credentials remain in the existing encrypted credential store and are never returned by the update settings API. SOCKS profiles are not supported by this checker.

## Installation boundary

Release discovery is automatic; applying an update is still a deployment operation. Gate Core intentionally has no Docker Engine socket and cannot replace its own container. Use the published release assets or your deployment platform to update the image/package, then verify `/readyz` and the running version. This feature does not silently restart Gate, migrate data outside the normal startup migration path, or roll back a deployment.
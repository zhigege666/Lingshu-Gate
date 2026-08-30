# Release artifacts

[简体中文](zh-CN/releases.md) · [Documentation index](README.md)

Lingshu Gate release automation produces directly runnable native packages, a Docker Compose deployment bundle, and tagged-release offline Core images. Every published asset is covered by `SHA256SUMS` and a repository build-provenance attestation.

## Artifact matrix

| Target | Asset | Build architecture |
|---|---|---|
| Linux x86-64 | `lingshu-gate-v<version>-linux-x86_64.tar.gz` | Ubuntu x86-64 |
| Linux ARM64 | `lingshu-gate-v<version>-linux-aarch64.tar.gz` | Ubuntu ARM64 |
| Windows x86-64 | `lingshu-gate-v<version>-windows-x86_64.zip` | Windows x86-64 |
| macOS x86-64 | `lingshu-gate-v<version>-macos-x86_64.tar.gz` | macOS Intel |
| macOS ARM64 | `lingshu-gate-v<version>-macos-arm64.tar.gz` | macOS Apple silicon |
| Docker Compose | `lingshu-gate-v<version>-docker-compose.tar.gz` | Platform-neutral deployment files |
| Offline Core amd64 | `lingshu-gate-v<version>-docker-core-linux-amd64.tar.gz` | Tagged releases only |
| Offline Core arm64 | `lingshu-gate-v<version>-docker-core-linux-arm64.tar.gz` | Tagged releases only |
| Application SBOM | `lingshu-gate-v<version>-application-sbom.spdx.json` | Tagged releases only |
| Container image reference | `lingshu-gate-v<version>-container-image.txt` | Tagged releases only; exact published image digest |

Do not run an archive built for a different operating system or CPU architecture.

## Native package contents

Each native archive contains one top-level directory and:

- the `lingshu-gate` executable (`lingshu-gate.exe` on Windows) with its bundled runtime files;
- `start.sh` or `start.cmd`;
- `lingshu-gate.env.example`;
- empty `data`, `config/mcp.d`, and `workspace` directories;
- `README.md`, `LICENSE`, `NOTICE`, and `THIRD_PARTY_NOTICES.md`;
- `SBOM.spdx.json` using SPDX 2.3 and covering the bundled Python runtime plus the Console production dependency closure;
- `BUILD-INFO.json` with version, target, source revision, normalized build time, builder versions, and a file digest manifest.

The launcher selects package-local writable directories and then starts Gate. Direct executable use follows normal `LINGSHU_GATE_*` configuration.

The package includes Gate's application runtime, not every downstream project toolchain. Managed projects must find their required interpreters, package managers, and container engine on the host; run preflight before confirming execution.

The SBOM is an inventory, not a vulnerability verdict. Evaluate it against the policy and advisory data used by your deployment environment.

## Verify a download

Download the chosen asset and `SHA256SUMS` into the same directory before extraction.

Linux:

```bash
asset='lingshu-gate-v<version>-linux-x86_64.tar.gz'
awk -v asset="$asset" '$2 == asset {print}' SHA256SUMS | sha256sum --check -
```

macOS:

```bash
asset='lingshu-gate-v<version>-macos-arm64.tar.gz'
awk -v asset="$asset" '$2 == asset {print}' SHA256SUMS | shasum --algorithm 256 --check
```

Windows PowerShell:

```powershell
$Asset = "lingshu-gate-v<version>-windows-x86_64.zip"
$Line = Get-Content SHA256SUMS | Where-Object { $_ -match "  $([Regex]::Escape($Asset))$" }
if (-not $Line) { throw "Checksum entry not found" }
$Expected = ($Line -split "\s+")[0].ToLowerInvariant()
$Actual = (Get-FileHash -Algorithm SHA256 $Asset).Hash.ToLowerInvariant()
if ($Actual -ne $Expected) { throw "Checksum mismatch" }
```

An exact file-name match prevents verifying the digest for a different asset. A missing or mismatched line is a hard failure.

As an additional source check, use a current GitHub CLI:

```bash
gh attestation verify <asset> --repo zhigege666/Lingshu-Gate
gh attestation verify SHA256SUMS --repo zhigege666/Lingshu-Gate
```

Checksum verification proves byte integrity against the release manifest. Attestation verification binds the asset to the repository workflow identity. Use both for production deployment.

## Start a native package

After successful verification:

```bash
tar -xzf lingshu-gate-v<version>-linux-x86_64.tar.gz
cd lingshu-gate-v<version>-linux-x86_64
./start.sh
```

Windows:

```powershell
$Destination = "release"
Expand-Archive -Path lingshu-gate-v<version>-windows-x86_64.zip -DestinationPath $Destination
Set-Location "$Destination\lingshu-gate-v<version>-windows-x86_64"
.\start.cmd
```

Open <http://127.0.0.1:8000/console>, retrieve the one-time credentials from the package-local `data` directory, and change the password immediately.

The workflow does not apply platform code signing or macOS notarization. Operating-system reputation prompts may therefore appear. Verify the checksum and attestation, inspect the release record, and follow your organization's approved execution policy; do not disable system-wide protections.

## Compose bundle

After verification and extraction:

1. read the bundled `DEPLOYMENT.md`;
2. copy `.env.example` to `.env`;
3. set a digest-pinned `LINGSHU_GATE_IMAGE`;
4. configure `LINGSHU_GATE_BOOTSTRAP_ADMIN_USERNAME` and a protected `LINGSHU_GATE_BOOTSTRAP_PASSWORD_FILE`;
5. review workspace and proxy values;
6. run `docker compose config --quiet`;
7. start the Core service and verify `/readyz`.

The Compose bundle contains `SBOM.spdx.json`, `BUILD-INFO.json`, and the legal/documentation files used for that release.

## Offline Core image

Tagged releases record the exact promoted registry image and digest in `lingshu-gate-v<version>-container-image.txt`. They can also be deployed without pulling the image from a registry:

```bash
gunzip -c lingshu-gate-v<version>-docker-core-linux-amd64.tar.gz | docker load
```

The loaded tag is:

```text
ghcr.io/zhigege666/lingshu-gate:<version>-amd64-offline
```

Use the `arm64` asset and tag on ARM64. Point `LINGSHU_GATE_IMAGE` at the loaded tag and keep the archive checksum and attestation result with the deployment record. Verify and retain `lingshu-gate-v<version>-application-sbom.spdx.json` as the Gate application dependency inventory. It covers the Python application runtime dependency closure and bundled Console production dependencies, not operating-system or container layers; the published container's image-level SBOM is provided through its container attestation.

## Automation behavior

The release workflow runs on pull requests that affect packaging, on manual dispatch, and on `v*` tags. The separate **Publish release** workflow is the repository-approved entry point for a formal release: dispatch it from `main` with the exact `v<version>` tag. It validates the source version, creates or verifies a non-moving tag at that exact `main` revision, and dispatches `release.yml` at the verified tag.

- pull requests and branch-level manual runs build and smoke-test the native matrix and Compose bundle, then upload short-lived workflow artifacts;
- a tag must match the version in `src/lingshu_gate/_version.py` exactly;
- tagged runs additionally export offline Core images from the verified container payloads, build the application SPDX SBOM, assemble a collision-free asset directory, regenerate the aggregate `SHA256SUMS`, attest every asset, and create the GitHub Release;
- if a release already exists for the tag, the workflow requires an immutable, non-draft release with an exact asset-name set and byte-for-byte matching content, then leaves it unchanged; a mutable release or missing, stale, or different assets fail the run;
- a newly created release is immediately re-read and must be immutable, complete, and byte-for-byte identical to the verified local assets; enable **Settings > Releases > Enable release immutability** before creating a release tag;
- native packages are built on their target operating system and architecture with PyInstaller `6.22.2`;
- Console assets and frozen Python dependencies are built from lock files before packaging;
- archive paths, timestamps, modes, symlinks, required notices, checksums, SBOM structure, and startup behavior are verified before publication.

A successful build on a pull request is not a published release. Only a matching, verified tag produces the release record.

## Versioning and release checklist

Before creating a tag:

1. update the single source version and user-facing release notes;
2. run backend, Console, identity, packaging, and container checks;
3. confirm `LICENSE`, `NOTICE`, and `THIRD_PARTY_NOTICES.md` are current;
4. confirm English and Simplified Chinese documentation match the artifact behavior;
5. enable GitHub release immutability for the repository before creating its first release;
6. dispatch **Publish release** from `main` with the exact `v<version>` tag; the workflow creates or verifies the tag without moving an existing ref, then starts the verified tagged release;
7. wait for every matrix job and publication step;
8. independently download and verify at least one native archive, the Compose bundle, `SHA256SUMS`, and their attestations;
9. verify the published container digest and release links.

The workflow never updates or deletes an existing release or asset. If initial creation is interrupted and leaves a draft, or if release immutability was not enabled beforehand, resolve that failed release manually before retrying.

Release notes should describe current behavior and operational impact in neutral language.

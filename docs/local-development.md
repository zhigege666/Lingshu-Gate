# Local development

[简体中文](zh-CN/local-development.md) · [Documentation index](README.md)

Lingshu Gate uses Python for the service and React/TypeScript for the Console. The built Console is embedded in the Python package and served under `/console`.

## Requirements

- Python 3.11, 3.12, or 3.13
- Node.js 22 and npm
- `uv` 0.11.33 or the version pinned by CI
- Docker with Compose for container verification
- PowerShell 7 only when testing the bundled Delivery packaging script

## Repository layout

| Path | Purpose |
|---|---|
| `src/lingshu_gate/` | Python package, API, policy, runtime, persistence, and embedded Console |
| `web/` | Console source, unit tests, and UX contract checks |
| `tests/` | Backend, protocol, security, packaging, and startup tests |
| `scripts/` | Local launch, quality, container policy, smoke, and release utilities |
| `packaging/` | Native launchers, PyInstaller specification, and release bundle assets |
| `.agents/skills/lingshu-gate-upload-build-start/` | Repository-owned Project Delivery Skill |
| `docs/` | English guides and `zh-CN` mirrors |

## Install

```bash
uv sync --frozen
npm --prefix web ci
```

Build the Console into `src/lingshu_gate/static/console`:

```bash
npm --prefix web run build
```

Run Gate:

```bash
uv run lingshu-gate
```

Use temporary, repository-ignored directories when testing writes:

```bash
export LINGSHU_GATE_DATA_DIR="$PWD/local/data"
export LINGSHU_GATE_CONFIG_DIR="$PWD/local/config/mcp.d"
export LINGSHU_GATE_ALLOWED_ROOT="$PWD/local/workspace"
uv run lingshu-gate
```

Do not reuse production data or credential keys in development.

## Backend checks

```bash
uv run ruff check .
uv run mypy
uv run pytest -q
```

Run a focused test while iterating, then run the complete suite before review:

```bash
uv run pytest -q tests/test_mcp_protocol_current.py
uv run pytest -q tests/test_project_delivery_mcp.py
uv run pytest -q tests/test_access_control.py
```

Tests that execute subprocesses must use temporary directories, bounded timeouts, and inert fixtures. Never download or execute an unrelated project as a test fixture.

## Console checks

```bash
npm --prefix web run check
npm --prefix web test
npm --prefix web run build
```

`check` runs TypeScript and the repository UX contract. Console changes should also be tested at narrow and wide viewports with authentication, loading, empty, error, and permission-denied states.

Do not edit generated files under `src/lingshu_gate/static/console` by hand. Change `web/` and rebuild.

## Container checks

```bash
docker compose config --quiet
docker build --target core -t lingshu-gate:dev .
```

Verify that the image runs as the expected non-root account, becomes ready, contains no local project toolchain, and does not receive a container-engine socket. Container tests must not publish the service beyond loopback.

## Identity check

The repository identity gate scans first-party identity and content in source,
documentation, scripts, configuration, and generated Console assets while
reporting only rule IDs and locations. Dependency lock data and packaged
third-party license or SBOM metadata are outside this identity-content policy;
their security and license checks remain separate.

```bash
uv run python scripts/quality/check_repository_identity.py
```

Generated build and release directories are excluded from that repository-tree
scan. After packaging, artifact mode recursively checks first-party identity and
content in every final asset and archive member:

```bash
uv run python scripts/quality/check_repository_identity.py --artifacts dist/release
```

Release maintainers also validate first-party identity and content throughout
the curated commit graph, including tracked files under generated-directory
names:

```bash
uv run python scripts/quality/check_repository_identity.py --history
```

Do not weaken, print, or duplicate the digest-backed policy rules to make a failure disappear. Resolve the reported file or artifact and rerun the check.

## Release checks

The release workflow builds each native archive on its matching operating system and architecture. On a matching local host, a maintainer can build one target:

```bash
uv run python -m scripts.release.build_native --target linux-x86_64
```

Build the Compose bundle independently:

```bash
uv run python -m scripts.release.build_docker_bundle
```

Release tests validate archive names, required legal and documentation files, launcher behavior, checksums, SBOM structure, build metadata, safe paths, and version/tag agreement.

## Change guidelines

### Protocol and runtime

- Implement only the fixed protocol version used by the release.
- Keep transport parsing separate from registry and authorization policy.
- Preserve stateless per-request isolation and bounded timeouts.
- Add conformance and failure tests for every protocol change.

### Access and credentials

- Route checks and tool-invocation checks must agree.
- Discovery and classification never grant access automatically.
- API-token scopes cannot exceed the principal's permissions.
- Secret values must be encrypted at rest, masked in responses, and absent from structured logs.

### Project delivery

- Preserve distinct confirmation stages and strict request schemas.
- Bind write effects to current digests and idempotency keys.
- Treat network timeouts as unknown completion until resource state is checked.
- Keep build plans exact and reject caller-supplied command substitutions.

### Persistence

- Make schema updates deterministic and covered by fresh-database and upgrade tests.
- Use transactions for related SQLite state and atomic replacement for manifest files.
- Do not make tests depend on ordering, wall-clock timing, or developer machine paths.

### Documentation

Update English and Simplified Chinese files together. Commands, paths, environment variables, tool IDs, archive names, and security claims must match the same tree.

## Before review

```bash
uv run ruff check .
uv run mypy
uv run pytest -q
npm --prefix web run check
npm --prefix web test
npm --prefix web run build
docker compose config --quiet
uv run python scripts/quality/check_repository_identity.py
git diff --check
```

Record the commands and results in the pull request. Do not commit local data, credentials, dependency directories, upload/build state, logs, or release archives.

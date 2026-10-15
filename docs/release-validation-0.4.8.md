# 0.4.8 candidate and publication validation

## Source and patch scope

0.4.8 delivers unified personal credential management under "My Authorizations", continuous MCP authorization scoping, persistent per-authorization tool discovery modes defaulting to on-demand, configurable invocation quotas, and group purpose distinction. The release unifies personal API tokens, Gate OAuth grants, and external identity authorizations into a single management interface, removing disconnected token pages and redundant documentation bars.

The sole runtime version source is `src/lingshu_gate/_version.py`. This release changes it to `0.4.8` and synchronizes both READMEs, CHANGELOGs, the release guide and bilingual release notes. Existing group/session, root Console, on-demand directory, OAuth editor and package staging behavior is carried forward. The occupied v0.4.5, v0.4.6, and v0.4.7 tags retain their original revisions; this source release uses the new `v0.4.8` tag identity.

## Executed verification and test evidence

Candidate verification includes full static analysis, unit, and integration regressions:

- **Static analysis & formatting**:
  - Python linting: `ruff check .` passed with zero errors.
  - Type checking: `mypy --platform linux` passed with zero issues across all 165 source files.
  - Repository git check: `git diff --check` passed with no trailing whitespace or boundary violations.
- **Backend tests**:
  - Continuous MCP authorization, token authorization policies, and authorization discovery test suites passed:
    - `tests/test_authorization_discovery.py`
    - `tests/test_continuous_authorization_runtime.py`
    - `tests/test_oauth_continuous_scope.py`
    - `tests/test_token_authorizations.py`
    - `tests/test_builtin_oauth.py`
    - `tests/test_external_oauth_http.py`
    - `tests/test_mcp_gateway.py`
    - `tests/test_oauth_live_scope.py`
    - `tests/test_oauth_paged_catalog.py` (all 29 tests passed)
- **Frontend checks**:
  - TypeScript type checking: `npm run typecheck` passed (`tsconfig.app.json` and `tsconfig.node.json`).
  - Static UX contract: `npm run check:ux` verified all 19 pages, 11 searchable pages, and 2 staged workflows.
  - Unit and integration tests: `vitest run` passed with 78 test files and 477 passing tests (0 failures).
  - Production build: `npm run build` compiled both the Console and OAuth distribution bundles with Vite 8 / Rolldown.
- **Deployment & configuration**:
  - `docker compose config --quiet` validated the deployment configuration cleanly.

## Database migrations and upgrade path

Upgrading to 0.4.8 applies three database migrations:
1. `token_authorizations`: persists independent MCP scope policies, server policies, and per-token quotas.
2. `mcp_authorization_identity`: binds service identity to authorizations so deleted and recreated services or replaced trust targets require re-authorization.
3. `authorization_discovery`: stores persistent tool discovery mode (`on_demand` vs `direct`) per authorization.

Single-writer SQLite semantics, isolated unprivileged Core execution, and atomic transaction boundaries remain intact.

## Support boundaries

The optional Native/Linux rootless Podman executor remains disabled by default; real Podman host, ChatGPT OAuth client, and multi-machine acceptance remain incomplete. Installing the release does not automatically provision these resources, enable OAuth, or expand permissions.

## Mandatory publication gate

Pushing a version change to `main` automatically starts tag creation and the formal release workflow. Formal publication requires 11 verified assets with provenance:
- 5 native binaries (Linux x86_64/ARM64, Windows x86_64, macOS x86_64/ARM64)
- 1 Docker Compose bundle
- 2 offline Core images (Linux amd64/arm64)
- 1 application SPDX SBOM
- 1 container image reference
- `SHA256SUMS` covering all assets

# 0.4.9 candidate and publication validation

## Source and patch scope

0.4.9 preserves tool classifications, reviewer timestamps, and OAuth authorization snapshots across MCP service restarts, temporary connection outages, and upgrades for unchanged tool definitions. Offline tools leave the callable tool catalog immediately upon disconnect, ensuring offline safety while avoiding redundant re-authorization or re-review cycles when the service recovers.

The sole runtime version source is `src/lingshu_gate/_version.py`. This release changes it to `0.4.9` and synchronizes both READMEs, CHANGELOGs, the release guide and bilingual release notes. Existing group/session, root Console, on-demand directory, OAuth editor and package staging behavior is carried forward. The occupied v0.4.5, v0.4.6, v0.4.7, and v0.4.8 tags retain their original revisions; this source release uses the new `v0.4.9` tag identity.

## Executed verification and test evidence

Candidate verification includes full static analysis, unit, and integration regressions:

- **Static analysis & formatting**:
  - Python linting: `ruff check .` passed with zero errors.
  - Type checking: `mypy --platform linux` passed with zero issues across all 165 source files.
  - Repository git check: `git diff --check` passed with no trailing whitespace or boundary violations.
- **Backend tests**:
  - MCP review lifecycle and continuous OAuth scope regression suites passed (all 30 tests passed):
    - `tests/test_mcp_review_lifecycle.py`
    - `tests/test_oauth_continuous_scope.py`
  - Unchanged tool reviews and OAuth authorization snapshots survive service restart and smooth upgrade.
  - Offline tools leave the callable catalog immediately during outages and reconnect cleanly.
  - Newly added tools default to `pending` with `unknown` access requiring review and publication.
  - Definition changes, explicit removals, and service recreations strictly invalidate previous reviews.
- **Frontend checks**:
  - TypeScript type checking: `npm run typecheck` passed (`tsconfig.app.json` and `tsconfig.node.json`).
  - Static UX contract: `npm run check:ux` verified all 19 pages, 11 searchable pages, and 2 staged workflows.
- **Deployment & configuration**:
  - `docker compose config --quiet` validated the deployment configuration cleanly.

## Database migrations and upgrade path

Upgrading to 0.4.9 introduces no new database migrations. The database schema from 0.4.8 remains backward and forward compatible. Single-writer SQLite semantics, isolated unprivileged Core execution, and atomic transaction boundaries remain intact.

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

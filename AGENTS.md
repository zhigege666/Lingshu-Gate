# Repository instructions

These instructions apply to the entire repository.

## Product identity and scope

- Use `Lingshu Gate` for the product, `Gate` for short prose, `lingshu_gate` for the Python package, `lingshu-gate` for commands and artifacts, `LINGSHU_GATE_` for environment variables, and `gate_` for first-party MCP tools.
- Use `MCP` only for the open protocol and its generic messages, transports, servers, tools, resources, and prompts.
- Keep downstream connections vendor-neutral through the generic manifest and protocol transports. Use neutral examples and original project text.
- The only repository-owned Skill is `.agents/skills/lingshu-gate-upload-build-start/`. It is part of the Project Delivery boundary and must retain confirmation, digest, idempotency, credential, and classification checks.

## Architecture boundaries

- Keep protocol transport, application policy, persistence, and HTTP presentation separable.
- Control-plane writes require explicit permission checks and auditable events.
- Tool discovery never grants access. Classification review and publication remain distinct operations.
- Credentials are stored outside manifests, encrypted at rest, masked in responses, and never logged as values.
- Project upload, build, deployment, overwrite, startup, cancellation, and abandonment keep independent confirmation boundaries.
- Docker Core remains unprivileged, read-only at the root filesystem, and disconnected from container-engine sockets.
- SQLite deployment is single-writer and single-Core unless a different store is implemented and tested.

## Change discipline

- Read the nearest code, tests, and documentation before editing.
- Preserve unrelated work in a dirty worktree.
- Prefer focused changes with tests for observable behavior.
- Failure paths must fail closed and return structured, actionable errors without secrets.
- Do not add silent fallback aliases for renamed package, environment, event, database, cookie, or tool identities.
- Use neutral commit and release text that describes the engineering result.

## Required checks

Run the checks relevant to the change. The complete baseline is:

```bash
uv sync --frozen
uv run ruff check .
uv run mypy
uv run pytest -q
npm --prefix web ci
npm --prefix web run check
npm --prefix web test
npm --prefix web run build
docker compose config --quiet
git diff --check
```

Run repository identity checks and release-package verification when those scripts are present and affected.

## Documentation

- English is the default language.
- Keep `README.md` paired with `README.zh-CN.md` and every `docs/*.md` user guide paired with `docs/zh-CN/*.md`.
- Commands, paths, environment variables, tool IDs, archive names, and support claims must match the same tree.
- Use neutral example hosts and IDs. Never include real secrets, personal data, local absolute paths, or unreviewed copied content.
- Update release and security documentation when configuration, public APIs, artifacts, or trust boundaries change.
- Every version change must also update `packaging/release-notes.md`: its version heading,
  both English and Simplified Chinese release text, and the version overview/release summary.
  Describe the actual changes, support boundaries, validation and known issues for that version;
  never reuse an earlier release's heading or summary. Before publishing, compare the source
  version, tag, notes, overview and GitHub release page, and read back the published title/body.

- Keep the single source version, paired README overview, paired CHANGELOG and release notes synchronized for every release. Sign-in and Console show the running backend health version; never substitute a separately hardcoded frontend version.

- Before release, manually review source version, paired overviews/changelogs, bilingual release notes and the published title/body together. Verify every formal release job and native/Compose/offline asset, checksum, SBOM and provenance before reporting publication complete; a tag alone is not completion. Keep authorization claims precise: owner-confirmed live tool changes stay within each token's existing OAuth scopes, and client cache refresh is separate from OAuth authorization.

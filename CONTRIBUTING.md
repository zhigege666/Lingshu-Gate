# Contributing to Lingshu Gate

[简体中文](CONTRIBUTING.zh-CN.md)

Thank you for improving Lingshu Gate. Contributions should preserve a small, vendor-neutral gateway core and make security-sensitive behavior easy to review.

## Before you start

For a bug or focused improvement, open an issue or a draft pull request with:

- the problem and expected behavior;
- the affected deployment mode and operating system;
- the smallest reproducible example with secrets removed;
- the security and upgrade impact, if any.

For changes to authentication, authorization, credentials, protocol negotiation, project execution, persistent schemas, or release packaging, describe the proposed boundary before implementation.

Security vulnerabilities follow [SECURITY.md](SECURITY.md), not the public issue tracker.

## Project scope

Lingshu Gate owns these product domains:

- authenticated MCP gateway and downstream HTTP/stdio runtime;
- configuration, lifecycle, tool registry, classification, grants, and audit;
- encrypted credentials, health, diagnostics, logs, events, and runtime cache;
- controlled project upload, build, deployment, startup, and reconciliation;
- the repository-owned Delivery Skill in `.agents/skills/lingshu-gate-upload-build-start/`.

Keep examples and interfaces vendor-neutral. Extend downstream behavior through the generic manifest and protocol transport boundaries.

Use the canonical identity everywhere:

- product: `Lingshu Gate`;
- Python package: `lingshu_gate`;
- command and artifact prefix: `lingshu-gate`;
- environment prefix: `LINGSHU_GATE_`;
- first-party MCP tool prefix: `gate_`.

Use `MCP` only for the open protocol, its messages, transports, servers, tools, resources, and prompts.

## Development setup

Requirements:

- Python 3.11, 3.12, or 3.13;
- Node.js 22 and npm;
- `uv` 0.11.33 or the version pinned by the project;
- Docker with Compose for container checks.

Install and build:

```bash
uv sync --frozen
npm --prefix web ci
npm --prefix web run build
```

Run locally:

```bash
uv run lingshu-gate
```

The default endpoint is <http://127.0.0.1:8000>. Use disposable `data`, `config`, and `workspace` directories during development.

## Quality gates

Run the checks that cover your change. Before requesting review, the complete baseline is:

```bash
uv run ruff check .
uv run mypy
uv run pytest -q
npm --prefix web run check
npm --prefix web test
npm --prefix web run build
docker compose config --quiet
git diff --check
```

When dependencies change, update the lock files with the project tooling and verify that `requirements.lock` matches a frozen `uv export`.

Tests should cover both success and failure-closed paths. Security-sensitive writes need tests for authorization, confirmation, idempotency, digest conflicts, redaction, and interrupted operations.

## Documentation

English is the default documentation language. Any user-facing change to `README.md` or `docs/*.md` must update the corresponding Simplified Chinese file in `README.zh-CN.md` or `docs/zh-CN/` in the same pull request.

Documentation must:

- use commands and fields implemented by the same change;
- use neutral example IDs, hosts, and projects;
- avoid real tokens, private paths, personal data, and copied product text;
- describe confirmation and failure boundaries before convenience workflows;
- link to the authoritative in-repository page instead of duplicating long contracts.

## Pull requests

Keep commits focused and use neutral messages that describe the engineering result. A pull request should include:

- a concise change summary;
- the user-visible and security impact;
- commands run and their results;
- screenshots for Console changes;
- release-note impact when artifact contents, configuration, or public APIs change.

Do not commit generated credentials, local databases, packaged project uploads, build outputs, dependency directories, runtime logs, or release archives.

By contributing, you agree that your contribution is licensed under the repository license.

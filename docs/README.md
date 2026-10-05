# Lingshu Gate documentation

[简体中文](zh-CN/README.md) · [Project README](../README.md)

This documentation describes the current Gate product boundary. English is authoritative for navigation and release packaging; Simplified Chinese mirrors are maintained alongside it.

| Guide | Purpose |
|---|---|
| [Performance review](performance-review.md) | Reproducible synthetic benchmarks and validation limits |
| [Retention controls](retention.md) | Separate log, event and invocation lifetimes, cleanup preview and confirmation |
| [Invocation content recording](invocation-recording.md) | Opt-in bounded redacted content, owner isolation, audit capability and retention |
| [Architecture](architecture.md) | Components, request paths, persistence, and trust boundaries |
| [Configuration](configuration.md) | Environment variables, directories, manifests, credentials, and reverse proxy settings |
| [MCP gateway](mcp-gateway.md) | Gateway endpoint, protocol negotiation, downstream HTTP/stdio, discovery, classification, and invocation |
| [On-demand tools](on-demand-tools.md) | Six bounded discovery/session entries, per-client modes, unchanged authorization and synthetic scale benchmarks |
| [On-demand integration provenance](on-demand-integration.md) | Exact group commit mapping, conflict resolution and targeted security evidence |
| [On-demand integration validation](on-demand-integration-validation.md) | Exact test checkpoints, physical/group measurements and native worker evidence |
| [Gate feature integration candidate](gate-feature-integration.md) | OAuth/catalog/groups/Native inputs, merge provenance, recorded 31b7cca test checkpoint and repository evidence, support limits |
| [MCP groups](mcp-groups.md) | Logical groups, explicit instances, administrator management and contract partitions |
| [MCP group routing adapter](mcp-group-routing-contract.md) | Internal interface for the on-demand directory and connection-bound instance sessions |
| [Project delivery](project-delivery.md) | Upload/build/deploy/start workflow, `gate_*` tools, and bundled Delivery Skill |
| [External MCP configuration](external-mcp-configuration.md) | Administrator offline plan/apply/status/cancel for existing HTTP MCPs; development addition |
| [Administrator OAuth configuration](oauth-external-management-design.md) | Unreleased default-off management resource, exact targets, isolated scopes/families; real-client integration unverified |
| [Git import and network settings](git-import-network.md) | Versioned delivery networking, bounded Git sources, deterministic tools and executor limits |
| [Native isolated executor](native-executor.md) | Implemented Linux/rootless adapter, provisioning/readiness, bounded npm/pnpm 8–9/Yarn Classic caches and remaining host acceptance |
| [Console delivery workspace](console-delivery.md) | Private delivery drafts, confirmation, conflicts and records |
| [Git executor implementation and rollout decision](git-executor-decision.md) | Concrete code gaps, default deployment limits and the required isolated-worker scope decision |
| [Deployment](deployment.md) | Docker Compose, native service, production hardening, backup, upgrade, and rollback |
| [Operations](operations.md) | Health probes, logs, events, diagnostics, runtime cache, audits, and incident checks |
| [Local development](local-development.md) | Source setup, Console build, test suites, and repository conventions |
| [UI interaction contract](ui-interaction-contract.md) | Acceptance rules for new or migrated Console UI, editor safety, evidence, and independent review |
| [Browser regression](browser-regression.md) | Isolated real-backend Playwright, synthetic large lists, scenario IDs and evidence boundaries |
| [External OAuth resource access](external-connections.md) | Default-disabled JWT verification, trust configuration, personal delegations and integration boundaries |
| [Built-in OAuth authorization](builtin-oauth.md) | Existing Gate users, static clients, consent, refresh/revoke and public proxy allowlist |
| [Release artifacts](releases.md) | Platform archives, checksums, SBOM, build metadata, offline images, and publishing rules |
| [0.4.0 validation record](release-validation.md) | Executed checks, synthetic screenshots and remaining acceptance gaps |
| [0.4.1 validation record](release-validation-0.4.1.md) | OAuth compatibility/setup, personal grants and runtime version evidence |
| [0.4.4 validation record](release-validation-0.4.4.md) | External HTTP management, Skills, resource isolation and acceptance gaps |

API schemas are served by a running Gate instance at `/docs`. Security policy and reporting instructions live in [SECURITY.md](../SECURITY.md).

## Stable entry points

| Entry point | Purpose | Authentication |
|---|---|---|
| `/console` | Web Console | Authenticated cookie |
| `/docs` | OpenAPI UI | Deployment policy applies |
| `/mcp` | Stateless Streamable HTTP MCP gateway | Console cookie or bearer token |
| `/v1/*` | Control and operation APIs | Permission-specific |
| `/healthz` | Process liveness | Probe |
| `/startupz` | Initialization completion | Probe |
| `/readyz` | Request-path readiness | Probe |

Use the three purpose-specific endpoints above for orchestration.

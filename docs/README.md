# Lingshu Gate documentation

[简体中文](zh-CN/README.md) · [Project README](../README.md)

This documentation describes the current Gate product boundary. English is authoritative for navigation and release packaging; Simplified Chinese mirrors are maintained alongside it.

| Guide | Purpose |
|---|---|
| [Architecture](architecture.md) | Components, request paths, persistence, and trust boundaries |
| [Configuration](configuration.md) | Environment variables, directories, manifests, credentials, and reverse proxy settings |
| [MCP gateway](mcp-gateway.md) | Gateway endpoint, protocol negotiation, downstream HTTP/stdio, discovery, classification, and invocation |
| [Project delivery](project-delivery.md) | Upload/build/deploy/start workflow, `gate_*` tools, and bundled Delivery Skill |
| [Deployment](deployment.md) | Docker Compose, native service, production hardening, backup, upgrade, and rollback |
| [Operations](operations.md) | Health probes, logs, events, diagnostics, runtime cache, audits, and incident checks |
| [Local development](local-development.md) | Source setup, Console build, test suites, and repository conventions |
| [Release artifacts](releases.md) | Platform archives, checksums, SBOM, build metadata, offline images, and publishing rules |

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

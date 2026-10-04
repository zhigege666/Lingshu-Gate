# 0.4.2 validation record

The source candidate isolates private HTTP MCP authorization from other local
configuration/startup/UI proposals. All fixtures use synthetic services and
identities; no production trust policy or grant was changed.

Executed locally for the isolated candidate:

- 89 backend HTTP trust, endpoint security and current-protocol cases passed.
- Nine current browser cases passed, including cached authorization after revocation, renewed denial invalidating confirmation and failed-read explicit retry.
- Sixty HTTP trust/CLI cases passed, including ten HTTPS-proxy-to-HTTP-backend Origin cases.
- 407 frontend unit cases passed; Console and OAuth production builds passed.
- Ruff, Mypy (107 source files), TypeScript, source UI contract, repository
  identity, version/tag consistency and Compose syntax checks passed.

Browser coverage exercises explicit exact-target confirmation, invalidation on
endpoint edits, single-write busy protection, draft-preserving re-precheck,
recoverable CAS failure and operator guidance without policy disclosure. The
initial run had five passes and one assertion failure: the assertion expected
`Can save` while the unchanged editor renders `Backend Precheck: Can save`.
The assertion was corrected to that exact rendered label; no product assertion
or baseline was loosened. The initial full backend run passed 1,107 cases and failed one launcher-mode check: local checkout umask produced mode 700 from Git mode 100755. Mode 755 was restored and that check passed. The complete rerun result is recorded in the PR checks before merge. No unexecuted suite is represented as
passing.

Release acceptance requires the existing GitHub release workflow to succeed
for every native target, Compose/offline images, checksums, SPDX and provenance.
The candidate checks do not establish real remote MCP connectivity, public TLS
or production upgrade acceptance. Independent exact-commit code/UI review is
required before merge. Download/SSH/deployment validation belongs to the
separate deployment task. Historical optional UI failures remain recorded;
this patch does not claim the complete optional UI suite passed.

HTTP is unencrypted and limited to explicitly approved canonical RFC1918
IPv4 literals and exact ports. OAuth/ordinary operators cannot approve trust.
The production SafeNetworkExecutor remains absent; no grants are expanded.

Proxy regression uses the existing Uvicorn ProxyHeadersMiddleware: preserve external Host/port and trust only configured peer IPs. Correct HTTPS same-origin requests pass; spoofed forwarded headers, an internal rewritten Host and cross-site Origin are denied. The backend Origin check was unchanged; see [reverse proxy configuration](configuration.md#reverse-proxy).

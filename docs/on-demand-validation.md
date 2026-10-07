# On-demand source validation

[简体中文](zh-CN/on-demand-validation.md) · [Guide](on-demand-tools.md) · [Measurements](performance-review.md)

This development checkpoint is based on exact main `d4786fd368e932bc758ea29da1a597c9d9551794` (0.4.4). Source and benchmark fixes through `58c46c4d6f04a04acd48cf43a8001211823396b6` are pushed to the independent `test/on-demand-tools-20261005` branch. No merge, tag, release, production service, SSH operation or real MCP credential was used. Git repository fetch/push is the authorized development delivery.

| Executed check | Observed result and scope |
|---|---|
| Full backend checkpoint | 1,438 passed / 3 skipped in 502.81 seconds at `af45c5d8f0b7fade110a70fff1454df33ea804ca` |
| Later backend changes | 184 targeted cases passed in 72.19 seconds after discovery re-authentication and the 1 MiB argument compatibility bound; catalog, registry concurrency, live OAuth, identity and release-package checks |
| Ruff / mypy | Passed for the production source and tests; subsequent percentile-only benchmark edit also passed Ruff |
| Frontend checks / build | TypeScript, static UX contract, 428 tests in 71 files, and production build passed; existing large-chunk warning remains |
| Actual browser scenario | Both locale cases passed in 12.4 seconds with local Chromium: centered dialog, radios, generated configuration, browser persistence, keyboard focus restoration and 390-pixel inline-label layout |
| Frozen dependencies / packaging syntax | `uv sync --frozen`, `npm ci`, Compose syntax and whitespace checks passed |
| Scale fixture | 5,000 services / 50,000 tools completed; exact SHA, scope assertions, RSS, bytes and timing distributions are checked in [raw JSON](benchmarks/tool-catalog-5000-50000.json) |

The first full backend attempt had one packaging failure because two tracked executable scripts were mode 0700 in the workspace. Restoring their tracked 0755 mode resolved it; the subsequent full run passed. Initial browser attempts used the wrong Console route and fixture invocation directory; after those corrections the two actual browser cases passed. These earlier failures are not included in the passing counts. Source-contract tests and engineer-viewed screenshots do not constitute an independent visual review.

Regression cases exercise permission-first ranking and paging, hidden-name/count isolation, exact OAuth subsets, read-token write denial, new/reappearing-tool review, stale schema and cursor rejection, revocation after queue waits, validation failure audit, local JSON Schema references, disabled remote references, bounded input/output, parallel targets, no warm full-registry reconstruction, API/MCP direct-mode compatibility and existing 512 KiB base64 upload chunks. Calls pass through the original target authorization, audit and runtime path.

Full backend testing predates the last small source changes; the later targeted run covers those changes. Group routing integration and its separate security fixes are outside this foundation checkpoint. Real-client end-to-end behavior, production credentials, OAuth consent beyond existing ceilings, nx5 deployment, long-running load and independent parent acceptance remain untested here. The synthetic benchmark is not a production SLA.

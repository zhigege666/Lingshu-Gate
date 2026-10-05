# On-demand integration validation

[简体中文](zh-CN/on-demand-integration-validation.md) · [Guide](on-demand-tools.md) · [Commit provenance](on-demand-integration.md)

The development branch `test/on-demand-groups-integration-20261005` is based on exact main `d4786fd368e932bc758ea29da1a597c9d9551794` (0.4.4). The final complete-suite and packaged-artifact checkpoint is `f51d1b18d7475034b61567be00ef999128918e83`. The final production checkpoint is `d99be556ff48e018792268abeb7c5a22c5517476`. It includes unchanged metadata TTL refresh invalidation (`3947ae4171d27d2e693ea3f505e49cf6b12fa752`) and follow-up authority-set/session-boundary corrections. Physical/group datasets identify production checkpoint `d99be55`. The final complete backend suite was repeated after both follow-ups at `f51d1b1`, whose changes from `d99be55` are documentation/data only. Final-head wheel and native artifacts were rebuilt and actually executed separately from the older native-worker checkpoint. Later evidence commits contain documentation and raw measurements only. No merge, tag, release, production service, real MCP credential or SSH operation was used. The separate foundation branch is a historical checkpoint, not the current security-fixed acceptance candidate.

| Executed check | Result and scope |
|---|---|
| Full backend | 1,734 passed / 3 skipped / 0 failures or errors in 1,289.04 seconds at `f51d1b18d7475034b61567be00ef999128918e83`; complete suite repeated after the final fixes. Five existing record_property/JUnit xunit2 warnings. [Raw checkpoint](benchmarks/backend-full-final-head.json) |
| Metadata refresh follow-up | 136 cases passed in 549.44 seconds at `3947ae4`, including three 50,000-tool directory/cache/concurrent-writer scenarios; 51 dispatch/external-authority cases passed in 52.06 seconds |
| Authority/session follow-up | 94 catalog/schema/audit/group/external-authority cases passed in 63.70 seconds at `d99be556ff48e018792268abeb7c5a22c5517476`; all six new ordering/private-initialization cases passed in 12.19 seconds |
| Ruff / mypy | Passed; mypy checked 139 source files |
| Frozen dependencies | `uv sync --frozen` and `npm --prefix web ci` passed; the pinned release group was installed separately for the native worker build |
| Frontend check / tests | TypeScript and static UX checks passed; 436 tests in 73 files passed in 42.38 seconds |
| Frontend build | Console and authorization bundles built; the existing large OAuth chunk warning remains |
| Browser checkpoint | 39 actual local browser group/client cases passed previously; after the six-entry wording correction, both locale client cases passed. The final backend-only changes do not change their UI source. Engineer-viewed screenshots are not independent visual acceptance |
| Final-head wheel / Linux native | Both built at `f51d1b1`. Isolated installed-wheel validator and actual native workers passed five cases each (valid, invalid type, deadline/kill, reuse, 512 KiB chunk); all ten children reaped. Two direct native entry probes passed. Actual wheel CLI and frozen native parents each passed synthetic local read-only on-demand API dispatch plus invalid-type denial, with one success and one `not_invoked` audit; both parents reaped. No source checkout supplied the installed validator |
| Packaging and repository | Identity check, 0.4.4 version check, Compose syntax and whitespace checks passed |

All three final skips are `tests/test_mcp_playwright_interop.py`: `test_fixed_peer_rejects_modern_discovery_with_real_http_400_null_id`, and `test_fixed_peer_auto_initializes_and_lists_without_any_browser_call` for `None` and `auto`. Each reports “fixed Playwright MCP test installation not supplied”. `GATE_PLAYWRIGHT_MCP_ROOT` was not supplied for the opt-in fixed `@playwright/mcp@0.0.83` / `playwright-core@1.64.0-alpha-1790635538000` peer. These skipped cases cover discovery/automatic negotiation/listing, not browser execution. The five warnings are the existing record_property measurements under the requested JUnit xunit2 report.

The first full attempt observed one authorization-page locale failure while the frontend build was replacing static authorization assets. That single case passed in isolation and in the fixed-checkpoint complete run; the build clears its output directory, which is consistent with a transient asset race. Earlier full attempts were intentionally interrupted when code changed; one interrupt also produced a pytest fixture-teardown error. They are not passing complete runs or environmental blockers. Two group-benchmark fixture initialization errors (role seed order and unintended default database path) were corrected before formal measurements. Native worker construction initially lacked the optional pinned release dependency group; installing that group enabled the actual build. None of these earlier failures is included in the final passing count.

Independent review found two further dispatch regressions: complete-dataclass comparison rejected valid multi-role/unsorted OAuth grants, and selected-only final resolution omitted session close/expiry after private initialization. The final checkpoint canonicalizes unordered authority collections without weakening proof or changed-ceiling rejection, and reuses the bounded selected-instance session guard at the actual call boundary. Real system/custom-role and signed built-in/external-OAuth regression cases cover valid ordering, actual revocation and zero-call single-audit close/expiry during slow private initialization. Early new-test failures were fixture imports, a pre-existing `None` echo handler and assertions expecting an exception instead of the documented failed identity response; these were corrected without changing dispatch behavior.

The first 30-sample group benchmark stopped on `catalog_changed`: its unchanged 30-second metadata TTL reread advanced a structural marker during a page. The final follow-up preserves the marker only for unchanged IDs/names; explicit writes/reloads and changed external metadata still invalidate it. The repeated formal run uses the ordinary refresh logic, without ignoring errors or modifying the TTL. 

Saved built-in OAuth grants now use exact database IDs for both JWT verification and in-process proof refresh. The independent phase-A fix is copied with registry-owned immutable snapshot semantics preserved. Large-owner regressions use real synthetic signing/client/token state on 5,000 services and 50,000 tools, with grants of 1, 100 and 5,000 tools. No complete registry or classification projection is allowed in the verified path. These are separate from the directory benchmarks' synthetic operator/token scope.

Physical and group measurements are separate datasets. The physical directory uses 5,000 services / 50,000 tools / 20 input fields per tool, with one denied service. The group fixture uses 1,000 members / 50,000 tools / one input field per tool, within its unchanged 32 MiB structural limit. Its primary actor can see 999 members and 49,950 tools; its small subset sees two members and 100 tools. Search rechecks current physical and logical policy and constructs one bounded projection per page. Describe and invoke inspect the selected instance's 50 tools, retain original argument/audit routing, and never call the unselected synthetic peer.

[Physical raw measurements](benchmarks/tool-catalog-integrated-5000-50000.json), source `d99be556ff48e018792268abeb7c5a22c5517476`.

| Physical profile | Samples | Median / p95 ms | Maximum bytes |
|---|---:|---:|---:|
| MCP six-entry list | 30 | 6.932 / 10.784 | 4,893 |
| Indexed narrow search | 30 | 22.622 / 32.229 | 2,797 |
| Broad keyword search | 30 | 404.697 / 615.974 | 5,735 |
| Empty query search | 30 | 417.790 / 656.046 | 5,735 |
| Five-service subset search | 30 | 329.717 / 381.574 | 5,735 |
| Single physical schema | 30 | 3.236 / 4.233 | 1,681 |
| MCP indexed search | 30 | 22.012 / 30.669 | 2,995 |
| MCP echo invoke | 30 | 363.440 / 444.405 | 273 |
| Legacy complete list | 3 | 14167.368 / 16884.124 | 83,433,501 |

Baseline/registry RSS: 66,820 / 738,792 KiB; measured on-demand profiles 838,932–871,204 KiB (about 819–851 MiB); legacy 1,013,216 KiB. Index build 13.832 seconds; database 131,833,856 bytes. Following the legacy allocation and garbage collection, the three bounded search observations remained 901,016 KiB. No long-running leak conclusion follows.

[Group raw measurements](benchmarks/group-catalog-1000-50000.json), source `d99be556ff48e018792268abeb7c5a22c5517476`.

| Group profile | Samples | Median / p95 ms | Maximum bytes |
|---|---:|---:|---:|
| Cold group search | 1 | 6398.798 / 6398.798 | 6,855 |
| Warm group search | 30 | 2006.823 / 2517.210 | 6,855 |
| Group keyword search | 30 | 1948.947 / 2213.005 | 378 |
| Two-instance subset search | 30 | 166.627 / 228.036 | 6,855 |
| Selected-instance schema | 30 | 15.443 / 33.500 | 393 |
| Public API group search | 30 | 2235.131 / 2757.009 | 378 |
| Public MCP selected describe | 30 | 33.237 / 38.536 | 591 |
| Public MCP selected echo invoke | 30 | 470.667 / 624.746 | 385 |

Baseline/registry parent RSS: 67,352 / 266,756 KiB. Sampled parent peak 682,676 KiB (666.7 MiB); validator-child peak 27,764 KiB (27.1 MiB). Structural cache holds 49,950 entries / 61,388,550 charged bytes, within 64 MiB; the raw group structure is 16,500,000 bytes, within 33,554,432. Index build 9.324 seconds; database 124,825,600 bytes. The keyword page still authorizes/projects the bounded full group, hence its seconds-scale latency; selecting one instance limits subsequent resolution to 50 tools.

[Linux frozen-worker evidence](benchmarks/native-schema-validation-linux.json) identifies source `a320b8cdffdb6f68c06206186c47ecbef8587f3f` and hashes the actual binary, validator, CLI and build specification. The validator/CLI/spec blobs are unchanged at the final checkpoint. This older four-call proof is historical. [Final-head wheel/native evidence](benchmarks/package-schema-workers-final-head-linux.json) records rebuilt artifact hashes and complete native-directory manifest digest, locked dependency digest, ten real validation children, two direct native entry probes and actual packaged-parent local API dispatch. The installed wheel is isolated from the source checkout. The initial HTTP driver lacked the dev-only HTTP client in the runtime-only environment; using the dev interpreter for the driver retained the two isolated artifact parents and required no product change. These functional observations were collected alongside the complete backend suite and are not a latency distribution.

The measurements are single-process Linux warm-cache SQLite and local ASGI results with synthetic state and echo peers. They include schema-validation subprocess overhead where invoked. RSS means observed process residency; the group validator-child peak is reported separately and is not added to a parent peak from a different moment. Three-sample OAuth regression timings are diagnostic and were collected alongside another synthetic fixture. No result establishes a production SLA, real downstream latency, sustained concurrency or a long-duration leak guarantee.

Remaining scope: real MCP-provider/client E2E, real credentials, independent parent security/visual acceptance, nx5 deployment, Windows/macOS native execution, real downstream native E2E, formal archive/SBOM/provenance/release assets and long-running production load are untested here. Owner-candidate OAuth paging/bulk selection remains the separate phase-B integration; the legacy full-catalog consent path and 100-service/5,000-tool grant ceiling were not widened. No future tool/service is implicitly authorized.

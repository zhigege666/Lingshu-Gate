# Performance review and reproducible checks

[简体中文](zh-CN/performance-review.md)

## Scope and evidence

2026-10-01 review covers Console loading/rendering, SQLite audit queries, build-log streaming, tool discovery/authorization, cache inspection, retention, and transport resource bounds. The measurements below use disposable synthetic data in one cloud development environment. They are warm-cache function timings, not end-to-end latency, throughput, production capacity, or a long-running memory-leak certification.

| Scenario | Before, median | After, median | Evidence / interpretation |
| --- | ---: | ---: | --- |
| Audit filter candidates, 30,000 audits / 100 users / 100 services / 3,000 tool IDs | 3,278.988 ms | 7.505 ms | Three runs each; select distinct users before latest-name lookup, with the `user_id, created_at DESC, id DESC` index |
| Audit filter candidates, 100,000 audits | Not measured | 15.163 ms | Three runs; same fixed user/service/tool cardinality |
| Runtime-cache status, 10,000 files / 1,280,000 bytes | 120.681 ms | 37.059 ms | Three runs each; one traversal and one stat per entry instead of three walks |
| Discovery of 3,000 published tools in one service | Not measured | 71.256 ms | Five runs; existing request-local authorization snapshot, no cross-request permission cache |
| 24-hour invocation statistics, 100,000 seeded audits | Not measured | 153.384 ms | Three runs; only records within the 24-hour window contribute |

Do not compare these as a system-wide speedup. The frontend mock's 100 services and 5,000 tools establish UI scale, not backend concurrency capacity.

## Changes and regression coverage

- Audit lookup migration `0003_audit_user_latest_lookup` is additive and transactional. It preserves deleted-user snapshots and timestamp/ID tie-breaking; migration and query-plan tests cover reuse on an existing database. Applying the index to a large real database can take a write lock: schedule an upgrade window and retain a backup.
- Build SSE reads execute in the thread pool and advance an indexed sequence cursor. Previously every tick loaded the first 1,000 records, both repeating work and hiding later records. A 2,501-record test now verifies all pages arrive before terminal status and database reads do not run on the event-loop thread.
- Cache inspection computes size, file count and modification time in one traversal. Missing, empty and non-directory paths retain their prior semantics.
- Initial Console loading and configuration mutations no longer launch runtime diagnostics. Diagnostics run on entry to their page or an explicit diagnostic action. Other initial tool/configuration reads remain; this is not a complete startup request redesign.
- The new trend chart uses native SVG, memoized geometry, bounded 7/12-point series, a zero baseline and no chart-library dependency. Metric switching is local; component tests cover keyboard inspection and no statistics request on series switching.

Backend suite after the three backend fixes: 767 tests passed; Ruff and mypy passed. Frontend checks/build and 306 tests passed before the final empty-state layout follow-up. These counts are checkpoint evidence, not a permanent statement about all later edits. Browser layout/interaction evidence and E2E results must be reported separately.

## Remaining risks / next measurements

- Main production JavaScript chunk is approximately 1,184.75 kB raw / 312.23 kB gzip. Pages already use lazy imports. Shared dependency attribution and a real cold-load profile are needed before claiming bundle work improved startup; splitting files alone does not reduce transferred bytes.
- Log/event historical scope discovery and substring searches still scan history as cardinality grows. Measure realistic retention volume and permission mixes before adding indexes or a materialized directory. Never remove authorization checks to speed up selectors.
- Build live-tail record count and rendered rows are now bounded; see the follow-up below. Large per-record stdout/stderr still needs byte-level profiling.
- SQLite remains single-writer/single-Core. Real simultaneous writes, downstream MCP latency, lock waits and long-running RSS have not been load-tested here. Transport limits and short isolated benchmarks do not establish production capacity.
- Full Playwright execution is blocked in this environment before assertions by Chromium `socket() failed: Operation not permitted`. Test collection or unit tests must not be reported as E2E acceptance. Do not bypass browser security restrictions.

## Reproduce safely

From the repository root:

```sh
uv run python scripts/benchmark_performance.py --rows 30000 --cache-files 10000
uv run pytest -q tests/test_audit_lookup_performance.py tests/test_build_log_stream.py tests/test_runtime_cache_summary.py
```

The benchmark always creates its own temporary SQLite database and cache directory. It does not read or clean a deployment database, launch MCP servers, access credentials, or call external services. Record OS, CPU, filesystem and repeat counts alongside comparisons. Use stable correctness/query-plan assertions in CI; do not make noisy absolute timing thresholds a release gate.

## Bounded build-log follow-up

The Console now keeps at most 200 live build-log records and renders 50 rows per page. Incoming SSE records are deduplicated/sorted in bounded animation-frame batches; the queue also flushes at 200 entries when a background tab suspends animation frames. Older logs are not deleted: Earlier/Newer/Latest controls read indexed server-side sequence windows. Browsing or filtering pauses live following, and failed reads retain the current window. Search covers the currently loaded window, not all server history.

The authenticated log endpoint adds mutually exclusive `before_sequence`, `after_sequence`, and `tail` options, plus `has_earlier`/`has_later` metadata. Defaults remain compatible. SSE `tail=true` starts at the latest 200; the default stream still drains full history. Tests cover 2,501 server records, authorization, navigation boundaries, 50,000 synthetic stream records, duplicate/out-of-order rows and 50-row rendering in both locales. The complete backend suite passed 769 tests at this checkpoint. This is a record-count bound, not a byte-level memory guarantee: large stdout/stderr payloads still require separate profiling.

## Additional runtime and startup review

- A single user invocation used to deep-copy the entire service tool catalog even on the shared-credential path. It now skips that unused copy; recovery snapshots only the called tool, preserving metadata-change and non-replay checks. With a synthetic 5,000-tool catalog and 20 input fields per tool, 20 in-process echo-stub dispatches had a median of 219.133 ms before and 0.001 ms after. This isolates removed copying overhead; it is not a claim that real MCP calls take microseconds.
- Unfiltered operational log/event reads by an explicitly authorized global reader no longer build the historical service directory first. The shared permission policy, token ceilings, named-resource validation, scoped grants and revocation remain authoritative. API regressions cover both optimized global reads and unchanged scoped reads.
- Global search dependencies load on the first search action instead of initial Console rendering. A dismissible loading/error surface remains available; a failed lazy import must not replace the rest of the Console or silently reload unsaved work. The diagnostic command no longer starts a second diagnostic request when navigation itself already loads that page.
- An isolated repeated-discovery run used 100 services / 5,000 tools / 1,500 requests over 241.19 seconds. Median 149.84 ms; p95 208.442 ms. From request 750 through 1,500, RSS samples were mostly 93,648 KiB, with one 92,640 KiB sample. No sustained increase appeared in that observation window; this is not a long-duration leak proof.
- A local synthetic stdio echo subprocess handled 500 calls from 8 caller threads through Gate authorization and SQLite audit: all 500 audit outcomes succeeded, duration 1.337 seconds, median 22.141 ms, p95 28.847 ms. The registry handler connects directly to this controlled client; the full runtime manager, external workloads, HTTP/OAuth and production capacity are not established by that run.

Reproduce these isolated fixtures without a production instance:

```sh
uv run python scripts/benchmark_discovery.py --iterations 1500
uv run python scripts/benchmark_stdio.py
```

Both use disposable temporary directories and synthetic identities. Discovery RSS is reported only where `/proc/self/status` is available. The stdio fixture executes only its generated local echo subprocess and uses no network or external credentials. Neither benchmark belongs in the default fast CI path.

## On-demand directory, 5,000 services / 50,000 tools

The 2026-10-05 source measurement used commit `58c46c4d6f04a04acd48cf43a8001211823396b6` on `test/on-demand-tools-20261005`, based on exact 0.4.4 main `d4786fd368e932bc758ea29da1a597c9d9551794`. [Raw measurements](benchmarks/tool-catalog-5000-50000.json) record Python 3.12.14, Linux 6.18.44, the benchmark script digest and all scope cases. Each tool has 20 input fields. The primary caller is an ordinary synthetic operator token with 5,000 explicit service grants, one denied service and 49,990 visible tools. A second operator sees five services / 50 tools; administrator results are measured separately.

| Scenario | Requests | Median | p95 | Maximum response |
|---|---:|---:|---:|---:|
| On-demand MCP `tools/list` | 30 | 4.162 ms | 6.337 ms | 3,194 bytes |
| Narrow indexed search | 30 | 15.745 ms | 20.784 ms | 2,797 bytes |
| Broad keyword search | 30 | 294.852 ms | 302.959 ms | 5,735 bytes |
| Empty-query search | 30 | 283.457 ms | 343.565 ms | 5,735 bytes |
| Five-service actor, broad search | 30 | 232.109 ms | 272.732 ms | 5,735 bytes |
| Administrator, broad search | 30 | 302.425 ms | 352.769 ms | 5,735 bytes |
| Denied-instance search | 30 | 14.912 ms | 19.689 ms | 48 bytes |
| One-schema describe | 30 | 1.142 ms | 1.651 ms | 1,681 bytes |
| MCP narrow search | 30 | 24.838 ms | 82.103 ms | 2,995 bytes |
| MCP synthetic echo invoke | 30 | 35.587 ms | 51.336 ms | 273 bytes |
| Legacy complete MCP `tools/list` | 3 | 16,616.950 ms | 17,438.540 ms | 83,433,501 bytes |

p95 uses the nearest-rank percentile. RSS was 68,244 KiB before registry creation, 439,588 KiB after populating it, approximately 460,340–468,888 KiB during on-demand operations, and 566,888 KiB after the legacy full-list profile. The first index build took 7.813 seconds; SQLite occupied 51,974,144 bytes. A 30-request follow-up sampled 475,200 KiB at requests 1, 16 and 30. This bounded observation does not establish long-term leak freedom. Registry schemas still consume memory; on-demand discovery bounds what reaches the client, rather than eliminating the underlying definitions.

The fixture verified distinct authorized pages, denial of the hidden instance, immediate removal of a revoked instance and rejection of its old cursor. The real built-in OAuth catalog method returned `tool_catalog_limit` in 4,321.280 ms for the large operator directory. Its existing full-catalog authorization cost and 100-service / 5,000-tool ceiling remain; external grant input remains limited to 100 services / 1,000 tools. None of these limits was widened and no future-tool subscription was introduced.

Reproduce with `uv run python scripts/benchmark_tool_catalog.py --iterations 30 --output /tmp/gate-catalog-benchmark.json`. These are disposable single-process warm-cache SQLite/function and loopback-ASGI measurements, with synthetic identities and echo handlers. They measure no real MCP connection, downstream latency, sustained concurrency, TLS/browser/client compatibility, production SLA or nx5 deployment. Broad/small-actor queries still scan policy candidates and need realistic workload profiling. See [source validation](on-demand-validation.md) for the separate correctness and Console evidence.

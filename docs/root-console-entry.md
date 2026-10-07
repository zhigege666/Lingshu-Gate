# Root Console entry candidate

[简体中文](zh-CN/root-console-entry.md)

The separately tested source is `77d0815756ab4b03ccc66155dfc2ce6c758c8b5a` on
`test/gate-root-entry-20261007`, based on
`227db541871ef8753390760d323414efbbe94d7c`. Version remains 0.4.4. This stage
retains hash navigation; no clean-path migration or release is included.

| Entry / request | Behavior |
|---|---|
| Browser navigation to `/` | Existing Console sign-in/page |
| `/` with no preference or `Accept: */*` | Existing service JSON |
| `/` with explicit acceptable `application/json` | JSON takes precedence even when HTML is also listed |
| `/` with neither representation acceptable | 406; `q=0` excludes its media range and overrides broader wildcards |
| `/v1/meta` | Same service JSON, independently of Accept |
| `/console`, `/console/`, `/console/index.html` | Uncached 307 to `/`, retaining query and browser fragment |

Existing JSON fields remain; `console` now points to `/` and `meta` identifies
`/v1/meta`. HTML, JSON and root errors send `Vary: Accept`, `Pragma: no-cache` and
`Cache-Control: no-store, no-cache, must-revalidate, max-age=0`. An HTML ETag does
not turn a later JSON request into cached HTML.

New bundles use `/assets/` and three explicit existing icon routes. Current files
also remain available through their old `/console/assets/` and icon paths with
identical bytes. Hashed bundles are immutable for one year; other assets have a
one-hour cache. Both namespaces serve only regular files confined to the package
Console tree. Traversal, unsafe path syntax, outside symlinks, symlink loops,
missing files and directories return 404. Missing HTML returns 404 while JSON
metadata remains available. There is no catch-all SPA fallback: API, MCP, OAuth,
discovery, OpenAPI and probes retain their own handlers. `/oauth/consent` and
`/oauth/assets/` remain independent.

Actual validation in the saved cloud Linux workspace:

| Check | Result |
|---|---|
| Frozen Python synchronization | Passed |
| Frozen frontend install, check and unit tests | Passed; 441 cases in 74 files |
| Official Console and public OAuth builds | Both passed; existing large-chunk warnings retained |
| Root / startup / probes / composition / OAuth / packaging / MCP / configuration / bootstrap | 420 passed, 0 failed, 0 skipped; 174.68 s |
| Root-specific cases within that backend run | 64 passed |
| Eight selected Chromium specs | 112 passed, 0 failed, 0 skipped, 0 flaky; one worker, zero retries |
| Root-specific browser cases within that run | 10 passed; no API or asset responses mocked in that spec |
| Ruff, Mypy, identity, version and Compose configuration | Passed; Mypy checked 158 source files; version stayed 0.4.4 |

Both backend and browser fixture used CPython 3.13.15. Browser tooling was Node
24.19.0, npm 11.9.0 and system Chromium 151.0.7922.173. Real root checks preserve
duplicate query keys, encoded values, hash targets, login return position,
reload and native back/forward history in both languages. Cookie path, HttpOnly,
SameSite and viewer denial remain intact. Other specs include mock presentation
states and real loopback login, permissions and request-bound one-use CSRF.
The browser temporary root was removed and the listener closed. The earlier
ten-case root diagnostic overlaps the 112 cases and is not added to the total.

The first browser attempt had 112 launch errors before page assertions because
its temporary path exceeded Chromium's Unix socket limit. A short owned disk
temporary directory fixed the environment without changing product/assertions.
The first identity scan included generated pytest archives and npm caches inside
an ignored checkout temporary directory. Moving only this task's outputs outside
the checkout retained the logs; the unchanged full identity check then passed.
The version check passed through its Python module entry after a direct-file
invocation could not import `scripts`.

The inventory contains 97 Console files and three OAuth files, with canonical
SHA-256 `28e5f475bfd27138fe80f238aec5f7fa6df77ff614f2f5401419405573b40a8b`.
All three OAuth files exactly match the earlier be30 inventory. No wheel, sdist
or native binary was rebuilt or relabelled. The full backend suite, whole-site
browser suite, other Python/platform versions, Podman, real ChatGPT OAuth and
formal release matrix were not run on this source. New-source nx5 deployment
acceptance belongs to the delegating root. No SSH, production, main or tag action
occurred here; authorization and CSRF logic were not changed.

PR #51's CI repair belongs to another task. Its interim source
`63cab1c5b9f2a8eb6503fcee9193055c55262a2d` was trial-merged locally without
conflicts, including both `builtin-oauth` guides, before root's latest steering
arrived. Root then reported three remaining high CodeQL findings and requested
waiting for the final repair head. The unpublished trial is retained in a local
side branch and withdrawn from this candidate; its runtime remains the tested
77d0815 source. PR #51's head was not modified here. Final combined acceptance
still requires the completed repair source and relevant revalidation, especially
the paired OAuth documentation. No final-head conflict claim is made.

[Structured evidence and complete inventory](benchmarks/gate-root-entry-77d0815.json)
record source hashes, commands and scope.
[Normalized logs](benchmarks/gate-root-entry-77d0815.log) retain actual test output
without private host paths or fixture passwords.

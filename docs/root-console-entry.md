# Root Console entry candidate

[简体中文](zh-CN/root-console-entry.md)

The validated combined source is `689b4f9eb9e1836431376dd4f84a67f9fd3edacd` on
`test/gate-root-entry-20261007`. It normally merges the root-entry parent
`84c4b8bcf364eef33d8e4fafafce22866c936a31` with the explicitly reviewed PR51 head
`71f2a25db196f126a4f7e7e0a0b9e8ac952d7181`, which matched the remote head at
inspection. There were no conflicts. Both OAuth guides merged automatically;
their private Console proxy boundary and browser-binding explanation coexist.
The root implementation remains byte-for-byte identical to `77d0815`, and the
imported repair files remain byte-for-byte identical to `71f2a25`. Version stays
0.4.4. Hash navigation is retained; no clean-path migration or release is included.

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

Actual validation rerun on the combined source in the saved cloud Linux workspace:

| Check | Result |
|---|---|
| Frozen Python synchronization and pip export | Passed with CI-pinned uv 0.11.33; export exactly matches `requirements.lock` |
| Frozen frontend install, check and unit tests | Passed; 441 cases in 74 files |
| Official Console and public OAuth builds | Both passed; existing large-chunk warnings retained |
| 22 selected backend modules | 859 passed, 0 failed, 0 skipped; 328.189 s in JUnit |
| Root-specific cases within that backend run | 64 passed |
| Synthetic native-executor cases within that backend run | 203 passed; no real Podman host |
| Eight selected Chromium specs | 112 passed, 0 failed, 0 skipped, 0 flaky; one worker, zero retries |
| Root-specific browser cases within that run | 10 passed; no API or asset responses mocked in that spec |
| Ruff, Mypy, identity, version and Compose configuration | Passed; Mypy checked 158 source files; version stayed 0.4.4 |

The backend selection covers root negotiation and old Console compatibility,
startup/probes/composition, built-in and management OAuth, packaging, MCP
HTTP/protocol/configuration, authentication bootstrap, Git acquisition, benchmark
reporting and all six synthetic native-executor modules. It includes the imported
cookie-binding, public-error-message, token/password hashing, TLS/configuration
and object-stream cleanup regressions. These are combined-source results; the
earlier root-checkpoint counts are not added to them.

Both backend and browser fixture used CPython 3.13.15. Browser tooling was Node
24.19.0, npm 11.9.0 and system Chromium 151.0.7922.173. Real root checks preserve
duplicate query keys, encoded values, hash targets, login return position,
reload and native back/forward history in both languages. Cookie path, HttpOnly,
SameSite and viewer denial remain intact. Other specs include mock presentation
and OAuth states and real loopback login, permissions and request-bound one-use
CSRF. The browser temporary root was removed and its listener closed.

The first pinned-uv tool bootstrap tried its default directory under read-only
user home and exited before application checks. Setting `UV_TOOL_DIR` and
`UV_TOOL_BIN_DIR` to owned validation directories fixed the environment; HOME,
repository policy and product assertions were unchanged. All generated validation
output stayed outside the checkout. No browser retry was required in this run.

The rebuilt inventory contains 97 Console files and three OAuth files, with
canonical SHA-256
`28e5f475bfd27138fe80f238aec5f7fa6df77ff614f2f5401419405573b40a8b`.
All 100 files exactly match the `77d0815` inventory. No wheel, sdist or native
binary was rebuilt or relabelled. The complete backend suite, whole-site browser
suite, other Python/platform versions, real Podman, real ChatGPT OAuth and formal
release matrix were not run on this merged source. New-source nx5 deployment
acceptance belongs to the delegating root.

Security workflows, alert state and policy were not changed. Imported PR51
repairs tighten TLS, browser-cookie reflection and public protocol errors;
scopes, permissions, human-password/token hash algorithms and CSRF boundaries
remain unchanged. Known token-hashing and Git-fixture findings still require
authorized independent formal triage. No alert was dismissed, and this task did
not run CodeQL on the merged SHA or certify all GitHub checks green. See the
[PR51 repair evidence](pr51-ci-validation.md) for its separately scoped results.
Only this candidate branch is written; PR51, main, tags, production and SSH are
outside this task.

[Combined-source structured evidence and complete inventory](benchmarks/gate-root-entry-integration-689b4f9.json)
record source preservation, commands and scope.
[Normalized combined-source logs](benchmarks/gate-root-entry-integration-689b4f9.log)
retain actual output without private host paths or generated bootstrap credentials.
The [earlier standalone root evidence](benchmarks/gate-root-entry-77d0815.json)
and [its logs](benchmarks/gate-root-entry-77d0815.log) remain an unchanged historical
checkpoint; the earlier unpublished interim CI trial is superseded by this exact
reviewed merge.

## Native readiness smoke follow-up

Repair source `63e31a9ec1eaebd3cceb7a65c8d50f3fab5a9acd` fixes the Release smoke contract that failed on all five
native platforms at `8f3f946`. Original Linux and Windows logs were independently
read. The old request to `/console` had no HTML Accept, so its root destination
correctly returned JSON; the asset pattern also still required `/console/`.
The updated checker explicitly requests root HTML, retains machine JSON checks,
and verifies each legacy entry's single 307, final root URL, duplicate query,
HTML content type and identical body. It requires both JavaScript and CSS,
fetches every referenced asset with status/type/nonempty checks, and verifies
identical bytes through the legacy asset aliases. Resource checks were retained
and strengthened.

The repair passed 176 related backend/release checks, including 29 new loopback
HTTP regressions. The preliminary 31-case native subset overlaps that total.
Fresh official web/native builds, archive identity, safe extraction and actual
Linux x86_64 frozen readiness smoke passed with CPython 3.13.15/PyInstaller
6.22.2. The candidate archive SHA-256 is
`dc5386253dd3e164a125156a76aabcdcc38a871104dfe1de9182b5e6b86990b9`. All 100 packaged static files match the fresh web build and
the inventory above. Product/web source, locks, version and security workflows
are unchanged. This is an unpublished local candidate; other native platforms
and new exact-head GitHub CI require their own checks. nx5 has not been switched
by this task. The remaining real-host/client acceptance and formal alert triage
stay separate.

[Native-smoke repair evidence](benchmarks/gate-root-native-smoke-63e31a9.json) and
[normalized logs](benchmarks/gate-root-native-smoke-63e31a9.log) preserve the
original failures, actual before/after HTTP probes, test commands and candidate
inventory. New CI status is intentionally not inferred from the old head's
successful CI, Code scanning and Container workflows.

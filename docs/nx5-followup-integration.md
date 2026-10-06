# Combined follow-up candidate

[简体中文](zh-CN/nx5-followup-integration.md)

The tested source is `be30faf1c293c64dc90a160150ad182f7a4177a9` on
`test/gate-nx5-followup-integration-20261006`. A normal `--no-ff` merge brought final
UI source `95bfa7d97d936275781d11ec5c4939574390a27f` into the existing candidate
`76391f5f8abec6649cfc9a119af31f27fb832fee`, retaining the earlier CLI and catalog
histories and acceptance notes. There were no conflicts. UI source blobs match
their reviewed source, and backend code, backend tests, build scripts and
dependency locks are unchanged by this merge.

Actual validation in the saved cloud workspace:

| Check | Result |
|---|---|
| Frozen frontend install, typechecks and source UI contract | Passed |
| Frontend unit tests | 441 passed across 74 files |
| Console and public OAuth builds | Both passed; existing large-chunk warnings retained |
| CLI / schema worker / four OAuth backend files | 208 passed on CPython 3.14.4 |
| Post-build consent locale replay | 9 passed, 98 deselected; overlaps the 208 cases |
| Eight selected browser specs | 206 passed, 0 failed, 0 skipped, 0 flaky |
| Ruff, Mypy, identity, version and diff checks | Passed; Mypy checked 158 source files |

Browser tests used Node 22.23.2, system Chromium 151.0.7922.173 and the CPython
3.13.15 loopback fixture. The suite includes mock presentation states and real
owner-visible 5,000-MCP / 50,000-tool catalog pages. Both locales passed keyboard
load-more/retry/focus return, unchanged-draft checks, and committed-save response
loss/readback. The browser root was removed by teardown and the listener closed.
Owned disk temporary directories were used; no system setting was changed.

Root reported approval of the two final 1600×900 Chinese screenshots (five full
infrastructure client rows, nine full scope rows, visible footer actions).
Root's independent review closed the prior keyboard P2 and found no code-level
blockers; the three parent controllers' request/state/confirmation logic remained
bytewise unchanged. These owner reports are separate from this cloud automation.

Fresh Git/codeload source excludes generated static assets. Build before running
backend tests containing pages, from the candidate root in the intended Python
environment:

```bash
npm --prefix web ci
npm --prefix web run build
python -m pytest -q tests/test_builtin_oauth.py -k authorization_ui_locales_reaches_consent_without_entering_the_security_envelope
```

The existing `build` typechecks and generates both package static directories.
There is no separate `build:oauth` package script. The consent route reads
module-relative `src/lingshu_gate/static/oauth/oauth.html`, not `web/dist`; its
fixture does not build or replace HTML. Missing HTML deliberately returns
`authorization_ui_unavailable` 503. This explains the reported nine assertions'
missing-build precondition without relaxing assertions or adding skips. The
208-case command ran alongside the frontend pipeline in an already prepared
workspace; the explicit nine-case replay ran after the new dual build finished.

Root's `7bc834` tmpfs full suite was OOM-killed after approximately 81% at D01.
Root reported 1.53GB temporary-file shmem alongside 1.55GB Python anonymous memory.
The old `7bc834` disk run ultimately had 11 missing-static precondition failures;
the earlier nine consent-page failures above were an interim subset. Neither old
run is accepted as passed. Root subsequently completed the build prerequisites
and tested final source `be30faf1c293c64dc90a160150ad182f7a4177a9` on disk.
[Earlier checkpoint and host observations](cli-catalog-integration.md) retain
their source and provenance. This disk retest does not establish that a product
memory leak was fixed. No complete backend suite was repeated in this cloud
workspace.

Root's final nx5 report is for deployed source
`be30faf1c293c64dc90a160150ad182f7a4177a9`, whose runtime code matches the
documentation checkpoint `9154d15cfe0a24875b0808418d5a8ea0b03fcd1e`.
The full pytest run used CPython 3.14.4 in a single process, `MemoryMax=3GiB` and
`CPU=200%`. Both `TMPDIR` and pytest `--basetemp` pointed to that run's owned disk
directory on `/srv`; concrete host paths are omitted.

| nx5 check reported by root | Result |
|---|---|
| Complete backend pytest | 2201 passed, 4 skipped, 0 failed, 5 warnings; 2632.83 s |
| Frontend check and unit tests | Passed; 441 unit tests passed |
| Official Console and public OAuth builds | Both passed |
| Post-build builtin OAuth / release packaging / startup smoke | 184 passed; overlaps the complete backend suite |
| Real nx5 login, navigation and horizontal-overflow checks | 22 pages × 4 sizes = 88 passed |
| Infrastructure config / clients / management config | All returned HTTP 200 |
| Connection guide | Open, Escape close and focus return to trigger passed |

All four backend skips are in `test_native_executor_host_acceptance` and require
rootless Podman, an image and tmpfs. The host security configuration was not
authorized, so these cases remain unexecuted. The 88 browser checks cover login,
navigation and horizontal overflow, not all business flows. OAuth was disabled
and there were no clients in this test environment; real ChatGPT authorization
was not accepted.

Root saved the acceptance receipt and reported cleanup of approximately 3.15GB
of this run's disk temporary databases and dependency caches. All source,
deployment, necessary logs, screenshots and JUnit evidence were retained. The
reported test Chrome process count was zero; the Gate test service remained
active. This cloud workspace did not perform that cleanup or independently
fetch or verify the retained nx5 logs. Root supplied these SHA-256 values:

| Root-retained evidence | SHA-256 supplied by root |
|---|---|
| Final `run.log` | `634bfe4d16d67c8a79e75a43f7fa511f45b3f1cc965fe5f3914f6875debafd2a` |
| Final `results.xml` | `06a02b46eb1479ca80ebcfe5af512b25d4892d3c928ea461eac13c71a5c7f94d` |
| Build log | `608e90e9009dee4e3c74c6a690e692fa4e56ffe1750f5cbc907383e2ad4435a7` |
| Navigation log | `36ee451b075cb890021db58f547d604443de020f7a820ddd3b0310f1c7353c6f` |

The built web inventory has 97 Console files and three public OAuth files; its
canonical SHA-256 is `5a7fad02c10fd6d3dc98911ebc90683f336ae41ac37c5fe7600818057e1c0013`.
No new wheel, sdist or native binaries were built or relabelled. This cloud run
did not execute Podman, the formal release matrix, other platforms, whole-site
browser acceptance or real Gate/Plane/ChatGPT acceptance. No SSH, main, tag or
release action occurred.

[Structured evidence and complete web inventory](benchmarks/gate-ui-final-integration-be30faf.json)
record exact sources, commands, hashes and scope.
[Logs](benchmarks/gate-ui-final-integration-be30faf.log) contain the actual checks.
[Final nx5 receipt](benchmarks/gate-nx5-final-acceptance-be30faf.json) separately
records root's reported results and evidence hashes. This acceptance update only
changes documentation; it does not rerun tests or rebuild artifacts.

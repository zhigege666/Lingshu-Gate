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
The same source and 3GiB disk-temp full run remains pending and has the nine
missing-HTML failures above; root's post-build replay is pending. Neither full
run is accepted as passed. [Earlier checkpoint and host observations](cli-catalog-integration.md)
retain their source and provenance. No complete backend suite was repeated here.

The built web inventory has 97 Console files and three public OAuth files; its
canonical SHA-256 is `5a7fad02c10fd6d3dc98911ebc90683f336ae41ac37c5fe7600818057e1c0013`.
No new wheel, sdist or native binaries were built or relabelled. Podman, the
formal release matrix, other platforms, whole-site browser acceptance and real
Gate/Plane/ChatGPT acceptance were not run here. No SSH, main, tag or release
action occurred.

[Structured evidence and complete web inventory](benchmarks/gate-ui-final-integration-be30faf.json)
record exact sources, commands, hashes and scope.
[Logs](benchmarks/gate-ui-final-integration-be30faf.log) contain the actual checks.

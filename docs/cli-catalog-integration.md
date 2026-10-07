# CLI and catalog integration checkpoint

[简体中文](zh-CN/cli-catalog-integration.md)

The branch `test/gate-nx5-followup-integration-20261006` integrates the reviewed
CLI identity fix and narrow catalog classification projection from exact base
`7d145c28a94a00a6c5d6f4f7d4fc38c0e6153436`. The tested combined source is `d8b1ee076ff39f60a9b633e414932adbd6478129`.

This report covers the earlier CLI/catalog checkpoint. UI head
`4fc96c8b45635f2ba886eb6cc8f14691c1810319` was deferred at that point. The refined
UI source `95bfa7d97d936275781d11ec5c4939574390a27f` was subsequently merged normally
at `be30faf1c293c64dc90a160150ad182f7a4177a9`; its combined validation is recorded
separately from these 382 tests.

Two normal `--no-ff` merges preserve both complete source histories:
CLI `a4f9be911852a9d354fe29804e1eafb8f301f9ba` and catalog `2b6a2c5173595787cb57fed394515c4fc0dd73bc`. There were no conflicts or overlapping
changed files. Every merged file matches its source blob. The production changes
are confined to `cli.py` and `access_control.py`: the CLI explicitly uses
`lingshu-gate`, and directory reads omit large analysis/evidence columns while
retaining the existing current-policy checks. The complete classification loader
and schema worker implementation remain unchanged.

Actual merged-source validation ran in the saved cloud Linux x86_64 environment
with CPython 3.14.4 and pytest 8.4.2. Frozen
dependency synchronization checked 51 packages. The two regression processes
used separate temporary roots and caches:

| Run | Passed | Pytest time |
|---|---:|---:|
| CLI / schema worker / projection / ACL / group cache / adapter | 120 | 49.23 s |
| Group catalog / routing / authority / classification / OAuth consumers | 259 | 287.87 s |

The three original 5,000-instance / 50,000-tool HTTP scale cases also ran, each
in a separate process, with all original samples, assertions and thresholds:

| Scale case | Passed | Pytest time |
|---|---:|---:|
| five_groups | 1 | 41.38 s |
| maximum_single_group | 1 | 101.55 s |
| over_cache_bytes | 1 | 150.57 s |

The combined result is **382 passed, 0 failed, 0 skipped**. Whole-repository
Ruff, Mypy (158 source files), repository identity, version and diff checks passed
in the CPython 3.13.15 project environment. No schema worker process with the
exact worker argument remained after testing.

These scale runs are post-change measurements. The earlier controlled allocation
comparison remains inherited evidence at its original checkpoint. This cloud
cgroup permits 16 GiB and differs from nx5. Recorded scale RSS is cumulative
process-lifetime `ru_maxrss`, including fixtures and all requests. It does not
establish a per-request peak, a leak, or resolution of the nx5 whole-suite OOM.

The delegating root reported 2,175 premerge baseline results on nx5. Of the three
initial failures, one CLI result required new-source retesting; the two Delivery failures
passed after activating PATH. Root also reported three passing peer cases and
40 passing wheel tests after installing `uv`. Four Podman cases remain unrun.
Those reports are separate from this cloud run and do not accept the new source.

On 2026-10-06, root reported the full backend run on candidate
`7bc834e38f7b737bca1c660b92de2d3b6f60acd3` at approximately 75%, with no failures
reported at that observation. The run was still in progress; this is not its
final result. Root also reported the following host measurements:

| Observation | Reported value |
|---|---|
| Temporary mount | `/tmp`, tmpfs, capacity 3.9G |
| Retained pytest temporary data | `pytest-of-root`, 2.7G |
| Cgroup memory limit | 3GiB |
| `memory.stat` anonymous / shmem | 1.55GB / 1.53GB |
| Total accounted memory | Approximately 3.13GB |
| OOM events at this observation | 0 |

These are approximate values and unit labels supplied by root, not independent
cloud measurements or exact byte conversions. The total is retained as reported,
not reconstructed from the rounded categories. Temporary storage and shmem are
material environment evidence; the earlier single-process OOM does not by itself
establish a product leak, and its cause remains unresolved.

At that observation, root planned a separate verification with both `TMPDIR`
and pytest `--basetemp` directed to an owned disk directory for that run on the
host's `/srv` mount. Root subsequently reported that the tmpfs run was OOM-killed
after approximately 81%, while executing
`tests/test_real_delivery_journey.py::test_d01_real_upload_build_deploy_and_configuration_reapply`.
Root reported 1.53GB of temporary-file shmem alongside 1.55GB of Python anonymous
memory. The full suite did not complete and is not accepted as passed.

Root then started the same `7bc834` source and 3GiB limit with disk-backed
`TMPDIR` and `--basetemp` in unit `gate-full-backend-7bc-disk`. The interim report
recorded nine consent-page assertion failures with 503 instead of 200; root's
final report records 11 missing-static precondition failures in that old run.
Root confirmed that the fresh source archive lacks the generated public OAuth HTML.
Read-only inspection confirms that the route and fixture do not depend on the
temporary directory for static lookup: the route reads module-relative
`src/lingshu_gate/static/oauth/oauth.html`, and the fixture does not build or
replace it. Missing HTML deliberately produces `authorization_ui_unavailable`
503. This matches the missing-build precondition and does not justify relaxing
the assertion or skipping the test.

For fresh Git/codeload source, install frontend dependencies and run the existing
dual build before backend tests containing pages:

```bash
npm --prefix web ci
npm --prefix web run build
```

`build` typechecks and builds both Console and public OAuth into the package's
two static directories. There is no separate `build:oauth` package script, and
`web/dist` is not the consent route's lookup target. The former pending-run and
post-build-retest notes are historical observations. Root subsequently completed
the build prerequisites and the single-process nx5 full suite on final source
`be30faf1c293c64dc90a160150ad182f7a4177a9`: CPython 3.14.4, `MemoryMax=3GiB`,
`CPU=200%`, and both temporary controls on that run's owned `/srv` disk directory.
The result was **2201 passed, 4 skipped, 0 failed, 5 warnings in 2632.83 s**.
All four skips are `test_native_executor_host_acceptance`; rootless Podman,
image and tmpfs security configuration remains unauthorized. The 184 post-build
builtin OAuth / release packaging / startup smoke cases overlap the full suite.
Test assertions and system safety settings remain unchanged. No duplicate full
suite was started here; this disk retest does not prove a product memory leak was
fixed. [Combined candidate acceptance](nx5-followup-integration.md) records root's
441 frontend unit passes, dual build, 88 navigation/overflow checks, API and guide
checks, retained-log hashes and cleanup. OAuth was disabled with no clients, so
real ChatGPT authorization remains unaccepted.

This earlier CLI/catalog cloud checkpoint did not run the full backend suite,
frontend/browser tests, other platforms, nx5/Podman acceptance, or the formal
release matrix. It does not claim
full Python 3.14 support. No web, wheel, sdist or native candidates were rebuilt;
old binary evidence remains attached to its original source SHA. OAuth UI work
was excluded pending its follow-up and review. Versions, dependencies and permission behavior were
not changed, and no SSH, main, tag or release action was performed.

[Structured evidence](benchmarks/gate-nx5-followup-integration-d8b1ee0.json) records merge parents, source/test
hashes, exact test commands, scope and all three raw scale metrics.
[Test logs](benchmarks/gate-nx5-followup-integration-d8b1ee0.log) contain the two regression summaries and the
three independent scale runs. The source reports remain available for
[CLI identity](cli-validation.md) and
[catalog classification projection](catalog-classification-projection.md).
[Final nx5 receipt](benchmarks/gate-nx5-final-acceptance-be30faf.json) records the
later root-reported acceptance separately; the original interim JSON snapshots
and cloud test-log hashes remain preserved.

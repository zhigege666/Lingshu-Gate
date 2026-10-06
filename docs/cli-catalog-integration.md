# CLI and catalog integration checkpoint

[简体中文](zh-CN/cli-catalog-integration.md)

The branch `test/gate-nx5-followup-integration-20261006` integrates the reviewed
CLI identity fix and narrow catalog classification projection from exact base
`7d145c28a94a00a6c5d6f4f7d4fc38c0e6153436`. The tested combined source is `d8b1ee076ff39f60a9b633e414932adbd6478129`.

This report covers the CLI/catalog checkpoint. OAuth UI integration is deferred
while its author addresses the root's visual-review follow-up; the inspected UI
head `4fc96c8b45635f2ba886eb6cc8f14691c1810319` is not merged here.

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

After this run finishes, root plans a separate verification with both `TMPDIR`
and pytest `--basetemp` directed to an owned disk directory for that run on the
host's `/srv` mount. That verification has not run. Test assertions and system
safety settings will remain unchanged. No duplicate full suite or old UI
integration was started here; UI remains pending its refined source SHA.

This cloud follow-up did not run the full backend suite, frontend/browser tests, other
platforms, nx5/Podman acceptance, or the formal release matrix. It does not claim
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

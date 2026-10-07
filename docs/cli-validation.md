# CLI program identity validation

[简体中文](zh-CN/cli-validation.md)

Gate now identifies its CLI as `lingshu-gate` for both the installed console
script and `python -m lingshu_gate.cli`. The parser explicitly sets `prog`;
`--version` continues to use the existing single source `__version__`.
The change also makes help and argument-error usage text consistent across
those entry points.

Validated source: `ae999912e3175bc6f79daf54da1d586836d4d06e` on
`test/gate-nx5-validation-fixes-20261006`, based on
`7d145c28a94a00a6c5d6f4f7d4fc38c0e6153436`. Execution took place in the saved
cloud Linux x86_64 environment.

The unchanged base reproduced **1 failed, 8 passed** on CPython 3.14.4.
`test_version_flag_uses_single_version_source` expected `lingshu-gate 0.4.4`
and received `python -m pytest 0.4.4`. That interpreter's `argparse` infers an
unspecified program name from `__main__.__spec__`, so replacing `sys.argv[0]`
inside a module-invoked pytest process did not select the command name.
The fix follows the repository's declared console-script identity and retains
the original assertion.

All four environments ran the following command against the validated commit,
with separate owned temporary roots and caches:

```bash
python -m pytest -q tests/test_cli.py tests/test_schema_validation_budget.py
```

| CPython | CLI cases | Schema worker cases | Result | Pytest time |
|---|---:|---:|---|---:|
| 3.11.16 | 12 | 13 | 25 passed, 0 failed, 0 skipped | 5.58 s |
| 3.12.14 | 12 | 13 | 25 passed, 0 failed, 0 skipped | 5.60 s |
| 3.13.15 | 12 | 13 | 25 passed, 0 failed, 0 skipped | 5.86 s |
| 3.14.4 | 12 | 13 | 25 passed, 0 failed, 0 skipped | 5.99 s |

Three new regression cases invoke the real installed console script and the
module from a temporary directory outside the checkout. They compare exit
codes, stdout and stderr for `--version`, `--help`, and an invalid port. An
inert invalid service setting checks that these paths exit before loading
service configuration. Each subprocess has a 20-second timeout.

The unchanged schema worker suite covers complexity limits, deadline and
cancellation handling, child termination, slot reuse, frozen command selection,
and real module worker entry with service configuration bypassed. No process
with the exact worker argument remained after the tests. Ruff, Mypy (158 source
files), repository identity, version and diff checks passed in the 3.13.15
project environment. Dependency and version files remain unchanged.

This is focused CLI and worker validation. It does not establish full Python
3.14 support, full-suite acceptance, or nx5 acceptance. The delegating root
reported an OOM-killed nx5 full-suite attempt under a 3 GB cap and is conducting
separate isolated-file validation; no performance root cause was established
here. OAuth UI, permissions and worker implementation were unchanged. Frontend
and browser tests, new package/native candidate builds, other platforms, Podman
and the formal release matrix were not run for this follow-up. Earlier package
evidence remains tied to its earlier source checkpoint.

The [structured evidence](benchmarks/gate-cli-identity-ae99991.json) records
source and test hashes, exact interpreter versions, scope and unexecuted work.
The [test log](benchmarks/gate-cli-identity-ae99991.log) contains the reproduced
failure and the four successful runs; temporary paths and object addresses are
redacted.

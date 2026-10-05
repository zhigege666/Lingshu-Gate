# Clean wheel staging validation

[简体中文](zh-CN/wheel-build-validation.md) · [Development guide](local-development.md#release-checks)

This is an unreleased test-branch packaging fix. Base: `98d945a37839e6cbd4619245dcee3e66c7ae7ffe`. Recovery input:
`3e774c9c6ed5444b67506af84a022520ac5cb687`. Final tested build checkpoint:
`a186c9ad5de44e98f39552c0bca09a8c0dabd97c` on `test/gate-clean-wheel-20261006`. Version remains `0.4.4`.
The runtime and UI source trees match product checkpoint `a3b57f708ae3d848382e46ee9c9b85ccae8e5722`.

## Root cause and fix

Setuptools 81 incrementally copies package data into `build/lib` and copies the whole resulting tree into
the wheel install directory. Vite cleans only the source static directories. Native/PyInstaller cleanup
does not clear `build/lib`. A regular repeated wheel build can therefore retain old hashed assets.
The earlier integration evidence recorded 141 stale Console and two stale OAuth files.

The recovery input isolated package copying. Independent reproduction also found stale files in the
default `build/bdist.<platform>/wheel` tree could still enter its final wheel. The completed fix retains
the setuptools PEP 517 backend and isolates package copying, wheel installation and archive creation.
It verifies both complete static SHA-256 inventories at the copy/install/final-archive stages, verifies
the final zip paths and every RECORD hash/size, then atomically replaces the output with verified bytes.
It deletes only newly created private staging or output temporary files. Existing cache directories,
native artifacts, custom build paths and user-data targets are preserved. Editable installs work without
the frontend; noneditable wheels reject `--skip-build`. The sdist carries the hooks and built assets.

## Executed evidence

| Check | Result |
|---|---|
| Focused wheel, release, automation and CI tests | 200 passed, zero failed/skipped |
| Ruff, mypy, repository identity, version, whitespace | Passed; mypy covers 158 source files |
| Baseline A→B reproduction | Failed as expected: second wheel contains A and B in both roots |
| Complete repository A→B builds after fix | Second wheel contains B and no A; old lib/bdist caches and user files retained |
| Two concurrent complete repository wheels | Passed; identical B hashes; private staging cleaned |
| Missing/extra/changed assets, path boundaries, failed build/retry | Passed, including final zip/RECORD corruption and output symlink preservation |
| Latest frontend and ordinary PEP 517 sdist→wheel/direct wheel | Passed; identical wheel hashes and payloads |
| Current dist/wheel/installed wheel/extracted Linux native static files | 97 Console + 3 OAuth, exact file lists and SHA-256; match prior browser-tested assets |
| Wheel RECORD / Python payload / native BUILD-INFO | 265 / 158 / 457 entries verified |
| Native archive, standard extraction/readiness and glibc | Passed; maximum required glibc 2.35 |
| Schema IPC/deadline/cancel/reuse and direct worker entries | 14 real validation children + 4 direct probes; all reaped |
| Wheel/native CLI and loopback HTTP | Both passed; all 97 Console files served byte-exact; service processes reaped |

The full backend result (2126 passed, 7 skipped) is inherited from `31b7cca`; frontend unit tests
(439 passed) and 98 browser cases are inherited from `a3b57f7`. Those suites were not rerun here.
The newly built 100 static files exactly match their recorded product manifest. Packaging tests and
candidate smoke were executed for this fix. The native executor remains disabled during local smoke.

## Private candidate hashes

| Artifact | SHA-256 |
|---|---|
| Wheel, both direct and sdist-derived | `696bde45fccca195560fbe200df53378f7dc2bd3e7886a59dfab01c6d78b5fb0` |
| Source distribution | `f6f54e022dddecb9c5243513307c2fc0ee06d173b6f83fd12ad3f23c3c8b4fc3` |
| Linux x86-64 native archive | `c416244eb5cae39a7400480583ede8246403227a49fa6c3c69b76bdd51738d93` |

Candidates stay under ignored `dist/candidates/gate-clean-wheel-20261006` in the saved cloud environment.
These hashes identify private candidates, not official published assets.

- [Validation and inherited/not-run checks](benchmarks/gate-clean-wheel-validation-a186c9a.json)
- [Consecutive/concurrent builds and baseline/input reproductions](benchmarks/gate-clean-wheel-repeated-build-a186c9a.json)
- [Full package/static manifests and hashes](benchmarks/gate-clean-wheel-packages-a186c9a.json)
- [Worker entry/reaping evidence](benchmarks/gate-clean-wheel-package-workers-a186c9a.json)
- [Installed wheel/native HTTP evidence](benchmarks/gate-clean-wheel-package-http-smoke-a186c9a.json)
- [Focused test log](benchmarks/gate-clean-wheel-validation-a186c9a.log)

## Remaining scope

Real nx5/rootless Podman acceptance awaits the root connection and approved safe host configuration.
Real credentials/providers/clients, the four Podman host cases, three external Playwright opt-ins,
other operating systems/architectures and the formal release matrix were not executed. The inherited
requirements export still differs only in jsonschema `via` comments; all requirement versions and hashes
match, and both lock/export files were preserved. That textual drift is outside this packaging fix.
No main merge, tag, release, SSH, permission change or official 0.4.4 asset publication occurred.

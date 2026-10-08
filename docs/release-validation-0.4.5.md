# 0.4.5 candidate validation and release gates

[简体中文](zh-CN/release-validation-0.4.5.md) · [Release guide](releases.md) · [Release summary](../packaging/release-notes.md) · [Exact evidence](benchmarks/gate-release-0.4.5-2ef739b.json) · [PR #55](https://github.com/zhigege666/Lingshu-Gate/pull/55)

The product candidate is frozen at `2ef739b5a9f72e8a7a01c7044f20b5d766de415c`, based on exact main `8941738096ab69c0b9fa014f39ff9749cca64822`. The independent `test/gate-release-0.4.5-evidence-20261007` branch changes only these paired reports and the historical/current JSON evidence; it does not change PR #55's head or cancel its CI. The full local frontend/backend/browser product checks retain their actual 7c7e39f provenance. This head adds only the CI installation repair; product/runtime/UI/package inputs are byte-identical to 7c7. Fresh package builds, packaging regressions, installed-wheel/native probes and current CI use 2ef739b. No earlier package or later evidence commit is substituted for that build SHA. The CI PR merge checkout is `d49696e29d92f1627160ab18b77b560175826d85`; a fetched tree comparison proves its tree is identical to the product head.

## Scope and packaging correction

The candidate increments the single version source to 0.4.5 and minimally adapts omitted account-menu behavior from `4c61cb4fa9301805386122e27a2e88098c0770fc` and classification explanations from `8ff92ef5694f47faed30b3a38c288c72ccbf3551`. The controlled menu closes on Escape, outside click, selection and navigation; Escape/selection restore trigger focus. Builtin roles are localized in English/Chinese, empty and duplicate roles are removed, unknown custom names remain plain text, and an all-empty list falls back to the primary role. Classification explanations show known changed fields, discard unknown fields and explain an unrecorded historical definition without treating absent evidence as a proven schema difference. Review and publication remain separate actions.

The backend policy, authorization, dependencies, current tokens/header actions/search dimensions and CSS do not change. Vite 8/Rolldown, both `mangle: false` entries and Console `base: "/"` remain intact. The release guides now name the actual pinned PyInstaller 6.22.3. After two proven APT mirror/index timeouts, this head also moves complete official browser dependency installation before the expensive backend gate, using invocation-owned signed Ubuntu primary/updates/security sources, bounded network retries/timeouts, and normal-user browser download. Product smoke assertions and their 180-second command remain intact.

The already integrated [clean-wheel fix](wheel-build-validation.md) addresses incremental setuptools `build/lib` copies plus whole-tree wheel installation. Vite cleans source static directories and native cleanup does not clean that package cache. The original candidate contained 143 stale files. The formal setuptools PEP 517 hooks now use fresh owned copy/install/archive staging, compare complete Console/OAuth inventories at every stage, validate archive paths and every RECORD hash/size, then atomically replace the output with verified bytes. Existing build/native/custom/user-data trees are preserved; only invocation-owned staging/temporary output is removed. The sdist contains the hooks and built assets. These hooks are unchanged in this version PR; their regression suite was actually rerun on the current source.

## Executed local checks

| Check | Actual result and provenance |
|---|---|
| Frozen dependency sync/export, version, Ruff, mypy, repository identity/history, Compose config, whitespace | Passed; Python 3.13.15, uv 0.11.33, Node 22.23.2/npm 10.9.8; mypy 158 files; exported requirements byte-identical |
| Frontend checks, unit tests, both Vite builds | Local product 7c7: 75 files / 455 tests passed; Console 115 + OAuth 3 static files |
| Complete backend | Local product 7c7: 2311 passed, 7 skipped, 134 subtests passed; 5 existing JUnit property warnings |
| Required browser smoke | Local product 7c7: 29 passed, zero failed/skipped/flaky; includes 10 root-entry cases and bilingual menu/role/classification cases; 16 account-menu viewport/theme/locale frames |
| Actual root HTTP | Source fixture on 7c7 and fresh isolated installed wheel on 2ef each checked 261 requests, including 114 current/legacy Console file pairs, HTML/JSON negotiation, redirects, API auth, OAuth-off and traversal boundaries |
| Packaging regressions | 156 passed; actual two-round PEP 517 fixture wheels A→B in both static roots, stale lib/bdist preservation, missing/extra/changed files, path/symlink/FIFO/user-data boundaries, final zip/RECORD corruption, sdist/editable and native contracts |
| Current repository PEP 517 direct wheel and sdist→wheel | Passed offline; both wheel byte streams identical; all static files and every RECORD entry verified; setuptools.build_meta 84.0.0 |
| Fresh Linux x86_64 native | Official builder, archive identity, standard extraction and readiness passed; PyInstaller 6.22.3; extracted static files match the current Vite output |
| Installed wheel and frozen native schema workers | 9 probes per package: valid/local-ref, invalid/unsupported/remote-ref refusal, real parent dispatch, deadline/cancel kill and slot reuse; all children reaped; no service runtime created by worker entry |
| Cleanup | Owned HTTP processes reaped, listeners closed, runtime directories removed; 7c7 backend post-run audit found no owned runtime directories or pytest processes; private wheel staging removed |

The seven backend skips are three fixed external Playwright MCP-peer opt-ins whose installation was not supplied, and four real rootless Podman/image/tmpfs cases requiring operator provisioning. They are not passes. The historical fixed-peer follow-up retains its own SHA. Vite chunk/config-loader warnings and the backend JUnit warnings remain visible in the original logs.

The complete current 118-file static inventory is stored in the JSON. Its canonical SHA-256 is `95bf75f824b5d0770931666340a1b4a3156fc660eba46e81154176d566b60902`. The rebuilt Vite outputs, direct/sdist wheels, installed wheel and extracted Linux native have exactly the same file list and bytes.

## Private package hashes

| Artifact | Bytes | SHA-256 |
|---|---:|---|
| `lingshu_gate-0.4.5-py3-none-any.whl` (direct and sdist-derived) | 1923055 | `099aea2df45506c0975ea620e528fbe17d43193aeb08df3547b583952fe5353c` |
| `lingshu_gate-0.4.5.tar.gz` | 2136451 | `8d74105e35f1af813917adbbf622a3b5c980926ddc2687488ee0a9e6d7f8243a` |
| `lingshu-gate-v0.4.5-linux-x86_64.tar.gz` | 36315093 | `af98eb535cbd9e279c66a1a6722e443fd956aabca228fa78f2068e60e1c088d0` |

These are private candidates in the saved cloud environment. They were not uploaded as formal release assets. The JSON records raw-log hashes, exact commands, builders, package inventories and cleanup; sensitive fixture data and runner absolute paths are omitted.

## Exact CI checkpoint

Observed at `2026-10-07 20:37:50 UTC` for branch head `2ef739b5a9f72e8a7a01c7044f20b5d766de415c` and actual checkout `d49696e29d92f1627160ab18b77b560175826d85`. No cancelled or older-head result is reused.

| Workflow | Status / conclusion |
|---|---|
| [Continuous integration](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428487) | completed / success |
| [Release artifacts](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428322) | completed / success |
| [Container images](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428302) | completed / success |
| [Code scanning](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428324) | completed / success |

| Exact current source / compatibility job | Actual status and log result |
|---|---|
| [Source checks](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428487/job/112981013531) | completed / success; Python 3.12.14 pytest 2311 passed / 7 skipped / 134 subtests; frontend 455; browser 29 |
| [Python 3.11](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428487/job/112993170545) | completed / success; Python 3.11.17 pytest 2311 passed / 7 skipped / 134 subtests |
| [Python 3.13](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428487/job/112993170553) | completed / success; Python 3.13.16 pytest 2311 passed / 7 skipped / 134 subtests |
| [CI result](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428487/job/113004203758) | completed / success |

| Platform / bundle job | Status / conclusion |
|---|---|
| [Docker Compose bundle](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428322/job/112981690636) | completed / success |
| [Native macos-arm64](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428322/job/112981690722) | completed / success |
| [Native linux-x86_64](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428322/job/112981690742) | completed / success |
| [Native macos-x86_64](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428322/job/112981690752) | completed / success |
| [Native linux-aarch64](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428322/job/112981690753) | completed / success |
| [Native windows-x86_64](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37676428322/job/112981690786) | completed / success |

All five native jobs verify package identity, validated extraction and readiness on their own platform; Linux jobs also enforce the glibc baseline. The PR release quality job ran 194 release-engineering tests. Container contracts performed real Core build/inspection/readiness/critical-vulnerability checks and QEMU native/emulated execution, rather than a documentation-only check.

Compose validation covered model/config checks for the local, production and packaged Compose files. Core readiness was tested through `docker run` of the secure image on the GitHub runner. These results do not establish nx5 deployment, real rootless Podman provisioning/readiness or real OAuth-client acceptance.

The historical 7c7 source CI attempts 1 and 2 each passed 455 frontend tests and Python 3.12 backend 2311/7/134, then failed with exit 124 during Ubuntu APT mirror/index preparation before Chromium download. Browser assertions and Python 3.11/3.13 never ran; both failures and original log hashes are retained. No third unchanged rerun was requested. The necessary 2ef739b repair changes only `.github/workflows/backend.yml`; 35 existing CI-contract tests and YAML/Shell ordering checks passed locally. On the actual new CI runner, complete official dependency/font installation plus Chromium download passed before backend testing. The current exact-head source workflow is **completed / success**. The actual browser smoke, both complete Python compatibility runs and CI result gate are all terminal and successful on this head; their exact versions/counts and log proofs are recorded in the JSON.

Downloaded Windows, both macOS and Compose artifacts passed their actual GitHub ZIP digest, inner SHA256SUMS, complete BUILD-INFO inventories and SPDX SBOM checks. Both macOS builds match all 118 Linux static bytes. Windows has the same 118 paths and all JS/CSS bytes, with CR/CRLF differences in two HTML/two SVG text files; its own declared hashes are valid and removing CR reproduces the Linux text. No cross-platform byte-identity claim is made for those four files. The two Linux CI artifact ZIPs exceed the local download tool's 32 MiB bound and were not independently downloaded here; their CI validation/extraction/readiness logs and artifact metadata are recorded separately from the freshly built and fully inspected local Linux package.

Conditional skips are explicit in the JSON: PR tag-only Core-image candidate/offline-image/publication jobs, the main-push-only multi-architecture Core-image job, platform-specific Delivery Skill/OpenSSL/glibc steps, and the PR quality branches delegated to source CI. Skipped formal jobs do not establish publication.

## Blocking and separate scope

Required current source, browser, package/static/RECORD, worker/cleanup or CI failures block acceptance. Main merge/tag/release remains owner-controlled. A version change pushed to main automatically creates a tag and dispatches release workflows; formal acceptance still requires every mandatory job, all 11 exact assets, aggregate/inner checksums, SBOM, exact source/workflow provenance and published title/body readback. PR artifacts are candidates.

The authorized isolated-host check below adds real temporary source/wheel HTTP and MCP fixtures, with the original active service preserved. No existing-service switch, real Podman provisioning/readiness, real ChatGPT OAuth client or multi-machine integration was executed. Native execution and OAuth defaults remain unchanged. The parent-reported PR49 broader browser results remain historical failures: default 418 passed/55 skipped/2 failed of 475; optional 27 passed/3 skipped/7 failed. Attribution remains unproven; this record does not claim whole-site or optional-browser green. Earlier launcher-path/locator/checkout-mode preparation failures are retained in the JSON with their corrections and exact source SHAs. The extra installed-wheel probe also retains its initial missing offline index metadata and development-driver `httpx` failures; neither reached product assertions before correction.

## Authorized isolated-host check, 2026-10-08

[Host evidence](benchmarks/gate-release-0.4.5-host-isolation-2ef739b.json) records a fresh HTTPS Git fetch of exact `2ef739b5a9f72e8a7a01c7044f20b5d766de415c` and tree `716da35e388aab6784d8b41d6ae4e79a4c17f948`, using the existing authorized test identity, a new private directory, new venvs/caches and empty fixtures. No original service directory, credential or business database was reused. The actual host tools were Python 3.14.4, Node 22.22.1, npm 9.2.0 and uv 0.11.33; production/release dependencies were frozen, and pytest/HTTP-driver dependencies used exact uv.lock hashes. This is an additional host smoke, not an extension of the published Python compatibility matrix.

| Executed check | Actual result |
|---|---|
| Both Vite builds | Passed at 04:26:24 UTC; Console 115 + OAuth 3; canonical static SHA remains `95bf75f824b5d0770931666340a1b4a3156fc660eba46e81154176d566b60902` |
| Packaging and schema regressions | 143 + 13 passed, zero failures/errors/skips; includes real two-round A→B wheels, both static roots, missing/extra/path/RECORD boundaries and native packaging contracts |
| Synthetic D01/D02 | 2 passed; real local stdio delivery/reapply, failed build preservation and artifact replacement/rollback inside disposable fixtures |
| Direct wheel and sdist→wheel | Passed; both host wheels byte-identical, complete static inventories and every RECORD entry verified |
| Source and installed-wheel HTTP | Each passed 261 requests / 114 current-legacy Console pairs, health 0.4.5, root negotiation, redirects, unauthorized API/MCP, OAuth-off and traversal refusal |
| Installed-wheel schema worker | 9 probes passed; deadline/cancellation killed and reaped owned children, slot reuse passed, worker entry created no service runtime |
| Installed-wheel TCP MCP | 36 real loopback RPCs, six on-demand entries; initialize/discover/list → search/describe/invoke → chunk upload/plan/build/deploy/start/refresh/status → actual downstream stdio call; stale schema and invalid arguments refused |
| Cleanup and original service | All temporary services/peers reaped and listeners closed; fixed, guarded allowlist removed generated directories at 04:46:43 UTC; tracked source/Git and evidence retained. At 04:48:30 UTC the original service remained active/running, health 200/version 0.4.4, with the same PID, unit/start digests and protected-directory identities/owners/modes |

The new synthetic tool correctly remained `needs_review=1`, with `effective_permissions_expanded=false`, no classification publication and no new grants. The explicitly authorized administrator fixture call verifies runtime dispatch without establishing user publication or OAuth acceptance. **Deployment and process startup succeeded; delivery acceptance remains incomplete.** The disposable fixture was then removed.

| New host artifact | Bytes | SHA-256 |
|---|---:|---|
| Direct and sdist-derived wheel | 1923055 | `a9234933cce5cbb1f8553fbf9c0a2540ff5641700aac19fde3fd6ffa0ea672c8` |
| sdist | 2137280 | `2c4e0a72b2ddc99701727a845547e6259e36dc071acb470f16ac77798ad406c8` |

All 283 wheel member payloads, including RECORD, match the earlier cloud wheel. Its different archive digest comes solely from 281 ZIP external-attribute fields inherited from checkout file modes (sample 0600 versus 0644). An in-memory attribute normalization reproduces the cloud wheel's exact `099aea2d…5353c` digest; the actual host candidate was left unchanged. Only metadata was compared; the original handoff package was not transferred.

Preparation history is retained: initial uv pip transfer reached its 600-second deadline; bounded continuation of the same official file verified its PyPI SHA before local installation. The unused full-development download was deliberately stopped before the focused frozen setup. The first installed-runtime requirement resolution reached a 180-second deadline before product execution; frozen uv.lock installation into that same owned venv then succeeded, and all applicable committed requirement versions were checked. An extra help diagnostic attempted an unowned configuration path and received permission denied; that diagnostic stopped without a permission/configuration override. Library 403 was not retried. No host native rebuild, Podman provisioning, full host product suites, real OAuth client, multi-machine integration, main merge, tag or formal release ran. Earlier cloud/CI results retain their own provenance.

## Upgrade boundary

The root-entry no-new-migration comparison covered already integrated be30-to-6663203 source. Upgrading from published v0.4.4 to this combined release also includes tool-directory/group migrations. Preserve configuration, data, credentials and signing keys, take a consistent backup and retain one SQLite writer and the prior package. Historical benchmarks, screenshots and immutable tags retain their original provenance; third-party `typing-inspection==0.4.4` is not the Gate version.

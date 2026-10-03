# 0.4.0 validation record

[简体中文](zh-CN/release-validation.md) · [Release guide](releases.md) · [PR #43](https://github.com/zhigege666/Lingshu-Gate/pull/43)

This record distinguishes candidate source validation from publication and real integration. Product code and screenshot provenance use `4816673fcac237bce398c2e3a57124616492ebce`, integrated with main `d500116548a90e4edaa0bfa0e0c1138afe45354a` (including built-in OAuth PR #42). That snapshot includes the bounded classification action-column fix; later documentation updates do not change its product code. The final PR head must pass its own checks; an earlier green run is not evidence for a later commit.

## Executed checks

| Check | Observed result | Scope |
|---|---|---|
| Frozen uv sync / npm clean install | Passed | Locked development/runtime dependencies |
| Ruff, mypy, Python syntax | Passed; mypy checked 106 source files | Source checks, not real-network acceptance |
| Full Python tests | 1,044 passed | Includes Git input/protocol rules, redaction, inheritance, permissions, timeout/cancel, locks, old-deployment preservation and integrated OAuth/API-token/external-auth regressions |
| Git/network focused tests | 80 passed | Controlled fake adapters plus actual HTTP adapter audit; no user Git/proxy connection |
| Console check, Vitest, both asset builds | Passed; 62 files / 325 tests | Console and independent OAuth bundle; Vite reports existing large-chunk warnings |
| Browser failure-focused suite | 72 passed | Both languages and requested desktop sizes, ownership/confirmation, external-mode guide and actual loopback MCP |
| Default full browser suite | 108 passed / 38 opt-in skips | Real isolated backend plus explicitly mocked presentation scenarios; skips are not passes |
| Extended browser first run | 55 passed / 17 failed | All available opt-in files, three-size list matrix and visual tests; no retry or skipped failure |
| Extended targeted follow-up | 8 passed / 9 failed | Corrected rendered controls and reset semantics; remaining failures recorded below |
| Panel-fixture follow-up | 2 passed / 4 failed | Subject diagnostics passed; build-log remaining-space assertions still fail |
| Pinned Chromium visual recheck | 1 passed / 1 failed | Existing 390×844 baseline passed; 1280×600 differs by 18,241 pixels (~3%); baseline unchanged |
| Requirements export, identity, version, Compose, diff | Passed | Synchronized lock export, repository identity, `v0.4.0` source match, static Compose contract and whitespace |

After the fixture corrections, eight optional scenarios remain failing: dashboard ranking height / narrow time-axis density (2), a narrow personal-tool drawer (1), build-log remaining-space assertions (4), and the desktop login visual baseline (1). The latest per-scenario results come from the runs above, not a new single all-green extended run. They are separate from the passed four-size Git/OAuth journeys. No unrelated layout redesign or visual-baseline regeneration is bundled to make the optional tests green. The externally supplied preview-adapter scenario remains unavailable because its opt-in source path was not supplied.

The exact `8b3dc8a` source [CI](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37121331535), [CodeQL](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37121331529), [container contracts](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37121331527) and [release artifacts](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37121331608) succeeded. CI includes Python 3.11/3.12/3.13 and isolated browser smoke. The PR release matrix built and smoke-tested five native targets and a Compose bundle. Tag-only image promotion, offline images and GitHub publication were skipped on the PR; those operations are not reported as passed or published. Final-head and eventual tag results must be checked separately through PR #43 and the release record.

## Screenshot provenance

Supplemental desktop review used the unchanged optional-fixture assertions at all four acceptance sizes. The ranking-height ceiling (256px) failed at 367/404/404/404px respectively; all four rankings remained inside the viewport with their own scrollbar and seven desktop axis labels. Personal-list/drawer journeys passed at all four sizes. The English review button initially overflowed its 104px sticky column by about 15px; scrolling right made it reachable, but the initial clipping was real. The bounded 144px column fix keeps the status offset and colgroup aligned. Eight bilingual button-boundary, hit-test and dialog/cancel regressions passed in the 108-case default suite; no classification mutation is submitted.

| Desktop viewport | Build-log row client height | Pagination height | Original 44px-budget predicate | Page overflow / enabled controls |
|---|---:|---:|---|---|
| 1600×900 | 543px | 56px | false | None / within viewport and unobscured |
| 1920×1080 | 723px | 56px | false | None / within viewport and unobscured |
| 2560×1080 | 723px | 56px | false | None / within viewport and unobscured |
| 2560×1440 | 1083px | 56px | false | None / within viewport and unobscured |

For each log fixture, the final row and sticky first header were reachable. The row bottom reserves 56px pagination (24px padding plus 32px controls), 14px card padding, 1px border and 32px outer spacing: 103px total. The original predicate reserves 44px and misses about 57px after its 2px tolerance and integer rounding. These observations support a test-budget mismatch, not hidden controls or unused row space in the desktop fixtures; the original assertion has **not** been relaxed or reported passing. Disabled navigation controls are excluded from operability claims.

The original eight optional failures remain separately identifiable: [ranking](../web/e2e/layout-audit.spec.ts#L44) at 2048×1222 (404px > 256px); [axis](../web/e2e/layout-audit.spec.ts#L47) at 390×844 (7 > 4 labels); [personal drawer](../web/e2e/personal-layout.spec.ts#L88) at 390×844 (last header right edge 444px > 390px); [log budget](../web/e2e/remaining-panels.spec.ts#L113) at 2048×1119, 1188×761, 1366×768 and 390×844 (predicate false); and [login visual](../web/e2e/visual.spec.ts#L10) at 1280×600 (18,241 differing pixels against a 1% limit). The narrow drawer failure is horizontal visibility, not a measured height failure. Login controls were visible at the four desktop sizes, but those sizes have no stored pixel baselines; their visual equivalence is unverified. No baseline was generated or replaced.

Both READMEs link nine views in each language: overview, tool catalog, classifications, personal workspace, trusted ZIP delivery, blocked Git source, network settings, disabled OAuth and tool invocation. All 18 PNGs are actual 1920×1080 light-theme browser captures from the same candidate product code, without edited pixels or mocked API responses. The [capture manifest](images/console/v0.4.0-capture.json) records the source revision, product-source digest, locale, viewport, observed state and each PNG SHA-256.

The fresh instance uses synthetic administrator/viewer accounts, a reviewed dependency-free ZIP fixture, a local synthetic HTTP MCP peer, a disabled encrypted profile pointing to a reserved invalid host, and a reserved Git host. OAuth has no configured signing key or client secret. Git planning returns the actual `safe_executor_unavailable` response before DNS or acquisition. No profile probe, user repository, dependency install, SSH operation, external account or production deployment was performed for capture. Synthetic names are fixture data. Backend-provided tool names/descriptions and raw diagnostic codes retain their original language; the surrounding Console controls use the selected locale.

Screenshot review checks loaded controls, matching Chinese/English navigation, legible forms/tables, the disabled/blocked status, and absence of real credentials or local filesystem paths. Screenshots demonstrate rendered presentation, not production authorization-provider or network acceptance.

## Remaining release and execution boundaries

- The production `SafeNetworkExecutor` is absent. Real Git resolution/fetch, proxy probes, tool preparation and configured network install remain blocked; fake-adapter tests provide no production isolation claim.
- Real GitHub/private Git, user proxies, Git SSH, pnpm/npm/Yarn distribution preparation, private dependency sources, ChatGPT, public TLS/proxy cookies and external OAuth accounts were not connected or accepted.
- No production upgrade, deployment or uninterrupted session migration was exercised. Failed-build/old-deployment and bounded rollback behavior is covered by controlled tests; rollback can interrupt a running service.
- Repository rulesets were readable (empty response); the current integration could not read legacy `main` protection (HTTP 403). Its exact required-check/approval policy is therefore unverified. Preserve existing rules, use the exact reviewed head, and do not use administrator bypass, force push or skip CI.
- Version/tag/release follow the existing `main` version-change workflow. It requires configured release credentials and enabled immutable releases, then verifies the fixed tag, artifacts, checksums, SBOM and provenance. No new token is created and no existing tag is moved. CI success and a version bump do not prove publication.

Final integration review receives the exact-head diff, file inventory, check URLs and separate passed/failed/skipped/unrun evidence before merge. No production network or credential configuration is authorized by this record.

# 0.4.10 candidate and publication validation

[简体中文](zh-CN/release-validation-0.4.10.md) · [Release guide](releases.md)

## Source and scope

The candidate starts from `bc8a920fa1987dfedb8e47ff4c984bd2cd55cd48` and uses the sole runtime version in `src/lingshu_gate/_version.py`. Paired overviews, changelogs, configuration guides and bilingual release notes describe 0.4.10. Existing tags, including v0.4.8 and v0.4.9, are not moved.

The runtime change is limited to normalizing empty or whitespace-only optional endpoints for stdio. Non-empty endpoint declarations and Streamable HTTP retain URL validation, private-origin trust and redaction. The editor's existing lossless runtime switching remains unchanged. No dependency, database migration, permission expansion or default-enabled execution is added.

## Reproduction and focused checks

Verification on 2026-10-17 used an isolated native Linux checkout, Python 3.14.4, Node 22.23.2 and uv 0.11.33. Frozen lock dependencies and the synchronized pip export were retained. This is additional native-host evidence, not a substitute for the workflow's Python 3.12 source checks and pinned Python 3.13.15 release builds.

The new stdio regression first reproduced six failures on the unchanged model. After the fix, the stdio, endpoint security, manifest consistency and private HTTP trust suites passed 117 tests, including authenticated ASGI precheck/create/read/edit, HTTP rejection, unchanged saved digest after a rejected edit, and denial without authentication. Saving was checked not to start a process; no user-provided downstream package or production database was contacted.

The repository identity, reviewed PNG provenance and authorization discovery suites passed 61 tests. Frontend verification passed 478 tests across 78 files, TypeScript/UX checks and both production builds. Ruff passed, Mypy reported no issues in 165 source files, and the frozen pip export matched `requirements.lock`.

The initial full-suite run exposed two pre-existing external-management tests that still assumed direct MCP discovery. Both also failed against the unchanged 0.4.9 source. The corrected tests use real owner preview/confirmation to select direct discovery, or the default on-demand describe/invoke sequence with the returned schema revision. Seven focused cases passed, including default direct-name rejection without a write. Runtime discovery, authority and request-override restrictions were not loosened. Focused groups overlap and must not be added together as a full-suite total.

Four legacy-protocol tests also failed against unchanged 0.4.9 because their access-store double lacked the current `dispatch_guard` argument and evaluation method. The double now executes the guard; all three legacy versions assert the check runs, and a negative case verifies guard failure prevents invocation. That file passed 13 tests. The combined external-configuration, gateway, legacy-protocol, authorization-discovery and stdio run passed 179 tests plus 2 subtests. Only test contracts changed; gateway security rules did not.

Further current-protocol and SDK doubles now implement dispatch guards. OAuth and log tests use persisted discovery settings and actual catalog wiring while checking unchanged grant scope, hidden-tool privacy and global-log non-disclosure. That group passed 48 tests plus 15 subtests. The initial full run recorded 56 failures, 2425 passes, 7 skips and 132 passed subtests; failure accounting includes two subtest failures. After normal frozen dependency synchronization prepared the isolated build environment, all 40 existing offline wheel tests passed unchanged, including source-integrity and security negative cases. The final complete commit still requires full-suite and workflow acceptance.

## Release identity boundaries

Current documentation and test-helper wording are neutral. Seven historical snapshots are limited to the exact existing 0.4.8/0.4.9 commits, paths, Git blobs, SHA-256 values and findings. The previous independently reviewed exception remains intact. Reuse in other commits, commit messages, current text and release artifacts is not covered by a historical waiver.

Four concept PNGs retain their entire original byte streams and C2PA metadata. Only exact approved image and `caBX` chunk digests distinguish the metadata's source attribution from product identity. CRC, changed image/chunk, changed location, product metadata and other identity-rule regressions remain checked. This preserves existing provenance bytes; it is not a new cryptographic validation of the image signatures.

## Full-suite and publication evidence

The commit's workflow checks are the authority for complete source and release verification. The focused results above do not assert a successful full-suite run or formal publication. Vite's existing large-chunk warnings remain non-fatal and are not treated as a performance acceptance result. No browser-layout or production deployment acceptance is claimed for this patch.

Formal publication requires every existing release job and eleven verified assets: five native packages, Compose, two offline Core images, application SPDX SBOM, exact container image reference and SHA256SUMS. Asset bytes, build provenance and published title/body must match the exact source. A tag, successful identity check or successful candidate test is not publication. Installing a released package remains separate from publishing it and must preserve existing data, configuration and credential keys.

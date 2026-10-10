# 0.4.7 candidate and publication validation

The immutable [v0.4.7 release](https://github.com/zhigege666/Lingshu-Gate/releases/tag/v0.4.7)
was published on 2026-10-10 at 05:56:43 UTC. The final receipt below binds the
merge source and all eleven downloaded assets.

## Source and patch scope

This patch carries the catalog snapshot retry repair reviewed in
[PR64](https://github.com/zhigege666/Lingshu-Gate/pull/64), exact head
`2f59a904a8f90da6a242699a62b1ad8f556cee29`. The code content commit is
`2534eb9032b8165d40d732bf1b033a55b96f3cbe`; the following evidence commit
does not change those bytes. The release candidate must start from the accepted
main merge and retain its exact source identity in fresh package receipts.

The normal PR64 merge is `0fcfd27ba9f8e1474f6b7975a39512c1298ae279`, tree
`f02ab9c5f207d5b333a650f73efe3dc9fdf4059a`. All 989 remote leaf modes, types
and Git blobs match the reviewed head exactly. Exact-head ordinary CI
[38014839844](https://github.com/zhigege666/Lingshu-Gate/actions/runs/38014839844)
completed successfully, including Source/Python 3.12 with hosted browser smoke,
Python 3.11, Python 3.13 and the CI result. Ordinary main CI
[38018193498](https://github.com/zhigege666/Lingshu-Gate/actions/runs/38018193498)
completed successfully before the version PR was merged.

The sole runtime version source is `src/lingshu_gate/_version.py`. This patch
changes it to `0.4.7` and synchronizes both READMEs, CHANGELOGs, the release
guide and bilingual release notes. Existing group/session, root Console,
on-demand directory, OAuth editor and package staging behavior is carried
forward. Authorization rules, migrations, dependencies and optional
executor/OAuth defaults are unchanged. The occupied v0.4.5/v0.4.6 tags retain
their original SHAs; a source repair requires a new patch identity.

## Executed repair checks and limits

The [retry evidence](benchmarks/gate-catalog-snapshot-retry-333862e.json)
records four intentionally failing pre-fix controls, 32 passing cache/authority
checks, all three real 5,000-instance/50,000-tool directory scenarios, and 481
passing catalog, OAuth, configuration and Registry checks. All three scale
cases retain their concurrent writer, bounds and original 20-second reader
budget. The over-cache writer race prepares its 7742 initial misses once,
instead of the observed 15483 preparations before the repair. Current token
scopes, grants, classifications and version vectors are rechecked.

Independent read-only review of all four PR64 diffs, the 715-line evidence,
Registry/frozen-data/authority/lock code found no P1/P2 issue. This review did
not rerun the author's tests. The 64 MiB limit is the shared cache's accounting
limit; bounded request references do not establish a process RSS limit.

The new user-provided failure text is 551 lines and truncated, without a final
pytest summary. It shows the original hosted reader timeout. Local runs of
the original scenario passed, so the exact hosted 20-second failure and its
unique cause are not claimed as reproduced. Local elapsed times and peak RSS
are measurements with their recorded process histories, not production SLAs.

Earlier [0.4.6 validation](release-validation-0.4.6.md) retains its source,
browser and host boundaries. Real OAuth clients, multi-machine acceptance
and optional Native/Linux Podman provisioning remain incomplete. No browser
sandbox setting is weakened, and no real host identity/grant/session is
created by local synthetic checks.

## Fresh candidates and mandatory publication gate

Fresh 0.4.7 receipts must cover the current web build, both static inventories,
direct PEP 517 wheel and sdist-to-wheel paths, exact RECORD, Linux native inner
manifest/SBOM, glibc compatibility and schema-worker/main-entry smoke with
owned-process reap. Earlier candidate hashes do not identify these packages.

Fresh local candidates completed at source `2d6b469f8c8d661b92f0da8d1fd2f55937342923`, tree
`9cd19c15e0d4d4833aef0f1fc216da33d0713b83`. Both wheel routes have identical bytes.

| Candidate | SHA-256 |
|---|---|
| Direct wheel and sdist-to-wheel | `e6138f23148b44e68c7bfd6c85ce90eebc152111296db910930b7ea1884db4e0` |
| sdist | `7bbda98aa873009ff323522c85de9bf4151b74e47dcc0afc4013d35e4263d680` |
| Linux x86_64 native | `6d432eb4977f5e94fc770b994794389a24fac59889392cc54823ca3d3bb37570` |

[Package receipts](benchmarks/gate-release-0.4.7-packages-2d6b469.json) verify
118 static files (115 Console, 3 OAuth), all 283 wheel RECORD entries, 467
native manifest entries, the 200-package SPDX SBOM and glibc maximum 2.35.
Twelve entry checks and twelve parent worker lifecycle checks pass, including
deadline/cancellation, slot reuse and reap. The official frozen main-service
readiness/HTTP/static smoke also passes with temporary owned loopback data;
that service fixture is separate from the identity-free worker checks.

[Executed check receipts](benchmarks/gate-release-0.4.7-checks-2d6b469.json)
record 455 passing frontend tests and 207 passing packaging/schema/release
regressions, including repeated A-to-B builds in both static directories,
missing/unexpected files, path boundaries and native staging. CPython 3.13.15,
Node 22.23.2, PyInstaller 6.22.3 and setuptools 84.0.0 were used. Local uv is
0.12.19; the formal workflow pins 0.11.33. Missing local registry metadata was
resolved by installing the unchanged locked production requirements with
required hashes and normal TLS verification. These candidate receipts bind
to the source commit above, before the following documentation/evidence
commit. New formal assets and the final version main merge require their own
source identities and hashes.

After candidate acceptance and the version PR's required checks, the version
merge to main invokes the existing `publish-release` selector. Credential and
release-immutability prechecks precede tag creation and `release.yml` dispatch.
No credential value is read or created by this validation work.

Formal publication retains the complete independent quality gate, five native
targets, Compose, both Core architectures/offline images, application SPDX
SBOM, image reference and SHA256SUMS: eleven exact assets. Verify every
mandatory job, archive checksum, inner inventory, SBOM, source/workflow
attestation and published title/body. A tag, dispatch, local candidate or PR
artifact alone does not establish publication. Existing failed tags and
denied artifacts are not reused or rerouted as substitutes for this gate.

## Completed formal publication and downloaded bytes

PR65 merged as `45cec40c1e57d7290ab249e620b5a50fa939e115`, tree
`5cf23e968371ca7623eaef75e7d774a38d022240`. All 993 remote leaf modes,
types and blobs match reviewed head `c9261a2c95cc30edb7e46317a1c36778ac0227bf`.
The existing selector created v0.4.7 at this merge; v0.4.5/v0.4.6 retain their
original SHAs. Main CI, code scanning, container validation, the selector and
[formal run 38022781421](https://github.com/zhigege666/Lingshu-Gate/actions/runs/38022781421)
completed successfully.

The first formal quality attempt reached the unchanged 40-minute job limit
without finishing pytest. After fresh source checks and a passing local
66-case timing probe, the execution agent requested one bounded retry through
the original tool under the authorized release scope. This engineering
decision does not prove a transient runner cause. The second attempt passed
on pinned CPython 3.13.15: 2,336 passed, 7 skipped, 134 subtests, 1,967.56 seconds.
Original budgets, assertions and job limits are unchanged.
[Initial attempt evidence](benchmarks/gate-release-0.4.7-formal-attempt-45cec40.json)
preserves the failure and retry decision.

[Final completion evidence](benchmarks/gate-release-0.4.7-formal-completion-45cec40.json)
records actual downloads of all eleven assets, exact names/sizes/API digests
and SHA256SUMS, five native BUILD-INFO inventories and static lists, SPDX SBOMs,
Compose inventory and both offline Core blob identities. Each native contains
115 Console and 3 OAuth files. Linux/macOS bytes match the fresh Linux build.
Windows has four text hashes affected by CRLF checkout and Vite HTML whitespace;
a fresh CRLF checkout and Vite build matches all 118 Windows paths and hashes
exactly. This reference ran on Linux and is not a Windows runtime test. The
initial verifier's incorrect cross-platform reference and correction are
retained; each asset was downloaded once.

The downloaded Linux x86_64 SHA-256 is
`be4d4b52c4074da76f49bb2b8fe52d66a2853ad2fd6172c508ba454991adee80`.
Six entry checks and six worker lifecycle cases passed against these frozen
bytes, including deadline/cancellation, reuse and child reap. The parent is
installed candidate-wheel Python launching the formal native worker, not a
test of the entire frozen application parent chain. Hosted native readiness,
Linux glibc checks, Intel macOS OpenSSL isolation, Compose validation, both Core
critical-vulnerability scans and offline load smoke all succeeded.

The publisher verified immutability and all eleven mandatory source/workflow
attestations with trusted timestamps before updating Docker Hub latest.
Optional environment-key OCI signing was unconfigured and skipped; mandatory
asset attestations are recorded separately. Published title/bilingual notes
match the source. Real nx5/x16, Podman provisioning and real OAuth-client
acceptance remain outside these cloud receipts.

## Integrated branch cleanup

At 2026-10-10 06:59:59 UTC, eight branch heads whose exact remote SHAs were
ancestors of the released main were deleted in one atomic operation with
separate expected-SHA leases. Their commits remain reachable from main.
Ten branches with unique content, including release evidence and the isolated
UI alignment change, were preserved. All other remote refs, main and
v0.4.5/v0.4.6/v0.4.7 tags matched the preflight snapshot exactly; no release
assets changed. [Cleanup receipt](benchmarks/gate-integrated-branch-cleanup-45cec40.json)
lists every deleted and preserved head. The UI change is separate from these
immutable assets and still awaits independent design review.

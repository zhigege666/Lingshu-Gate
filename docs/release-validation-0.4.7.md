# 0.4.7 candidate and publication validation

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
is still running at this source capture and remains a separate acceptance gate.

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

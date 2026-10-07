# 0.4.5 candidate validation and release gates

[简体中文](zh-CN/release-validation-0.4.5.md) · [Release guide](releases.md) · [Release summary](../packaging/release-notes.md)

This candidate starts from exact main `8941738096ab69c0b9fa014f39ff9749cca64822`, which normally merged the root-entry and dependency PRs. Its only runtime change is the single source version to 0.4.5; Vite 8/Rolldown, `mangle: false` on both entries and Console `base: "/"` remain unchanged. The working tree at the earlier root-entry checkout had no unique tracked or untracked changes; that checkout and its old packages are retained separately.

## Candidate checks

The candidate is being validated before owner review. Executed results, exact source/CI checkout SHAs, fresh static inventories, archive hashes and cleanup evidence will be added after each check completes. Unexecuted checks are pending, not passes. The parent-reported main CI checkpoint is [37651915688](https://github.com/zhigege666/Lingshu-Gate/actions/runs/37651915688); it is baseline evidence, not a rerun on this version candidate.

All local services use newly created synthetic data/config/workspace directories and loopback listeners. Existing databases, keys, MCP auto-start configurations and nx5 services are outside this run. Local build artifacts must record their own actual build commit; earlier 6663203/63e31a9 artifacts cannot represent this combined tree.

## Blocking and separate scope

Candidate acceptance is blocked by any failed required frozen dependency/source check, frontend check/unit/build, backend suite, root real-HTTP/browser check, static inventory/RECORD validation, Linux native build/extraction/readiness/worker check or its cleanup. The candidate PR must also pass the actual multi-platform native, Compose and container-contract jobs on its own exact checkout; conditional skips must be listed.

Formal publication remains owner-controlled. A version change pushed to main automatically creates a tag and dispatches the release workflow. Owner acceptance and the complete formal tag workflow are required: every mandatory quality/native/Compose/offline-image/container job, 11 exact assets, aggregate checksums, inner inventories, SBOM, exact source/workflow provenance and published title/body readback. PR artifacts are not formal assets; tag-only jobs skipped on PR remain a formal-release gate.

The cancelled nx5 service-configuration read has not been reauthorized. No SSH, existing-service switch or nx5 acceptance is performed by this candidate work. Real Podman readiness/provisioning, ChatGPT OAuth client and multi-machine integration remain unverified, with optional execution/OAuth defaults unchanged. They do not block preparing this isolated version/package PR, and the release makes no claim that these integrations passed.

The parent-reported PR49 default browser checkpoint was 475 total: 418 passed, 55 skipped, 2 failed. Its optional checkpoint was 27 passed, 3 skipped, 7 failed. These are historical failures, not passes; their attribution to the toolchain or old product code is unproven. This candidate validates the required root/smoke scope and does not claim a clean whole-site or optional browser suite. The owner must explicitly consider that residual scope when accepting the release; required current failures cannot be relabelled as historical or waived by this record.

## Upgrade boundary

The no-new-migration comparison for the root-entry change covered already integrated be30-to-6663203 source. Upgrading from published v0.4.4 to this combined source also includes tool-catalog/group migrations. Preserve configuration/data/credential/signing keys, use a consistent backup and retain one SQLite writer and the prior package.

Historical benchmark records, screenshots and release tags retain their original versions and provenance. The package version is dynamic in pyproject, and the lockfile's third-party `typing-inspection==0.4.4` is not the Gate version; no global version substitution is required.

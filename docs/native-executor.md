# Native isolated delivery executor

[简体中文](zh-CN/native-executor.md) · [Git/network contract](git-import-network.md) · [Rollout decision](git-executor-decision.md)

This development branch implements an optional Native/Linux adapter. It uses local rootless Podman, an already loaded administrator-reviewed image selected by its full manifest digest, a durable single-owner job journal, and trusted HTTPS acquisition. It reuses Gate's GitImport, ProjectUpload, BuildPlan and BuildDeploy coordinators. It adds no Core engine access, remote worker, stdio bridge, deployment service or automatic image pull. The release version remains 0.4.4; this is unreleased development work.

## Provisioning contract

Provisioning belongs to the host administrator and is separate from code development. No host daemon, mount, network policy, credential or production project was provisioned by these tests.

Run the Native Gate process under a dedicated non-root Linux account. That same trusted account owns the local engine, journal and cache; project containers receive none of its home, Gate data/configuration, credentials, sockets or engine storage. Keep the executor root separate from Gate's data, configuration and project workspace. Provision its root and `workspaces` subdirectory as owned, non-linked mode 0700 directories. The `workspaces` directory must be an actual separate `tmpfs` mount with `nodev,nosuid` and total capacity at most 2 GiB. A regular host directory or a free-space estimate does not satisfy readiness. Journal and verified tools remain on persistent storage outside that tmpfs. The cache retains at most four verified distributions; each extraction is limited to 200 MiB/4,000 entries. Reaching cache capacity requires administrator eviction, never automatic substitution.

The selected local Podman binary must be an administrator-reviewed absolute executable path without group/world write permission. Rootless user mapping, cgroup v2 and delegated CPU, memory and pids controllers are mandatory. Gate forces local CLI mode and uses no engine API socket. Its subprocesses invoke only compiled Podman operations, never a host project command or shell.

Compiled create flags ignore image volumes, clear default image/engine environment, disable implicit writable tmpfs, restart policy and image health commands. Before start, Gate matches observed container ID/job label and every actual content bind source/destination/write permission against its compiled mounts. Unexpected engine-configured mounts reject execution before any process starts. Identity mismatch retains an unknown job without killing or deleting the mismatched resource.

The image must already exist under the exact `registry/name@sha256:<64 lowercase hexadecimal digits>` RepoDigest. No tags, floating latest or automatic pulls are accepted. The reviewed image must provide `/usr/bin/python3`, `/usr/bin/git` with collision-aware SHA-1 decoding, and `/usr/local/bin/node`; it must contain no secret or unreviewed startup code. The container entrypoint is replaced with Gate's fixed read-only runner. Node must satisfy the requested distribution's exact official engines (including pnpm 11's additional >=22.13 requirement). Gate never upgrades Node. The [image contract recipe](../packaging/native-executor/Containerfile) takes a previously reviewed base; it installs or downloads nothing.

Set `LINGSHU_GATE_RUNTIME_ROLE=local`. Configure `LINGSHU_GATE_NATIVE_EXECUTOR` as a JSON object with:

| Field | Meaning |
|---|---|
| `enabled` | Boolean, default false. Explicit enablement permits startup reconciliation and a synthetic sandbox self-test. |
| `root` | Absolute provisioned executor directory, separate from Gate data/config/workspace. |
| `image` | Exact already loaded reviewed manifest digest; never a project input. |
| `podman_bin` | Administrator binary path, default `/usr/bin/podman`. |
| `proxy_hosts` | At most 32 exact reviewed proxy host/port rules with optional explicit private CIDRs. Default empty. |

An example configuration shape is below. Replace the placeholder with the reviewed digest; it is deliberately not a runnable image reference.

```json
{
  "enabled": true,
  "root": "/var/lib/lingshu-gate-executor",
  "image": "registry.example.invalid/gate-executor@sha256:<reviewed-64-hex-digest>",
  "podman_bin": "/usr/bin/podman",
  "proxy_hosts": [
    {"host": "proxy.example.invalid", "port": 8080, "private_cidrs": []}
  ]
}
```

Gate's Network settings response now reports observed `executor.available`, a stable code, exact missing conditions and the bounded support matrix. Startup checks account/directory/engine/image prerequisites, then actually observes distinct user/mount/PID/network namespaces, read-only roots and runner/cgroup mounts, no capabilities, no-new-privileges, no network interfaces beyond loopback, and applied CPU/memory/pids limits. The self-test leaves an independent descendant alive; readiness succeeds only after the entire observed sandbox cgroup is empty. Merely finding Podman on PATH or declaring capabilities does not enable execution. Failure never dispatches a host fallback. A Core configuration does not even construct or probe the engine.

Missing controllers are named separately (`delegated_cgroup_controller_cpu_required`, `delegated_cgroup_controller_memory_required`, `delegated_cgroup_controller_pids_required`). A missing local image reports `preloaded_exact_image_digest_required`; each failed sandbox observation reports `sandbox_selftest_<check>_required`. These checks never trigger a pull or host fallback.

## Acquisition and package support

| Phase | Implemented support | Explicit rejection |
|---|---|---|
| Git | HTTPS smart protocol v0/v1, SHA-1 full commit, exact branch/tag advertisement, shallow exact commit fetch, isolated strict Git pack decoding, verified raw object export | SSH, helpers, redirects, hooks/filters, submodules/LFS, SHA-256 repositories, unsupported protocols |
| Proxy | HTTP CONNECT, SOCKS5 and SOCKS5H, with numeric validated upstream IP and TLS SNI/certificate verification | HTTPS proxy transport; unreviewed proxy host/port; remote proxy DNS selection; direct fallback |
| Tool preparation | Exact official npm 9–11, pnpm 8–11 and Yarn Classic 1.22 distribution, official SHA-512 metadata and optional declared integrity, bounded link-free extraction, actual CLI/Node probe | Missing/unknown metadata, engine mismatch, changed cache, tool lifecycle, Corepack/global install/Node bootstrap |
| Dependency install | Registry-only npm lock v2/v3; pnpm 8/9 matching lock + official v3 store; Yarn Classic 1.22 v1 lock + official offline mirror/cache; strong pinned SRI, bounded acquisition and frozen offline install | pnpm 10/11 package-ID store, Berry, workspaces/link/patch/override/bundled dependencies, Git/file/alias/custom-origin sources, weak/missing integrity and project rc/hook files |
| Python | Existing upload/direct `requirements.txt` legacy flow outside this adapter | Git/profile Python sandbox installation, Poetry/uv/bootstrap; no new Python cache adapter |
| Build | The selected verified npm/pnpm/Yarn `run build` in a secret-free offline sandbox, including build-only projects with already sufficient source | Arbitrary commands, paths/images, online fallback, unplanned manager/Node downloads |

The broader existing manager matrix describes source and plan formats. It is not a claim that every manager's cache install works in this adapter. Unsupported install commands are visibly blocked at planning/queueing. Other unsupported npm cache shapes are rejected before dependency acquisition. A chosen manager is never replaced with npm. Multiple locks keep the existing exact `packageManager`/saved override and native shrinkwrap precedence rules.

Tool cache identity binds the official distribution bytes, version and SRI. Each project's optional declared hash is checked independently against verified archive hashes; absence, case-equivalent hashes and different supported algorithms do not bind another project's pin to the cache. Incorrect request pins fail before the CLI probe.

Gate adds fingerprinted read-only `/tool/shims` launchers binding the selected manager directly to `/usr/local/bin/node` and its verified CLI, including nested script invocations. Image-global alternative managers/Corepack are denied. `npx`/`pnpx` execute only an existing contained project binary, never download or automatically install packages. The operator-only `test_native_executor_host_acceptance.py` exercises actual nested npm and missing/existing npx, plus Yarn Classic/pnpm 8–9 verified caches, frozen offline installation, nested builds and missing-closure rejection under this adapter when `LINGSHU_GATE_TEST_EXECUTOR_ROOT` and `LINGSHU_GATE_TEST_EXECUTOR_IMAGE` identify an already provisioned reviewed sandbox; it provisions nothing and is skipped in the cloud environment.

Git and install selections remain independent immutable `inherit`/`direct`/`profile` resolutions in the original digest-bound plan. Every target DNS address must meet its host/port/private-CIDR rule; a mixed public/forbidden response is rejected. The connected address is numeric, with original-host TLS SNI. HTTP CONNECT and SOCKS also receive that numeric upstream, so a proxy cannot choose a different DNS result. Each proxy endpoint must separately match an administrator-reviewed host rule. Git credentials containing `username:token` use origin-bound HTTP Basic (appropriate for smart Git hosts requiring Basic); token-only values use Bearer. Registry credentials use origin-bound Bearer. HTTP/SOCKS proxy authentication references use `username:password`. Proxy credentials never reach the upstream TLS request, and mirror registry credentials never reach official metadata.

Snapshot and artifact scans include each Basic token/proxy password component, its URL/base64 encodings and the full authentication material. Public usernames alone are not treated as secret. Short secret components are still scanned; broad rejection returns the same bounded failure instead of silently omitting them. This also rejects an authorized endpoint reflecting a bare token into Git content.

HTTPS rejects redirects and encoded responses, bounds headers/body/deadlines, has no automatic retry and ignores environment proxy settings. DNS has a single bounded outstanding resolver slot. A timed-out resolver that has not actually exited is an unknown outcome, blocks network readiness, and cannot be reported as confirmed cancellation. Cancellation closes trusted sockets; project execution starts only with verified, secret-free content.

Persistent `unknown` jobs independently block readiness (`job_reconciliation_required`), even after `dns_busy` clears. Only a DNS interruption with live-process evidence of the exact worker's exit and its acquisition caller's completion qualifies for automatic reconciliation. An idle readiness check or the next admission takes the same exclusive admission gate, reconciles resources and all retained cleanup before reporting available or creating any new job. The interrupted acquisition stays `interrupted_terminated`; its key is never rerun. Generic unknown/stale rows or lost worker evidence require restart reconciliation. Live consumers prevent input/cache removal; every pending resource is inspected before any workspace is deleted. Concurrent observers report `job_reconciliation_in_progress` until cleanup finishes; any recovery/cleanup failure reports `job_reconciliation_incomplete` and continues blocking admission. Shutdown retains the journal owner and unknown inputs while a recorded DNS worker is still alive.

One socket supervisor owns the original deadline across TCP connect, proxy negotiation, explicit TLS handshake, send and response. Every stage recomputes the remaining budget; cancellation after a handshake is checked before constructing/sending origin authentication. Connecting and handshaking sockets are registered before their blocking operations, so cancellation can close them throughout the request.

Trusted acquisition never executes project or dependency code. Git receives only a verified pack file in a network-disconnected sandbox; raw object export bypasses checkout, attributes and filters. Official tool extraction executes no lifecycle. npm cache seeding uses only the SRI-verified official npm cache library and verified blobs. Yarn receives a read-only, verified registry mirror, including checked legacy SHA-1 fragments when present; its fixed CLI performs an offline frozen install with `--ignore-scripts` into a seed manifest carrying only dependency requests. pnpm 8/9's official CLI adds verified local tarballs to its SHA-512-addressed v3 store and then proves the seed's offline frozen installation with hooks/scripts disabled. Seed project files/node_modules are removed before cache export. The original lock bytes remain unchanged and are rechecked after project installation. The project container then copies read-only source/tool/cache inputs into its bounded work directory. It has no proxy/auth environment, external network, inherited SSH agent or Gate socket/home. All project and dependency lifecycle scripts run there under the confirmed install/build scope.

pnpm 10/11 preparation and build-only execution remain available, but dependency installation returns `pnpm_cache_format_unsupported` before acquisition. Their indexes also bind a package ID, so local-file seeding cannot establish the same registry index without a separate reviewed adapter. This gap needs a versioned, integrity-bound registry-ID cache writer and actual offline frozen closure verification; fabricated store JSON or npm substitution is prohibited. The v3 workflow requires SHA-512, a matching single-project lock and no patches/overrides. Yarn requires bounded Classic v1 registry records with one strong SRI; both workflows reject aliases, custom registry path prefixes and incomplete/unsupported closures. Official cache semantics were checked against [Yarn Classic's exact tarball implementation](https://github.com/yarnpkg/yarn/blob/v1.22.22/src/fetchers/tarball-fetcher.js) and [pnpm 9.15.4's exact v3 index paths](https://github.com/pnpm/pnpm/blob/v9.15.4/store/cafs/src/getFilePathInCafs.ts).

## Journal, output and recovery

`jobs.sqlite3` uses FULL-synchronous transactions and an exclusive single-owner lease. Phase identity binds the persisted actor, import/build ID, operation/source/plan/network/lock digests, deadline and fixed image. A record exists before acquisition or container creation. Controller jobs record deterministic names, actual container IDs, observed cgroups and frozen output inventory digests. Requests cannot choose engine options, images, host paths or arbitrary commands. Duplicate phase keys never dispatch again; differing bindings return an idempotency conflict.

Cancel and timeout kill the whole sandbox and verify its cgroup is empty before output freezing. Lost state, missing cgroup observation or unconfirmed group termination records `unknown`, blocks readiness and retains reconciliation. Restart reconciles journal entries/container IDs before new dispatch. Old coordinator imports/builds become `interrupted`; `terminal=true` ends polling while `execution_state=unknown`, `execution_terminated=false` and `requires_reconciliation=true` preserve uncertainty. Interrupted builds cannot be cancelled successfully or deleted. No import/build/deploy/start automatically resumes.

Only frozen, bounded output reaches the existing source/artifact path. Inventories bind paths, types, modes, byte counts, file hashes and link targets. Export retains only contained relative package links, rejects external/cyclic/special entries and known secret values, and uses the existing 500 MiB/30,000-entry/30-second artifact bounds. Failure cannot publish a partial new artifact or replace an existing deployment. Operator reconciliation must inspect the retained coordinator operation and private job record; do not delete the journal or choose a new key as a retry shortcut.

The fixed PID 1 runner disables Linux dumpability before admitting project code; this prevents same-UID children from modifying its process through ptrace or `/proc` file descriptors. All content stages, including dependency archive/cache preparation, wait for a durably recorded cgroup observation and a fresh cancellation check, then finish with the engine-observed container exit code. A project-created `result.json` cannot establish success or end a running stage; shared result fields never supply the trusted script-stage manager/Node versions.

Frozen result, inventory, Git object and artifact reads use nonblocking/no-follow descriptors and `fstat` regular-file checks. Result JSON has an 8 KiB/one-second read budget; FIFO, device, directory, changed inode and oversized output fail before parsing. A rejected result records a confirmed failed phase and releases controller admission.

The journal separately persists `cleanup_state=pending/cleaned`. Confirmed cancellation, timeout and other failed phases remove their workspace before releasing admission; successful output is removed after consumption. Startup reconciles both unfinished execution and terminal leftover directories, so a crash after termination does not accumulate bounded tmpfs usage. Unknown execution retains its output and blocks readiness. Command cleanup failure releases the operation gate, remains pending and blocks readiness (`job_workspace_cleanup_incomplete`) until restart reconciliation succeeds. A missing consumer output directory does not establish that its container or cgroup stopped.

Git pack and dependency-tarball staging also live in journal-owned `workspaces/<job-name>/output`, under that same tmpfs quota. Allocation requires the already running acquisition row. After consumption, the phase's durable cleanup state is cleared; a process crash reconciles and cleans it without replaying acquisition. An unknown consumer retains the verified tarballs and seeded read-only cache as well as its own output until all resources are reconciled.

The existing confirmed local deployment/start/rollback path is unchanged. Prepared tools are not installed into the host runtime. A manager-based runtime still needs its separately reviewed administrator registry; direct Node entrypoints retain their existing runtime rules. Build isolation does not change the existing unsandboxed Native managed-process runtime or add Core delivery/start support.

## Evidence and remaining acceptance

The synthetic suite exercises the real HTTPS framing/policy, raw-object verification, official extraction/cache logic, GitImport/BuildDeploy chain for npm/pnpm 8–9/Yarn Classic, idempotency, secret/link/changed-lock rejection, whole-group cancellation/timeout/unknown/restart semantics and Core guard using fixture sockets and engines. It executes no user repository, proxy, credentials or project scripts. Full physical Podman namespaces/controllers, live Git HTTP negotiation, actual npm/pnpm/Yarn offline cache/install behavior, manager distribution probes and a malicious lifecycle on a reviewed host remain separate untested acceptance items. The Native-only, Core-gateway stage does not complete the Docker user delivery/build/deploy/start chain. Refer to the branch's commit/check report for actual counts; synthetic success is not real host acceptance.

Podman flag and rootless semantics were checked against [the official run documentation](https://docs.podman.io/en/latest/markdown/podman-run.1.html). Host controller delegation and sandbox termination still require the observed self-test and operator acceptance.

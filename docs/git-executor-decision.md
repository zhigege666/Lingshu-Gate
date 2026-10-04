# Git execution gap and rollout decision

[简体中文](zh-CN/git-executor-decision.md) · [Git/network contract](git-import-network.md)

This is not an installed executor or evidence of isolation. The unreleased source acquisition/validation module is implemented against a trusted backend contract, but the production Git transport/isolation adapter and isolation runtime are still missing. Installing Git, pnpm or Docker beside the current Gate process does not resolve the gap.

The first stage concerns Git acquisition and offline dependency/build contracts only, with Linux rootless OCI selected as the first isolation backend. A remote MCP runtime, stdio bridge or new deployment system is outside that scope and requires a separate explicit decision. The broader runtime discussion below identifies a possible future gap; it authorizes no implementation. Existing local runtime tool pin fixes do not add a worker.

## First acquisition/validation slice (unreleased)

`ports/git_acquisition.py:TrustedGitBackend` supplies only bounded safe-ref resolution and exact-commit object access. It is a contract, not a Git transport, pack decoder or CLI implementation. `git_acquisition.py:VerifiedGitAcquisition` consumes that contract, verifies raw SHA-1 commit/tree/blob headers, lengths and object hashes, and produces `VerifiedSourceSnapshot`. The current repository contract remains full lowercase 40-hex SHA-1 IDs; SHA-256 repositories are explicitly unsupported and are never converted. The compatibility hash check is not a SHA-1 collision detector; collision-aware Git decoding is required from the future reviewed backend. A moving branch/tag is not resolved again during acquisition.

All root-tree descendants are checked, including outside the selected project. Source export reads raw objects without checkout, hooks, filters, submodule/LFS acquisition or attribute-based substitutions/omissions. Symlinks, gitlinks/submodule configuration, LFS pointers, ambiguous/unsafe paths, sensitive paths and detected credentials fail with explicit reasons. Valid source bytes retain the existing ZIP interface and Core inventory/upload verification. Content scanning is a bounded heuristic; it cannot certify that unknown or obfuscated secrets are absent.

Limits are enforced before object reads and while parsing/copying: 10,000 object reads/tree entries, 64 KiB commit metadata, 4 MiB per tree, 216 MiB total expanded object bytes, 3,000 source files, 200 MiB expanded source, 50 MiB ZIP output and 64 KiB read chunks. Resolution/fetch/export have 15/120/30-second ceilings, zero retries and checked monotonic deadlines. The future transport must independently enforce the 50 MiB compressed transfer ceiling while receiving/decoding; no real transport is present to demonstrate that guarantee. Requests can tighten these bounds but cannot relax them. ZIP entry content is also scanned incrementally across chunk boundaries.

`ExecutorReadiness` requires observed Linux/rootless, namespace, delegated CPU/memory/pids controller and whole-group termination evidence, plus phase-specific network evidence. A CLI or capability set is insufficient. The source-only adapter cannot satisfy `SafeNetworkExecutor`; production composition still supplies no executor and settings still report unavailable. Scanner cancellation is an unknown outcome unless trusted backend cleanup confirms whole-group termination. Uncertain completion never publishes a snapshot.

`offline_build_contract.py` defines immutable normalized dependency nodes, complete-root/edge closure checks, exact HTTPS origin binding, explicit SHA-256/384/512 SRI and bounded streamed content verification. It does not parse npm/pnpm/Yarn lockfiles or prove that a producer included every lockfile dependency; those full-graph adapters remain missing. Missing/weak/ambiguous integrity and unreviewed Git/file/link sources are rejected without rewriting. No dependency downloader, cache installer or lifecycle executor is implemented.

`OfflineBuildRequest` carries source/inventory/tool/graph/cache digests, bounded command/resource limits and a small non-network environment allowlist. It has no credential material, proxy, live registry, image selection or host path. Actual disconnected network-namespace evidence is mandatory even for commands using `--offline`. The existing safe build coordinator is unchanged and is not wired to this future contract yet; removing material from its eventual offline dispatch remains follow-up work.

Synthetic object/graph/worker fixtures exercise these validators without Git, network, containers, image/tool downloads, SSH or real credentials. They are module validation, not Git networking or offline installation/build acceptance. A read-only development preflight found Docker/runc CLIs but a read-only cgroup v2 mount without writable delegation/termination controls; rootless OCI could not be accepted. No backend is injected.

## Current execution trace

| Code | Actual behavior / missing work |
|---|---|
| `config.py:Settings.runtime_role` | Native default is `local`; only `local`/`core` are accepted. No worker connection configuration. |
| `compose.yaml`, `compose.prod.yaml`, Dockerfile `core` | Default Docker role is `core`: UID 10001, read-only root/workspace, no engine socket, no Git/Node build tools. This deployment is a control plane/external HTTP MCP gateway. |
| `build_deploy.py:BuildDeployStore._require_local_execution` | Builds/deploy/rollback require `local`. Injecting the new port alone cannot enable Core delivery. |
| `build_deploy.py:build_upload`, `_run_build_job`, `_execute_plan_dag`, `_run_single_step` | Existing queue/IR/coordinator/persistence. Safe plans dispatch to an optional port; legacy direct plans use `_run_command`. Preserve this chain. |
| `build_deploy.py:_build_subprocess_environment`, `_run_command` | Dedicated directories, clean environment, host `subprocess.Popen`, bounded output/time, process-group termination. No filesystem/network/cgroup isolation; descendants can escape a process group. |
| `ports/safe_network_executor.py:SafeNetworkExecutor` | Five methods are Protocol-only: `resolve_commit`, `export_snapshot`, `probe`, `prepare_package_manager`, `run_command`. Concrete implementations are missing. |
| `git_acquisition.py`, `ports/git_acquisition.py`, `offline_build_contract.py` | Bounded raw-object export and normalized graph/offline-request validators exist; trusted transport, full lock graph adapters, cache installation and the real offline worker do not. |
| `main.py:create_app` | Neither BuildDeployStore nor GitImportService receives an executor. Factory, configuration, readiness and lifecycle are missing. |
| `git_import_mcp.py:GitImportService._executor` | Core is blocked by role; native by missing adapter. |
| `network_settings.py:NetworkSettingsStore.settings` | Availability is hardcoded false; must use real trusted adapter readiness. |
| `build_plan.py:finalize_manifest` | Produces a local `managed_process` manifest and artifact path; no remote artifact/runtime target. |
| `mcp_runtime.py:McpRuntimeManager.start_server` | Core refuses managed processes/containers; supports external HTTP MCP. Remote build success is not deploy/start support. |
| `mcp_container.py:build_docker_command` | Existing managed containers have no network, read-only roots/mounts. This is not an install/build sandbox; its baseline must remain intact. |

Native/local can still build trusted uploaded projects when Node/Python and a supported matching manager are present and the plan does not require the new safe port. That is not isolation for untrusted Git. Git acquisition, controlled probes, configured egress and tool bootstrap have no production implementation in either deployment. Default Core cannot build/deploy/start local uploaded code independently of this change. The functional goal is not complete.

## Required scope decision

| Scope | Code | Infrastructure and cost | Result |
|---|---|---|---|
| Native/local first | Concrete isolated adapter, trusted fetch/egress, verified tool cache, factory/readiness/lifecycle | Dedicated Linux execution account/host, reviewed pinned images, rootless engine with verified namespaces/resource controllers, separate workspace/cache | Existing local deploy/start retained. Docker Core stays gateway-only; Windows/macOS need an explicit Linux executor host. |
| Default Core + remote worker | Above plus authenticated phase RPC, source/artifact transfer, durable operation reconciliation, remote deployment/start target | Independently operated worker service outside Core, mTLS/trust/secret provisioning, image/cache upkeep, quotas/monitoring | Core coordinates the full chain without running project code or controlling an engine. |
| Dedicated VM worker | Same remote phase/journal/digest contracts, with an operator-provisioned disposable VM boundary for build jobs | VM images, VM lifecycle/quotas, verified guest isolation, controlled egress and cleanup; greater provisioning cost | An additional deployment option for stronger host separation; not a third host-shell fallback or an implemented adapter. |

The first isolation backend is Linux rootless OCI. If the default Docker product must offer the full chain, remote-worker scope still needs a separate decision; current in-process `cwd`/result ports and local guards cannot represent remote artifacts and runtime targets. No daemon, engine exposure, Core privilege, service deployment or real credential has been added.

## Proposed safety boundary

Core remains the single authoritative SQLite writer and existing Project Delivery coordinator. It retains actor/permissions, confirmation, source/plan/config digests, idempotency, pinned profile versions and deployment records. The worker executes a validated phase; it does not create a parallel delivery workflow. Requests cannot select arbitrary host paths, images, commands, credentials or probe URLs. Network secrets go only through an approved authenticated channel to trusted fetch/egress code, never project code, public replies, logs or artifacts.

The worker runs outside Core under a dedicated account. Only that account can reach the reviewed engine; neither Core nor project containers can. Jobs use preloaded digest-pinned images with no automatic pull, separate PID/mount/user namespaces, dropped capabilities, no privilege escalation, immutable tool roots, bounded workspace/tmp and verified resource controllers. No Gate data/config/keys, host sockets/home or engine control is mounted. Readiness verifies actual prerequisites; unsupported hosts return precise unmet conditions. A container command alone is not sufficient evidence.

Controlled dependency egress is the hardest gap. A bridge plus HTTP_PROXY does not enforce DNS/redirect/origin policy or protect authentication from lifecycle code. Proposed trusted fetch/cache code owns upstream proxy values and origin credentials. Git and exact official tool distributions run there without source hooks/filters. Dependency acquisition executes no project hook; pnpm hooks, alternate tool/bootstrap and other code during resolution must be disabled or rejected. Verified cache is then exposed without secrets for frozen install/build. Unplanned lifecycle network fetches fail. Network-dependent scripts/custom registry flows require separately reviewed egress/origin policy; proxy selection does not imply their support. All claimed frozen npm/pnpm/Yarn cache workflows need verification.

Every phase binds actor/operation ID, source/plan/network digest, pinned revisions, limits, deadline and phase idempotency key. A durable worker journal maps the key to exactly one sandbox and output digest. Uncertain completion triggers status lookup, never blind write replay. Cancel/timeout stops the entire sandbox/cgroup and all writers before freezing output. Restart reconciles journals/container IDs before accepting duplicates. Unknown outcomes stay blocked.

Bounded, digest/inventory-bound streams transfer sources/artifacts; worker paths are never trusted. Core revalidates output and writes a new artifact. Failure never replaces an active deployment. Remote deploy/start requires a separate immutable target/generation CAS. A stdio project needs an authenticated HTTP bridge on the worker; Core connects as external Streamable HTTP, not a worker-local managed process. Existing grants/classification/user-credential semantics remain. Runtime does not inherit delivery proxies, and updates may interrupt sessions.

## Implementation after decision

1. Implement strict configuration, readiness and phase/source/artifact contracts; wire a real factory. Keep legacy local behavior and Core host-execution guards.
2. Implement concrete bounded TLS/DNS/redirect Git/probe/official-tool acquisition, immutable cache and isolated frozen install/build; add offline transport/container/journal tests. Distinguish missing code/configuration from missing runtime prerequisites.
3. For Core scope, extend the existing coordinator with remote artifact/target operations. Only verified remote dispatch may pass the execution decision; host fallback stays prohibited. Retain separate confirmed deploy/start/rollback.
4. Document operator-reviewed images/service provisioning. The first slice remains local code/fixtures only: no daemon/engine/network service/Git/install/deploy runs.
5. Later acceptance must verify real namespaces/controllers, DNS/proxy credentials, source fidelity, tool integrity, every supported lock workflow, malicious lifecycle confinement, timeout/cancel/restart, old deployment/rollback and bilingual desktop layout.

The proposed runtime prerequisites draw on [Podman run documentation](https://docs.podman.io/en/latest/markdown/podman-run.1.html) and [Docker rootless resource limits](https://docs.docker.com/engine/security/rootless/tips/#limiting-resources). Namespace/network options and host controller delegation require actual verification; these references do not demonstrate a working sandbox in this branch.

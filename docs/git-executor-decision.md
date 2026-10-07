# Git executor implementation and rollout decision

[简体中文](zh-CN/git-executor-decision.md) · [Git/network contract](git-import-network.md) · [Native provisioning](native-executor.md)

The selected scope is **Native/Linux first**. This development branch implements trusted HTTPS acquisition plus a concrete local rootless Podman adapter. It reuses the existing plans, confirmation/digest/idempotency checks, GitImport/ProjectUpload and BuildDeploy chain. The Native adapter is optional and defaults to disabled; an administrator must provision and review its prerequisites. Actual host acceptance remains untested. The source version stays 0.4.4; no release, tag or merge is part of this work.

Core remains an unprivileged gateway and authoritative single SQLite coordinator. It does not construct an engine adapter or access an engine/socket, execute local projects, prepare host tools, deploy a remote runtime or bridge stdio. Core network readiness explicitly reports `core_gateway_only_native_delivery_disabled`. Native build success does not add Core deployment/start support.

## Code now present

| Area | Implementation |
|---|---|
| `native_executor_config.py`, `adapters/safe_network_factory.py` | Strict administrator-only digest/root/binary/proxy policy; Linux/local-only factory before engine imports. |
| `main.py`, `network_settings.py` | Same adapter injected into GitImport and BuildDeploy, observed readiness, startup reconciliation/self-test and shutdown admission closure. |
| `adapters/native_executor/controller.py`, `journal.py` | Fixed local Podman argv, pinned preloaded image, actual namespace/controller checks, bounded tmpfs, durable phase/resource records, whole-cgroup stop and unknown blocking. |
| `adapters/native_executor/https.py`, `git.py`, `git_acquisition.py` | Bounded TLS/validated numeric DNS/proxy connects, smart HTTPS exact fetch, offline strict pack decode, hash-bound raw object export without checkout. |
| `adapters/native_executor/packages.py`, `runner.py` | Official exact npm/pnpm/Yarn preparation and integrity/engines verification; npm/pnpm 8–9/Yarn Classic registry caches followed by secret-free frozen offline install/build. |
| `build_deploy.py`, `git_import_mcp.py` | Existing coordinator and artifact path retained; persisted actor/source/plan/network phase bindings; interrupted outcomes cannot blind-replay or delete unknown resources. |

The old five-method protocol and capability names remain. Production composition now additionally requires real readiness; capability declarations do not suffice for the Native implementation. Factory/settings/lifecycle are no longer stubs. Historical raw-object/scanner/offline integrity validators were reused without unrelated Stage 1 changes.

## Bounded supported scope

Git supports HTTPS smart protocol v0/v1 and SHA-1 exact commits with no hooks/helpers/checkout/submodules/LFS/redirects. Selected HTTP CONNECT/SOCKS proxies receive validated numeric upstream IPs, with original-host TLS verification. Unsupported HTTPS proxy transport fails explicitly. Proxy host policy is separate from Git host policy, and Git/install selections keep immutable independent revisions.

Official pinned npm/pnpm/Yarn tools can be prepared without Corepack or global installation. Reviewed registry workflows use npm lock v2/v3, pnpm 8/9 v3 stores and Yarn Classic 1.22 mirrors with strong pinned integrity, bounded content and official offline closure verification. pnpm 10/11 package-ID stores, Berry, Python sandbox caches, workspaces/link/bundled/custom/Git/file sources and project rc/hooks are explicitly refused. Python remains legacy upload/direct-only outside this adapter. There is no manager/version/network fallback. The selected verified Node manager can execute its confirmed build script offline.

Project code receives only read-only verified source/tools/cache plus a bounded writable work directory, no network/secret/engine mounts. Output is frozen only after whole-group termination and revalidated through the existing bounded artifact boundary. The durable journal binds phase identity to exactly one sandbox; restart/cancel/timeout preserve unknown outcomes and never automatically replay writes. Independent deployment/start/overwrite/rollback boundaries remain.

## Administrator acceptance still required

The code is implemented; provisioning and real acceptance are separate. A reviewed preloaded image, dedicated non-root Native account, actual delegated cgroup v2 CPU/memory/pids controls and an owned bounded tmpfs mount are prerequisites. Missing namespaces/controllers/image/quota/journal ownership return actionable readiness reasons without host execution.

The cloud evidence is synthetic. Acceptance on the prepared host must still verify live HTTPS Git/credential/proxy fidelity, actual official manager versions and npm/pnpm/Yarn cache behavior, malicious lifecycle confinement, complete descendant termination, restart reconciliation, artifacts and existing deployment/rollback behavior. No production credentials, SSH, nx services, trust changes or host network provisioning were performed. See [the deployable Native contract](native-executor.md).

A future Core remote worker would need separate authenticated phase/artifact/runtime and remote deployment/stdio contracts. That remains outside this implementation and is not silently authorized by Native support.

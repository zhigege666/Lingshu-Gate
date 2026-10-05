# Gate feature integration candidate

[简体中文](zh-CN/gate-feature-integration.md) · [OAuth paging](oauth-catalog-scaling.md) · [Native executor](native-executor.md)

`test/gate-feature-integration-20261005` combines reviewed development inputs on exact main `d4786fd368e932bc758ea29da1a597c9d9551794`, version 0.4.4. It is an unreleased test candidate. Main, tags, deployment and host provisioning are outside this integration.

| Input | Exact source | Integration treatment |
|---|---|---|
| OAuth UI, saved-grant verification, candidate paging and public catalog/groups | `d8d4833bfdefbf7e679190565294f38f7a109145` | First parent of the ordinary three-way merge; its copied public `f51d1b18d7475034b61567be00ef999128918e83` / production `d99be556ff48e018792268abeb7c5a22c5517476` changes are already included |
| Native isolated acquisition/offline execution and security follow-ups | `76bfe2c4eeae7f1a693e1d86b03c78e6098866d1` | Second parent; all nineteen Native commits retained as actual ancestry |
| Public catalog final full-suite/package evidence | `6f3e87145a8ff581d8738ffbc3ee6f374ab56010` | Documentation/data-only cherry-pick; no repeated product patch |
| OAuth scope save response-loss recovery | `9af3ddb5f5d7699f3c2bfe408c4f09cf04861020` | Conflict-free cherry-pick as `a3b57f708ae3d848382e46ee9c9b85ccae8e5722`; all twelve changed blobs match the source |

The merge is `31f5195`; the documentation-only evidence copy is `a089dc2`. There is no ancestry-only merge or one-sided source replacement. The inputs change 151 and 54 paths respectively, with nine overlapping paths. The only textual conflicts are the English and Chinese CHANGELOG unreleased headings; both sets of entries are retained under one unreleased section. README, security guides, guide indexes and `main.py` merge automatically.

## Composition and safety review

The same application now constructs the shared catalog, explicit group router and OAuth candidate index alongside the Native factory. GitImport and BuildDeploy share the configured isolated executor and immutable network selections; group definitions retain their separate store and existing configuration service boundary. The Core role neither constructs nor starts the Native engine boundary, even when an enabled Native configuration is supplied.

The catalog/group migrations remain the OAuth input's unchanged 0012–0016 sequence. Native adds no competing Gate migration; its private job journal has a separate single-owner SQLite file. Existing configuration and runtime locks, immutable registry snapshots, selected-instance guards, current-authority checks, management-resource allowlists and direct MCP interfaces remain from their reviewed sources.

Combined lifespan tests expose and correct one interaction: an unknown Native close must not skip independent external-configuration/runtime shutdown. Those cleanups run in `finally`, while the Native error and retained journal lease remain intact. `gate.shutdown_complete` is emitted only after successful close; unknown work is not described as terminated. The new composition tests cover success, unknown close, Core exclusion and coexistence of the catalog/group migrations.

## Package-manager support

| Phase | Supported | Explicit limits |
|---|---|---|
| Official fixed tool preparation | npm 9–11, pnpm 8–11, Yarn Classic 1.22 with integrity/engine checks | No latest, global install, Corepack, automatic Node download or project-selected image |
| Frozen offline dependency install | npm registry locks v2/v3; pnpm 8/9 reviewed v3 stores; Yarn Classic 1.22 registry mirror/cache | pnpm 10/11 package-ID stores, Yarn Berry, workspaces/link/patch/Git/custom-origin/weak-integrity caches remain refused |
| Offline build | Selected verified npm/pnpm/Yarn `run build`, including supported build-only projects | No arbitrary command/path/image, network/secret inheritance or manager substitution |
| Python | Existing uploaded-project/direct legacy path outside Native | Git/profile-backed Python sandbox caches are unsupported |
| Docker Core | Existing gateway/catalog/OAuth/group control plane | No engine/socket, project execution, remote worker/deployment or stdio bridge |

## Validation contract

Final results must name the exact combined candidate SHA. Earlier input benchmarks, screenshots and full-suite counts remain historical evidence for their recorded source SHAs; they are not validation of this combined tree. Run frozen Python/npm preparation, Ruff, mypy, full backend, frontend type/UX checks, Vitest, both frontend builds, identity/version checks, Compose syntax and whitespace checks. Keep asset builds separate from backend/browser runs that read those assets.

Backend regressions include OAuth A/B, normal and management resources, direct MCP/HTTP compatibility, catalog/group authority and dispatch locks, configuration/runtime/migrations and the Native acquisition/journal/cleanup suite. Package validation must execute schema-validation subprocesses from the built wheel with the checkout absent from the import path, confirm deadline/cancellation children are reaped and import the Native modules from that same artifact. Linux frozen-worker checks and local synthetic browser checks are separate evidence where executed.

Real rootless Podman namespaces/controllers, reviewed image/cache behavior, credentials/providers/clients and nx5 deployment still need operator/root acceptance. The four opt-in Native host tests remain skipped without operator-provisioned prerequisites; they do not use a host-shell fallback. No integrated synthetic result completes the Docker user delivery/build/deploy/start chain.

## Recorded validation checkpoint

The initial combined production-source and complete-test checkpoint is **`31b7cca9155d36094250a47bc7f688797b8217a7`**. Evidence export `75a033881d19d5225c0adbc3cf2f4916822c6fbe` changes documentation only. The later OAuth recovery change has its separate frontend checkpoint below; the initial results remain bound to their recorded source. Version remains 0.4.4 and no production deployment is claimed.

| Check at the checkpoint | Result |
|---|---|
| Complete backend | 2,126 passed, 7 skipped, 0 failed; 954.48 seconds |
| Frontend | 439 Vitest cases in 74 files passed; frozen npm install, type/UX checks and Console/OAuth builds passed |
| Synthetic Chromium browser | 196 regular cases passed; the 11 initially skipped scale cases then passed with the 5,000-service/50,000-tool fixture enabled |
| Installed wheel and Linux frozen workers | 14 actual schema children reaped, including deadline/cancellation and subsequent reuse; 2 direct native entry probes and 6 installed-wheel Native module imports passed; checkout excluded |
| Static/repository checks | Ruff, mypy (158 source files), repository identity, version, Compose configuration and whitespace checks passed |

Repository evidence: [complete validation record](benchmarks/gate-feature-integration-validation-31b7cca.json), [merge/source blob provenance](benchmarks/gate-feature-integration-provenance-31b7cca.json), [wheel/frozen-worker observations and artifact checksums](benchmarks/gate-feature-integration-package-workers-31b7cca.json), and [complete backend output](benchmarks/gate-feature-integration-backend-31b7cca.log).

The exports retain the observed results and original runner-record hashes. Temporary absolute paths are replaced by named relative aliases; they describe imports and commands, rather than download links. This documentation export publishes no binaries. All inputs are synthetic and contain no real credentials. The seven backend skips are four operator-provisioned Podman cases and three fixed external Playwright MCP installation cases. These differ from the 207 executed Console/OAuth browser cases. Root independently reviewed the true merge ancestry, source blobs, teardown fix and migration/lock composition at the checkpoint with no new P1/P2 finding. Real host, credential/provider/client, release-package and nx5 acceptance remain outstanding.

## OAuth response-loss integration checkpoint

The subsequent combined production-source and frontend test checkpoint is **`a3b57f708ae3d848382e46ee9c9b85ccae8e5722`**, including the independently reviewed `9af3ddb` recovery fix. When a scope update commits but its response is lost, the Console retains the draft, marks the result unknown and blocks review/save. Explicit refresh reads the actual saved grant, current catalog and retained selection before unlocking; failed reads keep the lock. Old confirmations cannot be replayed, and a later edit requires a fresh confirmation at the actual revision. Quota drafts remain intact. See the [response-loss scenarios](oauth-catalog-scaling.md#committed-save-with-a-lost-response).

At this exact integrated checkpoint, frozen npm installation, frontend type/UX checks, all **439 Vitest cases in 74 files**, and both Console/OAuth builds passed. All **98 browser cases** in `oauth-grants`, `oauth-consent` and `oauth-paged-catalog` passed with the 5,000-service/50,000-tool fixture enabled, in **291.19 seconds**, with zero skips, failures, retries or flaky cases. Both real post-commit response-loss cases passed.

The backend result is inherited from `31b7cca`: **2,126 passed / 7 skipped**, without a new full-backend execution. Git tree records for `src/`, `tests/`, `scripts/`, Python dependency definitions/lock, and npm dependency definitions/lock are identical to that checkpoint. Prior wheel/frozen-worker observations retain their original source SHA and artifact hashes. The frontend checkpoint did not include package rebuilding; subsequent fresh package acceptance is recorded below.

Read the [integrated validation and all 98 case results](benchmarks/gate-feature-integration-validation-a3b57f7.json) and [input-blob/backend-inheritance proof](benchmarks/gate-feature-integration-provenance-a3b57f7.json). These records preserve parent/root's separate independent reviews of `31b7cca` composition and `9af3ddb` recovery, both with no new P1/P2 findings. A subsequent documentation export does not change the product or frontend checkpoint. Browser execution remains synthetic; real Podman, provider/client, nx5 and the full platform release matrix remain separate.

## Fresh wheel and Linux native package acceptance

Fresh version 0.4.4 candidates were built from **`ed34c5a474747b2f0933b8fbee7fccf193ee7315`**, which differs from tested product **`a3b57f708ae3d848382e46ee9c9b85ccae8e5722`** only in documentation. The standard native builder used fixed **CPython 3.13.15, Node 22.23.2 and PyInstaller 6.22.2**, frozen dependencies and the official Node archive checksum. It produced the full Linux x86_64 archive, launchers, BUILD-INFO, SPDX SBOM and third-party licenses. No release or deployment was performed.

| New artifact | SHA-256 | Bytes |
|---|---|---:|
| `lingshu_gate-0.4.4-py3-none-any.whl` | `023f39a0bbf3830d8e1a41280face4feb429e117679e07effe07603a2412c8d4` | 1,785,586 |
| `lingshu-gate-v0.4.4-linux-x86_64.tar.gz` | `314f6ff0c9b6d072c629e126875c02a20a23493efeffbf90cc5e3321ddd179ec` | 33,843,127 |

All **97 Console and 3 OAuth files** in the wheel, its isolated installation, and the strictly extracted native archive match the current dist and the `a3b57f7` browser-tested build byte for byte. The recovery chunk `external-connections-page-5G7cff7c.js` has SHA-256 `f590c4b7289fd21e299bdfb32cec47c25aa18c5e6a35798f02197ceaf3605c90`; both running packages served that exact content, including unknown-save and saved-revision readback code. Every wheel RECORD entry and all 453 native BUILD-INFO file records passed validation. The archive passed its checksum, bounded extraction and glibc 2.35 maximum checks; 200 SPDX packages and 196 third-party license records were included and checked as inventory.

The newly installed wheel and new native executable passed **14 actual schema child cases**, including deadline/cancellation/reaping and subsequent reuse, **2 native worker entry probes**, **6 Native module imports**, and **4 CLI version/help probes**. Both real package processes passed readiness/health and recovery-chunk HTTP checks and were stopped and reaped. OAuth stayed default-disabled with HTTP 404; native readiness smoke and final wheel/archive identity checks also passed. These isolated tests start no Podman engine or project job and use no real credentials.

The first wheel inventory was rejected for 141 stale Console and 2 stale OAuth files in ignored `build/lib`. Only that verified generated directory was cleared before rebuilding and reinstalling; final extra/missing files are zero. An initial offline dependency-resolution attempt lacked fixed `annotated-doc` metadata; exact exported versions were subsequently installed with hash verification. These preparation incidents and their resolution are recorded, without product-source changes.

Repository evidence: [new artifact hashes, toolchain and complete static-resource manifest](benchmarks/gate-feature-integration-packages-ed34c5a.json), [new wheel/native schema workers](benchmarks/gate-feature-integration-package-workers-ed34c5a.json), and [live package/CLI smoke](benchmarks/gate-feature-integration-package-http-smoke-ed34c5a.json). Candidate binaries and SHA256SUMS remain in the cloud's ignored `dist/candidates/ed34c5a`; this evidence export publishes no binaries. Full backend remains inherited from `31b7cca`. Real Podman, external Playwright MCP, provider/client, nx5, other platforms and the complete formal release matrix remain unverified.

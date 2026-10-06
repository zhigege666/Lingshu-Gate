# Catalog classification projection

[简体中文](zh-CN/catalog-classification-projection.md)

The development branch `test/gate-catalog-memory-20261006` starts at exact source `7d145c28a94a00a6c5d6f4f7d4fc38c0e6153436`. The change limits `AccessControlStore.visible_tool_contracts` to a directory-specific classification read. Group administration catalogs, variant member pages and on-demand group routing all share this projection.

The complete classification loader remains unchanged for synchronization, classification review, normal tool evaluation and OAuth snapshot consumers. Directory consumers need these ten columns: `server_id`, `tool_id`, `fingerprint`, `status`, `effective_access`, `reviewed_by`, `reviewed_at`, `destructive`, `idempotent`, `open_world`. The SQL query omits `evidence_json`, analysis/source fields, display names and creation/update timestamps. The fingerprint and reviewed safety fields remain necessary even when structural normalization is cached.

This changes row width only. The 250-tool batching, current user/grant/token/OAuth checks, fingerprint/publication checks and reviewed contract partitioning remain unchanged. The directory still authorizes the entire bounded candidate set before ordering and pagination. No authorization result is cached. Fifty thousand requested tools still require 200 classification SELECT statements; this work does not remove complete group snapshot construction.

The focused regression checkpoint passed 95 tests in 50.75 seconds: `test_catalog_classification_projection.py`, `test_mcp_group_cache_api.py`, `test_catalog_group_adapter.py` and `test_access_control.py`. A real HTTP catalog/variant test uses two 2 MiB synthetic evidence payloads and a SQLite column authorizer that rejects any classification column outside the ten-column set. It compares cold/warm responses to the original complete loader and verifies full synchronization still preserves the evidence. Twenty-five policy/review scenarios compare full-row and narrow-row contract projections; the multi-batch test covers 501 keys, duplicates and a missing key.

The production fix checkpoint is `93d70525e848a571c429ef80e77f5513640bceb4`. [Raw comparative measurements](benchmarks/catalog-classification-projection-5000-50000.json) contain four sequential, separate Linux processes with 5,000 service IDs and 50,000 classification/tool records. The baseline replays the unchanged complete loader from exact source `7d145c2`; all other projection and current-grant code is identical. Each stage has five ordinary warm latency samples and a separate tracemalloc allocation probe. Both modes return identical classification/policy digests, including 49,989 visible tools after a hidden service and an explicit tool-level `none` override.

| Synthetic evidence payload per row | Loader | Classification median / p95 ms | Classification allocation peak MiB | Policy projection median / p95 ms | Policy allocation peak MiB |
|---|---|---:|---:|---:|---:|
| 1 KiB | Complete, 18 columns | 485.163 / 500.562 | 116.99 | 720.222 / 732.491 | 128.72 |
| 1 KiB | Catalog, 10 columns | 292.721 / 302.221 | 40.69 | 548.533 / 552.283 | 52.42 |
| 8 KiB | Complete, 18 columns | 806.650 / 820.633 | 458.79 | 1177.183 / 1272.946 | 470.52 |
| 8 KiB | Catalog, 10 columns | 376.018 / 479.708 | 40.69 | 664.621 / 743.522 | 52.42 |

Reproduce each mode in its own process; repeat with `--evidence-bytes 8192`:

```bash
uv run --frozen python scripts/benchmark_catalog_classification_projection.py --mode complete --evidence-bytes 1024 --samples 5 --output complete.json
uv run --frozen python scripts/benchmark_catalog_classification_projection.py --mode catalog --evidence-bytes 1024 --samples 5 --output catalog.json
```

The measurements cover classification/policy projection, excluding file configuration and complete group snapshot construction. The Linux cgroup allowed 16 GiB memory and four CPU equivalents; this differs from nx5's acceptance environment. The four process-lifetime `ru_maxrss` values are 467,260 / 330,924 / 817,048 / 332,052 KiB in table order, including fixture preparation, all samples and allocation probes. They are not request RSS.

[Full HTTP scale evidence](benchmarks/catalog-classification-projection-directory-scale.json) records all three original cases, each in a separate pytest process. `test_mcp_group_catalog_scale.py` is byte-for-byte unchanged from exact baseline `7d145c2`. Each case retains 5 cold reads, 10 hot reads, 10 keyword catalog pages and 10 variant member pages, followed by the existing configuration-writer/changed-publication checks. The over-cache case also retains all 4 alternating reads and the original 64 MiB cache limit. All three cases passed with no threshold reductions or skips.

| Case | Total seconds | Cold p95 ms | Hot p95 ms | Catalog page p95 ms | Member page p95 ms | Process lifetime peak KiB |
|---|---:|---:|---:|---:|---:|---:|
| Five groups; 10,000 tools/request | 42.35 | 1535.286 | 823.255 | 840.527 | 811.377 | 820392 |
| Maximum single group; 50,000 tools/request | 122.44 | 7465.634 | 2669.541 | 2743.274 | 2546.592 | 820264 |
| Over cache; 50,000 tools/request | 171.43 | 11243.867 | 3250.854 | 2936.641 | 3296.626 | 820088 |

These are post-change whole HTTP measurements; the controlled before/after comparison above measures only classification/policy projection. The scale RSS values are cumulative per-process `ru_maxrss`, including the fixture and every request, not per-request peaks or cgroup `MemoryCurrent`. A reduction in classification allocations does not establish that a whole-suite cgroup OOM is fixed or that earlier cumulative RSS demonstrates a leak. No production connection, real credential, SSH, merge, tag or release is part of this work.

[Validation checkpoint](benchmarks/catalog-classification-projection-checks.json): a further 15 related files passed 259 tests in 349.00 seconds at `64140292520667b12aa39bbb9f0119737fc89ca0`, covering group catalog/routing/structures/authority, ordinary catalog dispatch/audit and complete classification/OAuth consumers. Together with the focused 95 and three isolated scale cases, this is 357 passing relevant tests, with no final failures, warnings or skips. Frozen dependency synchronization, whole-repository Ruff, mypy (158 source files), whitespace, paired links and raw JSON checks passed. No product/test file changed after production checkpoint `93d7052`; later commits contain the benchmark script and documentation/data. This is not a repeated complete backend suite, frontend/native acceptance or nx5 OOM reproduction. Neither the OAuth UI nor CLI repair branch was edited.

The first new multi-batch regression fixture omitted required classification fields; the initial benchmark fixture omitted required grant `created_by`. Both fixture setup errors were corrected before the passing regressions/formal measurements, without changing product behavior.

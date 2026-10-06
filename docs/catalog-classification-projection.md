# Catalog classification projection

[简体中文](zh-CN/catalog-classification-projection.md)

The development branch `test/gate-catalog-memory-20261006` starts at exact source `7d145c28a94a00a6c5d6f4f7d4fc38c0e6153436`. The change limits `AccessControlStore.visible_tool_contracts` to a directory-specific classification read. Group administration catalogs, variant member pages and on-demand group routing all share this projection.

The complete classification loader remains unchanged for synchronization, classification review, normal tool evaluation and OAuth snapshot consumers. Directory consumers need these ten columns: `server_id`, `tool_id`, `fingerprint`, `status`, `effective_access`, `reviewed_by`, `reviewed_at`, `destructive`, `idempotent`, `open_world`. The SQL query omits `evidence_json`, analysis/source fields, display names and creation/update timestamps. The fingerprint and reviewed safety fields remain necessary even when structural normalization is cached.

This changes row width only. The 250-tool batching, current user/grant/token/OAuth checks, fingerprint/publication checks and reviewed contract partitioning remain unchanged. The directory still authorizes the entire bounded candidate set before ordering and pagination. No authorization result is cached. Fifty thousand requested tools still require 200 classification SELECT statements; this work does not remove complete group snapshot construction.

The focused regression checkpoint passed 95 tests in 50.75 seconds: `test_catalog_classification_projection.py`, `test_mcp_group_cache_api.py`, `test_catalog_group_adapter.py` and `test_access_control.py`. A real HTTP catalog/variant test uses two 2 MiB synthetic evidence payloads and a SQLite column authorizer that rejects any classification column outside the ten-column set. It compares cold/warm responses to the original complete loader and verifies full synchronization still preserves the evidence. Twenty-five policy/review scenarios compare full-row and narrow-row contract projections; the multi-batch test covers 501 keys, duplicates and a missing key.

Scale and comparative measurement evidence will be recorded separately after execution. A reduction in classification allocations does not establish that a whole-suite cgroup OOM is fixed or that earlier cumulative RSS demonstrates a leak. No production connection, real credential, SSH, merge, tag or release is part of this work.

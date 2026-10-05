"""Actual directory reads: current policy, bounded work and concurrent writers."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from lingshu_gate.application import mcp_group_catalog as application
from lingshu_gate.application import mcp_group_structures as structures
from lingshu_gate.domain.mcp_groups import McpGroupError

from test_mcp_groups import catalog_path, catalog_token, catalog_tool, create
from test_mcp_groups import gate as gate


def test_warm_pages_reuse_structure_but_current_review_and_scopes_remain_authoritative(gate):
    group = create(gate)
    first, first_handler = catalog_tool(gate, "instance-0")
    second, second_handler = catalog_tool(gate, "instance-1")
    token, headers = catalog_token(gate, ["operations.manage", "tools.read"])
    with patch.object(structures, "_tool_fingerprint", wraps=structures._tool_fingerprint) as fingerprints, \
            patch.object(structures, "normalize_tool_contract", wraps=structures.normalize_tool_contract) as normalization, \
            patch.object(gate["registry"], "list_definitions", side_effect=AssertionError("No global Registry scan")):
        body = gate["client"].get(catalog_path(group), headers=headers).json()
        variant = body["variants"][0]["variant_id"]
        assert fingerprints.call_count == normalization.call_count == 2
        for _ in range(3):
            page = gate["client"].get(catalog_path(group), params={"q": second.id, "offset": 0, "limit": 1}, headers=headers)
            assert page.status_code == 200 and page.json()["total"] == 1
            detail = gate["client"].get(catalog_path(group, "/" + variant), params={"offset": 1, "limit": 1}, headers=headers)
            assert detail.status_code == 200 and detail.json()["members"][0]["tool_id"] == second.id
        gate["access"].set_classification(server_id="instance-1", tool_id=second.id, access="write",
            destructive=True, idempotent=False, reviewer_id=gate["principal"].id)
        reduced = gate["client"].get(catalog_path(group), headers=headers).json()
        assert reduced["visible_tool_count"] == 1 and reduced["variants"][0]["visible_member_count"] == 1
        assert second.id not in json.dumps(reduced)
        gate["database"].execute("UPDATE api_tokens SET scopes_json=? WHERE id=?", (json.dumps(["operations.manage"]), token["id"]))
        assert gate["client"].get(catalog_path(group), headers=headers).json()["visible_tool_count"] == 0
        assert fingerprints.call_count == normalization.call_count == 2
        gate["database"].execute("UPDATE api_tokens SET scopes_json=? WHERE id=?", (json.dumps(["operations.manage", "tools.read"]), token["id"]))
        gate["registry"].update_definition(first.model_copy(update={"input_schema": {"type": "object"}}))
        changed = gate["client"].get(catalog_path(group), headers=headers).json()
        assert changed["visible_tool_count"] == 0, "Old review must not authorize a newly published structure"
        assert fingerprints.call_count == normalization.call_count == 3, "Only the changed publication is prepared again"
    first_handler.assert_not_called()
    second_handler.assert_not_called()


@pytest.mark.parametrize("budget", ["tools", "bytes"])
def test_input_capacity_is_checked_before_fingerprinting_copy_or_normalization(gate, monkeypatch, budget):
    group = create(gate)
    catalog_tool(gate, "instance-0")
    catalog_tool(gate, "instance-1")
    monkeypatch.setattr(application, "MAX_CATALOG_TOOLS" if budget == "tools" else "MAX_CATALOG_CONTRACT_BYTES", 1)
    with patch.object(structures, "prepare_tool_structure", side_effect=AssertionError("Input budget must come first")):
        response = gate["client"].get(catalog_path(group))
    assert response.status_code == 503 and response.json()["detail"]["code"] == "group_catalog_capacity"
    assert "variants" not in response.json() and gate["catalog"].structures.usage() == (0, 0)


@pytest.mark.parametrize("change", ["scopes", "permission", "revoked", "deleted", "expired", "disabled", "admin"])
def test_authority_is_rechecked_in_fresh_transaction_after_cold_structural_work(gate, change):
    group = create(gate)
    _, handler = catalog_tool(gate, "instance-0")
    token, _ = catalog_token(gate, ["operations.manage", "tools.read"])
    actor = gate["auth"]._principal_from_api_token(token["token"])
    reached, release = threading.Event(), threading.Event()
    original = structures.prepare_tool_structure
    def paused(entry):
        reached.set()
        assert release.wait(5)
        return original(entry)
    original_projection = gate["access"].visible_tool_contracts
    def in_transaction(*args, **kwargs):
        assert kwargs["connection"].in_transaction
        return original_projection(*args, **kwargs)
    with patch.object(structures, "prepare_tool_structure", side_effect=paused), \
            patch.object(gate["access"], "visible_tool_contracts", side_effect=in_transaction) as projection, \
            ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(gate["catalog"].catalog, group["id"], actor)
        try:
            assert reached.wait(3)
            if change == "scopes":
                gate["database"].execute("UPDATE api_tokens SET scopes_json=? WHERE id=?", (json.dumps(["operations.manage"]), token["id"]))
            elif change == "permission":
                gate["database"].execute("DELETE FROM role_permissions WHERE permission_id=(SELECT id FROM control_permissions WHERE code='tools.read')")
            elif change == "revoked":
                gate["database"].execute("UPDATE api_tokens SET revoked_at='2026-10-05T00:00:00Z' WHERE id=?", (token["id"],))
            elif change == "deleted":
                gate["database"].execute("DELETE FROM api_tokens WHERE id=?", (token["id"],))
            elif change == "expired":
                gate["database"].execute("UPDATE api_tokens SET expires_at='2000-01-01T00:00:00Z' WHERE id=?", (token["id"],))
            elif change == "disabled":
                gate["database"].execute("UPDATE users SET status='disabled' WHERE id=?", (actor.id,))
            else:
                gate["database"].execute("DELETE FROM user_roles WHERE user_id=? AND role_id=(SELECT id FROM roles WHERE code='admin')", (actor.id,))
        finally:
            release.set()
        if change in {"scopes", "permission"}:
            result = future.result(timeout=5)
            assert result.total == result.visible_tool_count == result.visible_member_count == 0
            assert projection.call_count == 1
        else:
            with pytest.raises(McpGroupError) as denied:
                future.result(timeout=5)
            assert denied.value.status == 403
            projection.assert_not_called()
    handler.assert_not_called()


@pytest.mark.parametrize("stage", ["prepare", "compare"])
def test_cold_preparation_and_warm_comparison_allow_config_writer_and_retry(gate, stage):
    group = create(gate)
    catalog_tool(gate, "instance-0")
    catalog_tool(gate, "instance-1")
    if stage == "compare":
        assert gate["client"].get(catalog_path(group)).status_code == 200
    reached, release = threading.Event(), threading.Event()
    module, name = (structures, "prepare_tool_structure") if stage == "prepare" else (application, "build_catalog")
    original = getattr(module, name)
    calls = 0
    def paused(*args):
        nonlocal calls
        calls += 1
        if calls == 1:
            reached.set()
            assert release.wait(5)
        return original(*args)
    with patch.object(module, name, side_effect=paused), ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(gate["client"].get, catalog_path(group))
        try:
            assert reached.wait(3)
            writer = pool.submit(gate["configs"].save_config, {"id": "instance-0", "name": "Edited synthetic name",
                "launch": {"type": "external"}, "transport": {"type": "streamable_http", "endpoint": "https://mcp.example.test/mcp"}},
                overwrite=True)
            assert writer.result(timeout=2).manifest["name"] == "Edited synthetic name"
        finally:
            release.set()
        response = future.result(timeout=8)
    assert response.status_code == 200
    variant = response.json()["variants"][0]["variant_id"]
    detail = gate["client"].get(catalog_path(group, "/" + variant)).json()
    assert detail["members"][0]["instance_name"] == "Edited synthetic name"
    assert calls >= 2


def test_continuously_changing_structure_stops_after_three_attempts_without_partial_results(gate):
    group = create(gate)
    definition, _ = catalog_tool(gate, "instance-0")
    original = application.build_catalog
    changes = 0
    def changing(*args):
        nonlocal changes
        result = original(*args)
        changes += 1
        gate["registry"].update_definition(definition.model_copy(update={"description": f"Synthetic change {changes}"}))
        return result
    with patch.object(application, "build_catalog", side_effect=changing):
        response = gate["client"].get(catalog_path(group))
    assert changes == 3 and response.status_code == 409
    assert response.json()["detail"]["code"] == "group_catalog_changed"
    assert response.json()["detail"]["retryable"] is True
    assert response.headers["retry-after"] == "1" and response.headers["cache-control"] == "no-store"
    assert "variants" not in response.json()

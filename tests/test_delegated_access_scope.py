"""Delegation ceilings apply to administrators and classification control tools."""
from dataclasses import replace

import pytest

from lingshu_gate.access_control import AccessControlStore, _token_scope_allows
from lingshu_gate.auth import AuthPrincipal
from lingshu_gate.database import SQLiteDatabase
from lingshu_gate.models import ToolDefinition


@pytest.mark.parametrize("auth_type", ["token", "oauth"])
def test_scope_intersection(auth_type):
    principal = AuthPrincipal(id="admin", username="admin", role="admin", auth_type=auth_type,
        scopes=("mcp.write",), delegated_scopes=("mcp.read",))
    assert _token_scope_allows(principal, "read")
    assert not _token_scope_allows(principal, "write")
    assert not _token_scope_allows(replace(principal, delegated_scopes=()), "read")
    assert not _token_scope_allows(replace(principal, scopes=()), "read")


def test_admin_control_plane_cannot_bypass_delegation(tmp_path):
    store = AccessControlStore(SQLiteDatabase(f"sqlite:///{tmp_path / 'scope.db'}", tmp_path))
    principal = AuthPrincipal(id="admin", username="admin", role="admin", auth_type="oauth",
        scopes=("mcp.read",), delegated_scopes=("mcp.read",))
    write = ToolDefinition(id="gate_classification_publish", name="Publish", description="Synthetic", permission="write",
        metadata={"classification_control_plane": True,
                  "required_control_permission": "classifications.manage"})
    assert not store.evaluate(principal, write)["allowed"]
    assert not store.evaluate(replace(principal, delegated_scopes=()), write)["allowed"]


def test_admin_operations_capability_cannot_exceed_delegation(tmp_path):
    store = AccessControlStore(SQLiteDatabase(f"sqlite:///{tmp_path / 'scope.db'}", tmp_path))
    principal = AuthPrincipal(id="admin", username="admin", role="admin", auth_type="oauth",
        scopes=("operations.manage",), delegated_scopes=("mcp.read",))
    assert not store.has_control_permission(principal, "operations.manage")
    assert store.has_control_permission(replace(principal, delegated_scopes=("operations.manage",)),
                                        "operations.manage")


def test_delivery_context_preserves_admin_delegation_ceiling(tmp_path):
    from lingshu_gate.registry import ToolInvocationContext

    store = AccessControlStore(SQLiteDatabase(f"sqlite:///{tmp_path / 'scope.db'}", tmp_path))
    context = ToolInvocationContext(actor_id="admin", username="admin", auth_type="oauth",
        token_id=None, correlation_id="synthetic",
        roles=("admin",), scopes=("mcp.write", "operations.manage"),
        delegated_scopes=("mcp.read", "operations.manage"))
    assert not store.delivery_target_access(context, "synthetic", "write")
    assert not store.delivery_target_access(context, "synthetic", "read")
    assert not store.delivery_target_access(replace(context, delegated_scopes=()), "synthetic", "read")


@pytest.mark.parametrize("auth_type,delegated", [("oauth", None), ("session", ("tools.invoke",))])
def test_delegated_admin_requires_published_classification(tmp_path, auth_type, delegated):
    store = AccessControlStore(SQLiteDatabase(f"sqlite:///{tmp_path / 'scope.db'}", tmp_path))
    tool = ToolDefinition(id="mcp.synthetic.write", name="Write", description="Synthetic",
        source="mcp", metadata={"server_id": "synthetic"})
    principal = AuthPrincipal(id="admin", username="admin", role="admin", auth_type=auth_type,
        scopes=("tools.invoke",), delegated_scopes=delegated,
        external_grant_id="synthetic-grant", external_server_ids=("synthetic",),
        external_tool_ids=(tool.id,), external_access=("write",),
        external_expires_at="2099-01-01T00:00:00+00:00")
    ordinary_admin = replace(principal, auth_type="session", delegated_scopes=None)
    assert store.evaluate(ordinary_admin, tool)["allowed"]
    assert not store.evaluate(principal, tool)["allowed"]
    store.synchronize_tools([tool])
    store.set_classification(server_id="synthetic", tool_id=tool.id, access="write",
        destructive=False, idempotent=False, reviewer_id="synthetic")
    assert not store.evaluate(principal, tool)["allowed"]
    store.publish_classifications(server_id="synthetic", reviewer_id="synthetic")
    assert store.evaluate(principal, tool)["allowed"]
    store.set_classification(server_id="synthetic", tool_id=tool.id, access="write",
        destructive=False, idempotent=False, reviewer_id="synthetic")
    assert not store.evaluate(principal, tool)["allowed"]


@pytest.mark.parametrize("change", [
    {"external_grant_id": None}, {"external_server_ids": ()}, {"external_tool_ids": ()},
    {"external_access": ("read",)}, {"external_expires_at": "2000-01-01T00:00:00+00:00"},
])
def test_external_admin_tool_allowlist_is_fail_closed(tmp_path, change):
    store = AccessControlStore(SQLiteDatabase(f"sqlite:///{tmp_path / 'scope.db'}", tmp_path))
    tool = ToolDefinition(id="mcp.synthetic.write", name="Write", description="Synthetic",
        source="mcp", metadata={"server_id": "synthetic"})
    store.synchronize_tools([tool])
    store.set_classification(server_id="synthetic", tool_id=tool.id, access="write",
        destructive=False, idempotent=False, reviewer_id="synthetic")
    store.publish_classifications(server_id="synthetic", reviewer_id="synthetic")
    principal = AuthPrincipal(id="admin", username="admin", role="admin", auth_type="oauth",
        scopes=("tools.invoke",), delegated_scopes=("tools.invoke",),
        external_grant_id="grant", external_server_ids=("synthetic",), external_tool_ids=(tool.id,),
        external_access=("write",), external_expires_at="2099-01-01T00:00:00+00:00")
    assert store.evaluate(principal, tool)["allowed"]
    assert not store.evaluate(replace(principal, **change), tool)["allowed"]


def test_external_rate_and_concurrency_are_per_grant_and_release(tmp_path):
    from lingshu_gate.access_control import AccessDeniedError

    store = AccessControlStore(SQLiteDatabase(f"sqlite:///{tmp_path / 'scope.db'}", tmp_path))
    principal = AuthPrincipal(id="u", username="u", role="viewer", auth_type="oauth",
        external_grant_id="grant", external_rate_per_minute=2, external_concurrency=1)
    lease = store._acquire_external_invocation(principal)
    with pytest.raises(AccessDeniedError, match="concurrency"):
        store._acquire_external_invocation(principal)
    other = store._acquire_external_invocation(replace(principal, external_grant_id="other"))
    store._release_external_invocation(other)
    store._release_external_invocation(lease)
    lease = store._acquire_external_invocation(principal)
    store._release_external_invocation(lease)
    with pytest.raises(AccessDeniedError, match="rate"):
        store._acquire_external_invocation(principal)


@pytest.fixture
def external_invocation(tmp_path):
    from lingshu_gate.registry import ToolRegistry

    store = AccessControlStore(SQLiteDatabase(f"sqlite:///{tmp_path / 'invoke.db'}", tmp_path))
    tool = ToolDefinition(id="mcp.synthetic.read", name="Read", description="Synthetic",
        source="mcp", metadata={"server_id": "synthetic"})
    store.synchronize_tools([tool])
    store.set_classification(server_id="synthetic", tool_id=tool.id, access="read",
        destructive=False, idempotent=True, reviewer_id="synthetic")
    store.publish_classifications(server_id="synthetic", reviewer_id="synthetic")
    principal = AuthPrincipal(id="admin", username="admin", role="admin", auth_type="oauth",
        scopes=("tools.read",), delegated_scopes=("tools.read",), external_grant_id="grant",
        external_server_ids=("synthetic",), external_tool_ids=(tool.id,), external_access=("read",),
        external_expires_at="2099-01-01T00:00:00+00:00", external_rate_per_minute=10,
        external_concurrency=1)
    return store, ToolRegistry(), principal, tool


def test_concurrent_invocation_denied_before_handler_and_lease_released(external_invocation):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from lingshu_gate.access_control import AccessDeniedError

    store, registry, principal, tool = external_invocation
    entered, release = Event(), Event()
    calls = []
    def handler(arguments):
        calls.append(arguments)
        entered.set()
        assert release.wait(5), "test release timed out"
        return {"synthetic": True}
    registry.register(tool, handler)
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(store.invoke_tool, registry, principal, tool.id, {})
        try:
            assert entered.wait(5), "first invocation did not reach handler"
            with pytest.raises(AccessDeniedError, match="concurrency"):
                store.invoke_tool(registry, principal, tool.id, {})
            assert len(calls) == 1
            denied = store.list_invocation_audits(decision="deny")
            assert denied[0]["outcome"] == "not_invoked"
        finally:
            release.set()
        assert first.result(timeout=5).ok
    assert store.invoke_tool(registry, principal, tool.id, {}).ok
    assert len(calls) == 2


def test_handler_failure_releases_external_concurrency_lease(external_invocation):
    store, registry, principal, tool = external_invocation
    calls = []
    def handler(arguments):
        calls.append(arguments)
        if len(calls) == 1:
            raise ValueError("synthetic failure")
        return {"synthetic": True}
    registry.register(tool, handler)
    assert not store.invoke_tool(registry, principal, tool.id, {}).ok
    assert store.invoke_tool(registry, principal, tool.id, {}).ok
    assert len(calls) == 2


def test_sliding_minute_rate_boundary_blocks_dispatch_then_expires(external_invocation, monkeypatch):
    from lingshu_gate.access_control import AccessDeniedError

    store, registry, principal, tool = external_invocation
    principal = replace(principal, external_rate_per_minute=1)
    clock = [100.0]
    monkeypatch.setattr("lingshu_gate.access_control.monotonic", lambda: clock[0])
    calls = []
    registry.register(tool, lambda args: calls.append(args) or {"synthetic": True})
    assert store.invoke_tool(registry, principal, tool.id, {}).ok
    clock[0] = 159.999
    with pytest.raises(AccessDeniedError, match="rate"):
        store.invoke_tool(registry, principal, tool.id, {})
    assert len(calls) == 1
    clock[0] = 160.0
    assert store.invoke_tool(registry, principal, tool.id, {}).ok
    assert len(calls) == 2


def test_namespace_collision_only_discloses_name_when_all_resources_visible(external_invocation):
    from lingshu_gate.mcp_gateway import _can_disclose_collision
    from lingshu_gate.protocol.tool_namespace import ToolNamespaceCollisionError

    store, registry, principal, tool = external_invocation
    hidden = tool.model_copy(update={"id": "mcp__synthetic__read"})
    for definition in (tool, hidden):
        registry.register(definition, lambda _: {})
    error = ToolNamespaceCollisionError("mcp__synthetic__read", (tool.id, hidden.id))
    assert not _can_disclose_collision(error, registry, store, principal)
    assert _can_disclose_collision(error, registry, store,
        replace(principal, auth_type="session", delegated_scopes=None))

"""Rejected envelopes stay bounded and leave one non-secret audit trail."""
import json

import pytest

from lingshu_gate.access_control import AccessDeniedError
from lingshu_gate.registry import ToolExecutionError
from lingshu_gate.tool_catalog import CatalogInvoke, schema_revision

from test_tool_catalog import catalog as catalog


@pytest.mark.parametrize("reason", ["physical_grant", "instance", "read_scope", "arguments"])
def test_resolved_physical_rejection_has_exactly_one_not_invoked_audit(catalog, reason):
    from dataclasses import replace
    service, actor = catalog
    definition = service.registry.get_definition("mcp.one.read_0")
    arguments = {"key": "never-record-this-secret"}
    instance = "one"
    if reason == "physical_grant":
        service.database.execute("DELETE FROM mcp_resource_grants")
    elif reason == "instance":
        instance = "two"
    elif reason == "read_scope":
        service.database.execute("UPDATE mcp_tool_classifications SET effective_access='write'")
        service.access.save_grant(subject_type="user", subject_id=actor.id, server_id="one",
            permission_type_code="write", created_by=actor.id)
        actor = replace(actor, auth_type="token", scopes=("tools.read",))
    else:
        for _ in range(33):
            arguments = {"child": arguments}
    request = CatalogInvoke(tool_ref=definition.id, instance_id=instance,
        schema_revision=schema_revision(definition), arguments=arguments)
    with pytest.raises(ToolExecutionError):
        service.invoke(actor, request, correlation_id="known-rejection")
    audits = service.database.query_all("SELECT * FROM invocation_audits")
    assert len(audits) == 1
    assert (audits[0]["tool_id"], audits[0]["server_id"], audits[0]["outcome"], audits[0]["correlation_id"]) == (
        definition.id, "one", "not_invoked", "known-rejection")
    assert "never-record-this-secret" not in audits[0]["payload_json"]
    assert not service.database.query_all("SELECT * FROM invocation_payloads")


def test_unknown_ref_uses_hashed_correlation_event_without_raw_reference_or_values(catalog):
    service, actor = catalog
    with pytest.raises(ToolExecutionError) as error:
        service.invoke(actor, CatalogInvoke(tool_ref="unknown-private-reference", schema_revision="0" * 64,
            arguments={"token": "never-record-this-secret"}), correlation_id="unknown-rejection")
    assert error.value.code == "catalog_tool_unavailable"
    assert not service.database.query_all("SELECT * FROM invocation_audits")
    row = service.database.query_one("SELECT payload_json FROM events WHERE type='gate.catalog.invocation_rejected'")
    payload = json.loads(row[0])
    assert payload["correlation_id"] == "unknown-rejection" and len(payload["reference_sha256"]) == 64
    assert "unknown-private-reference" not in row[0] and "never-record-this-secret" not in row[0]


def test_rate_admission_precedes_schema_work_and_serialization(catalog, monkeypatch):
    service, actor = catalog
    definition = service.registry.get_definition("mcp.one.read_0")
    def denied(_):
        raise AccessDeniedError("synthetic rate rejection", required_access="read", granted_access="none")
    monkeypatch.setattr(service.access, "_acquire_external_invocation", denied)
    monkeypatch.setattr("lingshu_gate.tool_catalog._validate_arguments", lambda *_: pytest.fail("Validation before rate admission"))
    monkeypatch.setattr("lingshu_gate.access_control._payload_summary", lambda *_: pytest.fail("Unbounded pre-admission summary"))
    with pytest.raises(ToolExecutionError) as error:
        service.invoke(actor, CatalogInvoke(tool_ref=definition.id, schema_revision=schema_revision(definition), arguments={}))
    assert error.value.code == "catalog_tool_unavailable"
    assert service.database.query_one("SELECT outcome FROM invocation_audits")[0] == "not_invoked"

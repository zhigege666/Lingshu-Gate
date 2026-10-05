"""Opt-in loopback-only 5,000-service OAuth fixture; no downstream connections."""
from __future__ import annotations

import base64
import hashlib
import json

from fastapi import FastAPI

from lingshu_gate.models import ToolDefinition


def seed_oauth_catalog(app: FastAPI) -> None:
    state = app.state
    auth, access, registry, server = state.auth_store, state.access_store, state.registry, state.oauth_server
    admin = auth.list_users()[0]
    access.save_role(code="synthetic-oauth-owner", name="Synthetic OAuth owner", description="Browser fixture",
        permissions=["console.view", "tools.read", "tools.invoke", "credentials.manage.self"])
    user = auth.create_user(username="synthetic-oauth-owner", password="Synthetic-oauth-owner-123!", role="synthetic-oauth-owner")
    owner, session, _ = auth.login(username="synthetic-oauth-owner", password="Synthetic-oauth-owner-123!")
    _, consent_session, _ = auth.login(username="synthetic-oauth-owner", password="Synthetic-oauth-owner-123!", purpose="oauth_consent")
    definitions = []
    for service in range(5000):
        server_id = f"oauth-scale-{service:04}"
        for index in range(10):
            level = "read" if index % 2 == 0 else "write"
            definitions.append(ToolDefinition(id=f"mcp.{server_id}.tool-{index}", name=f"Scale tool {index}",
                description="Isolated synthetic OAuth tool; no downstream", source="mcp", permission=level,
                input_schema={"type": "object", "properties": {"example": {"type": "string"}}},
                metadata={"server_id": server_id, "original_tool_name": f"fixture_{index}"}))
    for tool in definitions[:2]:
        registry.register(tool, lambda arguments: {"synthetic": True})
    access.save_grant(subject_type="user", subject_id=user["id"], server_id="oauth-scale-0000",
        permission_type_code="write", created_by=admin["id"])
    with state.database.session() as connection:
        access._synchronize_tools(connection, definitions[:2])
        connection.executemany("UPDATE mcp_tool_classifications SET effective_access=?,status='published',"
            "reviewed_by=?,reviewed_at='2026-10-05T00:00:00+00:00' WHERE server_id=? AND tool_id=?",
            [(tool.permission, admin["id"], tool.metadata["server_id"], tool.id) for tool in definitions[:2]])
    issuer = "https://gate.example.test"
    server.save_config({"enabled": False, "issuer": issuer, "resource": issuer + "/mcp"}, 0)
    server.rotate_key()
    client = server.create_client("Synthetic scale OAuth client", ["https://client.example.test/callback"], ["tools.read", "tools.invoke"])["client"]
    server.save_config({"enabled": True, "issuer": issuer, "resource": issuer + "/mcp"}, 1)
    verifier = "synthetic-pkce-" + "a" * 48
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    browser = "synthetic-browser-" + "b" * 32
    interaction = server.start_authorization({"client_id": client["id"], "redirect_uri": client["redirect_uris"][0],
        "response_type": "code", "resource": issuer + "/mcp", "scope": "tools.read tools.invoke",
        "code_challenge": challenge, "code_challenge_method": "S256"}, browser)
    context = server.consent_context(interaction, browser, consent_session)
    server.consent(interaction, browser, context["csrf"], owner, [tool.id for tool in definitions[:2]], 7, 30, 1)
    grant = server.store.grants(user["id"])[0]
    options = server.scope_options(owner, grant["id"], session)
    preview = server.preview_scope(owner, grant["id"], session, options["csrf"], grant["revision"],
        [definitions[0].id], grant["expires_at"], 30, 1)
    server.update_scope(owner, grant["id"], session, preview["confirmation"], grant["revision"],
        [definitions[0].id], grant["expires_at"], 30, 1)
    for tool in definitions[2:]:
        registry.register(tool, lambda arguments: {"synthetic": True})
    permission = state.database.query_one("SELECT id FROM permission_types WHERE code='write'")[0]
    with state.database.session() as connection:
        access._synchronize_tools(connection, definitions[2:])
        connection.executemany("UPDATE mcp_tool_classifications SET effective_access=?,status='published',"
            "reviewed_by=?,reviewed_at='2026-10-05T00:00:00+00:00' WHERE server_id=? AND tool_id=?",
            [(tool.permission, admin["id"], tool.metadata["server_id"], tool.id) for tool in definitions[2:]])
        connection.executemany("INSERT INTO mcp_resource_grants"
            "(id,subject_type,subject_id,server_id,tool_id,permission_type_id,created_by,created_at,updated_at)"
            " VALUES(?,'user',?,?,'',?,?,?,?)", [(f"oauth-fixture-{index}", user["id"], f"oauth-scale-{index:04}",
                permission, admin["id"], "2026-10-05T00:00:00+00:00", "2026-10-05T00:00:00+00:00") for index in range(1,5000)])
    assert len(definitions) == 50000
    # A visible unpublished service gives the UI an actual classification reason.
    state.database.execute("UPDATE mcp_tool_classifications SET status='pending' WHERE server_id='oauth-scale-4998'")
    state.tool_catalog.synchronize()
    print(json.dumps({"fixture": "oauth-catalog", "services": 5000, "tools": 50000, "secrets_logged": False}))

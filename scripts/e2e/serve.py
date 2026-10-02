"""Loopback-only browser fixture: fresh database, synthetic users, no inherited Gate configuration."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import uvicorn


def main() -> None:
    for name in tuple(os.environ):
        if name.startswith("LINGSHU_GATE_"):
            del os.environ[name]
    with tempfile.TemporaryDirectory(prefix="gate-browser-synthetic-", dir=os.environ["GATE_E2E_TEMP_ROOT"]) as directory:
        root = Path(directory)
        os.environ.update({
            "LINGSHU_GATE_DATA_DIR": str(root),
            "LINGSHU_GATE_CONFIG_DIR": str(root / "mcp.d"),
            "LINGSHU_GATE_ALLOWED_ROOT": str(root),
            "LINGSHU_GATE_AUTH_ENABLED": "true",
        })
        os.environ["npm_config_cache"] = str(root / "npm-cache")
        os.environ["npm_config_audit"] = "false"
        os.environ["npm_config_fund"] = "false"
        os.environ["npm_config_update_notifier"] = "false"
        from lingshu_gate.main import create_app

        app = create_app()
        store = app.state.auth_store
        store.change_password(str(store.list_users()[0]["id"]), "Synthetic-admin-123!")
        viewer = store.create_user(username="synthetic-viewer", password="Synthetic-viewer-123!", role="viewer")
        # Safe in-process fixture definition; no downstream process or network connection.
        from lingshu_gate.models import ToolDefinition

        definition = ToolDefinition(id="mcp.synthetic.read", name="Synthetic read tool",
                                    description="Synthetic fixture; no external connection",
                                    source="mcp", permission="read",
                                    metadata={"server_id": "synthetic-fixture"})
        app.state.registry.register(definition, lambda arguments: {"synthetic": True})
        access = app.state.access_store
        admin_id = str(store.list_users()[0]["id"])
        access.synchronize_tools(app.state.registry.list_definitions())
        access.set_classification(server_id="synthetic-fixture", tool_id=definition.id, access="read",
                                  destructive=False, idempotent=True, reviewer_id=admin_id)
        access.publish_classifications(server_id="synthetic-fixture", reviewer_id=admin_id)
        access.save_grant(subject_type="user", subject_id=viewer["id"], server_id="synthetic-fixture",
                          permission_type_code="read", created_by=admin_id)
        from http_peer import synthetic_http_peer

        with synthetic_http_peer(Path(os.environ["GATE_E2E_TEMP_ROOT"])):
            uvicorn.run(app, host="127.0.0.1", port=18763, access_log=False)


if __name__ == "__main__":
    main()

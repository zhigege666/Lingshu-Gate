"""Fail-closed tests for configuration and deployment request boundaries."""

from __future__ import annotations

import inspect

import pytest
from pydantic import ValidationError

from lingshu_gate.build_deploy import BuildDeployStore
from lingshu_gate.mcp_manifest import McpServerManifest
from lingshu_gate.models import McpConfigSaveRequest


def _external_manifest() -> dict[str, object]:
    return {
        "id": "fail-closed-test",
        "launch": {"type": "external"},
        "transport": {
            "type": "streamable_http",
            "endpoint": "https://service.example.test/mcp",
        },
    }


def test_config_save_defaults_to_persistence_only() -> None:
    request = McpConfigSaveRequest(manifest=_external_manifest())

    assert request.apply is False
    assert request.start is False


@pytest.mark.parametrize(
    "payload",
    [
        {"apply": False, "start": True},
        {"apply": "false", "start": False},
        {"apply": False, "start": "false"},
        {"apply": False, "start": False, "unexpected": True},
    ],
)
def test_config_save_rejects_ambiguous_or_unknown_controls(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        McpConfigSaveRequest(manifest=_external_manifest(), **payload)  # type: ignore[arg-type]


def test_manifest_defaults_to_stopped_and_rejects_unknown_nested_fields() -> None:
    manifest = McpServerManifest.model_validate(_external_manifest())
    assert manifest.auto_start is False

    invalid_payloads = [
        {**_external_manifest(), "unexpected": True},
        {
            **_external_manifest(),
            "launch": {"type": "external", "unexpected": True},
        },
        {
            **_external_manifest(),
            "transport": {
                "type": "streamable_http",
                "endpoint": "https://service.example.test/mcp",
                "unexpected": True,
            },
        },
        {
            **_external_manifest(),
            "restart_policy": {"health_check": {"unexpected": True}},
        },
        {
            **_external_manifest(),
            "user_credentials": [
                {
                    "id": "token",
                    "name": "Token",
                    "injection": {"name": "Authorization", "unexpected": True},
                }
            ],
        },
        {
            **_external_manifest(),
            "user_credentials": [
                {
                    "id": "token",
                    "name": "Token",
                    "injection": {"name": "Authorization"},
                    "unexpected": True,
                }
            ],
        },
    ]

    for payload in invalid_payloads:
        with pytest.raises(ValidationError):
            McpServerManifest.model_validate(payload)


def test_package_manifest_rejects_unknown_package_fields() -> None:
    payload = {
        "id": "package-fail-closed-test",
        "launch": {
            "type": "managed_process",
            "command": "node",
            "package": {"name": "example-package", "unexpected": True},
        },
        "transport": {"type": "stdio"},
    }

    with pytest.raises(ValidationError):
        McpServerManifest.model_validate(payload)


def test_deploy_store_method_defaults_disable_optional_side_effects() -> None:
    deploy = inspect.signature(BuildDeployStore.deploy_build).parameters
    rollback = inspect.signature(BuildDeployStore.rollback_deployment).parameters

    assert deploy["start"].default is False
    assert deploy["overwrite"].default is False
    assert rollback["start"].default is False

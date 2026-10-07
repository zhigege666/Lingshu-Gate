"""Offline local startup pins. All tool probes and process launches are mocked."""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from lingshu_gate.build_plan import build_plan, finalize_manifest, validate_plan
from lingshu_gate.application.mcp_configuration import McpConfigurationService
from lingshu_gate.auth import AuthStore
from lingshu_gate.config import Settings
from lingshu_gate.interfaces.control_api.mcp_config_routes import register_mcp_config_routes
from lingshu_gate.mcp_config_store import McpConfigStore
from lingshu_gate.mcp_managed_http_client import ManagedHttpMcpClient
from lingshu_gate.mcp_manifest import LaunchConfig, McpServerManifest
from lingshu_gate.mcp_manifest_validation import _check_launch, validate_mcp_manifest
from lingshu_gate.mcp_stdio_client import StdioMcpClient
from lingshu_gate.observability_store import ObservabilityStore
from lingshu_gate.runtime_toolchain import MAX_VERSION_BYTES, NO_TOOL_DOWNLOADS, RuntimeToolchainError, _read_version, inspect_runtime_toolchain, resolve_runtime_toolchain


def launch(manager="npm", version="11.6.0"):
    return LaunchConfig(type="managed_process", command=manager, args=["run", "start"], toolchain={"manager": manager, "version": version})


@pytest.fixture
def trusted_settings(tmp_path):
    directory = tmp_path / "administrator-tools"
    directory.mkdir()
    paths = {}
    for manager, filename in (("node", "node"), ("npm", "npm-cli.js"), ("pnpm", "pnpm.cjs"), ("yarn", "yarn.js")):
        binary = directory / filename
        binary.write_text("// Inert test fixture; every execution probe is mocked.\n")
        binary.chmod(0o755)
        paths[manager] = str(binary)
    return Settings(data_dir=tmp_path / "data", config_dir=tmp_path / "configs", allowed_root=tmp_path / "project", runtime_toolchain_paths=paths)


@pytest.mark.parametrize("manager,version", [("npm", "11.6.0"), ("pnpm", "9.15.4"), ("yarn", "1.22.22")])
def test_built_start_manifest_has_consumable_pin_not_analysis_only(tmp_path, manager, version):
    plan = build_plan({"runtime": "node", "metadata": {"package_scripts": ["start"], "node_package_manager": {"name": manager, "version": version, "errors": [], "supported": True}}}, run_install=False, run_build=False)
    assert validate_plan(plan)["ok"]
    manifest = finalize_manifest(plan, {"filename": "fixture.zip", "id": "fixture"}, "build", tmp_path)
    parsed = McpServerManifest.model_validate(manifest)
    assert parsed.launch.toolchain.manager == manager and parsed.launch.toolchain.version == version
    del plan["package_manager"]
    assert not validate_plan(plan)["ok"]
    with pytest.raises(ValueError):
        finalize_manifest(plan, {"filename": "fixture.zip"}, "build", tmp_path)


def test_direct_node_entrypoint_has_no_manager_runtime_requirement(tmp_path):
    (tmp_path / "index.js").write_text("export {};")
    plan = build_plan({"runtime": "node", "metadata": {"package_scripts": []}}, run_install=False, run_build=False)
    manifest = finalize_manifest(plan, {"filename": "fixture.zip"}, "build", tmp_path)
    assert manifest["launch"]["command"] == "node" and "toolchain" not in manifest["launch"]


def test_exact_runtime_uses_registered_node_and_cli_not_project_or_host_path(trusted_settings, monkeypatch):
    monkeypatch.setenv("PATH", "/attacker-host-path")
    environment = {"PATH": "/project-bin", "Path": "/other-project-bin", "TOKEN": "secret-value", "NODE_OPTIONS": "--require=project-code", "COREPACK_ENABLE_NETWORK": "1", "LINGSHU_GATE_RUNTIME_TOOLCHAIN_PATHS": '{"npm":"/project/npm"}'}
    with patch("shutil.which") as lookup, patch("lingshu_gate.runtime_toolchain._read_version", return_value="11.6.0") as probe:
        command = resolve_runtime_toolchain(launch(), environment, settings=trusted_settings)
    expected = [trusted_settings.runtime_toolchain_paths["node"], trusted_settings.runtime_toolchain_paths["npm"]]
    assert command == [*expected, "run", "start"]
    lookup.assert_not_called()
    assert all(environment[name] == value for name, value in NO_TOOL_DOWNLOADS.items())
    assert environment["PATH"] == str(Path(expected[0]).parent) and "Path" not in environment
    assert probe.call_args.args[0] == expected
    assert probe.call_args.args[1]["PATH"] == environment["PATH"]
    assert not {"TOKEN", "NODE_OPTIONS", "LINGSHU_GATE_RUNTIME_TOOLCHAIN_PATHS"} & probe.call_args.args[1].keys()


def test_missing_registry_and_version_drift_never_fall_back(tmp_path, trusted_settings):
    with patch("shutil.which") as lookup, patch("lingshu_gate.runtime_toolchain._read_version") as probe:
        with pytest.raises(RuntimeToolchainError) as missing:
            resolve_runtime_toolchain(launch(), {"PATH": str(tmp_path)}, settings=Settings(data_dir=tmp_path))
    assert missing.value.code == "runtime_toolchain_unregistered"
    probe.assert_not_called()
    lookup.assert_not_called()
    with patch("lingshu_gate.runtime_toolchain._read_version", side_effect=["11.6.0", "10.9.0"]):
        assert resolve_runtime_toolchain(launch(), {}, settings=trusted_settings)[0] == trusted_settings.runtime_toolchain_paths["node"]
        with pytest.raises(RuntimeToolchainError) as drift:
            resolve_runtime_toolchain(launch(), {}, settings=trusted_settings)
    assert drift.value.code == "runtime_toolchain_version_mismatch"


def test_core_pin_does_not_probe_or_execute_any_installed_tool():
    with patch("shutil.which") as lookup, patch("lingshu_gate.runtime_toolchain._read_version") as probe:
        with pytest.raises(RuntimeToolchainError) as blocked:
            resolve_runtime_toolchain(launch(), {}, settings=Settings(runtime_role="core"))
    assert blocked.value.code == "runtime_role_execution_blocked"
    lookup.assert_not_called()
    probe.assert_not_called()


@pytest.mark.parametrize("node", ["22.12.0", "20.19.0"])
def test_pnpm11_runtime_node_requirement_uses_the_actual_registered_interpreter(trusted_settings, node):
    with patch("lingshu_gate.runtime_toolchain._read_version", side_effect=["11.5.0", node]) as probe:
        with pytest.raises(RuntimeToolchainError) as error:
            resolve_runtime_toolchain(launch("pnpm", "11.5.0"), {}, settings=trusted_settings)
    assert error.value.code == "runtime_toolchain_node_incompatible"
    assert probe.call_args_list[0].args[0][0] == probe.call_args_list[1].args[0] == trusted_settings.runtime_toolchain_paths["node"]


def test_unverified_probe_error_does_not_echo_tool_output_or_credentials(trusted_settings):
    with patch("lingshu_gate.runtime_toolchain._read_version", side_effect=RuntimeError("secret-value")):
        with pytest.raises(RuntimeToolchainError) as error:
            resolve_runtime_toolchain(launch(), {}, settings=trusted_settings)
    assert error.value.code == "runtime_toolchain_unverified" and "secret-value" not in str(error.value)


@pytest.mark.parametrize("mode", ["stdio", "streamable_http"])
def test_both_existing_local_clients_block_before_child_start_on_pin_failure(tmp_path, mode):
    settings = Settings(data_dir=tmp_path, runtime_role="local")
    manifest = McpServerManifest(id="fixture", launch=launch(), transport={"type": mode, **({"endpoint": "http://127.0.0.1:3120/mcp"} if mode == "streamable_http" else {})})
    module = "lingshu_gate.mcp_stdio_client" if mode == "stdio" else "lingshu_gate.mcp_managed_http_client"
    client = StdioMcpClient(manifest, settings) if mode == "stdio" else ManagedHttpMcpClient(manifest, settings)
    with patch(module + ".resolve_runtime_toolchain", side_effect=RuntimeToolchainError("runtime_toolchain_version_mismatch", "npm", "11.6.0")), patch(module + ".subprocess.Popen") as process:
        with pytest.raises(RuntimeToolchainError):
            client.start() if mode == "stdio" else client._start_process()
    process.assert_not_called()


@pytest.mark.parametrize("mode", ["stdio", "streamable_http"])
def test_existing_clients_cannot_select_tools_with_project_path(trusted_settings, mode):
    requested = launch()
    requested.env = {"PATH": str(trusted_settings.allowed_root / "bin"), "Path": "/project-bin"}
    manifest = McpServerManifest(id="fixture", launch=requested, transport={"type": mode, **({"endpoint": "http://127.0.0.1:3120/mcp"} if mode == "streamable_http" else {})})
    module = "lingshu_gate.mcp_stdio_client" if mode == "stdio" else "lingshu_gate.mcp_managed_http_client"
    client = StdioMcpClient(manifest, trusted_settings) if mode == "stdio" else ManagedHttpMcpClient(manifest, trusted_settings)
    with patch("lingshu_gate.runtime_toolchain._read_version", return_value="11.6.0"), patch(module + ".subprocess.Popen", side_effect=RuntimeError("fixture stop before execution")) as spawn:
        with pytest.raises(RuntimeError, match="fixture stop"):
            client.start() if mode == "stdio" else client._start_process()
    assert spawn.call_args.args[0] == [trusted_settings.runtime_toolchain_paths["node"], trusted_settings.runtime_toolchain_paths["npm"], "run", "start"]
    assert spawn.call_args.kwargs["env"]["PATH"] == str(Path(trusted_settings.runtime_toolchain_paths["node"]).parent)
    assert "Path" not in spawn.call_args.kwargs["env"]


def test_manifest_preflight_reports_missing_registration_without_probing(tmp_path):
    manifest = McpServerManifest(id="fixture", launch=launch(), transport={"type": "stdio"})
    checks = []
    with patch("lingshu_gate.runtime_toolchain.subprocess.Popen") as spawn, patch("lingshu_gate.runtime_toolchain._read_version") as probe:
        _check_launch(Settings(data_dir=tmp_path), manifest, checks)
    assert any(check["name"] == "launch.toolchain" and check["severity"] == "error" for check in checks)
    spawn.assert_not_called()
    probe.assert_not_called()


@pytest.mark.parametrize("manager,version", [("npm", "11.6.0"), ("pnpm", "9.15.4"), ("yarn", "1.22.22")])
@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("absolute", [False, True])
def test_both_readonly_validate_routes_never_execute_manifest_programs(trusted_settings, manager, version, existing, absolute):
    app = FastAPI()
    configs = Mock(spec=McpConfigStore)
    configs.get_config.side_effect = KeyError("not saved")
    service = Mock(spec=McpConfigurationService)
    audit = Mock(spec=ObservabilityStore)
    register_mcp_config_routes(app, settings=trusted_settings, auth_store=Mock(spec=AuthStore), mcp_config_store=configs, configuration_service=service, observability_store=audit, require_operations_manager=lambda: None)
    malicious = trusted_settings.allowed_root / manager
    manifest = {"id": "fixture", "auto_start": False, "launch": {"type": "managed_process", "command": str(malicious) if absolute else manager, "args": ["run", "start"], "cwd": str(trusted_settings.allowed_root), "env": {"PATH": str(trusted_settings.allowed_root), "NODE_OPTIONS": "--require=project-code"}, "toolchain": {"manager": manager, "version": version}}, "transport": {"type": "stdio"}}
    with patch("lingshu_gate.runtime_toolchain.subprocess.Popen") as spawn, patch("lingshu_gate.runtime_toolchain._read_version") as probe, TestClient(app) as client:
        response = client.post("/v1/mcp/configs/fixture/validate" if existing else "/v1/mcp/configs/validate", json={"manifest": manifest, "apply": True, "start": True})
    assert response.status_code == 200
    checks = response.json()["checks"]
    if absolute:
        assert any(check["name"] == "manifest.schema" and check["severity"] == "error" for check in checks)
    else:
        tool = next(check for check in checks if check["name"] == "launch.toolchain")
        assert tool["severity"] == "warning" and tool["metadata"]["version_verified"] is False
        assert any(check["name"] == "launch.cwd" for check in checks)
    spawn.assert_not_called()
    probe.assert_not_called()
    assert not service.mock_calls
    configs.save_config.assert_not_called()


def test_legacy_manifest_validation_remains_nonexecuting_and_keeps_authorized_command(tmp_path):
    legacy = LaunchConfig(type="managed_process", command=str(tmp_path / "npm"), args=["run", "start"], env={"PATH": "/project-bin"})
    manifest = McpServerManifest(id="legacy", launch=legacy, transport={"type": "stdio"}, auto_start=False)
    configs = Mock(spec=McpConfigStore)
    configs.get_config.side_effect = KeyError("new")
    with patch("lingshu_gate.runtime_toolchain.subprocess.Popen") as spawn, patch("lingshu_gate.runtime_toolchain._read_version") as probe:
        validate_mcp_manifest(Settings(data_dir=tmp_path), configs, manifest.model_dump(mode="json"))
        environment = dict(legacy.env)
        assert resolve_runtime_toolchain(legacy, environment, settings=Settings()) == [legacy.command, "run", "start"]
        assert environment == legacy.env
    probe.assert_not_called()
    spawn.assert_not_called()


@pytest.mark.parametrize("command", ["/project/npm", "../npm", "npm.cmd", "NPM"])
def test_pinned_manifest_cannot_choose_absolute_relative_or_alias_command(command):
    with pytest.raises(ValidationError, match="exact symbolic manager"):
        LaunchConfig(type="managed_process", command=command, toolchain={"manager": "npm", "version": "11.6.0"})


@pytest.mark.parametrize("protected", ["allowed_root", "data_dir", "config_dir"])
def test_administrator_registry_cannot_point_to_project_controlled_files(trusted_settings, protected):
    directory = getattr(trusted_settings, protected)
    directory.mkdir()
    candidate = directory / "npm-cli.js"
    candidate.write_text("// untrusted project input\n")
    settings = Settings(data_dir=trusted_settings.data_dir, config_dir=trusted_settings.config_dir, allowed_root=trusted_settings.allowed_root, runtime_toolchain_paths={**trusted_settings.runtime_toolchain_paths, "npm": str(candidate)})
    with patch("lingshu_gate.runtime_toolchain._read_version") as probe, pytest.raises(RuntimeToolchainError) as rejected:
        resolve_runtime_toolchain(launch(), {}, settings=settings)
    assert rejected.value.code == "runtime_toolchain_untrusted"
    probe.assert_not_called()


def test_project_symlink_to_registered_tools_cannot_become_registry_path(trusted_settings):
    trusted_settings.allowed_root.mkdir()
    link = trusted_settings.allowed_root / "npm-cli.js"
    link.symlink_to(trusted_settings.runtime_toolchain_paths["npm"])
    settings = Settings(data_dir=trusted_settings.data_dir, config_dir=trusted_settings.config_dir, allowed_root=trusted_settings.allowed_root, runtime_toolchain_paths={**trusted_settings.runtime_toolchain_paths, "npm": str(link)})
    with patch("lingshu_gate.runtime_toolchain._read_version") as probe, pytest.raises(RuntimeToolchainError) as rejected:
        resolve_runtime_toolchain(launch(), {}, settings=settings)
    assert rejected.value.code == "runtime_toolchain_untrusted"
    probe.assert_not_called()


def test_registry_is_immutable_copy_and_loaded_only_from_service_environment(trusted_settings, monkeypatch):
    original = dict(trusted_settings.runtime_toolchain_paths)
    settings = Settings(runtime_toolchain_paths=original)
    original["npm"] = "/project/npm"
    assert settings.runtime_toolchain_paths["npm"] == trusted_settings.runtime_toolchain_paths["npm"]
    with pytest.raises(TypeError):
        settings.runtime_toolchain_paths["npm"] = "/project/npm"
    monkeypatch.setenv("LINGSHU_GATE_RUNTIME_TOOLCHAIN_PATHS", json.dumps(dict(trusted_settings.runtime_toolchain_paths)))
    assert Settings.from_env().runtime_toolchain_paths == trusted_settings.runtime_toolchain_paths


@pytest.mark.parametrize("registry", [{"npm": "relative/npm"}, {"npx": "/reviewed/npx"}, {"node": 4}, None, ["node"]])
def test_invalid_administrator_registry_fails_closed(registry):
    with pytest.raises(ValueError, match="administrator-reviewed absolute paths"):
        Settings(runtime_toolchain_paths=registry)


def test_registry_missing_file_and_shell_launcher_do_not_probe(trusted_settings):
    paths = dict(trusted_settings.runtime_toolchain_paths)
    for candidate, expected in ((str(Path(paths["npm"]).with_name("missing.js")), "runtime_toolchain_unavailable"), (paths["node"], "runtime_toolchain_untrusted")):
        settings = Settings(runtime_toolchain_paths={**paths, "npm": candidate})
        with patch("lingshu_gate.runtime_toolchain._read_version") as probe, pytest.raises(RuntimeToolchainError) as rejected:
            inspect_runtime_toolchain(launch(), settings)
        assert rejected.value.code == expected
        probe.assert_not_called()


@pytest.mark.parametrize("output", [b"secret-value", b"x" * (MAX_VERSION_BYTES + 1)])
def test_version_probe_rejects_nonversion_and_oversize_without_unbounded_capture(output):
    process = SimpleNamespace(stdout=io.BytesIO(output), returncode=0, poll=lambda: 0, wait=lambda **kwargs: 0)
    with patch("lingshu_gate.runtime_toolchain.subprocess.Popen", return_value=process) as spawn:
        with pytest.raises(ValueError):
            _read_version("/reviewed/npm", {"COREPACK_ENABLE_NETWORK": "0"})
    assert spawn.call_args.args[0] == ["/reviewed/npm", "--version"]
    assert "gate-runtime-tool-probe-" in spawn.call_args.kwargs["cwd"]


def test_version_probe_timeout_stops_its_probe_group_without_tool_install():
    process = SimpleNamespace(stdout=io.BytesIO(), returncode=None, pid=4321, poll=lambda: None, wait=lambda **kwargs: 0, kill=lambda: None)
    with patch("lingshu_gate.runtime_toolchain.subprocess.Popen", return_value=process), patch("lingshu_gate.runtime_toolchain.threading.Thread") as reader, patch("lingshu_gate.runtime_toolchain.threading.Event") as signal_event, patch("lingshu_gate.runtime_toolchain.os.killpg") as stop_group:
        reader.return_value.is_alive.return_value = True
        signal_event.return_value.wait.return_value = False
        with pytest.raises(ValueError, match="timed out"):
            _read_version("/reviewed/npm", {})
    if __import__("os").name != "nt":
        stop_group.assert_called_once()


@pytest.mark.parametrize("pin", [
    {"manager": "yarn", "version": "4.0.0"},
    {"manager": "npm", "version": "latest"},
    {"manager": "pnpm", "version": "11.5.0", "command": "arbitrary"},
])
def test_runtime_pin_rejects_unsupported_versions_and_extra_command_injection(pin):
    with pytest.raises(ValidationError):
        LaunchConfig(type="managed_process", command=pin["manager"], toolchain=pin)

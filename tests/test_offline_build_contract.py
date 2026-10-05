"""Normalized graph/worker fixtures; no lock resolution, downloads or execution."""

from __future__ import annotations

import base64
import hashlib
from dataclasses import fields, replace
from unittest.mock import patch

import pytest

from lingshu_gate.offline_build_contract import (
    BUILD_LIMITS, DependencyNode, OfflineBuildRequest,
    validate_dependency_graph, verify_dependency_content,
)
from lingshu_gate.ports.safe_network_executor import PHASE_CHECKS, ROOTLESS_CHECKS, ExecutorReadiness
from lingshu_gate.registry import ToolExecutionError

ORIGIN = "https://registry.example.invalid"
ORIGINS = frozenset({ORIGIN})


def sri(data=b"fixture", algorithm="sha512"):
    return algorithm + "-" + base64.b64encode(hashlib.new(algorithm, data).digest()).decode()


def node(key, dependencies=(), **kwargs):
    return DependencyNode(key, kwargs.get("source_url", ORIGIN + "/content.tgz"), kwargs.get("integrity", sri()), dependencies)


def readiness(checks=None, *, platform="linux", backend="linux_rootless_oci"):
    return ExecutorReadiness(backend, platform, ROOTLESS_CHECKS | PHASE_CHECKS["offline_build"] if checks is None else checks)


def build_request(**kwargs):
    graph = validate_dependency_graph([node("fixture@1.0.0")], ("fixture@1.0.0",), allowed_origins=ORIGINS)
    request = OfflineBuildRequest("a" * 64, "b" * 64, "c" * 64, graph.sha256, "d" * 64, ("npm", "ci", "--offline"), 300, 512 * 1024 * 1024, 1000, 128, (("CI", "true"),))
    return replace(request, **kwargs)


def test_complete_normalized_graph_binds_roots_all_edges_origins_sri_and_stable_digest():
    nodes = [node("app@1", ("peer@2", "optional-linux@3", "dev@4")), node("peer@2", ("dev@4",)), node("optional-linux@3"), node("dev@4")]
    graph = validate_dependency_graph(iter(nodes), ("app@1",), allowed_origins=ORIGINS)
    reversed_nodes = [replace(nodes[0], dependencies=tuple(reversed(nodes[0].dependencies))), *nodes[1:]]
    same = validate_dependency_graph(reversed(reversed_nodes), ("app@1",), allowed_origins=ORIGINS)
    assert graph.sha256 == same.sha256 and len(graph.sha256) == 64
    changed = validate_dependency_graph([replace(nodes[0], source_url=ORIGIN + "/different.tgz"), *nodes[1:]], ("app@1",), allowed_origins=ORIGINS)
    assert graph.sha256 != changed.sha256
    changed_integrity = validate_dependency_graph([replace(nodes[0], integrity=sri(b"changed")), *nodes[1:]], ("app@1",), allowed_origins=ORIGINS)
    assert graph.sha256 != changed_integrity.sha256


def test_multiple_importer_roots_and_cycles_have_bounded_complete_closure():
    graph = validate_dependency_graph([node("one@1", ("shared@1",)), node("two@1", ("shared@1",)), node("shared@1", ("one@1",))], ("two@1", "one@1"), allowed_origins=ORIGINS)
    assert graph.roots == ("one@1", "two@1") and len(graph.nodes) == 3


@pytest.mark.parametrize("nodes,roots", [
    ([node("root@1", ("missing@1",))], ("root@1",)), ([node("root@1")], ("missing@1",)),
    ([node("root@1"), node("unreferenced@1")], ("root@1",)),
    ([node("root@1"), node("root@1")], ("root@1",)),
    ([node("root@1", ("child@1", "child@1")), node("child@1")], ("root@1",)),
    ([node("root@1")], ()), ([node("root@1")], ("root@1", "root@1")),
    ([node("bad key")], ("bad key",)), ([node("root@1", ["child@1"])], ("root@1",)),
])
def test_missing_duplicate_mutable_and_outside_closure_content_is_rejected(nodes, roots):
    with pytest.raises(ToolExecutionError) as denied:
        validate_dependency_graph(nodes, roots, allowed_origins=ORIGINS)
    assert denied.value.code == "offline_contract_invalid"


@pytest.mark.parametrize("url", [
    "http://registry.example.invalid/content.tgz", "https://other.example.invalid/content.tgz",
    "https://user:synthetic-secret@registry.example.invalid/content.tgz",
    ORIGIN + "/content.tgz?token=synthetic-secret", ORIGIN + "/content.tgz#fragment",
    "git+https://git.example.invalid/repo", "file:/workspace/dependency", "link:../other",
])
def test_unreviewed_dependency_origins_and_credential_urls_rejected_without_echo(url):
    with pytest.raises(ToolExecutionError) as denied:
        validate_dependency_graph([node("root@1", source_url=url)], ("root@1",), allowed_origins=ORIGINS)
    assert "synthetic-secret" not in str(denied.value)


@pytest.mark.parametrize("integrity", ["", "sha1-" + base64.b64encode(b"x" * 20).decode(), "md5-fixture", "sha512-AAAA", sri() + " " + sri(b"alternative"), sri()[:-2], "sha512-!"])
def test_missing_weak_ambiguous_or_malformed_integrity_is_not_rewritten(integrity):
    with pytest.raises(ToolExecutionError):
        validate_dependency_graph([node("root@1", integrity=integrity)], ("root@1",), allowed_origins=ORIGINS)


@pytest.mark.parametrize("algorithm", ["sha256", "sha384", "sha512"])
def test_pinned_sri_verified_incrementally_for_exact_supported_algorithm(algorithm):
    pinned = node("root@1", integrity=sri(b"firstsecond", algorithm))
    verify_dependency_content(pinned, iter([b"first", b"second"]), max_bytes=16)
    with pytest.raises(ToolExecutionError, match="does not match"):
        verify_dependency_content(pinned, [b"first", b"corrupt"], max_bytes=16)


@pytest.mark.parametrize("limit", ["nodes", "edges", "metadata_bytes"])
def test_graph_limits_stop_consumption_before_loading_the_entire_graph(limit):
    consumed = []

    def records():
        for index in range(20):
            consumed.append(index)
            yield node(f"fixture@{index}", ("fixture@0", "fixture@1") if limit == "edges" else ())

    with patch.dict("lingshu_gate.offline_build_contract.GRAPH_LIMITS", {limit: 1}):
        with pytest.raises(ToolExecutionError, match="limit"):
            validate_dependency_graph(records(), ("fixture@0",), allowed_origins=ORIGINS)
    assert len(consumed) <= 2


def test_dependency_byte_limit_stops_before_next_chunk():
    consumed = []

    def chunks():
        for index in range(3):
            consumed.append(index)
            yield b"xx"

    with pytest.raises(ToolExecutionError, match="byte or producer chunk limit"):
        verify_dependency_content(node("fixture@1"), chunks(), max_bytes=3)
    assert consumed == [0, 1]
    for chunk in (b"", b"x" * (64 * 1024 + 1)):
        with pytest.raises(ToolExecutionError):
            verify_dependency_content(node("fixture@1"), [chunk], max_bytes=128 * 1024)


def test_offline_request_has_no_material_proxy_registry_image_or_host_path_field():
    names = {field.name for field in fields(OfflineBuildRequest)}
    assert not names & {"material", "credential", "proxy", "network", "registry", "image", "cwd", "host_path"}
    with patch("subprocess.Popen") as popen, patch("subprocess.run") as run:
        build_request().validate(readiness())
    popen.assert_not_called()
    run.assert_not_called()


def test_offline_flags_do_not_replace_actual_disconnected_network_evidence():
    incomplete = readiness(ROOTLESS_CHECKS | {"verified_content_mounts", "secrets_outside_project"})
    with pytest.raises(ToolExecutionError) as denied:
        build_request(command=("pnpm", "install", "--offline", "--frozen-lockfile")).validate(incomplete)
    assert denied.value.code == "safe_executor_unavailable"
    assert "network_disconnected" in denied.value.details["missing"]


@pytest.mark.parametrize("platform,backend", [("darwin", "linux_rootless_oci"), ("win32", "linux_rootless_oci"), ("unknown", "linux_rootless_oci"), ("linux", "docker_cli"), ("linux", "missing")])
def test_unsupported_platform_or_cli_only_backend_never_readies(platform, backend):
    with pytest.raises(ToolExecutionError):
        build_request().validate(readiness(platform=platform, backend=backend))


@pytest.mark.parametrize("missing", sorted(ROOTLESS_CHECKS | PHASE_CHECKS["offline_build"]))
def test_each_actual_rootless_and_offline_requirement_is_mandatory(missing):
    ready = readiness()
    with pytest.raises(ToolExecutionError) as denied:
        build_request().validate(replace(ready, checks=ready.checks - {missing}))
    assert missing in denied.value.details["missing"]


@pytest.mark.parametrize("field", ["source_sha256", "file_list_sha256", "toolchain_sha256", "dependency_graph_sha256", "cache_sha256"])
def test_every_source_graph_and_cache_binding_is_required(field):
    with pytest.raises(ToolExecutionError):
        build_request(**{field: "a" * 63}).validate(readiness())


@pytest.mark.parametrize("field", list(BUILD_LIMITS))
def test_resource_limits_cannot_be_zero_bool_or_above_ceiling(field):
    for value in (0, True, BUILD_LIMITS[field] + 1):
        with pytest.raises(ToolExecutionError):
            build_request(**{field: value}).validate(readiness())


@pytest.mark.parametrize("key", ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NPM_TOKEN", "NODE_OPTIONS", "PATH", "HOME", "GIT_CONFIG_GLOBAL", "COREPACK_ENABLE_NETWORK"])
def test_script_environment_cannot_receive_credentials_proxy_or_bootstrap_settings(key):
    with pytest.raises(ToolExecutionError) as denied:
        build_request(environment=((key, "synthetic-secret"),)).validate(readiness())
    assert "synthetic-secret" not in str(denied.value)
